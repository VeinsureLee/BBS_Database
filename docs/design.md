# BBS_Database 设计文档

> 这是一份 **从零开始** 的设计稿，不含任何遗留实现。当前仓库里 BBS_Database 只保留这份文档和 [experiment/01_rag_mvp/](../experiment/01_rag_mvp/)（纯向量基线，作为后续算法对比的参考），其它一切待 TS 实现时再生成。
>
> 实现语言：**TypeScript**，与 BBS_Crawler、BBS_MCP 统一，复用同一个 npm workspace 包管理。

---

## 0. 一句话

BBS_Database 是 **BBS_Crawler 的图层伴侣**：把"哪个帖子物理上属于哪个版面"和"哪个帖子语义上应该属于哪个版面"这两件事用 Neo4j 图同时表达；只对 BBS_MCP 暴露一组查询/同步原语，让上层 agent 既能"在语义空间里找帖子"，也能反过来"知道该让爬虫去哪爬"。

---

## 1. 它要解决的真实问题

学校 BBS 的版面结构是 **物理路径**（"信息社会 → 计算机学院 → 学生交流"），但用户提问通常是 **语义意图**（"张三老师怎么样"）。同一条帖子可能：

- 物理上发在"悄悄话"或"灌水版"
- 语义上属于"信息社会下张三老师所在的学院版面"

只用物理结构搜不到；只用全局向量检索会把整个 BBS 拍平、丢掉版面这层先验。**图正好可以同时表达两者**：物理边记录真实位置、语义边记录"应该的位置"。Agent 拿到任意一头都能跳到另一头。

---

## 2. 整体架构

```
                ┌─────────────────────────────┐
                │  External Agent (Claude /…) │
                └──────────────┬──────────────┘
                               │ MCP (JSON-RPC over stdio)
                               │
                ┌──────────────▼──────────────┐
                │   BBS_MCP (TS, mcp SDK)     │
                │   — 工具目录 + 调度          │
                └────┬───────────────────┬────┘
                     │                   │
        in-proc call │                   │ in-proc call
                     │                   │
       ┌─────────────▼──────┐   ┌────────▼────────────┐
       │  BBS_Database (TS) │   │  BBS_Crawler (TS)   │
       │  - Neo4j 图层      │   │  - Playwright 爬取   │
       │  - SQLite 只读     │   │  - SQLite 写入       │
       │  - 检索 / 路由     │   │  - 事件流输出        │
       └────────┬───────────┘   └────────┬────────────┘
                │ ro read                │ writes
                │                        │
                │     ┌──────────────────▼─────┐
                └────►│   structure.db /        │  ← 唯一真相源
                      │   forums/*.db (SQLite)  │
                      └────────────────────────┘
                ┌─────────────────────────┐
                │       Neo4j (图)        │  ← 派生层（可重建）
                └─────────────────────────┘
```

三个 TS 包，通过 npm workspace 互相引用：

| 包 | 职责 | 关键依赖 |
|---|---|---|
| `bbs-crawler` | 抓取，写 SQLite，输出事件 | `playwright`, `better-sqlite3`, `zod` |
| `bbs-database` | 图建模、同步、查询、路由 | `neo4j-driver`, `better-sqlite3` (只读), `zod` |
| `bbs-mcp` | MCP server 入口、工具注册、并发调度 | `@modelcontextprotocol/sdk`, 内部依赖前两个 |

**为什么 in-proc 而不是 subprocess**：都是 TS，直接 import 函数最简单；爬虫不需要被独立部署。Crawler 内部已经有 BrowserPool / RateLimiter，把它当库调即可。

**为什么 SQLite 是唯一真相**：Neo4j 是派生层，删了能从 SQLite 全量重建。这条规则的好处是写入路径单点（只有 crawler 写 SQLite），所有同步都是"读 SQLite → 写 Neo4j"的单向流动，不会出现"图和库谁对"的纠纷。

---

## 3. 图模型

### 3.1 节点

| Label | 关键属性 | 含义 |
|---|---|---|
| `:Site` | `key`, `name`, `base_url` | 一个 BBS 站点 |
| `:Forum` | `node_id`, `name`, `db_file` | 顶级讨论区，如"信息社会" |
| `:SubForum` | `node_id`, `name` | 二级/三级讨论区（递归，深度不限） |
| `:Board` | `node_id`, `name`, `summary` | 最底层版面（实际能发帖的地方） |
| `:Thread` | `thread_id`, `forum_db`, `kind`, `url`, `title`, `posted_at` | 一条帖子 |

