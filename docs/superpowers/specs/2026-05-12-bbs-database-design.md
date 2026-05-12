# BBS_Database 设计方案

> 版本：v1.0.0
> 日期：2026-05-12
> 状态：草案，待实现

## 概览

BBS_Database 是 BBS-MCP 服务链路的中间层：

```
BBS_Crawler  ─────只读───▶  BBS_Database  ─────Python API───▶  BBS_MCP  ─────MCP tool───▶  外部 agent
（已完成）                  （本项目）                          （待建）
```

- BBS_Crawler 负责把 BBS 站点的版面树和帖子标题/正文写进分层 SQLite（`structure.db` + `forums/<key>.db`）
- BBS_Database 在爬虫数据之上构建**版面级知识图谱索引**（`index.db`），并对外提供 3 个查询函数
- BBS_MCP 把这 3 个函数包成 MCP 工具供外部 agent 调用

**核心问题**：当用户问"张三老师怎么样"这类基于实体/话题的开放问题，agent 不应当只查"看起来名字相关"的版面——很多匿名/树洞版面声明的话题（如"情感讨论"）与实际内容（人物评价、新鲜事）严重不符。

**核心方案**：以版面为节点、以从标题抽取的话题词和实体为关联，构建稀疏图。查询时先做关键词直接匹配（第一跳），再沿话题共现边做受控的多跳扩展，把"声明不相关但内容相关"的版面拉进候选集。

**关键约束**：
- 不读 `posts.content_text`（正文），所有索引仅基于 `threads.title`
- 不依赖 embedding 模型 / LLM 运行时调用
- 经典 NLP（jieba + TF-IDF + PMI）+ 结构信号（活跃度、置顶、路由）
- 上游契约严格遵守：只读 BBS_Crawler 的 SQLite 文件

---

## §1 架构与目录布局

```
                          BBS_Crawler （已完成，只写）
                          .data/
                            structure.db   ← 全局索引：sites + nodes(树) + fetch_log
                            forums/<key>.db ← 每个顶级讨论区一个：threads + posts + ...
                                │ (只读)
                                ▼
                          ┌──────────────────────────────────────┐
                          │ BBS_Database （本项目，Python）       │
                          │                                       │
                          │  ┌──────────┐   ┌─────────────────┐  │
                          │  │ builder/ │   │ index.db        │  │
                          │  │ 离线构建 ├──▶│ - forum_profile │  │
                          │  │ 版面画像 │   │ - edge_*        │  │
                          │  └──────────┘   │ - fts5 + map    │  │
                          │                 └─────────┬───────┘  │
                          │  ┌──────────┐             │          │
                          │  │ router/  │◀────────────┘          │
                          │  │ 在线查询 │  + FTS5 on titles      │
                          │  └────┬─────┘                         │
                          │       │                               │
                          │       ▼  Python API （3 个函数）       │
                          └───────┼───────────────────────────────┘
                                  │
                                  ▼
                          BBS_MCP （空壳，下一项目）
                          把 Python API 包成 3 个 MCP tool
                                  │
                                  ▼
                              外部 agent
```

### 边界

- BBS_Database **不写** crawler 的文件（契约规定只读）；自己拥有 `index.db`
- `index.db` 是离线构建产物，可以删了重建；不存业务真理（真理在 crawler 数据）
- MCP 层不在本项目内，本项目只暴露干净的 Python API；MCP 接口形态在 §5 一起定义但实现放 BBS_MCP

### 目录布局

```
BBS_Database/
  data/
    crawler.db/          ← 软链 / 路径配置指向 BBS_Crawler 的 .data
      structure.db
      forums/...
    index.db             ← 本项目自己产出
  src/
    bbs_database/
      __init__.py
      reader.py          ← 只读连接 crawler 数据 (按 contract)
      builder/
        profile.py       ← 构建 forum_profile
        keywords.py      ← jieba + TF-IDF
        entities.py      ← 标题中的人名/课程名提取
        cooccur.py       ← 话题共现 PMI
        similar.py       ← 版面近邻 top-N
        fts.py           ← 创建 FTS5 虚表
      router/
        parse.py         ← 查询解析（jieba + 实体 + 意图）
        rank.py          ← §3 多跳路由打分
        search.py        ← §4 版面内 FTS5
        api.py           ← 对外 3 个函数
  scripts/
    rebuild_index.py     ← --full / --incremental / --boards
    eval_self_routing.py
    eval_stability.py
    eval_golden.py
    eval_with_llm.py     ← 开发期评估，运行时不调
  config/
    routing.yaml
    stopwords_zh.txt
  tests/
    golden_queries.yaml
  docs/
    结构说明/             ← (镜像 crawler 的 data-contract)
    superpowers/
      specs/
        2026-05-12-bbs-database-design.md
```

