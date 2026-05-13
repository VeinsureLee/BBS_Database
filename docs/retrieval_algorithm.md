# BBS_Database 检索算法说明

> 本文档独立描述 **运行时检索算法**（不含离线建库 / embedding 入库 / 增量 ingest），
> 用于后续算法调整时作为唯一参考。代码细节请回到 [src/bbs_database/router/](../src/bbs_database/router/)。
>
> 文档对应实现版本：v2.0 向量路由层（commit `4c3f3e3` 之后）。
> 设计 spec：
> - 经典层 [docs/superpowers/specs/2026-05-12-bbs-database-design.md](superpowers/specs/2026-05-12-bbs-database-design.md)
> - 向量层 [docs/superpowers/specs/2026-05-12-bbs-database-vector-routing.md](superpowers/specs/2026-05-12-bbs-database-vector-routing.md)

---

## 0. 总览

对外暴露 4 个函数，全部走 `index.db`（只读）+ 各论坛子库 `forum_db_file`（只读）：

| 函数 | 职责 | 用到的检索逻辑 |
|---|---|---|
| `find_forums(query)` | 找最相关的 N 个版面 | **算法 A：版面路由（hybrid）** |
| `search_threads(query)` | 找最相关的 M 个帖子 | 内部先调算法 A 决定 board scope → **算法 B：帖级排序** |
| `get_thread(forum_db, tid)` | 取整帖楼层 | 直接读库，无打分 |
| `ingest_threads(...)` | 通知入库 | 与检索无关，本文档不展开 |

> 在线运行时**不调用 LLM**；只调用 1 次（find_forums）或 2 次（search_threads，内部复用）embedding API 用于 query 向量化。

数据流：

```
                          ┌──────────────────────┐
  user query (中文 / 中英) │  find_forums()       │
        │                  │   = 算法 A           │
        ▼                  └──────┬───────────────┘
  ┌──────────────────┐            │ 选 top_k 版面
  │ 算法 A：版面路由 │            ▼
  │  (hybrid fusion) │──→ list[ForumCandidate]
  └──────────────────┘            │
        │                          ▼
        │             ┌──────────────────────┐
        └────复用────▶│ search_threads()     │
                      │   = 算法 A → 算法 B   │
                      └──────┬───────────────┘
                             ▼
                       list[ThreadHit]
```

---

## 1. 数据基础（算法读取的表）

只列检索时用到的，**离线已建好**：

| 表 | 用途 |
|---|---|
| `forum_profile(board_node_id, site_key, name, path, forum_db_file, activity_score, title_count, content_signal_strength)` | 每板一行画像；`content_signal_strength ∈ [0,1]` 表示该板内容信号成熟度（用于 δ 自适应、content tfidf 折扣）|
| `edge_forum_topic(board_node_id, term, tfidf_declared, tfidf_content, source)` | 版面 ↔ 主题词边，分 declared（板名/路径）和 content（标题语料）两种权重 |
| `edge_forum_entity(board_node_id, entity, entity_type, thread_count)` | 版面 ↔ 实体边（人名/地名/机构等）|
| `edge_topic_cooccur(term_a, term_b, weight)` | 主题词共现边（`term_a < term_b` 字典序保证唯一）；`weight` ≈ PMI |
| `board_vector(board_node_id, vec)` | 每板一条 1024 维 float32 embed（板画像文本的 embed）|
| `thread_vector(board_node_id, thread_id, forum_db_file, vec)` | 每帖一条 1024 维 float32 embed（帖标题的 embed）|
| 各 `forum_*.db` 的 `threads` 表 | thread 元数据（title / author / posted_at / reply_count / ...）|

---

## 2. 算法 A：`find_forums` —— 版面路由

输入：`query`、`top_k`、`routing_cfg`、tokenizer、embed_client。
输出：`top_k` 个 `ForumCandidate`，按 `final_score` 降序。