`Thread` 的主键是 **(forum_db, kind, thread_id)** 三元组，因为同一个 forum 数据库里 pinned 池和 plain 池各自独立自增。`kind ∈ {"pinned", "plain"}`。

### 3.2 边

**Location（物理结构 / actual structure）—— 记录"实际在哪"**

- `(:Site)-[:HAS_CHILD]->(:Forum)`
- `(:Forum)-[:HAS_CHILD]->(:SubForum|:Board)`
- `(:SubForum)-[:HAS_CHILD]->(:SubForum|:Board)`
- `(:Thread)-[:LOCATED_IN]->(:Board)`

统一用 `:HAS_CHILD` 而不是 `:HAS_FORUM/:HAS_BOARD`，因为父子层级深度由数据决定，多种 parent/child 类型穿插，用一个关系类型 + 节点 label 区分即可。这样跨多层查询 `MATCH (f:Forum)-[:HAS_CHILD*]->(b:Board)` 自然成立。

**Meaning（语义结构 / theoretical structure）—— 记录"应该在哪"**

- `(:Thread)-[:MEANS {weight, model, built_at}]->(:Board)`

一条 thread 可以有多条 `:MEANS`（top-K，K 一般 3）。`weight` 是余弦相似度 ∈ [0, 1]，`model` 记录用了哪个 embedding 模型（便于将来换模型时 reconcile），`built_at` 用来做过期失效。

> **关键直觉**：Board 同时承担两个角色——既是 `:LOCATED_IN` 的终点（"物理版面"），也是 `:MEANS` 的终点（"语义版面"）。这两者用同一组 Board 节点表达，避免再造一套虚拟"meaning_board"。一条物理上发在"悄悄话"的张三贴 → `:LOCATED_IN -> 悄悄话Board`，同时 `:MEANS -> 信息社会-计算机学院学生交流Board`。

### 3.3 约束 / 索引（建库时一次性建）

```cypher
CREATE CONSTRAINT site_key      IF NOT EXISTS FOR (s:Site)     REQUIRE s.key IS UNIQUE;
CREATE CONSTRAINT forum_nid     IF NOT EXISTS FOR (f:Forum)    REQUIRE f.node_id IS UNIQUE;
CREATE CONSTRAINT subforum_nid  IF NOT EXISTS FOR (n:SubForum) REQUIRE n.node_id IS UNIQUE;
CREATE CONSTRAINT board_nid     IF NOT EXISTS FOR (b:Board)    REQUIRE b.node_id IS UNIQUE;
CREATE CONSTRAINT thread_pk     IF NOT EXISTS FOR (t:Thread)
                                REQUIRE (t.forum_db, t.kind, t.thread_id) IS UNIQUE;

CREATE INDEX thread_url   IF NOT EXISTS FOR (t:Thread) ON (t.url);
CREATE INDEX board_name   IF NOT EXISTS FOR (b:Board)  ON (b.name);
```

---

## 4. 数据流

### 4.1 Bootstrap（一次性建结构）

读 BBS_Crawler 的 `structure.db`，把每一条 site / forum / sub_forum / board 节点 `MERGE` 进 Neo4j，按 `parent_id` 建 `:HAS_CHILD` 边。**幂等**——重跑只更新属性、不重复建边。

### 4.2 增（每条 thread 落库后触发）

> "增"是唯一的写操作。**MVP 不支持改/删**。原因：crawler 当前的 upsert 实质是"覆盖式写"，没有真删除；图层也跟着只增不减，简单且足够好。未来需要清理时再加 reconcile job。

触发方式 = **爬虫成功 upsert 一条 thread 后调用 `bbs-database` 暴露的 `syncThread(...)`**。MVP 直接在 crawler 的 `upsertPinnedThread` / `upsertPlainThread` 成功路径上 in-proc 调用即可（同语言、同进程，零序列化）。

`syncThread(forum_db, kind, thread_id)` 内部：