---

## §2 版面级知识图谱

### 2.1 隐喻

```
   [Forum 学院版]──has_topic(0.8)──>[Topic "张三"]<──has_topic(0.6)──[Forum 悄悄话]
       │                                  ▲                              │
       │                                  │                              │
       └──has_entity──>[Entity 张三:person]┘                              │
                                                                         │
   [Topic "老师"]<──has_topic(0.7)─────────────────────────────────[Forum 悄悄话]
       ▲
       │ co_occurs(0.5)
       │
   [Topic "讲课"]<──has_topic(0.4)──[Forum 学院版]
```

不引入 Neo4j——三张关系表在 SQLite 里表达同一个图。图小（数百版面 × 数千 topic），完全可在内存里查询。

### 2.2 节点

| 节点 | 来源 | 数量级 |
|---|---|---|
| `Forum`（版面） | `nodes` 表里 `type='board'` 的行 | 100–1000 |
| `Topic`（话题原子） | 所有标题分词后**高 IDF 的词**（剔除停用词） | 几千 |
| `Entity`（实体） | 标题里抽出的人名/课程/地名 | 几百-几千 |

Topic 不是 LDA 聚类——就是一个高 IDF 的词。简单、可解释、可调试。

### 2.3 边

| 边 | 含义 | 权重 |
|---|---|---|
| `Forum --has_topic--> Topic` | 这个版面多大程度上"拥有"这个话题 | TF-IDF |
| `Forum --has_entity--> Entity` | 这个版面提到该实体多少次 | thread_count |
| `Topic --co_occurs--> Topic` | 两个话题在同一版面共现 | PMI |
| `Forum --similar--> Forum` | 版面话题向量的余弦（预计算 top-5 邻居） | 0..1 |

### 2.4 index.db schema

```sql
-- 元信息
CREATE TABLE _meta (
  key    TEXT PRIMARY KEY,
  value  TEXT NOT NULL
);
-- 初始化：('schema_version','1.0.0'), ('algorithm_version','1.0.0'), ('built_at', ...)

-- 版面画像
CREATE TABLE forum_profile (
  board_node_id            INTEGER PRIMARY KEY,    -- 跨库引用 structure.db.nodes.id (type='board')
  site_key                 TEXT NOT NULL,
  forum_db_file            TEXT NOT NULL,          -- 沿 parent 走到 forum 节点拿到的 db_file
  name                     TEXT NOT NULL,          -- nodes.name 镜像
  path                     TEXT NOT NULL,          -- "校园生活 > 学术科技 > 计算机"
  pinned_titles            TEXT,                   -- JSON list[str]
  title_count              INTEGER NOT NULL,       -- 构建画像用到的标题数
  activity_score           REAL NOT NULL,          -- 见 §2.5
  content_signal_strength  REAL NOT NULL,          -- min(1.0, title_count/200)
  vector_norm              REAL NOT NULL,          -- TFIDF 向量 L2 范数（cosine 用）
  built_at                 TEXT NOT NULL           -- ISO 8601
);
CREATE INDEX idx_profile_site ON forum_profile(site_key);

-- 边1：Forum →[has_topic]→ Topic
CREATE TABLE edge_forum_topic (
  board_node_id    INTEGER NOT NULL,
  term             TEXT NOT NULL,
  tfidf_declared   REAL NOT NULL DEFAULT 0.0,     -- 来自 name+path+置顶
  tfidf_content    REAL NOT NULL DEFAULT 0.0,     -- 来自所有标题
  source           TEXT NOT NULL,                  -- 'declared' / 'content' / 'both'
  PRIMARY KEY (board_node_id, term)
);
CREATE INDEX idx_eft_term ON edge_forum_topic(term);

-- 边2：Forum →[has_entity]→ Entity
CREATE TABLE edge_forum_entity (
  board_node_id    INTEGER NOT NULL,
  entity           TEXT NOT NULL,
  entity_type      TEXT NOT NULL,                  -- 'person' / 'course' / 'place' / 'org'
  thread_count     INTEGER NOT NULL,
  PRIMARY KEY (board_node_id, entity, entity_type)
);
CREATE INDEX idx_efe_entity ON edge_forum_entity(entity);

-- 边3：Topic →[co_occurs]→ Topic（对称对，只存 a<b）
CREATE TABLE edge_topic_cooccur (
  term_a           TEXT NOT NULL,
  term_b           TEXT NOT NULL,
  weight           REAL NOT NULL,                  -- PMI
  PRIMARY KEY (term_a, term_b),
  CHECK (term_a < term_b)
);
CREATE INDEX idx_etc_a ON edge_topic_cooccur(term_a);
CREATE INDEX idx_etc_b ON edge_topic_cooccur(term_b);

-- 边4：Forum →[similar]→ Forum（每版面 top-5 最近邻）
CREATE TABLE edge_forum_similar (
  board_a          INTEGER NOT NULL,
  board_b          INTEGER NOT NULL,
  cosine           REAL NOT NULL,
  PRIMARY KEY (board_a, board_b)
);

-- FTS5：标题全文（jieba 预分词写入）
CREATE VIRTUAL TABLE thread_title_fts USING fts5(
  title, content=''
);
CREATE TABLE fts_map (
  rowid          INTEGER PRIMARY KEY,
  board_node_id  INTEGER NOT NULL,
  thread_id      INTEGER NOT NULL,                 -- forum.db 内 threads.id
  forum_db_file  TEXT NOT NULL
);
CREATE INDEX idx_fts_map_board ON fts_map(board_node_id);
```

