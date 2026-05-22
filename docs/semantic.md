# 语义层设计 —— 生成式范式(零新节点)

> 范式不变:**同一个生成式似然 `P(text | board)` 驱动归档 / 检索 / 爬取,统计从数据里自学,不预设实体。**
>
> 落地约束:**不增加任何新的节点 label**。所有派生信号挂到已有节点 (`:Board` / `:Thread`) 的属性上;仅新增 **一条边类型 `:MEANS`**。

---

## 1. 已落地(不动)

```
:Site -+> :Forum -+> :SubForum -+> :Board -+> :Thread
:Thread -[:LOCATED_IN]-> :Board
:Thread -[:POSTED_IN]-> :Month
```

---

## 2. Schema 增量

### 2.1 节点新增 —— 0 个

不引入 `:Term` / `:Topic` / `:Person` / `:Department` 等任何 label。

### 2.2 边新增 —— 1 个

| 边 | 方向 | 含义 |
|---|---|---|
| `+[:MEANS {logp, model, built_at}]` | Thread → Board | 语义归属(top-K)|

### 2.3 属性新增

**`:Board` 上**

| Property | 类型 | 含义 |
|---|---|---|
| `top_terms` | JSON `[{term, pmi, p_t_given_b}, …]`(top 200) | 该板的"画像词"。**这是把"Term + CHARACTERIZED_BY"打平到 Board 自身上的等价表示**——查 board 就能拿到它的全部术语画像。 |
| `entropy` | float | `-Σ p(w|b)·log p(w|b)`,越高越"中性混杂" |
| `size` | int | 历史 thread 数 |
| `last_profiled_at` | datetime | 上次重算时间 |
| `dense_centroid` | float[]?(Phase 2 才填) | 板向量画像,用 thread.title_emb 平均 |

**`:Thread` 上**

| Property | 类型 | 含义 |
|---|---|---|
| `terms` | string[] | jieba+POS 抽取的标题词(每条 thread 一组,通常 3–10 个) |
| `title_emb` | float[]?(Phase 2 才填) | 标题向量 |

**所有信号都是属性 + 一条 MEANS 边。schema 图依然是 Site/Forum/SubForum/Board/Thread/Month 这 6 个 label**。

---

## 3. 模型 —— 平滑 Naive Bayes

输入文本 `x` → 抽取词集 `T(x)` → 对候选 board `b`:

```
log P(x | b) = Σ_{w ∈ T(x)}  log [ λ · P(w | b) + (1-λ) · P(w) ]
```

- `P(w | b)` 从 `Board.top_terms` 里查;不在表里则等于背景 `P(w)`
- `P(w)` 全库背景频率,存为全局缓存
- `λ=0.7` 默认

**没有"Term 节点"也能算这个公式**——`P(w | b)` 就是查一次 `Board.top_terms` 这个 JSON 属性。在 TS 里:

```ts
const profile = JSON.parse(board.top_terms) as Array<{term, p_t_given_b}>;
const map = new Map(profile.map(x => [x.term, x.p_t_given_b]));
const logp = terms.reduce((s, w) => s + Math.log(λ * (map.get(w) ?? 0) + (1-λ) * bg.get(w)), 0);
```

> Phase 2 接入 dense embedding 时,再用 `Board.dense_centroid` 与 `Thread.title_emb` 的 cosine 作为第二通道;NB · dense 两路 RRF 融合。仍然不需要新 label。

---

## 4. 三个任务,同一个公式

### 4.1 归档 —— 写 `:MEANS` 边

```
candidates = { b : b.entropy ≤ τ_entropy }    # 中性板靠 entropy 自动排除
for each thread t:
  scored = { b ∈ candidates : log P(t.terms | b) }
  top_k  = argmax_k scored                     # K=3
  MERGE (t)-[:MEANS]->(b)
```

例:
- 悄悄话里"今天食堂排骨饭难吃" → `t.terms = ["食堂","排骨饭","难吃"]` → 餐饮板 / 北邮生活 → MEANS
- 悄悄话里"张三老师讲课怎么样" → 张三在哪些板的 `top_terms` 里 PMI 高,就指向哪些板。**系统不知道"张三是人名"**,只看共现统计。

### 4.2 检索

agent 给 `query` (+ 可选 `route`):

