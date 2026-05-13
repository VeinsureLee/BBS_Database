# BBS_Database 建库与入库算法说明

> 本文档独立描述 **三条写路径**：
> 1. **算法 D：离线建库** — 全量重建 `index.db`（一次性/周期性）
> 2. **算法 E：Embedding 入库** — 算法 D 内的向量阶段 + 内部复用的构建函数
> 3. **算法 F：增量 ingest** — agent 让 crawler 爬完新帖后，单独把新 thread 的向量补进 `index.db`
>
> 与 [retrieval_algorithm.md](retrieval_algorithm.md) 互补：那份只讲在线检索，这份只讲离线/异步写入。
> 代码细节回到 [src/bbs_database/builder/](../src/bbs_database/builder/) / [src/bbs_database/embed/](../src/bbs_database/embed/) / [src/bbs_database/ingest.py](../src/bbs_database/ingest.py)。

---

## 0. 总览

```
                           ┌──────────────────────────┐
   crawler.db (只读)       │   算法 D：离线建库        │
   structure.db ─────────▶ │   build_index(cfg)        │
   forum_*.db              │                           │
                           │   ├─ Phase 0：经典索引    │ ──┐
                           │   ├─ Phase 1：board 向量  │   │
                           │   └─ Phase 2：thread 向量  │   │
                           └──────────────────────────┘   │
                                       │                   │
                                       ▼                   │
                                  index.db (新建/覆盖)     │
                                       ▲                   │
                                       │                   │
   crawler 新爬完一批 thread           │                   │
                ▼                       │                   │
   ┌──────────────────────────┐         │                   │
   │  算法 F：增量 ingest      │         │                   │
   │  ingest_threads(fdb,tids)│─────────┘                   │
   │  仅写 thread_vector       │                              │
   └──────────────────────────┘                              │
                                                              │
   算法 E：向量入库子例程（被 D 和 F 共用，包含 EmbedClient）  ─┘
```

**读路径** vs **写路径** 的边界：

| | 读哪些库 | 写哪些库 |
|---|---|---|
| 算法 D（build） | 爬虫的 `structure.db` + 所有 `forum_*.db`（只读） | **覆盖**重建 `index.db` |
| 算法 F（ingest） | 一个 `forum_*.db` + `index.db`（查 diff） | 只往 `index.db.thread_vector` **追加**行 |
| 检索（算法 A/B/C） | `index.db` + `forum_*.db`（只读） | 永远不写 |

**绝对不变量**：
- 爬虫的所有 db 全程**只读**（用 `mode=ro&immutable=1`，连 WAL 副本都不留）。
- 算法 D 是**全量覆盖**重建：开始就 `index_db.unlink()`，期间任何中断都意味着重跑。
- 算法 F 是**幂等追加**：靠 `(forum_db_file, thread_id)` 唯一约束 + 模型签名做去重，重复调用不会双写。

---

## 1. 数据基础（写路径会接触的表）

### 1.1 输入（爬虫提供，只读）

| 表 / 字段 | 用途 |
|---|---|
| `structure.db.nodes(id, parent_id, type, name, site_key, db_file, stats)` | 论坛树；type ∈ {site, forum, board, ...}；`board` 节点是建库的最小单位 |
| `forum_*.db.threads(id, board_node_id, title, url, posted_at, is_pinned, ...)` | 每个 forum 一个 db；threads 是建库的**主语料**（注意只用 title） |

### 1.2 输出（写到 `index.db`）

DDL 在 [src/bbs_database/builder/schema.py](../src/bbs_database/builder/schema.py)。版本号：
- `SCHEMA_VERSION = "1.0.0"`
- `ALGORITHM_VERSION = "1.0.0"`