### 2.5 构建流程

```
build_index():
  step 1: forum 节点 + has_topic 边
    for board in all boards:
      titles = read forum.db threads.title where board_node_id=board.id
      content_tf[board] = Counter(token for t in titles for token in jieba.cut_for_search(t)
                                  if token not in STOPWORDS and len(token) >= 2)
      declared_tf[board] = Counter(jieba.cut(board.name + " " + board.path + " " + " ".join(pinned_titles)))
    # 全局 DF / IDF 用 declared_tf 和 content_tf 的并集 term
    DF[term] = #boards containing term (in either declared_tf or content_tf)
    IDF[term] = log(N / (1 + DF[term]))
    for board:
      terms_union = set(content_tf[board]) | set(declared_tf[board])
      for term in terms_union:
        tfidf_declared = declared_tf[board].get(term, 0) * IDF[term]
        tfidf_content  = content_tf[board].get(term, 0)  * IDF[term]
        source = ('both' if term in declared_tf[board] and term in content_tf[board]
                  else 'declared' if term in declared_tf[board]
                  else 'content')
        if tfidf_declared + tfidf_content > 0:
          write edge_forum_topic(board.id, term, tfidf_declared, tfidf_content, source)
      vector_norm = sqrt(sum( (tfidf_declared + tfidf_content)^2 for terms_union ))
      write forum_profile(...)

  step 2: has_entity 边
    for board, for title in titles[board]:
      for (entity, type) in extract_entities(title):
        forum_entity_count[board, entity, type] += 1
    bulk insert edge_forum_entity

  step 3: co_occurs 边
    for term_a < term_b with DF >= 2:
      AB = #boards containing both
      pmi = log( (AB/N) / (A/N * B/N) )
      if pmi > PMI_THRESHOLD: insert edge_topic_cooccur(...)

  step 4: similar 边
    for board:
      candidates = boards sharing >=1 high-IDF term  (via edge_forum_topic 倒排)
      top5 = top by cosine(board.vec, c.vec) / (norm * norm)
      insert edge_forum_similar(board, c, cosine) for c in top5

  step 5: FTS5
    for board, for thread in threads[board]:
      title_seg = " ".join(jieba.cut(thread.title))
      insert thread_title_fts(rowid=auto, title=title_seg)
      insert fts_map(rowid, board, thread.id, forum_db_file)
```

### 2.6 实体抽取（titles 级）

| 类型 | 提取规则 |
|---|---|
| `person` | jieba 词性 `nr` + 正则 `r"([一-龥]{2,4})(?:老师\|教授\|导师\|学长\|学姐)"` |
| `course` | 词典匹配（先空，留运维接口）+ 正则 `r"[一-龥A-Za-z]{2,}(?:课\|学\|实验)"` |
| `place` | jieba 词性 `ns` |
| `org` | jieba 词性 `nt` |

规则简单粗暴够用；未来想换 HanLP 只换 `extract_entities()` 实现即可。

### 2.7 activity_score

```
raw = log1p(stats.online) + log1p(stats.today) + 0.1 * log1p(stats.threads)
activity_score = raw / max_raw_in_dataset    # 归一化到 0..1
```