1. 从 forum_db 读这条 thread 的 title / url / posted_at 等。
2. `MERGE (:Thread { (forum_db,kind,thread_id) })` 并写属性。
3. `MERGE (:Thread)-[:LOCATED_IN]->(:Board {node_id: board_node_id})`。
4. 计算这条 thread 的语义向量（见 §6）。
5. 取所有 Board 的 centroid（缓存于内存），与该向量做余弦相似度，取 top-K：
6. 对每个 board 写 `MERGE (:Thread)-[:MEANS]->(:Board) SET m.weight=...`。

**冷启动情况**：刚 bootstrap 完还没 thread 时，Board centroid 全空，第一批 thread 落库时跳过 meaning 边，等 board 累积了一些 pinned thread 再触发一次全量 re-link。

### 4.3 查（图查询）

所有读路径都是 Cypher。详见 §5。

### 4.4 删 / 改

**MVP 不做**。占位实现：

- `purgeThread(forum_db, kind, thread_id)` —— 留接口空实现，将来实现"crawler 真删除时调"。
- `reconcileThreads()` —— 比对 SQLite 现存 thread 集合 vs Neo4j，删图里多出来的。批处理任务，将来加。

---

## 5. 检索能力（对外暴露的图查询原语）

设计哲学：**只暴露查询原语，不做智能问答**。Agent 自己组合。

| 接口 | Cypher 草图 | 用途 |
|---|---|---|
| `listBoards(siteKey?)` | `MATCH (b:Board) RETURN b` | 让 agent 知道所有可用版面 |
| `getBoardSummary(boardNodeId)` | `MATCH (b:Board {node_id:$id}) RETURN b.summary` | 给 agent 一段板块简介，帮它判断是不是要查这板 |
| `threadsInMeaningBoard(boardNodeId, limit)` | `MATCH (t:Thread)-[m:MEANS]->(:Board {node_id:$id}) RETURN t ORDER BY m.weight DESC` | **核心读路径**：给一个 meaning board，列语义归属的 thread |
| `threadsInPhysicalBoard(boardNodeId, limit, since?)` | `MATCH (t:Thread)-[:LOCATED_IN]->(:Board {node_id:$id}) RETURN t` | 物理版面浏览（不依赖 meaning 边，永远准） |
| `getThread(forum_db, kind, thread_id)` | 直接走 SQLite 取正文 | 拿完整帖子 |
| `routeIntent(query, topK)` | embed(query) → cosine vs board centroids → top-K | "我想问 X，去哪几个板可能有"——给 agent 的入口 |
| `suggestCrawlTargets(meaningBoardId, topK)` | 见 §7 算法 | "想丰富这个 meaning board 的内容，让爬虫去哪爬" |

**Board summary 是关键**：它让 agent **不用读 thread 就能判断这板是不是它要的**。Summary 怎么生成见 §6.3。

---

## 6. Embedding / 总结 子系统

### 6.1 接口约定

把"调向量 API"这件事抽成一个 TS interface，**实现可换**：

```typescript
interface Embedder {
  readonly model: string;
  readonly dims: number;
  embed(texts: string[]): Promise<Float32Array[]>;
}
```

MVP 提供三个实现：

| 实现 | 用途 |
|---|---|
| `StubEmbedder` | 用 SHA-256 派生确定性伪向量。零 API 调用。形状对、语义无意义。**默认值**，让所有 wiring 都跑通 |
| `DashScopeEmbedder` | OpenAI 兼容协议调阿里云 `text-embedding-v3` |
| `OpenAIEmbedder` | 直连 OpenAI（备用） |

切换走 config，不动业务代码。

### 6.2 Thread 向量化策略

MVP：**只 embed title**，足够便宜且对路由够用。后续可升级：

- title + 首楼正文（前 N 字截断）
- title + 高赞回复（参考 [experiment/01_rag_mvp/](../experiment/01_rag_mvp/) 的 vote-ordered 拼接策略）

### 6.3 Board centroid 与 Board summary

**Centroid**：每个 Board 拿它下面的 **pinned thread 标题**做 embedding，取平均后 L2-normalize。pinned 因为是版主置顶，最能代表该板"在干嘛"。空 pinned 的板冷启动期不参与 meaning 路由。

**Summary**：MVP 用"前 N 条 pinned title 拼接"占位。未来升级为 LLM 真总结（Embedding-Summarize API 或 chat completion）。Summary 存在 `Board.summary` 节点属性上，查询时直接拿。

### 6.4 预算控制