| 表 | 由哪条算法写入 |
|---|---|
| `_meta(key, value)` | D 写所有 meta，E 追加 embed_provider/model/dim |
| `forum_profile` | D（含 `content_signal_strength`、归一化后的 `activity_score`）|
| `edge_forum_topic` | D（TF-IDF 边）|
| `edge_forum_entity` | D（实体计数边）|
| `edge_topic_cooccur` | D（PMI 共现边）|
| `edge_forum_similar` | D（板间余弦相似边）|
| `thread_title_fts` + `fts_map` | D（FTS5 标题倒排）|
| `board_vector` | D Phase 1（每板一行）|
| `thread_vector` | D Phase 2（pinned thread）+ F（其余 thread）|

---

## 2. 算法 D：离线建库 `build_index(cfg)`

入口：[src/bbs_database/builder/pipeline.py](../src/bbs_database/builder/pipeline.py) `build_index()`。
触发方式：`scripts/rebuild_index.py --full`（参见 [tests/test_rebuild_index_cli.py](../tests/test_rebuild_index_cli.py)）。

### 2.1 总体流程（伪代码）

```
function build_index(cfg):
    # ── 阶段 -1：清空 ─────────────────────────────────
    delete index_db file if exists
    index_db = create new sqlite, apply all DDL from schema.py

    # ── 阶段 0：扫板 + 扫帖（一次性把所有 thread 读进内存）─
    boards = list( iter_boards(structure.db, site_key=cfg.site_key) )
        # 走 structure.db 的递归 CTE：从 board 节点向上找到 forum 祖先，
        # 拿到 forum_db_file；path = root > ... > board 用 " > " 拼

    by_board_threads = {}
    for b in boards:
        for t in iter_threads(forum_db_file=b.forum_db_file, board_node_id=b.id):
            by_board_threads[b.id].append(t)

    # ── 阶段 1：为每个板准备 declared/content token + 实体 + FTS 行 ─
    board_tokens, fts_rows, entity_counts = [], [], {}
    for b in boards:
        pinned_titles = [t.title for t in threads if t.is_pinned]
        all_titles    = [t.title for t in threads]

        declared_text   = " ".join([b.name, b.path, *pinned_titles])
        declared_tokens = tokenizer.cut(declared_text)          # 见 §2.2
        content_tokens  = []
        for title in all_titles:
            content_tokens.extend( tokenizer.cut_search(title) )
            for (ent, ty) in extract_entities(title):           # 见 §2.4
                entity_counts[(b.id, ent, ty)] += 1
            fts_rows.append((b.id, t.thread_id, title, b.forum_db_file))

        board_tokens.append(BoardTokens(b.id, declared_tokens, content_tokens))
        raw_activity[b.id] = activity_from_stats(b.stats_json)  # 见 §2.5

    # ── 阶段 2：TF-IDF（一次性算所有板）─────────────────
    kw = compute_keywords(board_tokens)         # 见 §2.3
        # kw.edges        = [(bid, term, tfidf_declared, tfidf_content, source), ...]
        # kw.vectors      = {bid: {term: td+tc}}
        # kw.vector_norm  = {bid: L2 norm}

    # ── 阶段 3：PMI 共现 ─────────────────────────────
    coo = compute_cooccur(kw.vectors,                            # 见 §2.6
                          df=kw.df, total_boards=N,
                          pmi_threshold, top_terms_per_board, min_df)

    # ── 阶段 4：板间相似 ─────────────────────────────
    sim = compute_similar(kw.vectors, kw.vector_norm, top_n)     # 见 §2.7

    # ── 阶段 5：归一化 + 写经典 ─────────────────────
    max_raw_activity = max(raw_activity.values()) or 1.0
    full_threshold   = cfg.build.content_signal_strength_full     # e.g. 200
    for b in boards:
        activity = raw_activity[b.id] / max_raw_activity         # 全局 min-max（min=0）
        signal   = min(1.0, len(threads_of(b)) / full_threshold) # 内容信号成熟度
        INSERT INTO forum_profile(... activity, signal, vector_norm[b.id] ...)

    INSERT INTO edge_forum_topic    ← kw.edges
    INSERT INTO edge_forum_entity   ← entity_counts (cnt>0)
    INSERT INTO edge_topic_cooccur  ← coo
    INSERT INTO edge_forum_similar  ← sim
    populate_fts(fts_rows)                                       # 见 §2.8

    # ── 阶段 6：（可选）板级 embedding ────────────────
    if cfg.embed.enabled:
        embed_client = EmbedClient(cfg.embed)
        build_board_vectors(...)            # 见 §3.1

        # ── 阶段 7：（可选）置顶帖级 embedding ─────────
        thread_specs = [
            spec for b in boards for t in threads_of(b)
            if (NOT cfg.embed.pinned_only_at_full_build) OR t.is_pinned
        ]
        build_thread_vectors(thread_specs, ...)   # 见 §3.2

        write embed_provider / embed_model / embed_dim into _meta
```