`stats` 来自 `nodes.stats` JSON 列；NULL 视为 0。

### 2.8 冷启动行为

| 边/字段 | 数据依赖 | 何时可用 |
|---|---|---|
| `forum_profile.name / path` | 仅 `nodes` 表 | BBS_Crawler 的 init 阶段一结束就有 |
| `forum_profile.pinned_titles` | `threads.is_pinned=1` | init 后立即可用 |
| `forum_profile.activity_score` | `nodes.stats` JSON | init 后立即可用 |
| `edge_forum_topic` (source=declared) | name + path + 置顶标题 | init 后立即可用 |
| `edge_forum_topic` (source=content) | `threads.title` 大量样本 | 需要爬过几轮列表页 |
| `edge_forum_entity` | `threads.title` | 同上 |
| `edge_topic_cooccur` | `edge_forum_topic` 全量 | 等内容边稳定后 |
| `edge_forum_similar` | TFIDF 向量 | 同上 |

效果渐进式：
- **T0**（爬虫只跑了 init）：只能靠声明特征 + 置顶 + 活跃度路由
- **T1**（每版面 100+ 标题）：content 边开始稳定，entity 出现，多跳路由生效
- **T2**（每版面 1000+ 标题）：长尾词覆盖完整，进入稳态

打分公式靠 `content_signal_strength`（min(1, title_count/200)）显式控制冷启动权重，**避免少量标题被 TFIDF 推到首位**。

---

## §3 多跳路由打分算法

### 3.1 总流程

```
查询 "张三老师怎么样"
       │
       ▼
Step 1: 查询解析 → query_terms + query_entities + intent
       │
       ▼
Step 2: 直接打分（第一跳）→ direct_score, top-K₁ seeds
       │
       ▼
Step 3: 查询扩展（多跳）→ 沿 cooccur 找扩展 term → expansion_score
       │
       ▼
Step 4: 终合并 + 解释链路 → 排序 + evidence
```

### 3.2 Step 1 查询解析

```python
def parse_query(q: str) -> QueryRep:
    tokens = jieba.cut(q)
    INTENT_WORDS = {"怎么样", "如何", "评价", "好不好", "推荐"}
    terms = [t for t in tokens
             if t not in STOPWORDS
             and t not in INTENT_WORDS
             and len(t) >= 2]
    entities = extract_entities(q)
    intent = classify_intent(q)    # 'evaluation' / 'recent' / 'compare' / 'topic'
    return QueryRep(terms=terms, entities=entities, intent=intent)
```

`intent` 字段仅作元数据返回，不直接进入打分公式。

### 3.3 Step 2 直接打分

```
direct(b, q) =
   Σ over t in q.terms:
       α₁ · tfidf_declared(b, t)
     + α₂ · tfidf_content(b, t) · content_signal_strength(b)
 + Σ over (e, type) in q.entities:
       α₃ · log(1 + has_entity_count(b, e, type))
 + α₄ · activity_score(b)
```

默认权重：α₁=1.0, α₂=1.5, α₃=2.0, α₄=0.1。

倒排 SQL（一次拉所有候选）：

```sql
WITH q_terms(t) AS (VALUES ('张三'), ('老师')),
     q_entities(e, ty) AS (VALUES ('张三', 'person'))
SELECT
  p.board_node_id, p.name, p.path,
  COALESCE((SELECT SUM(1.0*eft.tfidf_declared + 1.5*eft.tfidf_content * p.content_signal_strength)
            FROM edge_forum_topic eft, q_terms
            WHERE eft.board_node_id = p.board_node_id AND eft.term = q_terms.t), 0.0)
  + COALESCE((SELECT SUM(2.0 * LN(1 + efe.thread_count))
              FROM edge_forum_entity efe, q_entities
              WHERE efe.board_node_id = p.board_node_id
                AND efe.entity = q_entities.e
                AND efe.entity_type = q_entities.ty), 0.0)
  + 0.1 * p.activity_score AS direct_score
FROM forum_profile p
ORDER BY direct_score DESC LIMIT 5;
```

取 top-K₁=5 当 seeds。

### 3.4 Step 3 查询扩展（多跳核心）

**3.4.1 收集候选扩展 term**