实现：[src/bbs_database/router/hybrid.py](../src/bbs_database/router/hybrid.py)

### 2.1 总体流程（伪代码）

```
function find_forums(query, top_k):
    # ── 阶段 0：查询解析 ─────────────────────────────────
    q_terms, q_entities = parse_query(query)
        # q_terms：jieba 分词 + 停用词过滤 + 长度过滤
        # q_entities：HanLP 风格实体抽取 [(entity, type), ...]

    # ── 阶段 1A：经典直接打分 ───────────────────────────
    classic_direct = score_classical_direct(q_terms, q_entities)
        # 见 §2.2，返回 {board_id: score}

    # ── 阶段 1B：向量直接打分 ───────────────────────────
    try:
        q_vec = embed_client.embed([query])[0]
        vec_score = {}
        for (bid, board_vec) in board_vector:
            cos = cosine(board_vec, q_vec)
            vec_score[bid] = max(0, cos)        # 负余弦截断为 0
        vector_disabled = false
    except EmbedAPIError:
        vec_score = {}                          # 整路关闭
        vector_disabled = true

    # ── 阶段 2：种子选取 + 共现扩展 ─────────────────────
    classic_seeds = top k1_seeds(classic_direct)
    vec_seeds     = top k1_seeds(vec_score)
    seeds = unique_keep_order(classic_seeds ++ vec_seeds)
        # 同时取经典 + 向量 top 是 v2.0 加的；纯 v1.0 只用 classic_seeds

    classic_exp = score_classical_expansion(seeds, q_terms)
        # 见 §2.3，返回 {board_id: score}

    # ── 阶段 3：经典融合 + 归一化 ───────────────────────
    classic_total = { bid : classic_direct[bid] + classic_exp[bid]
                      for bid in union(direct, exp, vec, all_profile) }
    classic_norm = min_max_normalize(classic_total)
    vec_norm     = vec_score           # 已经 ∈ [0,1]，不再归一

    # ── 阶段 4：经典 ↔ 向量自适应融合 ────────────────────
    candidates = []
    for bid in union(...):
        prof = profile[bid]
        sig  = prof.content_signal_strength    # ∈ [0,1]

        delta = δ_cold if sig < δ_signal_threshold else δ_base
            # 冷启动期（数据少）权重偏向 vector
            # 数据稳定后 delta 回落到 base

        if vector_disabled:
            final = classic_norm[bid]          # 完全退化到经典
            delta_used = 0
        else:
            final = delta * vec_norm[bid] + (1 - delta) * classic_norm[bid]
            delta_used = delta

        candidates.append( ForumCandidate(bid, final, ..., evidence) )

    sort candidates by final desc
    top = candidates[:top_k]

    # ── 阶段 5：附加证据（仅 top_k） ─────────────────────
    attach_matched_terms(top, q_terms)
        # 在 edge_forum_topic 里查 q_terms 命中的边作为 MatchedTerm

    if not vector_disabled:
        attach_top_vector_contributing_threads(top, q_vec)
        # 每板取 cosine 最高的 3 个 thread 作为可解释证据

    return top
```

### 2.2 经典直接打分（`score_classical_direct`）

实现：[router/classical.py](../src/bbs_database/router/classical.py) `classical_direct()`

```
function score_classical_direct(q_terms, q_entities):
    score[bid] = α_activity * activity_score[bid]      # 所有板先吃一份活跃度底分

    # 主题词贡献（按板 GROUP BY，一次 SQL）
    for each (bid, sum_tfidf_declared, sum_tfidf_content)
        in edge_forum_topic where term ∈ q_terms group by bid:
        sig = profile[bid].content_signal_strength
        score[bid] +=   α_declared * sum_tfidf_declared
                      + α_content  * sum_tfidf_content * sig
        # 注意：content 路径乘 sig 表示「该版面内容画像越不可信，content 信号越打折」

    # 实体贡献
    for each (entity, type) in q_entities:
        for each (bid, thread_count) in edge_forum_entity where entity = ?, type = ?:
            score[bid] += α_entity * log(1 + thread_count)

    return sorted(score, desc)
```