> **关键工程决定**（来自 spec + 代码）：
> - 全程在内存里跑完 `compute_keywords` / `compute_cooccur` / `compute_similar`，最后再批量写库。理由：板数量是 O(几百)，term 数量 O(万)，矩阵规模在内存能容下；避免重复 SQL 往返。
> - 经典阶段和向量阶段是**两个独立事务**：经典写完即 commit（一旦失败可保留经典层），向量阶段失败不会回退经典层。
> - **embed 阶段只索引 pinned thread**（默认）：剩余 thread 等 agent 上层逻辑通过 `ingest_threads` on-demand 入库。这是 v2.0 的成本控制策略，避免一次性 embedding 几十万帖。

### 2.2 分词（`tokenize.py`）

```
class Tokenizer:
    stopwords:   set[str]   # 来自 config/stopwords_zh.txt
    min_length:  int        # 默认 2

    cut(text):
        return [t for t in jieba.cut(text)
                if len(t) >= min_length and t ∉ stopwords and not is_space(t)]

    cut_search(text):
        return [t for t in jieba.cut_for_search(text)   # 更细的 n-gram
                if len(t) >= min_length and t ∉ stopwords and not is_space(t)]
```

**两种 cut 的语义**：
- `declared_tokens` 用 `cut`（精确模式）：板名/路径是短文本，避免过度分词噪声。
- `content_tokens` 用 `cut_search`（搜索模式）：标题语料用更细的切法，提高召回。

### 2.3 TF-IDF（`keywords.py`）

```
function compute_keywords(boards):
    n = len(boards)
    for b in boards:
        declared_tf[b.id] = Counter(b.declared_tokens)
        content_tf[b.id]  = Counter(b.content_tokens)

    df[term] = number of boards where term appears in declared∪content
    idf[term] = max(0, log( n / (1 + df[term]) ))
        # ── 与 spec 的差异：spec 是 log(N/(1+DF))，可能为负；
        #    实现钳到 0，原因：负 idf 会让"常见词"对该板产生"负贡献"
        #    （越常见越扣分），这与"常见词无区分度"的原意相反。
        #    钳到 0 = "常见词权重 0 但不扣分"，更稳。

    for b in boards:
        for term in declared_tf[b.id] ∪ content_tf[b.id]:
            td = declared_tf[b.id][term] * idf[term]
            tc = content_tf [b.id][term] * idf[term]
            if td + tc <= 0: continue
            source = "declared"|"content"|"both" by presence
            edge:    (b.id, term, td, tc, source)
            vec[b.id][term] = td + tc
            sq_sum         += (td + tc)^2
        vector_norm[b.id] = sqrt(sq_sum)
```

> `vector_norm` 写进 `forum_profile.vector_norm`，**当前在线检索没用上**，是 spec 预留字段。改算法时如果需要"按 norm 归一化版面分"，这就是钩子。

### 2.4 实体抽取（`entities.py`）