- **冷启动一次性建库**：只 embed pinned thread + board centroid（约几千条标题，几块钱）。
- **增量**：每天新增 plain thread 数量有限，单条 embed，可忽略。
- **重建**：换 embedding 模型时全量重 embed，需要预算评估——CLI 加 `--dry-run` 打印估算成本。

---

## 7. 算法（占位，待真正实现）

### 7.1 `routeIntent(query, topK)` — 意图 → meaning board

**MVP 占位实现**：

```
1. v = embed([query])[0]
2. 对每个 Board b：score(b) = cosine(v, centroid(b))
3. 返回 top_k {board_node_id, name, score, is_fallback:false}
```

**已知不足**：
- 当 query 里包含具体实体（"张三老师"）但 graph 里没该实体的 board centroid，会拍出泛化的"师生互评"之类的板，不准。
- 没有 query 关键词与 board 名字的 lexical 重合作为兜底信号。

**未来升级路径**：

1. **Entity-aware 路由**：把 query 跑 NER → 抽出 person/department 实体 → 查 `:Person` / `:Department` 节点 → 顺着 `:AFFILIATED_WITH` 边找 board。
2. **Lexical + vector 混合**：query 切词，与 board name/summary 的 token 重合度加分。
3. **Cold-start fallback**：每个顶级 Forum 在 routing 配置里声明 `fallback_board_node_id`（"找不到时落到这"），命中 fallback 时把 `is_fallback=true` 返回，agent 见此应停止反复爬。

### 7.2 `suggestCrawlTargets(meaningBoardId, topK)` — meaning → 物理 board

**MVP 占位实现**：

```
1. 查所有 (Thread)-[:MEANS]->(meaning_board) 的 thread 集合 T
2. 对 T 中每条 thread，沿 :LOCATED_IN 找到物理 board p
3. 按 p 分桶聚合：{p: count, weight_sum}
4. score(p) = weight_sum * log(1 + count)
5. 返回 top_k {board_node_id, name, score}
```

**未来升级路径**：

1. **时间衰减**：新帖权重高于老帖（rank_weight *= exp(-Δt / τ)）。
2. **爬虫成本先验**：pinned 多 / plain 少 / 上次 crawl 时间近 → 爬一次能"翻新"的预期收益高 → 加先验。
3. **Personalized PageRank**：在 meaning ↔ location 子图上从 meaning_board 跑 PPR，物理板按 PPR 分数排。能挖出"间接关联"的板（一条 thread 物理在 A 板，A 板的其他 thread 大量指向 meaning_board，则 A 板对该 meaning 很重要）。
4. **冷启动**：meaning_board 下没有 thread 时，靠 board name 的 lexical 相似度 + entity graph 推断。

---

## 8. MCP 工具目录

> 这是 BBS_MCP 包暴露给 agent 的工具。BBS_Database 不直接暴露 MCP，只通过 BBS_MCP 暴露——所以这一节实际上是"BBS_Database 给 BBS_MCP 提供的内部函数"对应的工具壳。

工具命名前缀统一 `forum_`（让 agent 一眼能识别这是 BBS 域的工具）。

### 8.1 读类（不触发爬虫）

| Tool | 入参（zod schema 草） | 返回 |
|---|---|---|
| `forum_list_sites` | — | `[{site_key, name, base_url}]` |
| `forum_list_boards` | `{ site_key?, limit? }` | `[{node_id, name, path, summary, ...}]` |
| `forum_get_board` | `{ board_node_id }` | 同上单条 |
| `forum_route_intent` | `{ query, top_k=5 }` | `[{board_node_id, name, score, is_fallback}]` |
| `forum_threads_by_meaning_board` | `{ board_node_id, limit=20, min_weight=0 }` | `[{thread_id, forum_db, kind, title, url, meaning_weight, physical_board_id}]` |
| `forum_threads_by_physical_board` | `{ board_node_id, limit=20, kind?, since? }` | `[{thread row}]` |
| `forum_get_thread` | `{ url } \| { forum_db, kind, thread_id }` | thread + posts |
| `forum_board_freshness` | `{ board_node_id }` | `{ last_crawled_at, threads_total, threads_24h, pinned_count }` |

### 8.2 写/动作类（触发爬虫）

