# BBS_Database 向量路由层设计 v2.0

> 版本：v2.0.0
> 日期：2026-05-12
> 状态：草案，待实现（P2 起）
> 与 v1.0 关系：本文档在 [`2026-05-12-bbs-database-design.md`](2026-05-12-bbs-database-design.md)（下称 "v1.0 spec"）之上，引入 embedding 向量层并重新定义 P2 及之后路线图。**v1.0 spec 的 §1（架构）、§2（schema + classical builder）、§6.4 (a)(b) 自检均继承不重述**；本文档只描述新增/变更内容。

---

## §1 概览

### 1.1 为何引入向量层

v1.0 的 classical NLP 路径（jieba + TF-IDF + PMI + entity）在 P1 自检上达 99.6% top-3 / 99.4% entity-top-5，但有两类场景它解决不了：

1. **冷启动期的语义匹配**——用户问"分手了"，"情感的天空"版面在 declared 文本里没有"分手"这个词；TF-IDF 找不到，但 embedding 能。
2. **板面名与正文不符**（v1.0 §0 提到的核心痛点）——匿名/树洞版面声明"情感讨论"但实际谈人物评价。classical 的多跳扩展只能在已观测词上发挥作用，对未观测的概念关联无能为力；vector 在语义空间里天然能拉近这些 board。

为此引入 thread 标题级 + board 画像级的 embedding，在 P1 classical 路径之上做 **hybrid 联合打分**。

### 1.2 工作流程（与 v1.0 的关键区别）

v1.0 默认 "先全爬 → 后查询" 模型；v2.0 改为 **on-demand** 闭环：

```
用户问 agent → MCP → BBS_Database.find_forums(query)
  ↓ 返回 [board#10 conf=0.92, board#20 conf=0.8, ...]
agent 让 crawler 去爬指定 boards 的 thread 列表
  ↓ crawler 写入 forum.db
agent → MCP → BBS_Database.ingest_threads(forum_db_file, thread_ids)
  ↓ embed 新 thread 标题 + 写 index.db.thread_vector
agent → MCP → BBS_Database.search_threads(query, board_node_ids=...)
  ↓ 返回排好序的 thread 列表（hybrid 打分）
agent → MCP → BBS_Database.get_thread(...)（可选，拉全文）
  ↓
agent 生成回答给用户
```

**关键含义：**
- `find_forums` 的语义从"检索"变成"预测应爬版面"（prediction）。冷启动时数据稀疏（每板只有几条置顶），vector 主导。
- BBS_Database 多一个 **`ingest_threads()` 公开函数**——爬虫爬完后由 agent 通知入库 + embed。
- 整个 BBS_Database 仍**只读 crawler db**（不改 v1.0 上下游契约）；ingest 写的是自己的 `index.db`。

### 1.3 边界与原则继承

| v1.0 原则 | v2.0 状态 |
|---|---|
| 不读 `posts.content_text`，仅基于 `threads.title` | **保留**：vector 只 embed 标题 |
| 运行时不调任何 LLM/embedding | **破弃**：每次 query 至少调 1 次 embedding API；ingest 时批量调 |
| 经典 NLP（jieba+TF-IDF+PMI）+ 结构信号 | **保留为 hybrid 一路**：classical 路径完整保留，与 vector 路径融合打分 |
| 可解释 | **加强**：vector 路径同样带 evidence（"哪些 thread 让本板 cosine 浮上来"） |
| 严格只读 crawler | **保留**：reader 用 `?mode=ro&immutable=1`，零 sidecar 文件 |

### 1.4 关键技术选型

| 项 | 选择 |
|---|---|
| Embedding provider | **DashScope Qwen v3**（`text-embedding-v3`，1024 维） |
| SDK | OpenAI Python SDK + `base_url` override（`https://dashscope.aliyuncs.com/compatible-mode/v1`） |
| API key 来源 | 环境变量 `DASHSCOPE_API_KEY`，由 `python-dotenv` 从 `.env` 加载 |
| 向量存储 | `index.db` 的两张新表（`board_vector` / `thread_vector`），`vec BLOB` = `np.float32.tobytes()` |
| 相似度计算 | runtime 全量加载向量进内存，numpy 暴力矩阵乘 cosine |
| 不引入 | FAISS / sqlite-vec / chromadb / 向量数据库 |