```
function extract_entities(text):
    out = []

    # ① 规则：人名（中文）
    for match in /([一-龥]{2,4})(?=老师|教授|导师|学长|学姐)/ :
        out.append( (match[1], "person") )

    # ② 规则：课程
    for match in /([一-龥A-Za-z]{2,}(课|学|实验))/ :
        out.append( (match[1], "course") )

    # ③ 词性：jieba.posseg
    for (word, flag) in posseg(text):
        if len(word) < 2: continue
        case flag:
            "nr" → out.append((word, "person"))
            "ns" → out.append((word, "place"))
            "nt" → out.append((word, "org"))

    deduplicate within single text   # 但是不同 text 之间不去重（计数有效）
    return out
```

**为什么先规则后词性**：规则命中（如"张三老师"）置信度更高；词性是 fallback。
**输出口径**：`(entity, type)` 二元组，type ∈ {person, course, place, org}。

### 2.5 活跃度（`pipeline._activity_score`）

```
function activity_from_stats(stats_json):
    s = parse json
    return log1p(s.online) + log1p(s.today) + 0.1 * log1p(s.threads)
        # online: 当前在线人数；today: 今日发帖；threads: 累计总帖
        # log1p 抑制头部板碾压；threads 系数 0.1 防累计量纲压过实时量
```

写库前再做一次全局 min-max（除以 `max(raw_activity)`），所以入库的 `activity_score ∈ [0, 1]`。

### 2.6 PMI 共现（`cooccur.py`）

```
function compute_cooccur(vectors, df, total_boards, pmi_threshold, top_per_board, min_df):
    co = Counter()                              # (term_a, term_b) -> 共出现板数
    for b, vec in vectors:
        candidates = [t for t in vec if df[t] >= min_df]
        candidates.sort by vec[t] desc
        top = candidates[:top_per_board]        # 每板取 top N 词
        top.sort lexicographically              # 保证 a < b
        for (a, b) in combinations(top, 2):
            co[(a, b)] += 1

    n = total_boards
    for (a, b), ab in co:
        p_ab = ab / n
        p_a  = df[a] / n
        p_b  = df[b] / n
        pmi  = log( p_ab / (p_a * p_b) )
        if pmi > pmi_threshold:
            emit (a, b, pmi)
```

> **为什么 per-board 取 top 再做 combinations**：避免对全局 term 集做 O(T²) 笛卡尔积；
> 实际意义也更合理 — 只统计「在同一板里都属于高权词」的共现，弱信号词不会污染共现表。
> term_a < term_b 的字典序约束由 DDL 的 `CHECK` 强制。

### 2.7 板间相似（`similar.py`）

```
function compute_similar(vectors, norms, top_n):
    # 倒排：term -> [(board, weight), ...]
    inv = invert vectors

    for b in boards (norm > 0):
        dot[other_board] = 0
        for (term, w) in vectors[b]:
            for (other, w2) in inv[term]:
                if other != b:
                    dot[other] += w * w2

        for other, prod in dot:
            cos = prod / (norms[b] * norms[other])
            if cos > 0:
                scored.append((other, cos))

        for (other, cos) in top_n of scored:
            emit (b, other, cos)        # 双向都发（A→B 和 B→A 都写）
```

> **当前在线检索没用 `edge_forum_similar`**，spec 预留用于"探索相邻板"/"扩展搜索范围"等扩展能力。

### 2.8 FTS5 标题索引（`fts.py`）

```
function populate_fts(threads):
    DELETE FROM thread_title_fts; DELETE FROM fts_map
    for (board, tid, title, db_file) in threads:
        segs = jieba.cut(title), drop spaces
        segmented_title = " ".join(segs) or title
        INSERT segmented_title INTO thread_title_fts → get rowid
        INSERT INTO fts_map(rowid, board, tid, db_file)
```

> **为什么用 jieba 切完空格再喂 FTS**：FTS5 默认 tokenizer 不支持中文，预先切好用空格分隔就能用默认 unicode61 分词器命中。
> **fts_map 是必要的**：FTS5 虚表里只有 title，需要 map 表把 rowid 对回 thread_id + forum_db。

---

## 3. 算法 E：Embedding 入库（共用子例程）