> 设计意图（来自 v1.0 spec §3.3）：
> - **声明信号**（板名/路径里出现的词）权重 α_declared，绝对可信。
> - **内容信号**（板内标题语料统计）权重 α_content，但乘 `content_signal_strength` 防止小板被噪声词带偏。
> - **实体信号**单独通道，log 抑制超热实体。
> - **活跃度**作为先验底分，避免完全冷板被任何噪声词随便拉起来。

### 2.3 经典共现扩展（`score_classical_expansion`）

实现：[router/classical.py](../src/bbs_database/router/classical.py) `classical_expansion()`

```
function score_classical_expansion(seeds, q_terms):
    if seeds is empty or q_terms is empty: return {}

    # ── (1) 从种子板拉「候选扩展词」 ─────────────────
    candidates = {}                    # term -> best tfidf weight 在 seeds 中
    for bid in seeds:
        top_terms = SELECT top seed_top_terms terms from edge_forum_topic
                    where board = bid and term ∉ q_terms
                    order by max(tfidf_declared, tfidf_content) desc
        for (term, w) in top_terms:
            candidates[term] = max(candidates[term], w)

    # ── (2) 用共现表过滤：候选词必须与某个 q_term 强共现 ─
    expansion_terms = []
    for (term, w) in candidates:
        cooccur_w = 0
        for qt in q_terms:
            (a, b) = sort_lex(term, qt)
            row = SELECT weight FROM edge_topic_cooccur WHERE term_a=a AND term_b=b
            cooccur_w = max(cooccur_w, row.weight if exists else 0)
        if cooccur_w >= pmi_threshold:
            expansion_terms.append( (term, w * cooccur_w) )
            # 扩展词得分 = 它在种子板的 tfidf 权重 × 与 q_term 的共现权重

    expansion_terms = top m_expansion of expansion_terms (desc by score)

    # ── (3) 用扩展词回过全局板，重新打分 ─────────────
    score = {}
    for (bid, term, td, tc) in edge_forum_topic where term ∈ expansion_terms:
        sig = profile[bid].content_signal_strength
        per_term_weight = score_of(term)             # = w * cooccur_w
        contribution = (α_declared * td + α_content * tc * sig) * per_term_weight
        score[bid] += β * contribution               # β = beta_expansion ∈ (0,1) 打折

    return score
```

> 设计意图：
> - **种子选板** → 从种子板里学「该话题语境下还会出现哪些词」→ 用共现表确认这些词跟 query 真的相关 → 拿这些扩展词重新打分。
> - `β = 0.5` 是为了「扩展信号比直接命中信号更弱」的折扣。
> - `pmi_threshold` 控制扩展严格度，越高越保守。

### 2.4 关键超参（见 `config/routing.yaml` `routing:`）

| 参数 | 默认 | 作用 |
|---|---|---|
| `alpha_declared` | 1.0 | 板名/路径主题词权重 |
| `alpha_content` | 1.5 | 标题语料主题词权重（再乘 sig）|
| `alpha_entity` | 2.0 | 实体匹配权重 |
| `alpha_activity` | 0.1 | 活跃度底分权重 |
| `k1_seeds` | 5 | 经典/向量各取多少个种子板进入扩展 |
| `seed_top_terms` | 20 | 每个种子板取多少个 top 主题词作为候选扩展词 |
| `m_expansion` | 10 | 过滤后保留多少个扩展词参与重打分 |
| `beta_expansion` | 0.5 | 扩展路径整体折扣 |
| `pmi_threshold` | 0.3 | 共现过滤阈值（越大越严）|
| `delta_vector_base` | 0.5 | δ 稳定期取值（vector 权重）|
| `delta_vector_cold` | 0.7 | δ 冷启动期取值（vector 权重更高）|
| `delta_signal_threshold` | 0.5 | sig 低于此值视为冷启动，用 cold δ |
| `k_final` | 8 | top_k 默认值（公共 API 也接收 `top_k` 参数）|