### 1.5 量级与成本估算

| 阶段 | 数据量 | 耗时 | 成本 |
|---|---|---|---|
| 首次 `rebuild_index.py --full`（board × 259 + 置顶 thread × ~1300） | ~1600 条文本 | ~1 分钟（~63 批） | ~¥0.03 |
| 单次 `ingest_threads`（典型一版面新爬 30 条） | 30 条 | ~3 秒（2 批） | ~¥0.001 |
| 单次 query 自身 embedding（runtime） | 1 条 | ~200 ms | ~¥0.00002 |
| 累计 1 万次 query + 对应 ingest（约 10 万新 thread） | (累积) | (累积) | **~¥30 / 年** |

> 引入 vector 层的运行成本约 **¥30/年级别**，远低于"全爬全 embed"路径的 ¥1-5 一次性。

---

## §2 Schema 变更

继承 v1.0 spec §2.4 的全部 5 张业务表 + FTS5 + `_meta`，**仅新增 2 张表**。

### 2.1 `board_vector`（每个 board 一行）

```sql
CREATE TABLE board_vector (
  board_node_id  INTEGER PRIMARY KEY,
  vec            BLOB NOT NULL,           -- 1024 × float32 = 4096 字节
  source_text    TEXT NOT NULL,            -- name + " " + path + " " + 置顶帖标题 join
  embed_model    TEXT NOT NULL,
  built_at       TEXT NOT NULL
);
```

- `embed_model` 列允许在 build 启动时检测：若 `_meta.embed_model` 与 cfg 不一致，全表清空重 embed
- 没有 FK 到 `forum_profile`（spec §2 沿用：无强 FK，bulk insert 简化）

### 2.2 `thread_vector`（每条 thread 标题一行）

```sql
CREATE TABLE thread_vector (
  rowid          INTEGER PRIMARY KEY,
  board_node_id  INTEGER NOT NULL,
  thread_id      INTEGER NOT NULL,
  forum_db_file  TEXT NOT NULL,
  vec            BLOB NOT NULL,
  embed_model    TEXT NOT NULL,
  built_at       TEXT NOT NULL,
  UNIQUE (forum_db_file, thread_id)        -- thread_id 跨 forum.db 重号，需复合唯一
);
CREATE INDEX idx_tv_board ON thread_vector(board_node_id);
```

- `UNIQUE (forum_db_file, thread_id)` → `ingest_threads()` 幂等：重复调用同一 (file, id) 不重 embed
- `rowid INTEGER PRIMARY KEY` 自增，runtime 在 cosine 后 join 拿元数据

### 2.3 `_meta` 新增字段

```
embed_provider  = 'dashscope'
embed_model     = 'text-embedding-v3'
embed_dim       = '1024'
```

---

## §3 离线 build pipeline + ingest 接口

### 3.1 `build_index(cfg)` 三阶段

```
def build_index(cfg):
    # Phase 0  classical（v1.0 §2.5 pipeline，零改动）
    classical_build()
    if not cfg.embed.enabled:
        return    # --no-embed 退化为 P1 行为

    # Phase 1  board-level embedding（259 板，~5 秒）
    boards = read forum_profile
    diff with board_vector where embed_model = cfg.embed.model
    for batch in chunked(diff_boards, cfg.embed.batch_size):
        source_texts = [b.name + " " + b.path + " " + " ".join(pinned_titles(b))
                        for b in batch]
        vecs = embed_api.embed(source_texts)
        upsert into board_vector(board_node_id, vec, source_text, embed_model, built_at)

    # Phase 2  thread-level embedding（仅置顶帖，~1300 条，~1 分钟）
    if cfg.embed.pinned_only_at_full_build:
        pinned_threads = [t for t in all_threads if t.is_pinned]
    else:
        pinned_threads = all_threads
    diff with thread_vector where embed_model = cfg.embed.model
    for batch in chunked(diff_threads, cfg.embed.batch_size):
        titles = [t.title for t in batch]
        vecs = embed_api.embed(titles)
        insert into thread_vector(...)
    
    write _meta(embed_provider, embed_model, embed_dim, ...)
```

**diff 机制：** 检查 `embed_model` 一致的已有 (forum_db_file, thread_id) → 跳过；不同 model 的 → 删除重做。保证：