实现：[src/bbs_database/builder/vectors.py](../src/bbs_database/builder/vectors.py) + [src/bbs_database/embed/](../src/bbs_database/embed/)。
被算法 D（Phase 1+2）和算法 F 共同使用。

### 3.1 `build_board_vectors`（板级）

```
function build_board_vectors(cx, specs, embed_client, model):
    # ── 模型签名隔离 ──────────────────────────────
    DELETE FROM board_vector WHERE embed_model != model
        # 换模型即全部作废，避免维度/语义不一致的混杂

    existing = SELECT board_node_id FROM board_vector WHERE embed_model = model
    to_embed = [s for s in specs if s.id ∉ existing]   # 增量

    if to_embed is empty: return (already=len(specs))

    texts = [build_source_text(s) for s in to_embed]
        # = " ".join([s.name, s.path, *s.pinned_titles])

    vecs = embed_client.embed(texts)              # 见 §3.3

    INSERT INTO board_vector(bid, vec=encode(v), source_text, model, now)
        for each (s, v, txt)
```

> **板 source text 选择**（v2.0 spec §3.1）：`name + path + pinned_titles`，不放普通 thread title 是为了"每板 1 次 embed"的成本红线。

### 3.2 `build_thread_vectors`（帖级）

```
function build_thread_vectors(cx, specs, embed_client, model):
    DELETE FROM thread_vector WHERE embed_model != model
    existing = SELECT (forum_db_file, thread_id) ... WHERE model = ...
    to_embed = [s for s in specs if (s.fdb, s.tid) ∉ existing]

    if to_embed empty: return

    titles = [s.title for s in to_embed]
    vecs   = embed_client.embed(titles)
    INSERT INTO thread_vector(bid, tid, fdb, vec, model, now) ...
```

> **去重粒度**：`(forum_db_file, thread_id)`（DDL 的 UNIQUE 约束），不是 `thread_id` 单列 — 不同 forum 可能撞 id。
> **是否 commit**：函数本身不 commit；调用方（pipeline.py 用 `with cx:` / ingest.py 用 `with icx:`）负责。

### 3.3 `EmbedClient`（`embed/client.py`）

```
class EmbedClient:
    init(cfg):
        api_key = read os.environ[cfg.api_key_env]    # 默认 DASHSCOPE_API_KEY
        if api_key empty: raise EmbedConfigError
        sdk = openai.OpenAI(api_key, base_url=cfg.base_url,
                             timeout, max_retries)
            # base_url = DashScope OpenAI-compatible 兼容端点

    embed(texts):
        truncated = [t[: max_input_chars] for t in texts]   # 默认 2000 字符
        out = []
        for batch in chunks(truncated, batch_size):         # batch_size=10
            try:
                resp = sdk.embeddings.create(
                    model=cfg.model,            # text-embedding-v3
                    input=batch,
                    dimensions=cfg.dimensions,  # 1024
                )
            except Exception as e:
                raise EmbedAPIError(e)          # 包成项目内错误类型
            out.extend([d.embedding for d in resp.data])
        return out                              # list[list[float]]，长度 = len(texts)
```

> **设计细节**：
> - `batch_size=10` 是 DashScope Qwen v3 的**实际**最大批量（spec 写过 25 是错的，[config/routing.yaml](../config/routing.yaml) 注释里也强调了）。
> - SDK 自身已经做指数退避重试（`max_retries=3`），客户端层不再加自定义重试。
> - **任何**底层异常一律包成 `EmbedAPIError` 抛上去；不在本层降级，由调用方（检索路径 catch 后退化经典 / ingest 路径 catch 后记 failed_id）决定。

### 3.4 BLOB 编码（`embed/cache.py`）

```
encode_vec(list[float]) → bytes:
    np.asarray(v, dtype=float32).tobytes()
    # 1024 维 × 4 字节 = 4 KB per vec

decode_vec(bytes) → np.ndarray:
    np.frombuffer(b, dtype=float32)

decode_vecs(list[bytes]) → np.ndarray (N, 1024):
    np.stack([decode_vec(b) for b in blobs])
```