| Tool | 入参 | 返回 |
|---|---|---|
| `forum_suggest_crawl_targets` | `{ meaning_board_id, top_k=5 }` 或 `{ query, top_k=5 }` | `[{physical_board_id, name, score}]` |
| `forum_crawl_board` | `{ board_node_id, mode: "recent"\|"deep", max_pages? }` | `{ job_id, status, threads_seen, threads_new }` |
| `forum_crawl_thread` | `{ url } \| { forum_db, kind, thread_id }, force=false` | `{ thread_id, fetched, skipped, reason? }` |
| `forum_refresh_pinned` | `{ board_node_id }` | `{ updated_pinned: N }` |
| `forum_job_status` | `{ job_id }` | `{ status, threads_new, errors, elapsed_s }` |

### 8.3 元/调试类

| Tool | 用途 |
|---|---|
| `forum_graph_stats` | `{ sites, forums, sub_forums, boards, threads, meaning_edges, last_synced_at }` |
| `forum_session_status` | crawler 登录状态 |

### 8.4 所有读类工具返回的 Freshness Envelope

```typescript
{
  data: T[],
  freshness: {
    as_of: string;                    // ISO timestamp
    board_last_crawled_at?: string;
    threads_in_result_newest?: string;
    graph_last_synced_at?: string;
  },
  confidence?: number;                // 仅 route / suggest 类
  is_fallback?: boolean;
}
```

**这是 MCP 设计里最容易漏的字段**。没有它，agent 永远不知道该不该触发爬虫，会陷入"反复爬"或"用陈旧数据答"两个失败模式。

---

## 9. Agent 使用流程（端到端示例）

```
USER:  张三老师最近怎么样

AGENT  forum_route_intent({ query:"张三老师怎么样", top_k:5 })
    →  [{board_node_id:88, name:"师生互评", score:0.62, is_fallback:false}, ...]

AGENT  forum_threads_by_meaning_board({ board_node_id:88, limit:20 })
    →  { data: [...3 threads...], freshness: { board_last_crawled_at: "3 天前" } }

AGENT  (内部判断：结果太少且数据陈旧)
       forum_suggest_crawl_targets({ meaning_board_id:88, top_k:3 })
    →  [{physical_board_id:42, name:"计算机学院学生交流", score:7.2}, ...]

AGENT  forum_crawl_board({ board_node_id:42, mode:"recent" })
    →  { threads_new: 8, elapsed: 23s }

AGENT  forum_threads_by_meaning_board({ board_node_id:88, limit:20 })   # 重查
    →  { data: [...11 threads...] }

AGENT  forum_get_thread({ forum_db:..., kind:"plain", thread_id:... })
    →  完整帖子

AGENT  RESPOND  "根据 BBS 讨论（最近抓取于 2 分钟前），张三老师..."
```

**关键点**：agent 全程不知道 forum_db、pinned/plain、Neo4j、SQLite 这些细节；这些都被 MCP 工具的入参/返回结构挡掉。

---

## 10. 并发与一致性

### 10.1 写写：crawler 之间

- **同 board 不并行爬**：MCP 维护 `Map<boardNodeId, Promise>`，`forum_crawl_*` 入参先抢锁——同 board 第二个请求要么排队、要么合并到现有 job、要么报忙。
- 不同 board 可并行，受 Crawler 的 BrowserPool 上限限流。

### 10.2 读写：agent 查 / crawler 写

- SQLite WAL 模式。`bbs-database` 用只读 + `immutable=1` 打开 forum db → 跳过 WAL 协议 → 可能读到 WAL 之前的快照。**MVP 接受**：新数据落库 → `syncThread` 写图 → agent 下一次查图就能看到，不是看 SQLite 直接看。
- Neo4j 是 ACID，多个 syncThread 并发安全。

### 10.3 Graph 与 SQLite 漂移

- **正向漂移**：crawler 写了 SQLite 但没触发 syncThread——只在 crawler bug 或外部脚本绕过时发生。补救：周期 `reconcileThreads()`。
- **反向漂移**：图里有但 SQLite 没——只可能发生在 SQLite 被外部删除后图没清。MVP 不处理。

---

## 11. TS 技术栈选型