- 中断重跑续上（已 commit 的批不重做）
- 切换 model（如从 Qwen v3 换到 BGE-M3）自动整表清空重 embed，无需 `--full`

### 3.2 `ingest_threads()` 公开 API

```python
def ingest_threads(
    forum_db_file: str,
    thread_ids: list[int] | None = None,
    *,
    overrides: dict | None = None,
) -> IngestResult:
    """
    给指定 forum.db 内的 thread_ids 调 embedding API 并写 thread_vector。
    
    - thread_ids=None 表示 'embed 该 forum.db 内所有尚未 embed 的 thread'
    - 幂等：已存在的 (forum_db_file, thread_id) 跳过
    - Partial：API 失败的条目记入 failed_thread_ids，不 raise；下次调用接着续
    """
```

**调用方典型流程：**

```python
res = bbs_database.ingest_threads("forums/3.db", thread_ids=[1001, 1002, ..., 1080])
if res.failed:
    # 隔几秒重试 failed_thread_ids（partial 续跑）
    bbs_database.ingest_threads("forums/3.db", res.failed_thread_ids)
```

### 3.3 错误处理矩阵

| 故障 | Phase 0 (classical) | Phase 1/2 (embed) | ingest_threads |
|---|---|---|---|
| API key 缺失 | n/a | `EmbedConfigError`（fail-fast） | `EmbedConfigError` |
| 单次 API 调用失败 | n/a | SDK 自动重试 3 次（exp backoff），最终失败抛 `EmbedAPIError` 或记录 partial | partial，记入 failed_thread_ids |
| Rate limit (429) | n/a | SDK 自动 backoff | 同 |
| Network timeout | n/a | 同上 | 同 |
| Content filter (敏感词) | n/a | 跳过该条目，记 partial，不阻塞批 | 同 |
| 中断 (Ctrl+C) | rollback 当前事务 | 已 commit 批不丢，下次续 | 同 |
| 模型切换 | n/a | 自动清旧 vector 重 embed | 自动清旧 vector 重 embed |

---

## §4 在线 query 算法

### 4.1 `find_forums(query, top_k=8)` 完整公式

```
Step 1. Parse query
  q_terms      = jieba.cut(query) - stopwords - len<2
  q_entities   = extract_entities(query)
  query_vec    = embed_api.embed(query)                    # ~200 ms

Step 2. classical direct score（v1.0 §3.3 沿用）
  cls_direct(b) = α₁·tfidf_declared(b, q_terms)
               + α₂·tfidf_content(b, q_terms)·signal_strength(b)
               + α₃·log(1+entity_count(b, q_entities))
               + α₄·activity_score(b)

Step 3. classical 多跳扩展（v1.0 §3.4，seeds 合并 vector）
  classic_seeds = top-K₁ by cls_direct
  vec_seeds     = top-K₁ by cosine(query_vec, board.vec)   ← vector 反哺 classical seeds
  seeds         = classic_seeds ∪ vec_seeds
  exp_terms     = cooccur_terms_for(seeds, q_terms)
  cls_exp(b)    = β · Σ over t∈exp_terms ...
  cls_total(b)  = cls_direct(b) + cls_exp(b)

Step 4. vector direct score
  vec_score(b)  = max(0, cosine(query_vec, board_vector(b)))

Step 5. 自适应融合
  signal(b)     = forum_profile.content_signal_strength
  δ(b)          = δ_cold  if signal(b) < signal_threshold else δ_base   # 默认 0.7 / 0.5
  cls_norm(b)   = min-max normalize cls_total over this batch
  vec_norm(b)   = vec_score(b)                              # 已在 [0,1]
  final(b)      = δ(b)·vec_norm(b) + (1-δ(b))·cls_norm(b)

Step 6. 返回 top_k，每个候选带 evidence
```

**δ 自适应动机：** 冷启动期（每板 `signal_strength ≈ 0`）vector 权重 0.7 主导；内容稳定后（200+ 标题）降到 0.5 平衡。所有阈值可在 `routing.yaml` 调。

### 4.2 `search_threads(query, board_node_ids=None)` 完整流程