> SQLite BLOB + numpy 直存策略 — 不引 FAISS / sqlite-vec。
> 读时一次性 `SELECT vec` 反序列化进内存做暴力 cosine（见检索文档算法 A/B）。

---

## 4. 算法 F：增量 `ingest_threads`

入口：[src/bbs_database/ingest.py](../src/bbs_database/ingest.py) `ingest_threads_impl()`。
公开 API：[src/bbs_database/api.py](../src/bbs_database/api.py) `ingest_threads()`。

### 4.1 输入

| 参数 | 含义 |
|---|---|
| `forum_db_file` | 哪个 forum 的子库（相对 data_root 的路径，如 `forums/academic.db`）|
| `thread_ids` | 要 ingest 哪些 thread；`None` 表示**整库**新帖 |
| `embed_client`、`embed_model` | 与建库共用 |
| `batch_size` | 默认 25（注意：与 EmbedClient 内部的 `batch_size=10` 不同 — 这里是 ingest 层的批次，最终还会被 EmbedClient 再切成 10 一批发到 API）|

### 4.2 流程（伪代码）

```
function ingest_threads(forum_db_file, thread_ids, index_db, data_root,
                        embed_client, embed_model, batch_size):

    started = monotonic()
    fdb_path = data_root / forum_db_file
    if not fdb_path.exists():
        raise ForumDbNotFoundError    # ← 显式而非静默忽略

    icx = open(index_db, read_write)
    fcx = open_ro(fdb_path)

    # ── 阶段 1：取要 ingest 的 thread 元数据 ─────────────
    if thread_ids is None:
        rows = SELECT id, board_node_id, title FROM threads
    elif thread_ids == []:
        return IngestResult(all-zero, elapsed=now-started)    # 早返回
    else:
        rows = SELECT ... FROM threads WHERE id IN (?, ?, ...)
    requested = len(rows)

    # ── 阶段 2：diff（关键去重逻辑）─────────────────────
    existing_ids = SELECT thread_id FROM thread_vector
                   WHERE forum_db_file = ? AND embed_model = ?
    to_embed = [r for r in rows if r.id ∉ existing_ids]
    already_indexed = requested - len(to_embed)

    # ── 阶段 3：批处理 embed + 部分失败容忍 ─────────────
    newly_embedded = 0
    failed_ids = []
    for batch in chunks(to_embed, batch_size):
        titles = [r.title for r in batch]
        try:
            vecs = embed_client.embed(titles)
        except EmbedAPIError:
            failed_ids.extend(r.id for r in batch)    # 整批失败
            continue                                    # 不抛，继续下一批
        with icx:                                       # 每批单独事务
            INSERT INTO thread_vector(bid, tid, fdb, vec, model, now) ...
        newly_embedded += len(batch)

    # ── 阶段 4：返回报表 ───────────────────────────────
    return IngestResult(
        forum_db_file, requested, already_indexed, newly_embedded,
        failed       = len(failed_ids),
        failed_thread_ids = failed_ids,
        elapsed_seconds = now - started,
        estimated_cost_cny = estimate_cost(newly_embedded),  # 见 §4.3
        embed_model,
    )
```

### 4.3 成本估算

```
function estimate_cost(num_threads,
                       avg_tokens_per_title = 30,
                       price_per_million_tokens = 0.7 CNY):
    tokens = num_threads * 30
    return tokens / 1_000_000 * 0.7
```

> 写死的近似值（基于 Qwen v3 当前定价）。**只是给上层 agent 一个量级估计**，不参与任何决策；
> 价格变了直接改这两个常量。

### 4.4 关键决策

