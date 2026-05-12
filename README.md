# BBS_Database

Forum-level knowledge-graph index and intelligent routing for the BBS-MCP stack.

中文版：[`README_ch.md`](README_ch.md) · 设计方案：[`docs/superpowers/specs/2026-05-12-bbs-database-design.md`](docs/superpowers/specs/2026-05-12-bbs-database-design.md)

## What this is

The middle layer of a three-project pipeline:

```
BBS_Crawler  ───read-only──▶  BBS_Database  ───Python API──▶  BBS_MCP  ───MCP tool──▶  agent
(done)                        (this repo)                     (empty)
```

- **BBS_Crawler** writes BBS data into layered SQLite (`structure.db` + `forums/<key>.db`)
- **BBS_Database** builds a forum-level knowledge-graph index (`index.db`) on top, exposes 3 Python functions
- **BBS_MCP** wraps those functions as MCP tools for an external agent

## Why a forum-level graph

A naive RAG over BBS posts has a known failure mode: when a user asks "How is teacher Zhang", an anonymous "secret talk" board can be ignored even though it discusses teachers all the time — because its declared category is "emotional discussion", not academic.

BBS_Database addresses this with a sparse graph built from **thread titles only** (no full content):

- Each board has TF-IDF weighted edges to topic atoms (high-IDF terms from titles)
- Topic atoms have co-occurrence edges (PMI on shared boards)
- Queries first match boards directly, then expand via co-occurrence to discover topically related boards whose declared category is misleading

This is **not** "boost anonymous boards" — it's a principled multi-hop walk on a content-derived graph. See `§3` of the spec for the algorithm.

## Constraints

- **Read-only** consumer of BBS_Crawler's SQLite. Strict adherence to its `docs/结构说明/data-contract.md`.
- **Titles only** — `posts.content_text` is never indexed (cheap to build, low memory).
- **Classical NLP** — jieba + TF-IDF + PMI. No embedding models, no runtime LLM calls.
- **Python** — `sqlite3` (stdlib), `jieba`, `pyyaml`. That's it.

## Public API (planned)

```python
find_forums(query)          → ranked list of forum candidates with reasoning
search_threads(query, ...)  → ranked thread hits across selected forums
get_thread(forum_db, id)    → full thread including all floors (the only API that reads posts)
```

## Status

Design phase. Implementation will follow the phased roadmap in the spec.

## Layout

```
data/
  crawler.db/           ← (configured path to BBS_Crawler .data)
  index.db              ← built by this project
src/bbs_database/
  builder/              ← offline index construction
  router/               ← online query (parse → rank → search)
config/
  routing.yaml
docs/
  结构说明/              ← mirror of crawler's data-contract
  superpowers/specs/    ← design documents
scripts/
  rebuild_index.py
  eval_*.py
tests/
```

## Related

- BBS_Crawler: upstream data producer
- BBS_MCP: downstream MCP service