```
Step 1. embed 一次 query → query_vec

Step 2. 决定 board 范围
  if board_node_ids 给了:
      board_score[bid] = 1.0    # 调用方框选，不参与 board 加权
  else:
      forums = find_forums(query, top_k=top_k_forums)
      board_score = {c.board_node_id: c.final_score for c in forums}

Step 3. 拉范围内全部 thread_vector（一次 IN 查询）
  rows = SELECT thread_id, board_node_id, forum_db_file, vec
         FROM thread_vector WHERE board_node_id IN (...)

Step 4. 内存 cosine（numpy 暴力矩阵乘）
  vecs    = np.stack([np.frombuffer(r.vec, ...) for r in rows])
  cosines = (vecs / ||vecs||) @ (query_vec / ||query_vec||)

Step 5. 拉 thread 元数据
  对每个 forum_db_file，open_ro(forum.db, immutable=1)，按 thread_id IN 查询
  拉 title / author / posted_at / last_reply_at / reply_count / view_count / url / is_pinned

Step 6. rerank 复合打分
  combined(t) = γ₁·cosine(t) + γ₂·board_score[t.board] + γ₃·recency(t.posted_at, τ=180d)
  recency(ts) = exp(-Δdays / τ)

Step 7. group by board，每板取 per_board_limit，全局 total_limit
  返回 list[ThreadHit]
```

### 4.3 参数表（`config/routing.yaml`）

```yaml
routing:
  # classical（v1.0 继承不变）
  alpha_declared: 1.0
  alpha_content: 1.5
  alpha_entity: 2.0
  alpha_activity: 0.1
  k1_seeds: 5
  seed_top_terms: 20
  m_expansion: 10
  beta_expansion: 0.5
  k_final: 8
  
  # hybrid 融合（新）
  delta_vector_base: 0.5
  delta_vector_cold: 0.7
  delta_signal_threshold: 0.5

search:
  gamma_vector: 0.6
  gamma_board: 0.3
  gamma_recency: 0.1
  recency_tau_days: 180
  per_board_limit: 20
  total_limit: 50

embed:
  enabled: true
  provider: dashscope
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  model: text-embedding-v3
  dimensions: 1024
  api_key_env: DASHSCOPE_API_KEY
  batch_size: 25                    # Qwen v3 单批上限 25 条
  max_input_chars: 2000             # 单条输入截断长度（DashScope 单条 token 上限 ~2048，留 buffer）
  max_retries: 3
  request_timeout_s: 30
  pinned_only_at_full_build: true
```

> **关于 `max_input_chars`：** Qwen v3 单条输入 token 上限约 2048。thread 标题极短（一般 < 100 字符），无截断风险；board 的 `source_text` 拼接 name + path + 多条置顶标题，理论可能逼近上限，故 builder 在 embed 前对 source_text 做 `text[:max_input_chars]` 截断防御，并在日志里打 warning（不阻塞 build）。

任何调用都可 `overrides={"gamma_vector": 0.8}` 临时覆盖单参数，方便 A/B。

### 4.4 边界 / 降级

| 异常 | 处理 |
|---|---|
| query 分词后空 | 跳过 classical 路径，仅用 vector |
| query embedding 调失败 | 跳过 vector 路径，仅用 classical（结果带 `vector_disabled=True`） |
| `board_node_ids` 里某板无 thread_vector 记录 | 跳过该板，不报错 |
| `thread_vector` 整表为空（仅做了 init build，没 ingest 过） | `search_threads` 返回 `[]` + warning |
| `board_vector` 表为空（连初始 build 都没跑） | `find_forums` raise `IndexNotBuiltError` |

### 4.5 evidence（可解释性）

`ForumCandidate` 在 v1.0 基础上新增字段：

```python
vector_cosine: float                              # query × board_vector cosine
delta_used: float                                 # 本次实际生效的 δ
top_vector_contributing_threads: list[VectorContributingThread]
    # vector 召回前 3 个促成本板浮起来的 thread (id, title, cosine)
vector_disabled: bool = False                     # API 失败时 True
```

`ThreadHit` 新增：

```python
vector_cosine: float
recency_factor: float
breakdown: dict[str, float]                       # {"vector": γ₁·cos, "board": γ₂·bs, "recency": γ₃·r}
```

agent 拿到这些可以告诉最终用户"为什么推这个版面 / 这个帖"。

---