```python
def collect_expansion_terms(seeds, query_terms):
    candidates = {}    # term -> max tfidf across seeds
    for b in seeds:
        rows = exec("""
            SELECT term, MAX(tfidf_declared, tfidf_content) AS w
            FROM edge_forum_topic
            WHERE board_node_id = ?
              AND term NOT IN (...query_terms...)
            ORDER BY w DESC LIMIT 20
        """, b)
        for term, w in rows:
            candidates[term] = max(candidates.get(term, 0), w)

    expansion = []
    for term, w in candidates.items():
        cooccur = max_cooccur_with_any(term, query_terms)
        if cooccur >= PMI_THRESHOLD:
            expansion.append((term, w * cooccur))
    return sorted(expansion, key=lambda x: -x[1])[:M_expansion]
```

**关键过滤**：只保留"和原 query term 在 `edge_topic_cooccur` 里有边的"扩展词——否则 seeds 里的无关高频词会污染扩展。

**3.4.2 扩展打分**

```
expansion(b, q) = β · Σ over (t, w_exp) in expansion_terms:
                       w_exp · (α₁·tfidf_declared(b,t) + α₂·tfidf_content(b,t)·signal_strength(b))
```

β=0.5。

### 3.5 Step 4 合并 + 证据

```
final(b, q) = direct(b, q) + expansion(b, q)
```

返回结构（每个候选 board 一份）：

```python
ForumCandidate(
    board_node_id, name, path, forum_db_file,
    score=final, direct_score, expansion_score,
    activity_score, title_count, content_signal_strength,
    matched_terms=[MatchedTerm(term, source, contribution), ...],
    expanded_via=[ExpansionLink(expanded_term, via_query_term, cooccur_weight, contribution), ...]
)
```

按 score 排序，取 top-K=8。

### 3.6 示例走读："张三老师怎么样"

Step 1: `terms=["张三","老师"]`, `entities=[("张三","person")]`

Step 2 直接打分：

| board | tfidf("张三") | tfidf("老师") | entity 命中 | direct |
|---|---|---|---|---|
| 学院A | 0.85 | 0.6 | 12 thread | **5.5** |
| 学院B | 0.3 | 0.5 | 4 | 3.1 |
| 教务版 | 0 | 0.7 | 0 | 1.1 |
| 悄悄话 | 0.4 | 0.3 | 3 | 2.4 |
| 美食版 | 0 | 0.05 | 0 | 0.1 |

seeds = [学院A, 学院B, 教务版, 悄悄话, ...]

Step 3 扩展：

seeds 高权 term `{讲课, 课程, 作业, 考试, 吐槽, 食堂, 自习, ...}`，过滤后保留：

| term | cooccur(t,"老师") | 保留 |
|---|---|---|
| 讲课 | 0.7 | ✓ |
| 课程 | 0.6 | ✓ |
| 考试 | 0.5 | ✓ |
| 作业 | 0.4 | ✓ |
| 吐槽 | 0.05 | ✗ |
| 食堂 | 0.0 | ✗ |

最终：

| board | direct | expansion | final |
|---|---|---|---|
| 学院A | 5.5 | +1.8 | **7.3** |
| 学院B | 3.1 | +1.2 | 4.3 |
| 教务版 | 1.1 | +2.4 | **3.5** ↑ |
| 悄悄话 | 2.4 | +1.6 | **4.0** ↑ |
| 美食版 | 0.1 | +0.0 | 0.1 |

悄悄话靠扩展从弱直接匹配爬到第二——因为它在 cooccur 图上"讲课/老师/课程"是相邻话题，并非"被偏向匿名版面"。美食版没有相关扩展，留在末尾。

### 3.7 参数总览

| 参数 | 默认 | 说明 |
|---|---|---|
| `K1_seeds` | 5 | Step 2 取多少 seeds 进入扩展 |
| `seed_top_terms` | 20 | 每个 seed 取多少高权 term 当扩展候选 |
| `PMI_THRESHOLD` | 0.3 | cooccur 过滤阈值 |
| `M_expansion` | 10 | 最终用多少扩展 term |
| `β` | 0.5 | 扩展项整体折扣 |
| `K_final` | 8 | 最终返回多少 board |
| `α₁/α₂/α₃/α₄` | 1.0 / 1.5 / 2.0 / 0.1 | direct 打分系数 |

所有参数读自 `config/routing.yaml`，API 调用时可临时 override。

### 3.8 SQLite 函数依赖

- `MAX(a, b)` 标量形式（多参数 max）：SQLite ≥ 3.7.16（2013）。仓库 CI 应锁定运行环境 `sqlite3 --version` 至少这一档。
- `LN()`：SQLite ≥ 3.35（2021）。
- FTS5 与 `bm25()`：SQLite 编译时启用 FTS5（CPython 自带的 `_sqlite3` 模块从 3.9 起默认启用）。