| 选型 | 用途 | 备注 |
|---|---|---|
| `neo4j-driver` | Neo4j 官方 TS 驱动 | 支持事务 / session / async iterator |
| `better-sqlite3` | 同步 SQLite | 与 BBS_Crawler 复用 |
| `zod` | Schema 校验 | 工具入参/返回都走 zod，与 MCP SDK 自然对齐 |
| `@modelcontextprotocol/sdk` | MCP server SDK | BBS_MCP 包用 |
| `pino` | 日志 | 与 crawler 复用 |
| `vitest` | 测试 | 与 crawler 复用 |
| `tsx` | 开发期跑 TS 脚本 | bootstrap / sync 脚本用 |
| `openai` 包（兼容协议） | DashScope / OpenAI embedding | 仅在真实 Embedder 实现里依赖 |

Neo4j 部署：**本地装 Community Server**(`neo4j console` 前台跑或注册成 Windows 服务),本地开发用。生产可换 Aura 云。

---

## 12. 目录结构（建议）

```
BBS_MCP/                                ← 仓库根 = npm workspace
├── package.json                        ← workspaces: ["BBS_Crawler", "BBS_Database", "BBS_MCP"]
├── tsconfig.base.json
│
├── BBS_Crawler/                        ← 已有
│   └── ...
│
├── BBS_Database/
│   ├── package.json                    ← name: "bbs-database"
│   ├── tsconfig.json
│   ├── NEO4J_QUICKSTART.md             ← 零基础上手指南
│   ├── docs/
│   │   └── design.md                   ← 本文件
│   ├── experiment/
│   │   └── 01_rag_mvp/                 ← 沙盒，与主代码隔离
│   ├── src/
│   │   ├── index.ts                    ← 对外 API：export { syncThread, routeIntent, ... }
│   │   ├── config.ts
│   │   ├── sqlite/
│   │   │   └── reader.ts               ← 只读访问 crawler 的 structure.db / forums/*.db
│   │   ├── graph/
│   │   │   ├── driver.ts               ← neo4j 连接管理
│   │   │   ├── schema.ts               ← constraints / indexes
│   │   │   ├── bootstrap.ts            ← 镜像 structure.db 到 :HAS_CHILD 树
│   │   │   ├── sync.ts                 ← syncThread / syncAll
│   │   │   └── queries.ts              ← 所有读 Cypher
│   │   ├── embed/
│   │   │   ├── types.ts                ← Embedder 接口
│   │   │   ├── stub.ts                 ← 哈希伪向量
│   │   │   ├── dashscope.ts            ← 真实接入
│   │   │   └── cache.ts                ← 向量本地缓存（vectors.db）
│   │   └── routing/
│   │       ├── intent.ts               ← routeIntent
│   │       └── suggest.ts              ← suggestCrawlTargets
│   ├── scripts/
│   │   ├── bootstrap.ts                ← 一次性建图结构
│   │   ├── sync-all.ts                 ← 全量同步 thread
│   │   └── reconcile.ts                ← 占位
│   └── tests/
│       └── ...
│
└── BBS_MCP/
    ├── package.json                    ← name: "bbs-mcp"
    ├── src/
    │   ├── server.ts                   ← mcp SDK 入口
    │   ├── tools/
    │   │   ├── read.ts                 ← 读类工具
    │   │   ├── crawl.ts                ← 触发爬虫的工具
    │   │   └── meta.ts                 ← 元/调试工具
    │   ├── concurrency.ts              ← per-board lock
    │   └── freshness.ts                ← envelope 构造
    └── ...
```

---

## 13. 分期实施（学习路线）

**完成顺序就是学习顺序**。每一阶段都能独立验收。

### Phase 1 — 把 Neo4j 跑起来 + 镜像物理结构

目标：在 Neo4j Browser 里看到完整的 site → forum → board 树。

里程碑：
- BBS_Database 包能 `npm run build`
- 本地 Neo4j 起来(`neo4j.bat console` 或 Windows 服务),`http://localhost:7474` 能登录
- `npm run bootstrap` 跑通：读 crawler structure.db，建 `:HAS_CHILD` 树
- 在 Neo4j Browser 跑 `MATCH (f:Forum)-[:HAS_CHILD*]->(b:Board) RETURN b` 看到全部板

### Phase 2 — Thread 落图 + LOCATED_IN 边

目标：每条 thread 在图里有节点和物理归属边。

里程碑：
- `src/graph/sync.ts` 的 `syncThread(forum_db, kind, thread_id)` 实现
- `scripts/sync-all.ts` 全量同步
- `MATCH (t:Thread)-[:LOCATED_IN]->(b:Board {name:'灌水'}) RETURN count(t)` 给出正确数字

