# BBS_Database

为 BBS-MCP 服务链路提供版面级知识图谱索引和智能路由。

English: [`README.md`](README.md) · 设计方案：[`docs/superpowers/specs/2026-05-12-bbs-database-design.md`](docs/superpowers/specs/2026-05-12-bbs-database-design.md)

## 这是什么

三项目流水线中的中间层：

```
BBS_Crawler  ───只读───▶  BBS_Database  ───Python API───▶  BBS_MCP  ───MCP tool───▶  agent
（已完成）                （本项目）                      （空壳）
```

- **BBS_Crawler** 把 BBS 数据写入分层 SQLite（`structure.db` + `forums/<key>.db`）
- **BBS_Database** 在爬虫数据之上构建版面级知识图谱索引（`index.db`），暴露 3 个 Python 函数
- **BBS_MCP** 把这 3 个函数包成 MCP 工具供外部 agent 调用

## 为什么要建版面级图

朴素 RAG 直接在 BBS 帖子上检索有个典型失败模式：当用户问"张三老师怎么样"时，一个声明类别是"情感讨论"的匿名树洞版面可能完全被忽略——即便它实际上经常讨论老师、新鲜事等。

BBS_Database 的解法是**只用帖子标题**（不读正文）构建稀疏图：

- 每个版面（board）通过 TF-IDF 边连接到话题原子（高 IDF 的词）
- 话题之间通过 PMI 共现边相互连接
- 查询先做关键词直接匹配，再沿共现边受控扩展，找到那些"声明话题不相关但内容相关"的版面

这**不是**"把匿名版面排前面"这种粗暴偏置——而是在内容导出的图上做有据可依的多跳游走。算法细节见 spec 的 `§3`。

## 约束

- **只读**消费 BBS_Crawler 的 SQLite。严格遵守其 `docs/结构说明/data-contract.md`。
- **只用标题** — `posts.content_text` 不入索引（构建便宜、内存小）。
- **经典 NLP** — jieba + TF-IDF + PMI。无 embedding 模型，运行时不调 LLM。
- **Python** — `sqlite3`（标准库）、`jieba`、`pyyaml`。仅此。

## 公开 API（设计中）

```python
find_forums(query)          → 候选版面排序列表，带打分证据
search_threads(query, ...)  → 跨选定版面的 thread 命中列表
get_thread(forum_db, id)    → 完整帖子楼层（唯一会读 posts 正文的接口）
```

## 状态

设计阶段。实现按 spec 中的 P1–P5 路线图推进。

## 目录布局

```
data/
  crawler.db/           ← (配置指向 BBS_Crawler 的 .data)
  index.db              ← 本项目构建产物
src/bbs_database/
  builder/              ← 离线索引构建
  router/               ← 在线查询（解析 → 排序 → 检索）
config/
  routing.yaml
docs/
  结构说明/              ← 镜像爬虫的 data-contract
  superpowers/specs/    ← 设计文档
scripts/
  rebuild_index.py
  eval_*.py
tests/
```

## 相关项目

- BBS_Crawler：上游数据生产者
- BBS_MCP：下游 MCP 服务