---

## §4 阶段 2 — 版面内 FTS5 检索

### 4.1 任务

§3 输出 top-K 候选 board。§4 在这些 board 内对 thread 标题做全文检索，返回 thread 列表。

**只搜标题**——`posts.content_text` 不入索引。Agent 拿到 thread 后可用 `get_thread()` 拉全文。

### 4.2 FTS5 查询转译

`thread_title_fts` 用 jieba 预分词建（写入时 `title = " ".join(jieba.cut(raw))`）。查询时同样分。

```python
def build_fts_query(query_terms, expansion_terms=None):
    primary = [f'"{t}"' for t in query_terms]
    if expansion_terms:
        secondary = [f'"{t}"' for t, _ in expansion_terms[:3]]
        return f"({' OR '.join(primary)}) OR ({' OR '.join(secondary)})"
    return ' OR '.join(primary)
```

例："张三老师" + ["讲课","课程","考试"] →
`("张三" OR "老师") OR ("讲课" OR "课程" OR "考试")`

### 4.3 单版面 SQL

```sql
SELECT fts.rowid, bm25(thread_title_fts) AS fts_score,
       m.thread_id, m.board_node_id, m.forum_db_file
FROM thread_title_fts fts
JOIN fts_map m ON m.rowid = fts.rowid
WHERE thread_title_fts MATCH ?
  AND m.board_node_id = ?
ORDER BY fts_score              -- BM25 升序（越小越相关）
LIMIT ?;
```

拿到 `thread_id` 后**到对应 forum.db 拉元数据**：

```sql
SELECT id, title, author, posted_at, last_reply_at,
       reply_count, view_count, url, is_pinned
FROM threads WHERE id IN (?, ?, ...)
ORDER BY posted_at DESC;
```

### 4.4 跨版面合并

```python
def search_threads(query, top_boards, per_board_limit=20, total_limit=50):
    fts_query = build_fts_query(query.terms, query.expansion_terms)
    all_threads = []
    for b in top_boards:
        rows = index_db.exec(FTS_SQL, fts_query, b.board_node_id, per_board_limit)
        with open_forum_db_ro(b.forum_db_file) as forum_db:
            metas = forum_db.exec(META_SQL, [r.thread_id for r in rows]).fetchall()
        for row, meta in zip(rows, metas):
            combined = combine_score(b.score, row.fts_score, meta.posted_at)
            all_threads.append(ThreadHit(...))
    return sorted(all_threads, key=lambda x: -x.combined_score)[:total_limit]
```

### 4.5 复合得分

```
combined(thread, board) =
   γ₁ · normalize(board.score)
 + γ₂ · normalize(-fts_score)
 + γ₃ · recency_factor(thread.posted_at)
```

- `normalize` = 当前批内 min-max → [0,1]
- `recency_factor(t) = exp(-Δdays / τ)`，τ=180
- 默认 γ₁=0.4, γ₂=0.5, γ₃=0.1

### 4.6 边界处理

- **空结果**：某 board FTS 命中 0 条，跳过，不报错
- **FTS 查询失败**：`MATCH` 不支持单字符，`build_fts_query` 内已过滤 len<2 token
- **连接池**：按需开/关 forum.db；一个查询会话最多打开 8 个（K_final 上限），开销可接受
- **置顶帖**：和普通帖一视同仁打分；元数据中 `is_pinned` 透传，agent 自行决定如何展示

---

## §5 Python API

### 5.1 公开函数

```python
def find_forums(
    query: str,
    site_key: str = "school-bbs",
    top_k: int = 8,
    overrides: dict | None = None,
) -> list[ForumCandidate]: ...

def search_threads(
    query: str,
    site_key: str = "school-bbs",
    board_node_ids: list[int] | None = None,
    top_k_forums: int = 5,
    per_board_limit: int = 20,
    total_limit: int = 50,
) -> list[ThreadHit]: ...

def get_thread(
    forum_db_file: str,
    thread_id: int,
) -> ThreadDetail: ...
```

### 5.2 数据结构