### Phase 3 — StubEmbedder + MEANS 边

目标：图里有语义边，能跑通最简 `routeIntent` 和 `threadsByMeaningBoard`。

里程碑：
- StubEmbedder 跑通
- Board centroid 计算 + 缓存
- `syncThread` 自动建 top-K MEANS 边
- `routeIntent("test")` 返回 top-5 board
- 在 Neo4j 里随便抽一条 thread 能看到 1 条 LOCATED_IN + ≤3 条 MEANS

### Phase 4 — MCP server 暴露读工具

目标：agent 能通过 MCP 调到 Phase 1-3 的所有读能力。

里程碑：
- BBS_MCP 包搭好，`@modelcontextprotocol/sdk` 跑通
- 注册所有 §8.1 读类工具
- 用 MCP Inspector 手动调一遍，每个工具有 freshness envelope
- Claude Desktop / 任意 MCP client 连上能列工具

### Phase 5 — MCP 触发爬虫 + 自动 sync

目标：agent 调 `forum_crawl_board` → 爬虫跑 → 图自动更新。

里程碑：
- BBS_MCP `forum_crawl_board` 工具：in-proc 调 bbs-crawler 的 crawl 函数
- 在 crawler 的 upsert 成功路径插桩，调 `syncThread` —— 同进程函数调用，零序列化
- per-board lock 实装，并发请求不会双跑同一板
- 端到端跑一遍 §9 的示例流程

### Phase 6 — 真实 Embedding

目标：把 StubEmbedder 换成 DashScopeEmbedder，所有边变成有语义意义的。

里程碑：
- DashScopeEmbedder 实现 + dry-run 预算估算 + 速率限制
- 全量重建 centroid + MEANS 边
- 同一个 query 在 stub vs 真实下的 routeIntent 结果对比明显

### Phase 7+ — 算法升级（按需）

- Entity graph（`:Person`/`:Department`/`:AFFILIATED_WITH`）
- 时间衰减、PageRank、PPR
- Board summary 升级为 LLM 总结
- 异步 job manager（爬虫调用立即返 job_id）
- Reconcile / 软删除

---

## 14. 与 `experiment/01_rag_mvp/` 的关系

`experiment/01_rag_mvp/` 是 **纯向量检索基线**（title + 正文 → embedding → 全局 cosine top-k），不依赖图。它的角色是 **对照组**：

- 当我们做完 Phase 3 / Phase 6 后，应该跑一组 golden queries 看：
  - 纯向量 baseline 的 hit@k
  - 图路由（routeIntent → threadsByMeaningBoard）的 hit@k
- 如果图路由不能稳定胜过 baseline，说明 meaning 边的质量不够 / 算法占位太弱，需要升级 Phase 7。

实验目录的 README 强调"不能被主项目代码反向锁死"——意思是它是沙盒，写脏代码无所谓，目标是探究算法，结论再反哺到 `src/`。

---

## 15. 开放问题（记下来防忘）

- **多 site**：当前默认单 site (`school-bbs`)。挂多个学校 BBS 时 agent 怎么选 site？工具入参可能要把 site_key 显式化。
- **跨 site 的 meaning**：A 校"学院" 和 B 校"学院" 是不是同一个 meaning？MVP 不跨。
- **Embedding 模型切换**：换模型后历史 MEANS 边失效，需要批量重建。MVP 在 `MEANS.model` 上判断，逐板懒重建 vs 全量一次重建——待定。
- **Agent 滥用 crawl**：agent 可能为了答一句小问题狂触发深爬。`forum_crawl_*` 默认 `mode=recent`，`mode=deep` 需要 agent 显式声明 + MCP 层加速率上限。
- **Neo4j 备份**：派生层理论上可重建，但全量重建要重新 embed (花钱)。需要定期 dump Neo4j 防 embedding 二次支出。

---

## 16. 不在本设计范围内的事

明确写下来，省得未来纠结：

- ❌ 智能问答 / RAG 回答生成。BBS_Database 不调 LLM，只暴露检索原语。回答由 agent 自己生成。
- ❌ 用户偏好 / 个性化排序。
- ❌ 跨 site 的实体联合（同名教师在多个学校）。
- ❌ 实时 push（thread 一发图就更新）。当前是"crawl 后 sync"模型，与"crawl 频率"绑死。
- ❌ 权限 / 多租户。本地单用户工具。