## §5 公开 API 与错误体系

### 5.1 四公开函数（`bbs_database.api`）

```python
def find_forums(
    query: str, *, site_key: str = "school-bbs",
    top_k: int = 8, overrides: dict | None = None,
) -> list[ForumCandidate]: ...

def ingest_threads(
    forum_db_file: str, thread_ids: list[int] | None = None,
    *, overrides: dict | None = None,
) -> IngestResult: ...

def search_threads(
    query: str, *, site_key: str = "school-bbs",
    board_node_ids: list[int] | None = None,
    top_k_forums: int = 5, per_board_limit: int = 20, total_limit: int = 50,
    overrides: dict | None = None,
) -> list[ThreadHit]: ...

def get_thread(forum_db_file: str, thread_id: int) -> ThreadDetail: ...
```

### 5.2 关键 dataclass

```python
@dataclass
class VectorContributingThread:
    thread_id: int
    forum_db_file: str
    title: str
    cosine: float

@dataclass
class ForumCandidate:
    board_node_id: int
    site_key: str
    name: str
    path: str
    forum_db_file: str
    final_score: float
    classic_direct_score: float
    classic_expansion_score: float
    vector_cosine: float
    delta_used: float
    activity_score: float
    title_count: int
    content_signal_strength: float
    matched_terms: list[MatchedTerm]
    expanded_via: list[ExpansionLink]
    top_vector_contributing_threads: list[VectorContributingThread]
    vector_disabled: bool = False

@dataclass
class ThreadHit:
    thread_id: int
    board_node_id: int
    board_name: str
    board_path: str
    forum_db_file: str
    title: str
    author: str | None
    posted_at: str | None
    last_reply_at: str | None
    reply_count: int | None
    view_count: int | None
    url: str
    is_pinned: bool
    combined_score: float
    vector_cosine: float
    board_score: float
    recency_factor: float
    breakdown: dict[str, float]
    routing_evidence: ForumCandidate

@dataclass
class IngestResult:
    forum_db_file: str
    requested: int
    already_indexed: int
    newly_embedded: int
    failed: int
    failed_thread_ids: list[int]
    elapsed_seconds: float
    estimated_cost_cny: float
    embed_model: str

# Post / ThreadDetail / MatchedTerm / ExpansionLink 沿用 v1.0 §5.2
```

### 5.3 错误体系

```python
class BBSDatabaseError(Exception):
    code: str

# v1.0 继承
class IndexNotBuiltError(BBSDatabaseError): ...      # code='index_not_built'
class EmptyQueryError(BBSDatabaseError): ...         # code='empty_query'
class InvalidBoardError(BBSDatabaseError): ...
class ThreadNotFoundError(BBSDatabaseError): ...
class ForumDbNotFoundError(BBSDatabaseError): ...

# v2.0 新增
class EmbedAPIError(BBSDatabaseError):                  # code='embed_api_error'
    """embed API 调用失败（rate limit / 5xx / network / auth / content filter）"""
class EmbedConfigError(BBSDatabaseError):               # code='embed_config_error'
    """配置错（key 缺、base_url 错、dimensions 与 _meta 不匹配）"""
class VectorIndexEmptyError(BBSDatabaseError):          # code='vector_index_empty'
    """vector 表为空，search_threads 调用时返回；调用方应先 ingest"""
```

`code` 字段方便 MCP 层 map 成 JSON-RPC error code。

### 5.4 MCP tool 暴露约定（在 BBS_MCP 实现）

```yaml
tools:
  - name: bbs_find_forums
    description: Predict which BBS boards are most relevant to a user question.
                 Returns ranked boards with both classical signals and vector similarity
                 evidence.
    input_schema: { query: string, site_key: string?, top_k: integer? }
    output: list[ForumCandidate as JSON]

  - name: bbs_ingest_threads
    description: Embed and index newly crawled threads. Idempotent; safe to retry on
                 partial failure.
    input_schema: { forum_db_file: string, thread_ids: integer[]? }
    output: IngestResult as JSON

  - name: bbs_search_threads
    description: Search thread titles via vector similarity + board score + recency,
                 optionally constrained to specific boards.
    input_schema: { query: string, board_node_ids: integer[]?, total_limit: integer? }
    output: list[ThreadHit as JSON]

  - name: bbs_get_thread
    description: Read full thread content including all floors.
    input_schema: { forum_db_file: string, thread_id: integer }
    output: ThreadDetail as JSON
```