| 决策 | 原因 |
|---|---|
| 整批失败就整批跳过 + 记入 `failed_thread_ids` | 上层 agent 可以拿这个列表重试。要是按单条 catch，吞掉过多错误信息 |
| 每个 batch 独立 commit | API 故障时已成功的批次不会回退；故障率高时也能逐步累积进度 |
| 用 `(forum_db_file, thread_id, embed_model)` 三元组做 diff | 同 thread_id 跨 forum 不撞；换模型即重 embed |
| 子库不存在 → 抛 `ForumDbNotFoundError` | 调用方应该感知到，不能静默写空 |
| `thread_ids=[]` 早返回零 | 与 `None` 区别开（None = 全量，[] = 空请求）|

> **算法 F 不会**：触发任何经典层重算、写 `forum_profile`、改 FTS、改板向量。它**只追加** `thread_vector` 行。如果新帖让一个板的 `content_signal_strength` 应该上升 / 主题词权重应变 → 必须重跑算法 D。

---

## 5. 写路径关键超参（`config/routing.yaml`）

### 5.1 经典建库（`build:`）

| 参数 | 默认 | 用在哪 |
|---|---|---|
| `min_token_length` | 2 | Tokenizer 过滤短词 |
| `stopwords_file` | `./config/stopwords_zh.txt` | Tokenizer 停用词 |
| `pmi_threshold` | 0.3 | cooccur 过滤阈值 |
| `similar_top_n` | 5 | 板间相似邻居数 |
| `seed_top_terms_for_cooccur` | 50 | 每板取多少 top 词参与共现枚举 |
| `cooccur_min_df` | 2 | 共现统计时 term 最少出现的板数 |
| `content_signal_strength_full` | 200 | 满信号的 title_count 阈值；`signal = min(1, title_count/full)` |

### 5.2 Embedding（`embed:`）

| 参数 | 默认 | 用在哪 |
|---|---|---|
| `enabled` | true | 关闭则算法 D 跳过 Phase 1+2 |
| `provider` | dashscope | 仅作 meta 记录 |
| `base_url` | DashScope OpenAI 兼容端点 | EmbedClient 初始化 |
| `model` | text-embedding-v3 | 同时作为表里的 `embed_model` 签名 — 改了会全表重算 |
| `dimensions` | 1024 | 向量维度，影响 BLOB 大小 |
| `api_key_env` | DASHSCOPE_API_KEY | EmbedClient 读取的环境变量名 |
| `batch_size` | 10 | DashScope Qwen v3 实际上限 — **改之前确认 provider 限制** |
| `max_input_chars` | 2000 | 单条文本字符级截断 |
| `max_retries` | 3 | SDK 自带退避重试次数 |
| `request_timeout_s` | 30 | 单批请求超时 |
| `pinned_only_at_full_build` | true | 算法 D Phase 2 是否只 embed pinned thread（控制全量建库成本）|

---

## 6. 调整钩子清单（按改动成本排序）

### 6.1 只改 yaml（零代码）
- 想**关掉向量层全量入库**（仅建经典）：`embed.enabled = false`。
- 想**全量建库直接 embed 所有 thread**：`embed.pinned_only_at_full_build = false`（注意成本，先估 `len(threads) * 0.7 / 1M * 30 tokens`）。
- 想**共现表更稀疏 / 更密**：调 `pmi_threshold`、`seed_top_terms_for_cooccur`、`cooccur_min_df`。
- 想让**小板更快脱离冷启动**：调小 `content_signal_strength_full`（满信号阈值降低）。
- 想**换 embedding 模型 / 维度**：改 `embed.model` / `dimensions`；下次建库会因模型签名不同清空旧向量重算。

### 6.2 改打分公式（中等改动）
- **活跃度公式**（pipeline.py `_activity_score`）：当前 `log1p(online) + log1p(today) + 0.1·log1p(threads)`。
  - 想加 reply_count 维度：改公式 + 让 `iter_boards` 把更多字段带出来。
- **content_signal_strength**：当前是 `min(1, title_count / full_threshold)`。
  - 想用别的成熟度信号（如帖均长、回帖率），改 pipeline.py 阶段 5 那两行。