```python
@dataclass
class MatchedTerm:
    term: str
    source: Literal['declared', 'content', 'entity']
    contribution: float

@dataclass
class ExpansionLink:
    expanded_term: str
    via_query_term: str
    cooccur_weight: float
    contribution: float

@dataclass
class ForumCandidate:
    board_node_id: int
    name: str
    path: str
    forum_db_file: str
    score: float
    direct_score: float
    expansion_score: float
    activity_score: float
    title_count: int
    content_signal_strength: float
    matched_terms: list[MatchedTerm]
    expanded_via: list[ExpansionLink]

@dataclass
class ThreadHit:
    thread_id: int
    board_node_id: int
    board_name: str
    board_path: str
    title: str
    author: str | None
    posted_at: str | None
    last_reply_at: str | None
    reply_count: int | None
    view_count: int | None
    url: str
    is_pinned: bool
    combined_score: float
    board_score: float
    fts_score: float
    routing_evidence: ForumCandidate

@dataclass
class Post:
    floor: int
    author: str
    posted_at: str | None
    content_text: str
    attachments: list[dict] | None

@dataclass
class ThreadDetail:
    thread_id: int
    board_node_id: int
    title: str
    author: str | None
    url: str
    posted_at: str | None
    posts: list[Post]
    raw: dict | None
```

### 5.3 错误体系

```python
class BBSDatabaseError(Exception):
    code: str

class IndexNotBuiltError(BBSDatabaseError):
    """index.db 不存在 / schema 版本不兼容 / 表为空"""

class EmptyQueryError(BBSDatabaseError):
    """query 分词后没有有效 token"""

class InvalidBoardError(BBSDatabaseError):
    """指定的 board_node_id 不存在或不是 board 类型"""

class ThreadNotFoundError(BBSDatabaseError):
    """thread_id 在指定 forum.db 内不存在"""

class ForumDbNotFoundError(BBSDatabaseError):
    """forum.db 文件不存在"""
```

每个错误带结构化 `code` 字段，方便 MCP 层 map 成 JSON-RPC error code。

### 5.4 配置文件

```yaml
# config/routing.yaml
data_root: "./data/crawler.db"
index_db: "./data/index.db"

build:
  min_title_length: 2
  stopwords_file: "./config/stopwords_zh.txt"
  pmi_threshold: 0.3
  similar_top_n: 5

routing:
  alpha_declared: 1.0
  alpha_content: 1.5
  alpha_entity: 2.0
  alpha_activity: 0.1
  k1_seeds: 5
  seed_top_terms: 20
  m_expansion: 10
  beta_expansion: 0.5
  k_final: 8

search:
  gamma_board: 0.4
  gamma_fts: 0.5
  gamma_recency: 0.1
  recency_tau_days: 180
  per_board_limit: 20
  total_limit: 50
```

`find_forums(overrides={"beta_expansion": 0.8})` 允许 agent 临时调宽扩展。

### 5.5 MCP tool 约定（在 BBS_MCP 实现）

```yaml
tools:
  - name: bbs_find_forums
    description: |
      Given a user question, return a ranked list of forum boards
      most likely to contain relevant threads, with reasoning.
    input_schema:
      query: string
      site_key: string (default school-bbs)
      top_k: integer (default 8)
    output: list[ForumCandidate as JSON]

  - name: bbs_search_threads
    description: |
      Full-text search thread titles, optionally constrained to specific boards.
    input_schema:
      query: string
      board_node_ids: integer[] (optional)
      site_key: string
      total_limit: integer (default 50)
    output: list[ThreadHit as JSON]

  - name: bbs_get_thread
    description: Read full content of a thread including all floors.
    input_schema:
      forum_db_file: string
      thread_id: integer
    output: ThreadDetail as JSON
```

---

## §6 增量更新 & 评估

### 6.1 重建触发

| 模式 | 命令 | 频率 |
|---|---|---|
| `--full` | `python scripts/rebuild_index.py --full` | 首次部署 / schema 升级 / 严重数据腐败修复 |
| `--incremental` | `python scripts/rebuild_index.py --incremental` | 日常，cron 每日一次 |
| `--boards 12,34` | `python scripts/rebuild_index.py --boards 12,34` | 调试 / 单版面热刷 |

### 6.2 增量算法

利用两组水位线：
- 爬虫侧：`board_crawl_state.last_crawled_at`
- 我们侧：`forum_profile.built_at`

```
incremental_build():
  dirty_boards = boards where crawler.last_crawled_at > index.built_at
  if empty: return
  if |dirty| / |all| > 0.5: escalate to full_build

  1. 重算 dirty boards 的 content_tokens
  2. 重算全局 IDF；若 IDF 漂移大 → escalate to full
  3. 重写 dirty boards 的 edge_forum_topic / edge_forum_entity
  4. 增量更新 edge_topic_cooccur（涉及 dirty 的对）
  5. 增量更新 edge_forum_similar（dirty + 它们的旧邻居）
  6. 增量更新 FTS5（按 fts_map 删旧 rowid 再插）
  7. 写 forum_profile.built_at = now
```