---

## 3. 算法 B：`search_threads` —— 帖级排序

输入：`query`、`board_node_ids`（可由调用方给定，否则内部先调算法 A）、`board_score`（每板 → final_score）、`search_cfg`。
输出：`list[ThreadHit]`，按 `combined_score` 降序，受 `per_board_limit` / `total_limit` 截断。

实现：[src/bbs_database/router/search.py](../src/bbs_database/router/search.py)

### 3.1 总体流程（伪代码）

```
function search_threads(query, board_node_ids, board_score):
    # ── 阶段 0：board scope ─────────────────────────────
    if board_node_ids is None:
        candidates = find_forums(query, top_k=top_k_forums)   # 算法 A
        board_node_ids = [c.board_node_id for c in candidates]
        board_score    = {c.board_node_id: c.final_score for c in candidates}

    # ── 阶段 1：query 向量化（失败即返回空）─────────────
    try:
        q_vec = embed_client.embed([query])[0]
    except EmbedAPIError:
        return []

    # ── 阶段 2：在 scope 内拉所有 thread_vector，全量 cosine ─
    rows = SELECT (board_id, thread_id, forum_db_file, vec)
           FROM thread_vector WHERE board_id ∈ board_node_ids
    scored = []
    for (bid, tid, fdb, tv) in rows:
        cos = cosine(tv, q_vec)
        scored.append( (cos, bid, tid, fdb) )

    # ── 阶段 3：从各 forum_*.db 拉 thread 元数据 ────────
    group scored by forum_db_file
    open each forum_db_file (read-only) and fetch
        (id, title, author, posted_at, last_reply_at, reply_count, view_count, url, is_pinned)
        for thread_ids in this fdb

    # ── 阶段 4：复合打分 ────────────────────────────────
    now = utcnow()
    for each (cos, bid, tid, fdb) in scored:
        m = meta[(fdb, tid)]
        bs = board_score[bid]                       # 算法 A 给的版面分
        rec = recency(m.posted_at)                  # = exp(-Δdays / τ)，Δ<0 截断为 0
        combined =   γ_vector  * cos
                   + γ_board   * bs
                   + γ_recency * rec
        emit ThreadHit(..., combined, breakdown={vector, board, recency})

    # ── 阶段 5：截断 ────────────────────────────────────
    sort hits by combined desc
    apply per_board_limit (每板最多 N 条)
    apply total_limit     (总条数上限)
    return final_hits
```

### 3.2 recency 函数

```
function recency(posted_at, τ_days = recency_tau_days):
    if posted_at 无法解析: return 0
    Δdays = (now - posted_at) / 1 day
    if Δdays < 0: Δdays = 0          # 未来时间钳到 0 days
    return exp(-Δdays / τ_days)
```

τ=180 时：30 天前 ≈ 0.85，半年前 ≈ 0.37，一年前 ≈ 0.14。

### 3.3 关键超参（见 `config/routing.yaml` `search:`）

| 参数 | 默认 | 作用 |
|---|---|---|
| `gamma_vector` | 0.6 | 帖标题向量 cosine 权重 |
| `gamma_board` | 0.3 | 所属版面 final_score 权重（继承算法 A 的判断）|
| `gamma_recency` | 0.1 | 时效权重 |
| `recency_tau_days` | 180 | 时效半衰参数（越大越「不在意时间」）|
| `per_board_limit` | 20 | 每个 board 最多保留多少条 hit |
| `total_limit` | 50 | 总返回上限 |

---

## 4. 算法 C：`get_thread` —— 取整帖

实现：[router/thread_detail.py](../src/bbs_database/router/thread_detail.py)