---

## §6 配置 / 依赖 / 环境

### 6.1 `pyproject.toml` 新增依赖

```toml
dependencies = [
  "jieba>=0.42",
  "PyYAML>=6.0",
  "numpy>=1.24",
  "openai>=1.0",
  "python-dotenv>=1.0",
]
```

### 6.2 `.env`（**新增**，列入 `.gitignore`）

```
DASHSCOPE_API_KEY=sk-your-key-here
```

仓库提供 `.env.example`（无 key）。运行时由 `python-dotenv` 自动加载到 `os.environ`。

### 6.3 `config/routing.yaml`

见 §4.3 全文（新增 `embed:` 段；`routing:` / `search:` 段保留 v1.0 字段 + 新增 hybrid/vector 字段）。

### 6.4 测试策略

- **单元测试**：用 `unittest.mock` 替换 embed client，所有 builder/router 逻辑用确定性玩具向量验证
- **集成测试 mock 模式**：`tests/conftest.py` 加 `fake_embed_api` fixture（hash-based 伪向量），整 pipeline 跑通不调真 API
- **smoke 测试（真 API）**：`pytest -m smoke`，CI 不跑、手动验证；需要 `DASHSCOPE_API_KEY` 环境变量
- **Golden set**：`tests/golden_queries.yaml`，20 条人工标注的 query → expected board/thread，CI 跑命中率

---

## §7 路线图重排

| Phase | v1.0 范围 | v2.0 调整 | 状态 |
|---|---|---|---|
| P1 | classical builder + §6.4 (a)(b) 自检 | **不动** | ✅ 已完成（main commit `c55108f`），含 sidecar 修复 `5d9b332` |
| **P2-vector** | router + 三函数 API + golden set | **vector layer**：board_vector + 初始 thread_vector（置顶） + 四函数 API（含新 `ingest_threads`） + hybrid 打分 + golden set 起步 | 待启动 |
| P3 | 增量构建 + CI | 增量 `--incremental --boards X,Y` + ingest 性能 + CI 接入 golden set + 文档 | 待启动 |
| P4 | 与 BBS_MCP 联调 | 不变：BBS_MCP 包装 4 个 tool | 待启动 |
| P5+ | 调参 / HanLP | 调参 + 探索 thread chunk 级正文向量（如未来想"看正文语义"再开放） + embedding 模型迭代评估 | — |

### 7.1 P2-vector 工作量预估

约 12-15 个 TDD 任务，比 P1 的 14 任务略多。能复用 P1 的：

- `reader.py`（仍只读 crawler）
- `builder/schema.py`（仅新增 2 张表的 DDL）
- `builder/pipeline.py` 中 Phase 0 全部
- `config.py` 模式（仅加 `EmbedConfig` dataclass）
- `tests/conftest.py` 合成 crawler 数据

需新建：

- `embed/client.py` — OpenAI SDK 封装 + batch / retry / timeout
- `builder/vectors.py` — board_vector + thread_vector 构建
- `api.py` — 四公开函数
- `router/parse.py` / `router/rank.py` / `router/search.py` — hybrid 打分（v1.0 spec §3/§4 的实现，但合并 vector）
- 对应所有测试

---

## 附录 A · 与 v1.0 spec 的差异概览（速查）

| 维度 | v1.0 | v2.0 |
|---|---|---|
| 标题/正文 | 仅标题 | **仅标题（不变）** |
| 运行时 LLM/embedding | 完全无 | **每 query 调 1 次 embedding** |
| 公开 API 数 | 3 | **4**（多 `ingest_threads`） |
| index.db 表数 | 5 表 + FTS5 + map = 7 | **9**（加 board_vector + thread_vector） |
| 依赖 | jieba + sqlite3 + PyYAML | **+ numpy + openai + python-dotenv** |
| 上下游契约 | crawler 只读 | **不变**（reader 已用 immutable=1） |
| 路由打分主路径 | classical 直接 + 多跳 | **classical + vector 自适应融合** |
| 数据流模型 | 先全爬 → 后查询 | **on-demand 闭环**（agent 触发 ingest） |