每步事务包裹，幂等可重跑。

### 6.3 索引版本

`_meta` 表存 `schema_version`、`algorithm_version`、`built_at`。
- `schema_version` 变 → API 拒绝运行，强制 `--full`
- `algorithm_version` 变 → 打分公式变化，建议 `--full`（不强制）

### 6.4 评估

无人工标注语料，组合四类自验证 + 一类小样本人工：

**(a) 版面名自路由**：每个 board 用 `name` 当 query，期望自己进入 top-1 / top-3
**(b) 实体路由一致性**：每个 (entity, board) 的 thread_count 最高对，期望 entity 当 query 时该 board 进 top-5
**(c) 扩展 term 质量**：开发期用 Claude API 评判扩展 term 是否同主题（一次性，结果 commit 进 config）
**(d) 漂移检测**：连续 N 次增量构建对比 top-K Jaccard 稳定性
**(e) Golden set**：`tests/golden_queries.yaml` 手工 20–50 条，CI 跑命中率

### 6.5 评估命令

```
scripts/
  rebuild_index.py
  eval_self_routing.py     → (a)(b)
  eval_stability.py        → (d)
  eval_golden.py           → (e)，CI 跑
  eval_with_llm.py         → (c)，开发期手动跑
```

CI（GitHub Actions）：

```yaml
- pytest tests/
- python scripts/eval_self_routing.py --min-top3-accuracy 0.85
- python scripts/eval_golden.py --min-hit-rate 0.7
```

### 6.6 运行时 ≠ LLM 依赖

本项目运行时**不调任何 LLM**。LLM 仅在开发期 `eval_with_llm.py` 评判扩展 term 质量，调好的 `PMI_THRESHOLD`、`M_expansion` 等参数 commit 进 `config/routing.yaml`。

这保证 BBS_Database 本身：
- 轻依赖（只需 jieba、sqlite3、PyYAML）
- 可复现（同样输入 → 同样输出）
- 无外部 API 调用 → 无网络依赖、无 API key 管理负担

### 6.7 P1 基线（2026-05-12）

首次跑通 builder 后，在 BBS_Crawler `.data` 全量（10 forums / 259 boards）上跑 `scripts/eval_self_routing.py`：

| 指标 | 值 | 备注 |
|---|---|---|
| self-name top-1 | 92.3% (239/259) | 用 board.name 作 query 命中自己 rank-1 |
| self-name top-3 | **99.6% (258/259)** | spec §6.4 (a) 目标 85%，远超 |
| entity top-5 | **99.4% (155/156)** | spec §6.4 (b)：每个 (entity, board-with-max-thread-count) 对，用 entity 作 query 命中目标 board top-5 |

仅有的 misses：
- name miss: board id 110——板面名（三字）里含高频通用词，导致直接打分被 activity 项盖过
- entity miss: 某通用词被 jieba 误识别为 `place` → board 73——该词实际是版面分类用语而非地名，不影响主路由

**何时重新 baseline：** 改 IDF 公式、改 entity 抽取规则、扩 stopword、调 α 权重——任何一项改动后跑一次 `eval_self_routing.py --json`，把数字 commit 进本节。

---

## 与上下游的边界

| 项目 | 角色 | 本项目对它的依赖 |
|---|---|---|
| BBS_Crawler | 数据生产者（写） | 只读 `structure.db` + `forums/*.db`；严格遵守其 data-contract v1.0.0；不写不改 |
| BBS_MCP | MCP 协议封装 | 本项目提供 3 个 Python 函数，MCP 项目把它们包成 tool 暴露给 agent |

跨项目共享：crawler 的 `docs/data-contract.{md,json}` 决定我们能读什么列。schema 升级 = major version bump = 我们这边代码也要升。

## 路线图

| Phase | 范围 |
|---|---|
| P1 | builder 完整跑通（§2 全部 schema 写入），覆盖 §6.4 (a)(b) 自检 |
| P2 | router（§3 + §4），完整三函数 API（§5），golden set 起步（10 条） |
| P3 | 增量构建（§6.2），CI 接入 golden set，文档完善 |
| P4 | 与 BBS_MCP 联调，agent 真实场景跑通 |
| P5+ | 调参（参数 tune），新意图类别支持，HanLP 替换实体抽取等 |