**无打分逻辑**，直接读对应 forum_db 的 `threads` + `posts` 表后组装 `ThreadDetail` 返回。可视为「读路径」，不在算法可调范围内。

---

## 5. 调参 / 调整算法的钩子清单

> 下面是「想调算法时最常动的位置」，按改动成本从小到大排：

### 5.1 只改 `config/routing.yaml`（零代码）
- 想让结果**更激进 / 更保守**：调 `α_*` 比例、`β_expansion`、`pmi_threshold`。
- 想让**向量更主导**：调高 `delta_vector_base` / `delta_vector_cold`。
- 想让**热门旧帖更不容易被埋**：调高 `gamma_recency` 或调高 `recency_tau_days`。
- 想**少返回但更精**：调小 `per_board_limit`、`total_limit`、`k_final`。
- 想让**冷启动期更激进吃向量**：调高 `delta_vector_cold` 和 `delta_signal_threshold`。

### 5.2 改 hybrid.py 内的归一化策略
- 当前 classical 用 **min-max**，vector 直接用 `max(0, cos)` 不再归一。
  - 想换 z-score / rank-norm → 改 `_min_max` 或在 `vec_score` 前加同样的处理。
- 当前 vector 负 cosine 被截断到 0；想保留排序信号可去掉 `max(0, cos)`。

### 5.3 改种子选取（v2.0 引入的 hybrid seeds）
- 当前 `seeds = classic_top_k1 ++ vector_top_k1`（去重保序）。
- 可调整成「只用经典种子」「只用向量种子」「带权重的合并」。

### 5.4 改打分公式本身
- **算法 A 融合**（hybrid.py 阶段 4）：
  当前是线性 `δ·vec + (1-δ)·classic`。
  可换成乘法（geometric mean）、rank fusion（RRF）、或加 `+ε·entity_bonus`。
- **算法 B 复合分**（search.py 阶段 4）：
  当前是线性 `γ_v·cos + γ_b·board + γ_r·recency`。
  可加项：作者权威度、回帖数/浏览数对数、`is_pinned` 加分等。

### 5.5 改扩展逻辑
- `classical_expansion` 现在用「**种子板 top 词** ∩ **与 q_term PMI ≥ 阈值**」两层过滤。
  - 想做「多跳扩展」：把 expansion_terms 再当 seeds 跑一遍（注意控制 β 的连乘衰减）。
  - 想做 entity 扩展：当前完全没做，q_entities 只参与 direct 打分，不进 expansion。

### 5.6 想 fail-soft 行为变化
- 当前 embedding API 挂掉 → `find_forums` 退化到纯经典；`search_threads` 直接返回 `[]`（因为帖级排序强依赖向量）。
- 想让 `search_threads` 也 fail-soft：可在 search.py 阶段 1 catch 后改用「q_terms 过 thread title FTS5」（注意 FTS 表当前只在 index.db 用于版面层，要先确认 thread 级 FTS 是否建过）。

---

## 6. 不变量（动算法时不要破坏）

- **不访问帖子正文**：所有排序信号都来自 thread **标题** + 版面画像。正文只在 `get_thread` 阶段读出，不参与打分。设计原因见 [memory feedback_design_philosophy.md]。
- **运行时不调 LLM**：embedding 是唯一的外部模型调用。任何引入 rerank LLM 的提议属于架构变更，需要新 spec。
- **`forum_db_file` 永远只读**：检索路径绝不写入 forum 子库。
- **embedding 失败不能让 `find_forums` 整路失败**：必须降级到经典分支（`vector_disabled=true`）。

---

## 7. 评测 / 回归

- 黄金集：[tests/](../tests/) 下 smoke 标签的 10-query 测试（commit `02b7d56`）。
- 自评脚本：[scripts/eval_self_routing.py](../scripts/eval_self_routing.py)（论坛自查回流）。
- 改算法后**必跑**：`pytest -m smoke` + 自评脚本对比 top-k 命中漂移。