- **TF-IDF idf 钳到 0**：当前 `idf = max(0, log(N/(1+df)))`。
  - 想恢复原始 spec（允许负 idf）：去掉 `max(0, ...)`。代码里有原因注释。

### 6.3 改实体抽取（entities.py）
- 加新规则：往 `_PERSON_RE` / `_COURSE_RE` 旁边加；如有第 3 类（如缩写课程代码 `CS101`）开新正则。
- 改 jieba flag 映射：当前只用 nr / ns / nt，想纳入 nz（其他专名）只需加分支。

### 6.4 改向量 source text（vectors.py）
- 板向量当前 source = `name + path + pinned_titles`。
  - 想加入"top-K 高 tfidf 主题词"做语义补充：改 `build_board_source_text`。
- 帖向量当前 source = `title`。
  - 想加首楼摘要：需要在调用方（pipeline.py / ingest.py）先把摘要拼好再传进 ThreadSpec，**但要重新评估成本和不读正文的设计原则**（见 [retrieval_algorithm.md §6](retrieval_algorithm.md)）。

### 6.5 改 ingest 容错策略（ingest.py）
- 当前整批失败整批跳。想"单条 retry"：改阶段 3 的 catch，加单条重新 embed 兜底（注意 API quota）。
- 当前不删旧向量。想"已有但 embed_model 不同就重 embed"：阶段 2 的 `existing_ids` 改成精确 `(forum_db_file, thread_id, embed_model)` 已经覆盖；想跨模型保留旧的就需要改 schema 允许多模型并存（当前 schema 没禁止，但 build_thread_vectors 开头会 DELETE 不同模型的行）。
- 当前没"全量重 embed 单板"开关。要做：去 `ingest_threads_impl` 加一个 `force=True` 分支，先 DELETE 再重建。

### 6.6 想加新的离线索引（建议改 schema + pipeline）
- 步骤：① schema.py 加 DDL → ② builder/ 新模块算结果 → ③ pipeline.py 阶段 5 加 `INSERT` → ④ 提升 `SCHEMA_VERSION`。
- 注意：**老 index.db 不会自动迁移**，必须重跑 `rebuild_index.py --full`。

---

## 7. 不变量（动建库 / 入库时不要破坏）

- **爬虫库永远只读**：`open_ro` 用 `immutable=1`，不要为了"看到 live 更新"就摘掉 — 那会写 WAL 副本到爬虫目录。
- **算法 D 是覆盖重建**：开始就 `unlink()` index.db；中途 crash 必须重跑，不要尝试"断点续传"，schema 设计上没考虑半成品状态。
- **算法 F 只追加 thread_vector**：不要在 ingest 里偷偷改 `forum_profile` 或主题词边 — 那是算法 D 的责任，混在一起会让"增量 vs 全量"语义崩坏。
- **embed_model 是事实上的命名空间键**：换模型 = 全部失效。任何想"两个模型共存对比"的尝试都需要先扩 schema。
- **`thread_vector.UNIQUE(forum_db_file, thread_id)` 不能放宽**：去掉了就会双写。

---

## 8. 评测 / 回归

- 单元测试：[tests/test_keywords.py](../tests/test_keywords.py)、[tests/test_cooccur.py](../tests/test_cooccur.py)、[tests/test_similar.py](../tests/test_similar.py)、[tests/test_entities.py](../tests/test_entities.py)、[tests/test_fts.py](../tests/test_fts.py)、[tests/test_tokenize.py](../tests/test_tokenize.py)、[tests/test_pipeline.py](../tests/test_pipeline.py)。
- CLI 入口测试：[tests/test_rebuild_index_cli.py](../tests/test_rebuild_index_cli.py)。
- schema 守护：[tests/test_schema.py](../tests/test_schema.py)。
- 改建库 / 入库后**必跑**：`pytest`（默认套件 ≈ 104 测试），再跑一次 smoke 检索（见 [retrieval_algorithm.md §7](retrieval_algorithm.md#7-评测--回归)）确认下游没漂。