```
# 通道 1 - NB 稀疏
score(b) = log P(query.terms | b)
top_boards = argmax_k score

# 通道 2 - dense (Phase 2)
score(b) = cos(emb(query), b.dense_centroid)

# 候选 thread = LOCATED_IN ∪ MEANS 指向 top_boards 的所有 thread
# 若有 route: 候选 board 再过滤为 R = subtree(route) ∪ {b : top_terms ∩ query.terms 显著}
```

**匿名贴跨树召回**走 MEANS 边;不需要任何 SCOPED_TO / AFFILIATED_WITH 配置。

### 4.3 爬取

```
yield_prior(b) = COUNT(t : LOCATED_IN(t,b) ∧ ∃ m∈R: MEANS(t,m))
                 / COUNT(t : LOCATED_IN(t,b))

priority(b)    = yield_prior(b)
               · log(1 + staleness_days(b))
               · density(b) / cost(b)
               + ε_explore
```

冷启动用 `log P(query | b)` 替代 `yield_prior`。所有信号同源。

---

## 5. 算法流水线(TS 侧)

```
[1] Thread.terms 抽取(增量,每条新 thread 入库后跑)
    jieba.cut + POS 过滤(n/nr/ns/nt/nz/vn + ASCII≥2)
    → 停用词过滤 → df∈[3, N·0.5] 过滤 → 写 Thread.terms

[2] Board.top_terms / entropy 计算(批,每日 / 每 +N 条新 thread)
    遍历 board 下所有 thread:统计 count(w, b)、size(b)
    P(w|b) Lidstone 平滑(α=1.0)
    PMI(w,b) = log [ P(w|b) / P(w) ]
    取 top-200 by PMI · log(1+count)
    entropy = - Σ p(w|b) log p(w|b)
    写回 Board.{top_terms, entropy, size, last_profiled_at}

[3] :MEANS 写库(增量,每条新 thread 入库后跑)
    candidates = boards with entropy ≤ τ_entropy
    对每个 b ∈ candidates,用 top_terms 查 P(w|b),算 log P(t.terms|b)
    top-K MERGE :MEANS 边
```

复杂度估算:
- [1] 每条 thread: jieba 切 1 个标题 ≈ 0.5 ms
- [2] 每日全量 profile:259 板 × ~30 thread = 8k 标题统计 ≈ 数秒
- [3] 每条 thread: 259 板 × 5 词 ≈ 1k 次 Map 查找 ≈ < 1 ms

整体远低于 IO 成本。

---

## 6. 唯一人工输入

- 中文停用词表(网上现成)
- 单标量 `τ_entropy`(中性板熵阈值;先取 `mean + 1·stddev` 自适应)
- 单标量 `K`(MEANS top-K,默认 3)
- 单标量 `λ`(Jelinek-Mercer 平滑,默认 0.7)

**没有任何"实体类型 / 名册 / 课表 / 归属表"需要维护。**

---

## 7. 分阶段

| Phase | 输入 / 产出 | 验收 |
|---|---|---|
| **3a** | jieba+POS+停用词 → 写 Thread.terms 属性 | 抽 10 条 thread 人工核对 terms 不漏不杂 |
| **3b** | 板级 profile 批处理 → 写 Board.{top_terms, entropy, size} | 悄悄话 entropy 显著高于专业板;Board.top_terms 第一项符合直觉 |
| **3c** | NB 归档 → 写 `:MEANS` 边 | 10 条匿名 golden(含食堂 / 老师 / 考研)人工核对 top-3 是否合理 |
| **3d** | MCP `forum_route_intent` / `threads_by_meaning_board` 接出 | 端到端 query 走通 |
| **4** | dense embedding 通道并入 | NB ⊕ dense RRF 优于单通道 |
| **5** | `suggest_crawl_targets` 用 yield_prior 排序 | 缺数据时候选板顺序合直觉 |

> 边界:**所有派生属性(top_terms / entropy / dense_centroid / terms / title_emb)+ MEANS 边全删,系统仅靠物理图 + 字面匹配仍能用**。语义是增益,不是依赖。

---

## 8. 不在本设计内

- 跨站点同名实体合并
- 用户偏好排序
- LLM 总结 board(可读性问题,不是算法问题)
- 实时索引(批处理 profile 已够)
