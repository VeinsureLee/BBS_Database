# P2 Vector Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the embedding-based vector layer described in v2.0 spec on top of P1 — two new tables (`board_vector` / `thread_vector`), an `EmbedClient` wrapping DashScope Qwen v3, the four public Python APIs (`find_forums` / `ingest_threads` / `search_threads` / `get_thread`), and hybrid scoring that fuses classical + vector via an adaptive δ.

**Architecture:** Pure Python + sqlite3 + jieba + numpy + openai SDK (configured to talk to DashScope's OpenAI-compatible endpoint). Vectors stored as `BLOB` (1024 × float32) inside the same `index.db`. Runtime cosine via numpy matrix-mul on the in-memory full set. Embeddings called: (a) at build for board source_texts + pinned thread titles, (b) per user query, (c) on `ingest_threads()` for newly crawled threads. P1 classical path is preserved end-to-end as a hybrid arm and as a degraded fallback when the embedding API is unavailable.

**Tech Stack:** Python 3.10+, sqlite3 (stdlib FTS5), jieba, PyYAML, numpy ≥ 1.24, openai ≥ 1.0, python-dotenv ≥ 1.0, pytest.

**Spec reference:** [`docs/superpowers/specs/2026-05-12-bbs-database-vector-routing.md`](../specs/2026-05-12-bbs-database-vector-routing.md) (v2.0). P1 baseline: spec [`2026-05-12-bbs-database-design.md`](../specs/2026-05-12-bbs-database-design.md) (v1.0). P1 plan: [`2026-05-12-p1-builder.md`](2026-05-12-p1-builder.md).

**Scope (P2-vector only):**
- Spec v2.0 §2 (schema), §3 (build + ingest), §4 (online query algorithms), §5 (API + errors), §6 (config + deps + tests)
- Golden set **starter** (10 queries) per §7
- Real-data baseline recording per §7

**NOT in P2** (deferred to P3/P4+): `--incremental --boards X,Y` performance optimization, CI integration, BBS_MCP wrapper, thread-chunk-level body vectors, parameter tuning beyond defaults.

---

## File Structure

```
BBS_Database/
  pyproject.toml                            ← MODIFY: deps += openai, numpy, python-dotenv
  .env.example                              ← NEW
  .gitignore                                ← MODIFY: + .env
  config/routing.yaml                       ← MODIFY: + embed: section, + δ/γ keys

  src/bbs_database/
    __init__.py                             (unchanged, empty)
    config.py                               ← MODIFY: add EmbedConfig + δ/γ fields
    reader.py                               (unchanged from P1)

    embed/
      __init__.py                           ← NEW (empty)
      client.py                             ← NEW: EmbedClient wrapping openai SDK
      cache.py                              ← NEW: encode/decode BLOB ↔ numpy

    builder/
      schema.py                             ← MODIFY: + DDL for board_vector, thread_vector
      pipeline.py                           ← MODIFY: + Phase 1 (board embed) + Phase 2 (thread embed)
      vectors.py                            ← NEW: source_text builder + batched embed pipelines
      (others unchanged from P1)

    router/
      __init__.py                           ← NEW (empty)
      errors.py                             ← NEW: BBSDatabaseError + 8 subclasses
      types.py                              ← NEW: all dataclasses (ForumCandidate, ThreadHit, ...)
      parse.py                              ← NEW: parse_query(query) → QueryRep
      classical.py                          ← NEW: direct_score + multi-hop expansion (P1 §3.3/§3.4 ported)
      vector_rank.py                        ← NEW: cosine top-K (board + thread)
      hybrid.py                             ← NEW: find_forums impl with δ adaptive fusion
      search.py                             ← NEW: search_threads impl
      thread_detail.py                      ← NEW: get_thread impl (read forum.db + posts)

    ingest.py                               ← NEW: ingest_threads() impl
    api.py                                  ← NEW: 4 public functions

  scripts/
    rebuild_index.py                        ← MODIFY: + --no-embed flag

  tests/
    conftest.py                             ← MODIFY: + fake_embed_api fixture
    test_schema_v2.py                       ← NEW
    test_config_v2.py                       ← NEW
    test_embed_client.py                    ← NEW
    test_vector_cache.py                    ← NEW
    test_vectors_build.py                   ← NEW (board + thread builders)
    test_pipeline_v2.py                     ← NEW (phase 1 + 2 integration)
    test_rebuild_index_v2.py                ← NEW (--no-embed flag)
    test_errors.py                          ← NEW
    test_types.py                           ← NEW
    test_parse_query.py                     ← NEW
    test_classical_score.py                 ← NEW
    test_vector_rank.py                     ← NEW
    test_hybrid_find_forums.py              ← NEW
    test_search_threads.py                  ← NEW
    test_thread_detail.py                   ← NEW
    test_ingest_threads.py                  ← NEW
    test_api.py                             ← NEW (integration)
    golden_queries.yaml                     ← NEW (10 hand-labeled queries)
    test_golden.py                          ← NEW (smoke-marked, skipped without API key)
```

**Design notes locked here:**
- Each `router/` module is a pure function (or pure-ish: only opens index.db, never embeds). The single owner of the embed API is `embed/client.py`. This means all `router/` tests can use a fake embed.
- `find_forums` lives at `router/hybrid.py`. `search_threads` at `router/search.py`. They both compose primitives from `parse.py` + `classical.py` + `vector_rank.py`.
- `api.py` is the thin façade — it owns the index.db connection lifecycle and the embed client instance for one process. Importers should never bypass it.
- All vectors are 1024-dim float32. `vec BLOB = numpy.float32.tobytes()`, 4096 bytes/row.
- Numpy is used for cosine (matrix-mul over the in-memory full set). No FAISS / sqlite-vec.

---

## Task 0: Scaffold P2 (deps, env, package dirs)

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Create: `.env.example`
- Create: `src/bbs_database/embed/__init__.py` (empty)
- Create: `src/bbs_database/router/__init__.py` (empty)

- [ ] **Step 1: Add deps to `pyproject.toml`**

Replace the `dependencies` block:

```toml
dependencies = [
  "jieba>=0.42",
  "PyYAML>=6.0",
  "numpy>=1.24",
  "openai>=1.0",
  "python-dotenv>=1.0",
]
```

- [ ] **Step 2: Modify `.gitignore`**

Append before the existing `.venv/` line (keep all other lines):

```
.env
```

- [ ] **Step 3: Create `.env.example`**

```
DASHSCOPE_API_KEY=sk-your-key-here
```

- [ ] **Step 4: Create empty package dirs**

```bash
mkdir -p src/bbs_database/embed src/bbs_database/router
```

Then create these two empty (zero-byte) files:
- `src/bbs_database/embed/__init__.py`
- `src/bbs_database/router/__init__.py`

- [ ] **Step 5: Install + verify**

```
./.venv/Scripts/pip.exe install -e .[dev]
./.venv/Scripts/pytest.exe -q
```

Expected: install succeeds; all 42 existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore .env.example src/bbs_database/embed/ src/bbs_database/router/
git commit -m "chore(p2): scaffold deps + package dirs for vector layer"
```

---

## Task 1: Schema v2 — add `board_vector` and `thread_vector` tables

**Files:**
- Modify: `src/bbs_database/builder/schema.py`
- Test: `tests/test_schema_v2.py`

- [ ] **Step 1: Write the failing test**

`tests/test_schema_v2.py`:
```python
import sqlite3

from bbs_database.builder.schema import (
    ALL_DDL,
    DDL_BOARD_VECTOR,
    DDL_THREAD_VECTOR,
    DDL_TV_BOARD_IDX,
)


def _apply(tmp_path):
    db = sqlite3.connect(tmp_path / "index.db")
    for stmt in ALL_DDL:
        db.execute(stmt)
    db.commit()
    return db


def test_board_vector_and_thread_vector_tables_exist(tmp_path):
    cx = _apply(tmp_path)
    try:
        names = {r[0] for r in cx.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','virtual')")}
        assert "board_vector" in names
        assert "thread_vector" in names
    finally:
        cx.close()


def test_board_vector_pk_is_board_node_id(tmp_path):
    cx = _apply(tmp_path)
    try:
        cx.execute(
            "INSERT INTO board_vector(board_node_id, vec, source_text, embed_model, built_at) "
            "VALUES (1, x'00', 'foo', 'm', '2026-01-01')")
        # second insert with same board_node_id should violate PK
        try:
            cx.execute(
                "INSERT INTO board_vector(board_node_id, vec, source_text, embed_model, built_at) "
                "VALUES (1, x'00', 'foo', 'm', '2026-01-01')")
            cx.commit()
            assert False, "expected PK violation"
        except sqlite3.IntegrityError:
            pass
    finally:
        cx.close()


def test_thread_vector_unique_constraint_on_forum_and_thread(tmp_path):
    cx = _apply(tmp_path)
    try:
        cx.execute(
            "INSERT INTO thread_vector(board_node_id, thread_id, forum_db_file, vec, embed_model, built_at) "
            "VALUES (10, 1, 'forums/a.db', x'00', 'm', '2026-01-01')")
        try:
            cx.execute(
                "INSERT INTO thread_vector(board_node_id, thread_id, forum_db_file, vec, embed_model, built_at) "
                "VALUES (10, 1, 'forums/a.db', x'00', 'm', '2026-01-01')")
            cx.commit()
            assert False, "expected UNIQUE violation"
        except sqlite3.IntegrityError:
            pass
        # same thread_id but different forum.db must be OK
        cx.execute(
            "INSERT INTO thread_vector(board_node_id, thread_id, forum_db_file, vec, embed_model, built_at) "
            "VALUES (10, 1, 'forums/b.db', x'00', 'm', '2026-01-01')")
        cx.commit()
    finally:
        cx.close()


def test_thread_vector_has_board_index(tmp_path):
    cx = _apply(tmp_path)
    try:
        names = {r[0] for r in cx.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='thread_vector'")}
        assert "idx_tv_board" in names
    finally:
        cx.close()
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_schema_v2.py -v
```
Expected: ImportError (DDL constants don't exist).

- [ ] **Step 3: Modify `src/bbs_database/builder/schema.py`**

Append before the `ALL_DDL = [...]` list:

```python
DDL_BOARD_VECTOR = """
CREATE TABLE board_vector (
  board_node_id  INTEGER PRIMARY KEY,
  vec            BLOB NOT NULL,
  source_text    TEXT NOT NULL,
  embed_model    TEXT NOT NULL,
  built_at       TEXT NOT NULL
)
"""

DDL_THREAD_VECTOR = """
CREATE TABLE thread_vector (
  rowid          INTEGER PRIMARY KEY,
  board_node_id  INTEGER NOT NULL,
  thread_id      INTEGER NOT NULL,
  forum_db_file  TEXT NOT NULL,
  vec            BLOB NOT NULL,
  embed_model    TEXT NOT NULL,
  built_at       TEXT NOT NULL,
  UNIQUE (forum_db_file, thread_id)
)
"""

DDL_TV_BOARD_IDX = "CREATE INDEX idx_tv_board ON thread_vector(board_node_id)"
```

Then extend the `ALL_DDL` list — append these three at the end:

```python
ALL_DDL = [
    DDL_META,
    DDL_FORUM_PROFILE,
    DDL_FORUM_PROFILE_IDX,
    DDL_EDGE_FORUM_TOPIC,
    DDL_EDGE_FORUM_TOPIC_IDX,
    DDL_EDGE_FORUM_ENTITY,
    DDL_EDGE_FORUM_ENTITY_IDX,
    DDL_EDGE_TOPIC_COOCCUR,
    DDL_EDGE_TOPIC_COOCCUR_IDX_A,
    DDL_EDGE_TOPIC_COOCCUR_IDX_B,
    DDL_EDGE_FORUM_SIMILAR,
    DDL_FTS,
    DDL_FTS_MAP,
    DDL_FTS_MAP_IDX,
    DDL_BOARD_VECTOR,
    DDL_THREAD_VECTOR,
    DDL_TV_BOARD_IDX,
]
```

- [ ] **Step 4: Run test, verify it passes**

```
./.venv/Scripts/pytest.exe tests/test_schema_v2.py -v
./.venv/Scripts/pytest.exe -q
```
Expected: 4 new tests pass; total 46/46.

- [ ] **Step 5: Commit**

```bash
git add src/bbs_database/builder/schema.py tests/test_schema_v2.py
git commit -m "feat(schema): add board_vector and thread_vector tables for P2"
```

---

## Task 2: Config v2 — `EmbedConfig` + δ/γ fields

**Files:**
- Modify: `src/bbs_database/config.py`
- Test: `tests/test_config_v2.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config_v2.py`:
```python
from pathlib import Path

from bbs_database.config import Config, EmbedConfig, load_config


def _write(tmp_path: Path, embed_block: str = None) -> Path:
    if embed_block is None:
        embed_block = """
embed:
  enabled: true
  provider: dashscope
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  model: text-embedding-v3
  dimensions: 1024
  api_key_env: DASHSCOPE_API_KEY
  batch_size: 25
  max_input_chars: 2000
  max_retries: 3
  request_timeout_s: 30
  pinned_only_at_full_build: true
""".strip()
    p = tmp_path / "routing.yaml"
    p.write_text(
        "data_root: ./data\n"
        "index_db: ./data/index.db\n"
        "site_key: school-bbs\n"
        "build:\n"
        "  min_token_length: 2\n"
        "  stopwords_file: ./config/stopwords_zh.txt\n"
        "  pmi_threshold: 0.3\n"
        "  similar_top_n: 5\n"
        "  seed_top_terms_for_cooccur: 50\n"
        "  cooccur_min_df: 2\n"
        "  content_signal_strength_full: 200\n"
        "routing:\n"
        "  alpha_declared: 1.0\n"
        "  alpha_content: 1.5\n"
        "  alpha_entity: 2.0\n"
        "  alpha_activity: 0.1\n"
        "  k1_seeds: 5\n"
        "  seed_top_terms: 20\n"
        "  m_expansion: 10\n"
        "  beta_expansion: 0.5\n"
        "  k_final: 8\n"
        "  delta_vector_base: 0.5\n"
        "  delta_vector_cold: 0.7\n"
        "  delta_signal_threshold: 0.5\n"
        "search:\n"
        "  gamma_vector: 0.6\n"
        "  gamma_board: 0.3\n"
        "  gamma_recency: 0.1\n"
        "  recency_tau_days: 180\n"
        "  per_board_limit: 20\n"
        "  total_limit: 50\n"
        + embed_block + "\n",
        encoding="utf-8",
    )
    return p


def test_embed_config_loads(tmp_path):
    cfg = load_config(_write(tmp_path))
    assert isinstance(cfg.embed, EmbedConfig)
    assert cfg.embed.enabled is True
    assert cfg.embed.provider == "dashscope"
    assert cfg.embed.model == "text-embedding-v3"
    assert cfg.embed.dimensions == 1024
    assert cfg.embed.batch_size == 25
    assert cfg.embed.max_input_chars == 2000
    assert cfg.embed.pinned_only_at_full_build is True


def test_routing_section_includes_delta_fields(tmp_path):
    cfg = load_config(_write(tmp_path))
    assert cfg.routing["delta_vector_base"] == 0.5
    assert cfg.routing["delta_vector_cold"] == 0.7
    assert cfg.routing["delta_signal_threshold"] == 0.5


def test_search_section_includes_gamma_vector(tmp_path):
    cfg = load_config(_write(tmp_path))
    assert cfg.search["gamma_vector"] == 0.6
    assert cfg.search["gamma_board"] == 0.3
    assert cfg.search["gamma_recency"] == 0.1


def test_embed_section_missing_defaults_to_disabled(tmp_path):
    # Omit embed section entirely
    cfg = load_config(_write(tmp_path, embed_block="embed: {}"))
    assert cfg.embed.enabled is False
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_config_v2.py -v
```
Expected: ImportError (EmbedConfig not defined).

- [ ] **Step 3: Modify `src/bbs_database/config.py`**

Add `EmbedConfig` dataclass and extend `Config` + `load_config`:

```python
"""Load routing.yaml into typed dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class BuildConfig:
    min_token_length: int
    stopwords_file: str
    pmi_threshold: float
    similar_top_n: int
    seed_top_terms_for_cooccur: int
    cooccur_min_df: int
    content_signal_strength_full: int
    _root: Path | None = field(default=None, repr=False, compare=False, hash=False)

    @property
    def stopwords_path(self) -> Path:
        return _resolve(self.stopwords_file, self._root)


@dataclass(frozen=True)
class EmbedConfig:
    enabled: bool = False
    provider: str = ""
    base_url: str = ""
    model: str = ""
    dimensions: int = 1024
    api_key_env: str = ""
    batch_size: int = 25
    max_input_chars: int = 2000
    max_retries: int = 3
    request_timeout_s: int = 30
    pinned_only_at_full_build: bool = True


@dataclass(frozen=True)
class Config:
    data_root: str
    index_db: str
    site_key: str
    build: BuildConfig
    routing: dict
    search: dict
    embed: EmbedConfig
    _root: Path | None = field(default=None, repr=False, compare=False, hash=False)

    @property
    def data_root_path(self) -> Path:
        return _resolve(self.data_root, self._root)

    @property
    def index_db_path(self) -> Path:
        return _resolve(self.index_db, self._root)


def _resolve(p: str, root: Path | None) -> Path:
    path = Path(p)
    if path.is_absolute() or root is None:
        return path
    return (root / path).resolve()


def load_config(path: Path, root: Path | None = None) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    build_raw = raw["build"]
    build = BuildConfig(
        min_token_length=build_raw["min_token_length"],
        stopwords_file=build_raw["stopwords_file"],
        pmi_threshold=float(build_raw["pmi_threshold"]),
        similar_top_n=int(build_raw["similar_top_n"]),
        seed_top_terms_for_cooccur=int(build_raw["seed_top_terms_for_cooccur"]),
        cooccur_min_df=int(build_raw["cooccur_min_df"]),
        content_signal_strength_full=int(build_raw["content_signal_strength_full"]),
        _root=root,
    )
    embed_raw = raw.get("embed") or {}
    embed = EmbedConfig(
        enabled=bool(embed_raw.get("enabled", False)),
        provider=str(embed_raw.get("provider", "")),
        base_url=str(embed_raw.get("base_url", "")),
        model=str(embed_raw.get("model", "")),
        dimensions=int(embed_raw.get("dimensions", 1024)),
        api_key_env=str(embed_raw.get("api_key_env", "")),
        batch_size=int(embed_raw.get("batch_size", 25)),
        max_input_chars=int(embed_raw.get("max_input_chars", 2000)),
        max_retries=int(embed_raw.get("max_retries", 3)),
        request_timeout_s=int(embed_raw.get("request_timeout_s", 30)),
        pinned_only_at_full_build=bool(embed_raw.get("pinned_only_at_full_build", True)),
    )
    return Config(
        data_root=raw["data_root"],
        index_db=raw["index_db"],
        site_key=raw["site_key"],
        build=build,
        routing=raw.get("routing", {}) or {},
        search=raw.get("search", {}) or {},
        embed=embed,
        _root=root,
    )
```

- [ ] **Step 4: Update `config/routing.yaml`**

Replace its content with:

```yaml
data_root: "./data/crawler.db"
index_db: "./data/index.db"
site_key: "school-bbs"

build:
  min_token_length: 2
  stopwords_file: "./config/stopwords_zh.txt"
  pmi_threshold: 0.3
  similar_top_n: 5
  seed_top_terms_for_cooccur: 50
  cooccur_min_df: 2
  content_signal_strength_full: 200

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
  batch_size: 25
  max_input_chars: 2000
  max_retries: 3
  request_timeout_s: 30
  pinned_only_at_full_build: true
```

- [ ] **Step 5: Run tests, verify pass**

```
./.venv/Scripts/pytest.exe tests/test_config_v2.py tests/test_config.py -v
./.venv/Scripts/pytest.exe -q
```
Expected: 4 new + 3 P1 tests pass; total 49/49 (some pre-existing tests may also touch config and should still pass).

- [ ] **Step 6: Commit**

```bash
git add src/bbs_database/config.py config/routing.yaml tests/test_config_v2.py
git commit -m "feat(config): EmbedConfig + delta/gamma fields for P2"
```

---

## Task 3: `EmbedClient` (OpenAI SDK wrapper)

**Files:**
- Create: `src/bbs_database/embed/client.py`
- Test: `tests/test_embed_client.py`

- [ ] **Step 1: Write the failing test**

`tests/test_embed_client.py`:
```python
import os
from unittest.mock import MagicMock, patch

import pytest

from bbs_database.config import EmbedConfig
from bbs_database.embed.client import EmbedClient, EmbedAPIError, EmbedConfigError


def _cfg(**overrides):
    base = dict(
        enabled=True, provider="dashscope",
        base_url="https://example.test/v1",
        model="text-embedding-v3",
        dimensions=1024,
        api_key_env="TEST_EMBED_KEY",
        batch_size=25,
        max_input_chars=2000,
        max_retries=3,
        request_timeout_s=30,
        pinned_only_at_full_build=True,
    )
    base.update(overrides)
    return EmbedConfig(**base)


def test_embed_client_raises_if_api_key_env_missing(monkeypatch):
    monkeypatch.delenv("TEST_EMBED_KEY", raising=False)
    with pytest.raises(EmbedConfigError):
        EmbedClient(_cfg())


def test_embed_returns_one_vector_per_input(monkeypatch):
    monkeypatch.setenv("TEST_EMBED_KEY", "sk-test")
    client = EmbedClient(_cfg())
    fake_response = MagicMock()
    fake_response.data = [
        MagicMock(embedding=[0.1] * 1024),
        MagicMock(embedding=[0.2] * 1024),
    ]
    with patch.object(client._sdk.embeddings, "create", return_value=fake_response) as m:
        vecs = client.embed(["hello", "world"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 1024
    m.assert_called_once()
    kwargs = m.call_args.kwargs
    assert kwargs["model"] == "text-embedding-v3"
    assert kwargs["dimensions"] == 1024
    assert kwargs["input"] == ["hello", "world"]


def test_embed_batches_inputs_above_batch_size(monkeypatch):
    monkeypatch.setenv("TEST_EMBED_KEY", "sk-test")
    client = EmbedClient(_cfg(batch_size=2))
    calls = []

    def fake_create(model, input, dimensions, **_):
        calls.append(list(input))
        r = MagicMock()
        r.data = [MagicMock(embedding=[float(i)] * 1024) for i in range(len(input))]
        return r

    with patch.object(client._sdk.embeddings, "create", side_effect=fake_create):
        vecs = client.embed(["a", "b", "c", "d", "e"])
    assert len(vecs) == 5
    assert [len(c) for c in calls] == [2, 2, 1]


def test_embed_truncates_long_inputs(monkeypatch):
    monkeypatch.setenv("TEST_EMBED_KEY", "sk-test")
    client = EmbedClient(_cfg(max_input_chars=10))
    captured = {}

    def fake_create(model, input, dimensions, **_):
        captured["input"] = list(input)
        r = MagicMock()
        r.data = [MagicMock(embedding=[0.0] * 1024) for _ in input]
        return r

    with patch.object(client._sdk.embeddings, "create", side_effect=fake_create):
        client.embed(["short", "x" * 100])
    assert captured["input"] == ["short", "x" * 10]


def test_embed_wraps_sdk_exception_as_embedapierror(monkeypatch):
    monkeypatch.setenv("TEST_EMBED_KEY", "sk-test")
    client = EmbedClient(_cfg())
    with patch.object(client._sdk.embeddings, "create", side_effect=RuntimeError("boom")):
        with pytest.raises(EmbedAPIError):
            client.embed(["hello"])
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_embed_client.py -v
```
Expected: ImportError on `bbs_database.embed.client`.

- [ ] **Step 3: Implement `src/bbs_database/embed/client.py`**

```python
"""DashScope Qwen v3 (and any OpenAI-compatible) embedding client.

Wraps `openai.OpenAI` with batch dispatch, character truncation, and exception
mapping to BBS_Database's error types. The OpenAI SDK already retries 5xx/429
with exponential backoff up to `max_retries`.
"""

from __future__ import annotations

import os

from bbs_database.config import EmbedConfig


class BBSDatabaseError(Exception):
    code: str = ""


class EmbedConfigError(BBSDatabaseError):
    code = "embed_config_error"


class EmbedAPIError(BBSDatabaseError):
    code = "embed_api_error"


class EmbedClient:
    def __init__(self, cfg: EmbedConfig):
        self._cfg = cfg
        api_key = os.environ.get(cfg.api_key_env, "").strip()
        if not api_key:
            raise EmbedConfigError(
                f"environment variable {cfg.api_key_env!r} is empty or missing"
            )
        from openai import OpenAI
        self._sdk = OpenAI(
            api_key=api_key,
            base_url=cfg.base_url,
            timeout=cfg.request_timeout_s,
            max_retries=cfg.max_retries,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input. Truncates each input to max_input_chars."""
        truncated = [t[: self._cfg.max_input_chars] for t in texts]
        out: list[list[float]] = []
        bs = self._cfg.batch_size
        for i in range(0, len(truncated), bs):
            batch = truncated[i : i + bs]
            try:
                resp = self._sdk.embeddings.create(
                    model=self._cfg.model,
                    input=batch,
                    dimensions=self._cfg.dimensions,
                )
            except Exception as e:
                raise EmbedAPIError(f"embedding API call failed: {e!r}") from e
            for d in resp.data:
                out.append(list(d.embedding))
        return out
```

Note: `BBSDatabaseError` is also redefined later in `router/errors.py` as the canonical hierarchy; for now we define it in `embed/client.py` to keep this module self-contained. **Task 10** will refactor to import from `router/errors.py` instead.

- [ ] **Step 4: Run test, verify it passes**

```
./.venv/Scripts/pytest.exe tests/test_embed_client.py -v
```
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/bbs_database/embed/client.py tests/test_embed_client.py
git commit -m "feat(embed): EmbedClient wrapping OpenAI SDK + batching + truncation"
```

---

## Task 4: Vector cache (encode/decode BLOB ↔ numpy)

**Files:**
- Create: `src/bbs_database/embed/cache.py`
- Test: `tests/test_vector_cache.py`

- [ ] **Step 1: Write the failing test**

`tests/test_vector_cache.py`:
```python
import numpy as np

from bbs_database.embed.cache import encode_vec, decode_vec, decode_vecs


def test_encode_then_decode_roundtrip_preserves_values():
    vec = [0.1, -0.5, 1.0, 0.0, 3.14] + [0.0] * 1019
    blob = encode_vec(vec)
    assert isinstance(blob, bytes)
    assert len(blob) == 1024 * 4
    decoded = decode_vec(blob)
    assert isinstance(decoded, np.ndarray)
    assert decoded.dtype == np.float32
    assert decoded.shape == (1024,)
    assert np.allclose(decoded[:5], np.array([0.1, -0.5, 1.0, 0.0, 3.14], dtype=np.float32))


def test_decode_vecs_stacks_into_2d():
    v1 = [0.0] * 1024
    v2 = [1.0] * 1024
    blobs = [encode_vec(v1), encode_vec(v2)]
    arr = decode_vecs(blobs)
    assert arr.shape == (2, 1024)
    assert arr.dtype == np.float32
    assert np.allclose(arr[1], 1.0)
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_vector_cache.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/bbs_database/embed/cache.py`**

```python
"""BLOB ↔ numpy float32 helpers for vector columns."""

from __future__ import annotations

import numpy as np


def encode_vec(vec: list[float]) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def decode_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def decode_vecs(blobs: list[bytes]) -> np.ndarray:
    return np.stack([decode_vec(b) for b in blobs])
```

- [ ] **Step 4: Run test, verify it passes**

```
./.venv/Scripts/pytest.exe tests/test_vector_cache.py -v
```
Expected: 2 pass.

- [ ] **Step 5: Commit**

```bash
git add src/bbs_database/embed/cache.py tests/test_vector_cache.py
git commit -m "feat(embed): vector BLOB ↔ numpy encode/decode helpers"
```

---

## Task 5: `fake_embed_api` fixture for tests

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Add fixture to `tests/conftest.py`**

Append to existing `tests/conftest.py`:

```python
import hashlib

import numpy as np
import pytest


class FakeEmbedClient:
    """Deterministic fake EmbedClient for unit tests.
    
    By default produces hash-based vectors (same text → same vector).
    Tests can call .set(text, vec) to override specific texts with controlled vectors.
    """

    def __init__(self, dimensions: int = 1024):
        self.dimensions = dimensions
        self._overrides: dict[str, list[float]] = {}
        self.call_log: list[list[str]] = []

    def set(self, text: str, vec: list[float]) -> None:
        assert len(vec) == self.dimensions
        self._overrides[text] = vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.call_log.append(list(texts))
        out: list[list[float]] = []
        for t in texts:
            if t in self._overrides:
                out.append(list(self._overrides[t]))
            else:
                out.append(self._hash_vec(t))
        return out

    def _hash_vec(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        bytes_needed = self.dimensions * 4
        repeated = (h * (bytes_needed // len(h) + 1))[:bytes_needed]
        arr = np.frombuffer(repeated, dtype=np.uint8).astype(np.float32)
        arr = (arr - 128.0) / 128.0
        return arr.tolist()


@pytest.fixture
def fake_embed_api():
    return FakeEmbedClient(dimensions=1024)
```

- [ ] **Step 2: Sanity check**

```
./.venv/Scripts/pytest.exe -q
```
Expected: all existing tests still pass; no test references `fake_embed_api` yet.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add FakeEmbedClient fixture for deterministic embed tests"
```

---

## Task 6: `vectors.py` — board + thread vector builders

**Files:**
- Create: `src/bbs_database/builder/vectors.py`
- Test: `tests/test_vectors_build.py`

- [ ] **Step 1: Write the failing test**

`tests/test_vectors_build.py`:
```python
import json
import sqlite3

import numpy as np

from bbs_database.builder.schema import ALL_DDL
from bbs_database.builder.vectors import (
    build_board_source_text,
    build_board_vectors,
    build_thread_vectors,
    BoardSpec,
    ThreadSpec,
)


def _index_db(tmp_path):
    db = sqlite3.connect(tmp_path / "index.db")
    for stmt in ALL_DDL:
        db.execute(stmt)
    db.commit()
    return db


def test_build_board_source_text_joins_name_path_pinned():
    spec = BoardSpec(
        board_node_id=10, name="名字", path="顶 > 父 > 名字",
        pinned_titles=["公告A", "公告B"],
    )
    txt = build_board_source_text(spec)
    assert "名字" in txt
    assert "顶 > 父 > 名字" in txt
    assert "公告A" in txt
    assert "公告B" in txt


def test_build_board_vectors_writes_rows(tmp_path, fake_embed_api):
    cx = _index_db(tmp_path)
    try:
        specs = [
            BoardSpec(board_node_id=10, name="A", path="A", pinned_titles=[]),
            BoardSpec(board_node_id=20, name="B", path="B", pinned_titles=[]),
        ]
        result = build_board_vectors(cx, specs, fake_embed_api, model="m1")
        cx.commit()
        assert result.newly_embedded == 2
        assert result.already_indexed == 0
        rows = cx.execute(
            "SELECT board_node_id, length(vec), embed_model FROM board_vector"
        ).fetchall()
        assert sorted(rows) == [(10, 1024 * 4, "m1"), (20, 1024 * 4, "m1")]
    finally:
        cx.close()


def test_build_board_vectors_is_idempotent(tmp_path, fake_embed_api):
    cx = _index_db(tmp_path)
    try:
        specs = [BoardSpec(board_node_id=10, name="A", path="A", pinned_titles=[])]
        build_board_vectors(cx, specs, fake_embed_api, model="m1")
        cx.commit()
        result = build_board_vectors(cx, specs, fake_embed_api, model="m1")
        cx.commit()
        assert result.newly_embedded == 0
        assert result.already_indexed == 1
    finally:
        cx.close()


def test_build_board_vectors_clears_old_model_rows(tmp_path, fake_embed_api):
    cx = _index_db(tmp_path)
    try:
        specs = [BoardSpec(board_node_id=10, name="A", path="A", pinned_titles=[])]
        build_board_vectors(cx, specs, fake_embed_api, model="m1")
        cx.commit()
        # Switch model
        result = build_board_vectors(cx, specs, fake_embed_api, model="m2")
        cx.commit()
        rows = cx.execute("SELECT embed_model FROM board_vector").fetchall()
        assert rows == [("m2",)]
        assert result.newly_embedded == 1
    finally:
        cx.close()


def test_build_thread_vectors_writes_rows(tmp_path, fake_embed_api):
    cx = _index_db(tmp_path)
    try:
        threads = [
            ThreadSpec(board_node_id=10, thread_id=1, title="标题1", forum_db_file="forums/a.db"),
            ThreadSpec(board_node_id=10, thread_id=2, title="标题2", forum_db_file="forums/a.db"),
            ThreadSpec(board_node_id=20, thread_id=1, title="标题3", forum_db_file="forums/b.db"),
        ]
        result = build_thread_vectors(cx, threads, fake_embed_api, model="m1")
        cx.commit()
        assert result.newly_embedded == 3
        n = cx.execute("SELECT count(*) FROM thread_vector").fetchone()[0]
        assert n == 3
    finally:
        cx.close()


def test_build_thread_vectors_is_idempotent_on_unique(tmp_path, fake_embed_api):
    cx = _index_db(tmp_path)
    try:
        threads = [
            ThreadSpec(board_node_id=10, thread_id=1, title="标题1", forum_db_file="forums/a.db"),
        ]
        build_thread_vectors(cx, threads, fake_embed_api, model="m1")
        cx.commit()
        result = build_thread_vectors(cx, threads, fake_embed_api, model="m1")
        cx.commit()
        assert result.newly_embedded == 0
        assert result.already_indexed == 1
    finally:
        cx.close()
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_vectors_build.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/bbs_database/builder/vectors.py`**

```python
"""Build board-level and thread-level embeddings into index.db.

Pure functions: take an open sqlite3 connection + an embed-client-like object
(must expose .embed(texts) -> list[list[float]]) + config knobs. Caller owns
the connection lifecycle and commits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import sqlite3

from bbs_database.embed.cache import encode_vec


@dataclass
class BoardSpec:
    board_node_id: int
    name: str
    path: str
    pinned_titles: list[str] = field(default_factory=list)


@dataclass
class ThreadSpec:
    board_node_id: int
    thread_id: int
    title: str
    forum_db_file: str


@dataclass
class BuildVectorsResult:
    newly_embedded: int = 0
    already_indexed: int = 0
    failed: int = 0
    failed_keys: list = field(default_factory=list)


def build_board_source_text(spec: BoardSpec) -> str:
    parts = [spec.name, spec.path, *spec.pinned_titles]
    return " ".join(p for p in parts if p)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_board_vectors(
    cx: sqlite3.Connection,
    specs: list[BoardSpec],
    embed_client,
    *,
    model: str,
) -> BuildVectorsResult:
    # purge any rows under a different embed_model
    cx.execute("DELETE FROM board_vector WHERE embed_model != ?", (model,))
    existing = {
        row[0]
        for row in cx.execute("SELECT board_node_id FROM board_vector WHERE embed_model = ?",
                              (model,))
    }
    to_embed = [s for s in specs if s.board_node_id not in existing]
    result = BuildVectorsResult(already_indexed=len(specs) - len(to_embed))
    if not to_embed:
        return result
    texts = [build_board_source_text(s) for s in to_embed]
    vecs = embed_client.embed(texts)
    now = _now_iso()
    rows = [
        (s.board_node_id, encode_vec(v), txt, model, now)
        for s, v, txt in zip(to_embed, vecs, texts)
    ]
    cx.executemany(
        "INSERT INTO board_vector(board_node_id, vec, source_text, embed_model, built_at) "
        "VALUES (?,?,?,?,?)",
        rows,
    )
    result.newly_embedded = len(rows)
    return result


def build_thread_vectors(
    cx: sqlite3.Connection,
    specs: list[ThreadSpec],
    embed_client,
    *,
    model: str,
) -> BuildVectorsResult:
    cx.execute("DELETE FROM thread_vector WHERE embed_model != ?", (model,))
    existing = set(cx.execute(
        "SELECT forum_db_file, thread_id FROM thread_vector WHERE embed_model = ?",
        (model,),
    ).fetchall())
    to_embed = [s for s in specs if (s.forum_db_file, s.thread_id) not in existing]
    result = BuildVectorsResult(already_indexed=len(specs) - len(to_embed))
    if not to_embed:
        return result
    titles = [s.title for s in to_embed]
    vecs = embed_client.embed(titles)
    now = _now_iso()
    rows = [
        (s.board_node_id, s.thread_id, s.forum_db_file, encode_vec(v), model, now)
        for s, v in zip(to_embed, vecs)
    ]
    cx.executemany(
        "INSERT INTO thread_vector(board_node_id, thread_id, forum_db_file, "
        "vec, embed_model, built_at) VALUES (?,?,?,?,?,?)",
        rows,
    )
    result.newly_embedded = len(rows)
    return result
```

- [ ] **Step 4: Run test, verify it passes**

```
./.venv/Scripts/pytest.exe tests/test_vectors_build.py -v
```
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/bbs_database/builder/vectors.py tests/test_vectors_build.py
git commit -m "feat(builder): board + thread vector builders"
```

---

## Task 7: Pipeline integration — add Phase 1 + Phase 2 + `--no-embed`

**Files:**
- Modify: `src/bbs_database/builder/pipeline.py`
- Modify: `scripts/rebuild_index.py`
- Test: `tests/test_pipeline_v2.py`
- Test: `tests/test_rebuild_index_v2.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_pipeline_v2.py`:
```python
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from bbs_database.builder.pipeline import build_index
from bbs_database.config import load_config


def _write_config(tmp_path, crawler_root, index_db, sw, embed_enabled=True):
    p = tmp_path / "routing.yaml"
    p.write_text(
        f"""
data_root: {crawler_root.as_posix()}
index_db: {index_db.as_posix()}
site_key: school-bbs
build:
  min_token_length: 2
  stopwords_file: {sw.as_posix()}
  pmi_threshold: -1.0
  similar_top_n: 5
  seed_top_terms_for_cooccur: 20
  cooccur_min_df: 2
  content_signal_strength_full: 5
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
  enabled: {str(embed_enabled).lower()}
  provider: dashscope
  base_url: https://example.test/v1
  model: text-embedding-v3
  dimensions: 1024
  api_key_env: TEST_EMBED_KEY
  batch_size: 25
  max_input_chars: 2000
  max_retries: 3
  request_timeout_s: 30
  pinned_only_at_full_build: true
""".strip(),
        encoding="utf-8",
    )
    return p


def test_build_index_with_embed_disabled_only_runs_classical(crawler_dataset, tmp_path):
    sw = tmp_path / "sw.txt"
    sw.write_text("\n", encoding="utf-8")
    index_db = tmp_path / "index.db"
    cfg = load_config(_write_config(tmp_path, crawler_dataset["root"], index_db, sw,
                                    embed_enabled=False))
    build_index(cfg)
    cx = sqlite3.connect(index_db)
    try:
        bv = cx.execute("SELECT count(*) FROM board_vector").fetchone()[0]
        tv = cx.execute("SELECT count(*) FROM thread_vector").fetchone()[0]
        assert bv == 0 and tv == 0
        # but classical tables still populated
        fp = cx.execute("SELECT count(*) FROM forum_profile").fetchone()[0]
        assert fp == 3
    finally:
        cx.close()


def test_build_index_with_embed_enabled_uses_injected_client(crawler_dataset, tmp_path,
                                                              fake_embed_api, monkeypatch):
    monkeypatch.setenv("TEST_EMBED_KEY", "sk-test")
    sw = tmp_path / "sw.txt"
    sw.write_text("\n", encoding="utf-8")
    index_db = tmp_path / "index.db"
    cfg = load_config(_write_config(tmp_path, crawler_dataset["root"], index_db, sw))
    # Inject fake embed client through monkeypatching the factory
    from bbs_database.builder import pipeline as pipe_mod
    monkeypatch.setattr(pipe_mod, "_make_embed_client", lambda c: fake_embed_api)
    build_index(cfg)
    cx = sqlite3.connect(index_db)
    try:
        bv = cx.execute("SELECT count(*) FROM board_vector").fetchone()[0]
        tv = cx.execute("SELECT count(*) FROM thread_vector").fetchone()[0]
        assert bv == 3  # 3 boards in fixture
        # pinned_only_at_full_build=true: only pinned threads embedded
        assert tv == 2  # fixture has 2 pinned (academic + anonymous each 1)
        meta = dict(cx.execute("SELECT key, value FROM _meta"))
        assert meta["embed_provider"] == "dashscope"
        assert meta["embed_model"] == "text-embedding-v3"
        assert meta["embed_dim"] == "1024"
    finally:
        cx.close()
```

`tests/test_rebuild_index_v2.py`:
```python
import subprocess
import sqlite3
import sys
from pathlib import Path


def test_cli_no_embed_skips_vector_phase(crawler_dataset, tmp_path):
    sw = tmp_path / "sw.txt"
    sw.write_text("\n", encoding="utf-8")
    index_db = tmp_path / "index.db"
    cfg_path = tmp_path / "routing.yaml"
    cfg_path.write_text(
        f"""
data_root: {crawler_dataset['root'].as_posix()}
index_db: {index_db.as_posix()}
site_key: school-bbs
build:
  min_token_length: 2
  stopwords_file: {sw.as_posix()}
  pmi_threshold: -1.0
  similar_top_n: 5
  seed_top_terms_for_cooccur: 20
  cooccur_min_df: 2
  content_signal_strength_full: 5
routing: {{}}
search: {{}}
embed:
  enabled: true
  provider: dashscope
  base_url: https://example.test/v1
  model: text-embedding-v3
  dimensions: 1024
  api_key_env: TEST_KEY
  batch_size: 25
  max_input_chars: 2000
  max_retries: 3
  request_timeout_s: 30
  pinned_only_at_full_build: true
""".strip(),
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[1] / "scripts" / "rebuild_index.py"
    res = subprocess.run(
        [sys.executable, str(script), "--full", "--no-embed", "--config", str(cfg_path)],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    cx = sqlite3.connect(index_db)
    try:
        bv = cx.execute("SELECT count(*) FROM board_vector").fetchone()[0]
        assert bv == 0
        fp = cx.execute("SELECT count(*) FROM forum_profile").fetchone()[0]
        assert fp == 3
    finally:
        cx.close()
```

- [ ] **Step 2: Run tests, verify they fail**

```
./.venv/Scripts/pytest.exe tests/test_pipeline_v2.py tests/test_rebuild_index_v2.py -v
```
Expected: failures (no `_make_embed_client`, no `--no-embed` flag).

- [ ] **Step 3: Modify `src/bbs_database/builder/pipeline.py`**

Replace the existing `build_index` function:

```python
"""End-to-end builder: read crawler → compute → write index.db.

Phase 0: classical (P1 unchanged).
Phase 1: board_vector — one embed per board (name + path + pinned titles).
Phase 2: thread_vector — embed pinned thread titles (initial; rest comes via ingest_threads).

Drops and recreates index.db each call.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from bbs_database.config import Config
from bbs_database.builder import (
    cooccur as cooccur_mod,
    entities as entities_mod,
    fts as fts_mod,
    keywords as keywords_mod,
    similar as similar_mod,
    tokenize as tokenize_mod,
    vectors as vectors_mod,
)
from bbs_database.builder.schema import ALL_DDL, meta_inserts
from bbs_database.reader import iter_boards, iter_threads


def _activity_score(stats_json: str | None) -> float:
    if not stats_json:
        return 0.0
    try:
        s = json.loads(stats_json)
    except json.JSONDecodeError:
        return 0.0
    online = float(s.get("online") or 0)
    today = float(s.get("today") or 0)
    threads = float(s.get("threads") or 0)
    return math.log1p(online) + math.log1p(today) + 0.1 * math.log1p(threads)


def _init_index_db(path: Path) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(path)
    cx.execute("PRAGMA foreign_keys = ON")
    for stmt in ALL_DDL:
        cx.execute(stmt)
    cx.commit()
    return cx


def _make_embed_client(cfg: Config):
    """Factory for the embed client. Patched in tests."""
    from bbs_database.embed.client import EmbedClient
    return EmbedClient(cfg.embed)


def build_index(cfg: Config) -> None:
    data_root = cfg.data_root_path
    index_db = cfg.index_db_path
    tokenizer = tokenize_mod.Tokenizer(
        stopwords=tokenize_mod.load_stopwords(cfg.build.stopwords_path),
        min_length=cfg.build.min_token_length,
    )

    # ---- Phase 0: classical collect ----
    boards = list(iter_boards(data_root, site_key=cfg.site_key))
    board_records = []
    board_tokens = []
    entity_counts = defaultdict(int)
    fts_rows = []
    raw_activity = []
    by_board_threads = defaultdict(list)
    for b in boards:
        for t in iter_threads(data_root, b.forum_db_file, board_node_id=b.board_node_id):
            by_board_threads[b.board_node_id].append(t)

    for b in boards:
        threads = by_board_threads[b.board_node_id]
        pinned_titles = [t.title for t in threads if t.is_pinned]
        all_titles = [t.title for t in threads]
        declared_text = " ".join([b.name, b.path, *pinned_titles])
        declared_tokens = tokenizer.cut(declared_text)
        content_tokens = []
        for title in all_titles:
            content_tokens.extend(tokenizer.cut_search(title))
        board_tokens.append(keywords_mod.BoardTokens(
            board_node_id=b.board_node_id,
            declared_tokens=declared_tokens,
            content_tokens=content_tokens,
        ))
        for title in all_titles:
            local_seen = set()
            for ent, ty in entities_mod.extract_entities(title):
                if (ent, ty) in local_seen:
                    continue
                local_seen.add((ent, ty))
                entity_counts[(b.board_node_id, ent, ty)] += 1
        for t in threads:
            fts_rows.append((b.board_node_id, t.thread_id, t.title, b.forum_db_file))
        raw = _activity_score(b.stats_json)
        raw_activity.append(raw)
        board_records.append(dict(
            board_node_id=b.board_node_id, site_key=b.site_key,
            forum_db_file=b.forum_db_file, name=b.name, path=b.path,
            pinned_titles=pinned_titles,
            title_count=len(all_titles), raw_activity=raw,
        ))

    max_raw = max(raw_activity) if raw_activity else 1.0
    if max_raw <= 0:
        max_raw = 1.0
    full_threshold = cfg.build.content_signal_strength_full

    kw = keywords_mod.compute_keywords(board_tokens)
    coo = cooccur_mod.compute_cooccur(
        kw.vectors, df=kw.df, total_boards=max(len(board_tokens), 1),
        pmi_threshold=cfg.build.pmi_threshold,
        top_terms_per_board=cfg.build.seed_top_terms_for_cooccur,
        min_df=cfg.build.cooccur_min_df,
    )
    sim = similar_mod.compute_similar(kw.vectors, kw.vector_norm, top_n=cfg.build.similar_top_n)

    # ---- Phase 0: classical write ----
    cx = _init_index_db(index_db)
    try:
        now = datetime.now(timezone.utc).isoformat()
        with cx:
            for sql, params in meta_inserts(now):
                cx.execute(sql, params)
            for rec in board_records:
                bid = rec["board_node_id"]
                activity = rec["raw_activity"] / max_raw
                signal = min(1.0, rec["title_count"] / full_threshold) if full_threshold else 1.0
                cx.execute(
                    """INSERT INTO forum_profile(
                          board_node_id, site_key, forum_db_file, name, path,
                          pinned_titles, title_count, activity_score,
                          content_signal_strength, vector_norm, built_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (bid, rec["site_key"], rec["forum_db_file"], rec["name"], rec["path"],
                     json.dumps(rec["pinned_titles"], ensure_ascii=False),
                     rec["title_count"], activity, signal,
                     kw.vector_norm.get(bid, 0.0), now),
                )
            cx.executemany(
                "INSERT INTO edge_forum_topic(board_node_id, term, tfidf_declared, "
                "tfidf_content, source) VALUES (?,?,?,?,?)",
                kw.edges,
            )
            entity_rows = [(bid, ent, ty, cnt)
                           for ((bid, ent, ty), cnt) in entity_counts.items() if cnt > 0]
            cx.executemany(
                "INSERT INTO edge_forum_entity(board_node_id, entity, entity_type, "
                "thread_count) VALUES (?,?,?,?)",
                entity_rows,
            )
            cx.executemany(
                "INSERT INTO edge_topic_cooccur(term_a, term_b, weight) VALUES (?,?,?)",
                coo,
            )
            cx.executemany(
                "INSERT INTO edge_forum_similar(board_a, board_b, cosine) VALUES (?,?,?)",
                sim,
            )
            fts_mod.populate_fts(cx, fts_rows)

        # ---- Phase 1+2: vectors (skipped if disabled) ----
        if not cfg.embed.enabled:
            return

        embed_client = _make_embed_client(cfg)
        board_specs = [
            vectors_mod.BoardSpec(
                board_node_id=rec["board_node_id"], name=rec["name"], path=rec["path"],
                pinned_titles=rec["pinned_titles"],
            )
            for rec in board_records
        ]
        with cx:
            vectors_mod.build_board_vectors(
                cx, board_specs, embed_client, model=cfg.embed.model)

        thread_specs = []
        for b in boards:
            for t in by_board_threads[b.board_node_id]:
                if cfg.embed.pinned_only_at_full_build and not t.is_pinned:
                    continue
                thread_specs.append(vectors_mod.ThreadSpec(
                    board_node_id=b.board_node_id, thread_id=t.thread_id,
                    title=t.title, forum_db_file=b.forum_db_file,
                ))
        with cx:
            vectors_mod.build_thread_vectors(
                cx, thread_specs, embed_client, model=cfg.embed.model)

        with cx:
            cx.execute("INSERT INTO _meta(key, value) VALUES (?,?)",
                       ("embed_provider", cfg.embed.provider))
            cx.execute("INSERT INTO _meta(key, value) VALUES (?,?)",
                       ("embed_model", cfg.embed.model))
            cx.execute("INSERT INTO _meta(key, value) VALUES (?,?)",
                       ("embed_dim", str(cfg.embed.dimensions)))
    finally:
        cx.close()
```

- [ ] **Step 4: Modify `scripts/rebuild_index.py` — add `--no-embed` flag**

Replace the argparse block + main body. Full file:

```python
"""CLI entry point: rebuild index.db."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bbs_database.builder.pipeline import build_index  # noqa: E402
from bbs_database.config import load_config  # noqa: E402

try:
    from dotenv import load_dotenv  # noqa: E402
    load_dotenv()
except ImportError:
    pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rebuild BBS_Database index.db")
    parser.add_argument("--full", action="store_true",
                        help="Drop and rebuild from scratch (P1+P2 default).")
    parser.add_argument("--incremental", action="store_true", help="Reserved for P3.")
    parser.add_argument("--boards", help="Reserved for P3.")
    parser.add_argument("--no-embed", action="store_true",
                        help="Skip vector embedding phases (classical only).")
    parser.add_argument(
        "--config",
        default=str((HERE.parent / "config" / "routing.yaml").resolve()),
        help="Path to routing.yaml",
    )
    args = parser.parse_args(argv)

    if args.incremental or args.boards:
        print("--incremental / --boards is not yet supported in P1.", file=sys.stderr)
        return 2

    cfg_path = Path(args.config).resolve()
    cfg = load_config(cfg_path, root=cfg_path.parent.parent)
    if args.no_embed:
        # Override cfg.embed.enabled = False
        from dataclasses import replace
        cfg = replace(cfg, embed=replace(cfg.embed, enabled=False))
        print("building index (classical only, --no-embed) →", cfg.index_db_path)
    else:
        print("building index →", cfg.index_db_path)
    build_index(cfg)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests, verify they pass**

```
./.venv/Scripts/pytest.exe tests/test_pipeline_v2.py tests/test_rebuild_index_v2.py -v
./.venv/Scripts/pytest.exe -q
```
Expected: 3 new tests pass; total suite green.

- [ ] **Step 6: Commit**

```bash
git add src/bbs_database/builder/pipeline.py scripts/rebuild_index.py \
        tests/test_pipeline_v2.py tests/test_rebuild_index_v2.py
git commit -m "feat(pipeline): integrate vector Phase 1+2 and --no-embed flag"
```

---

## Task 8: Error hierarchy (`router/errors.py`) and refactor `embed/client.py` to import

**Files:**
- Create: `src/bbs_database/router/errors.py`
- Modify: `src/bbs_database/embed/client.py` (import errors from router)
- Test: `tests/test_errors.py`

- [ ] **Step 1: Write the failing test**

`tests/test_errors.py`:
```python
from bbs_database.router.errors import (
    BBSDatabaseError,
    IndexNotBuiltError,
    EmptyQueryError,
    InvalidBoardError,
    ThreadNotFoundError,
    ForumDbNotFoundError,
    EmbedAPIError,
    EmbedConfigError,
    VectorIndexEmptyError,
)


def test_all_errors_inherit_from_base():
    for cls in [IndexNotBuiltError, EmptyQueryError, InvalidBoardError,
                ThreadNotFoundError, ForumDbNotFoundError, EmbedAPIError,
                EmbedConfigError, VectorIndexEmptyError]:
        assert issubclass(cls, BBSDatabaseError)


def test_each_error_has_unique_code():
    codes = {
        IndexNotBuiltError.code,
        EmptyQueryError.code,
        InvalidBoardError.code,
        ThreadNotFoundError.code,
        ForumDbNotFoundError.code,
        EmbedAPIError.code,
        EmbedConfigError.code,
        VectorIndexEmptyError.code,
    }
    assert len(codes) == 8
    assert "" not in codes


def test_embed_client_imports_from_router_errors():
    # Confirms there's only one source of truth for these classes
    from bbs_database.embed import client as ec
    from bbs_database.router import errors as re
    assert ec.EmbedAPIError is re.EmbedAPIError
    assert ec.EmbedConfigError is re.EmbedConfigError
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_errors.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/bbs_database/router/errors.py`**

```python
"""Error hierarchy for BBS_Database.

Every error carries a `code` string suitable for surfacing as a JSON-RPC
error code through MCP.
"""


class BBSDatabaseError(Exception):
    code: str = "bbs_database_error"


class IndexNotBuiltError(BBSDatabaseError):
    code = "index_not_built"


class EmptyQueryError(BBSDatabaseError):
    code = "empty_query"


class InvalidBoardError(BBSDatabaseError):
    code = "invalid_board"


class ThreadNotFoundError(BBSDatabaseError):
    code = "thread_not_found"


class ForumDbNotFoundError(BBSDatabaseError):
    code = "forum_db_not_found"


class EmbedAPIError(BBSDatabaseError):
    code = "embed_api_error"


class EmbedConfigError(BBSDatabaseError):
    code = "embed_config_error"


class VectorIndexEmptyError(BBSDatabaseError):
    code = "vector_index_empty"
```

- [ ] **Step 4: Modify `src/bbs_database/embed/client.py` — remove local error defs**

Replace the top of the file (deletes the local `BBSDatabaseError`, `EmbedConfigError`, `EmbedAPIError` class definitions and replaces them with imports):

```python
"""DashScope Qwen v3 (and any OpenAI-compatible) embedding client."""

from __future__ import annotations

import os

from bbs_database.config import EmbedConfig
from bbs_database.router.errors import EmbedAPIError, EmbedConfigError


class EmbedClient:
    def __init__(self, cfg: EmbedConfig):
        self._cfg = cfg
        api_key = os.environ.get(cfg.api_key_env, "").strip()
        if not api_key:
            raise EmbedConfigError(
                f"environment variable {cfg.api_key_env!r} is empty or missing"
            )
        from openai import OpenAI
        self._sdk = OpenAI(
            api_key=api_key,
            base_url=cfg.base_url,
            timeout=cfg.request_timeout_s,
            max_retries=cfg.max_retries,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        truncated = [t[: self._cfg.max_input_chars] for t in texts]
        out: list[list[float]] = []
        bs = self._cfg.batch_size
        for i in range(0, len(truncated), bs):
            batch = truncated[i : i + bs]
            try:
                resp = self._sdk.embeddings.create(
                    model=self._cfg.model,
                    input=batch,
                    dimensions=self._cfg.dimensions,
                )
            except Exception as e:
                raise EmbedAPIError(f"embedding API call failed: {e!r}") from e
            for d in resp.data:
                out.append(list(d.embedding))
        return out
```

- [ ] **Step 5: Run tests, verify they pass**

```
./.venv/Scripts/pytest.exe tests/test_errors.py tests/test_embed_client.py -v
./.venv/Scripts/pytest.exe -q
```
Expected: 3 new tests + all 5 embed tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/bbs_database/router/errors.py src/bbs_database/embed/client.py tests/test_errors.py
git commit -m "feat(router): error hierarchy; embed client imports from it"
```

---

## Task 9: Dataclasses (`router/types.py`)

**Files:**
- Create: `src/bbs_database/router/types.py`
- Test: `tests/test_types.py`

- [ ] **Step 1: Write the failing test**

`tests/test_types.py`:
```python
from bbs_database.router.types import (
    MatchedTerm,
    ExpansionLink,
    VectorContributingThread,
    ForumCandidate,
    ThreadHit,
    IngestResult,
    Post,
    ThreadDetail,
    QueryRep,
)


def test_matched_term_dataclass():
    m = MatchedTerm(term="x", source="declared", contribution=1.2)
    assert m.term == "x" and m.source == "declared"


def test_forum_candidate_minimum_fields():
    c = ForumCandidate(
        board_node_id=1, site_key="s", name="n", path="p", forum_db_file="f",
        final_score=1.0, classic_direct_score=0.5, classic_expansion_score=0.0,
        vector_cosine=0.7, delta_used=0.5,
        activity_score=0.1, title_count=10, content_signal_strength=0.05,
        matched_terms=[], expanded_via=[],
        top_vector_contributing_threads=[],
    )
    assert c.vector_disabled is False  # default


def test_thread_hit_with_evidence():
    routing = ForumCandidate(
        board_node_id=1, site_key="s", name="n", path="p", forum_db_file="f",
        final_score=1.0, classic_direct_score=0.5, classic_expansion_score=0.0,
        vector_cosine=0.7, delta_used=0.5,
        activity_score=0.1, title_count=10, content_signal_strength=0.05,
        matched_terms=[], expanded_via=[], top_vector_contributing_threads=[],
    )
    hit = ThreadHit(
        thread_id=1, board_node_id=1, board_name="n", board_path="p",
        forum_db_file="f", title="t", author=None, posted_at=None,
        last_reply_at=None, reply_count=None, view_count=None,
        url="u", is_pinned=False,
        combined_score=1.5, vector_cosine=0.8, board_score=1.0,
        recency_factor=0.5, breakdown={"vector": 0.48, "board": 0.3, "recency": 0.05},
        routing_evidence=routing,
    )
    assert hit.routing_evidence.vector_cosine == 0.7


def test_ingest_result_partial():
    r = IngestResult(
        forum_db_file="f", requested=10, already_indexed=2,
        newly_embedded=5, failed=3, failed_thread_ids=[101, 102, 103],
        elapsed_seconds=1.2, estimated_cost_cny=0.001,
        embed_model="text-embedding-v3",
    )
    assert r.newly_embedded + r.failed + r.already_indexed == r.requested


def test_query_rep_holds_terms_and_entities():
    q = QueryRep(terms=["a", "b"], entities=[("张三", "person")])
    assert q.entities[0] == ("张三", "person")


def test_thread_detail_with_posts():
    td = ThreadDetail(
        thread_id=1, board_node_id=1, title="t", author="u", url="x",
        posted_at=None,
        posts=[Post(floor=0, author="u", posted_at=None, content_text="hi",
                    attachments=None)],
        raw=None,
    )
    assert td.posts[0].floor == 0
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_types.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/bbs_database/router/types.py`**

```python
"""Dataclasses for BBS_Database public API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class MatchedTerm:
    term: str
    source: Literal["declared", "content", "entity"]
    contribution: float


@dataclass
class ExpansionLink:
    expanded_term: str
    via_query_term: str
    cooccur_weight: float
    contribution: float


@dataclass
class VectorContributingThread:
    thread_id: int
    forum_db_file: str
    title: str
    cosine: float


@dataclass
class QueryRep:
    terms: list[str]
    entities: list[tuple[str, str]]


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
```

- [ ] **Step 4: Run test, verify it passes**

```
./.venv/Scripts/pytest.exe tests/test_types.py -v
```
Expected: 6 pass.

- [ ] **Step 5: Commit**

```bash
git add src/bbs_database/router/types.py tests/test_types.py
git commit -m "feat(router): dataclasses for public API"
```

---

## Task 10: `parse_query`

**Files:**
- Create: `src/bbs_database/router/parse.py`
- Test: `tests/test_parse_query.py`

- [ ] **Step 1: Write the failing test**

`tests/test_parse_query.py`:
```python
from bbs_database.builder.tokenize import Tokenizer
from bbs_database.router.parse import parse_query
from bbs_database.router.types import QueryRep


def test_parse_strips_stopwords_and_short_tokens():
    tok = Tokenizer(stopwords={"的", "了", "怎么样"}, min_length=2)
    q = parse_query("张三老师怎么样", tok)
    assert isinstance(q, QueryRep)
    assert "张三" in q.terms
    assert "老师" in q.terms
    assert "怎么样" not in q.terms


def test_parse_extracts_entities():
    tok = Tokenizer(stopwords=set(), min_length=2)
    q = parse_query("张三老师怎么样", tok)
    assert ("张三", "person") in q.entities


def test_parse_empty_query_returns_empty_repr():
    tok = Tokenizer(stopwords=set(), min_length=2)
    q = parse_query("", tok)
    assert q.terms == []
    assert q.entities == []
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_parse_query.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/bbs_database/router/parse.py`**

```python
"""parse_query — jieba tokenization + entity extraction."""

from __future__ import annotations

from bbs_database.builder.entities import extract_entities
from bbs_database.builder.tokenize import Tokenizer
from bbs_database.router.types import QueryRep


def parse_query(query: str, tokenizer: Tokenizer) -> QueryRep:
    terms = tokenizer.cut(query) if query else []
    entities = extract_entities(query) if query else []
    return QueryRep(terms=terms, entities=entities)
```

- [ ] **Step 4: Run test, verify it passes**

```
./.venv/Scripts/pytest.exe tests/test_parse_query.py -v
```
Expected: 3 pass.

- [ ] **Step 5: Commit**

```bash
git add src/bbs_database/router/parse.py tests/test_parse_query.py
git commit -m "feat(router): parse_query reuses tokenizer + entity extractor"
```

---

## Task 11: Classical scoring (port P1 direct + expansion)

**Files:**
- Create: `src/bbs_database/router/classical.py`
- Test: `tests/test_classical_score.py`

This task ports the working `_direct_scores` from `scripts/eval_self_routing.py` into a reusable module, and adds the multi-hop expansion from v1.0 spec §3.4.

- [ ] **Step 1: Write the failing test**

`tests/test_classical_score.py`:
```python
import math
import sqlite3

from bbs_database.builder.schema import ALL_DDL
from bbs_database.router.classical import classical_direct, classical_expansion


def _seed_index(tmp_path):
    cx = sqlite3.connect(tmp_path / "index.db")
    for stmt in ALL_DDL:
        cx.execute(stmt)
    # 3 boards, simple data
    profiles = [
        # board, name, path, content_signal, activity
        (1, "A", "A", 0.5, 0.1),
        (2, "B", "B", 0.0, 0.5),
        (3, "C", "C", 0.5, 0.0),
    ]
    for bid, name, path, sig, act in profiles:
        cx.execute(
            "INSERT INTO forum_profile(board_node_id, site_key, forum_db_file, name, path, "
            "title_count, activity_score, content_signal_strength, vector_norm, built_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (bid, "s", f"forums/{name}.db", name, path, 100, act, sig, 1.0, "2026-01-01"),
        )
    # edge_forum_topic
    topic_edges = [
        (1, "x", 0.5, 0.0, "declared"),
        (1, "y", 0.0, 0.4, "content"),
        (2, "x", 0.0, 0.3, "content"),
        (3, "z", 0.0, 0.2, "content"),
    ]
    cx.executemany(
        "INSERT INTO edge_forum_topic(board_node_id, term, tfidf_declared, tfidf_content, source) "
        "VALUES (?,?,?,?,?)", topic_edges,
    )
    cx.execute(
        "INSERT INTO edge_forum_entity(board_node_id, entity, entity_type, thread_count) "
        "VALUES (1, 'foo', 'person', 5)"
    )
    # cooccur
    cx.execute(
        "INSERT INTO edge_topic_cooccur(term_a, term_b, weight) VALUES ('x', 'y', 0.5)"
    )
    cx.commit()
    return cx


def test_classical_direct_with_entity(tmp_path):
    cx = _seed_index(tmp_path)
    try:
        scores = dict(classical_direct(
            cx, q_terms=["x"], q_entities=[("foo", "person")],
            alpha_declared=1.0, alpha_content=1.5,
            alpha_entity=2.0, alpha_activity=0.1,
        ))
        # board 1: declared(x)=0.5*1.0 + entity(foo,person, count 5)=2*ln(6) + act=0.01
        expected_1 = 0.5 + 2.0 * math.log(1 + 5) + 0.1 * 0.1
        assert math.isclose(scores[1], expected_1, abs_tol=1e-6)
    finally:
        cx.close()


def test_classical_expansion_via_cooccur(tmp_path):
    cx = _seed_index(tmp_path)
    try:
        seeds = [1]  # board with high x weight
        scores = classical_expansion(
            cx, seeds=seeds, q_terms=["x"],
            alpha_declared=1.0, alpha_content=1.5,
            beta=0.5,
            seed_top_terms=20, pmi_threshold=0.3, m_expansion=10,
        )
        # 'y' should expand because cooccur(x,y)=0.5 > 0.3 threshold
        # board 1 has y in content → gets expansion contribution
        assert scores[1] > 0
    finally:
        cx.close()


def test_classical_direct_empty_terms_and_entities_returns_only_activity(tmp_path):
    cx = _seed_index(tmp_path)
    try:
        scores = dict(classical_direct(
            cx, q_terms=[], q_entities=[],
            alpha_declared=1.0, alpha_content=1.5,
            alpha_entity=2.0, alpha_activity=0.1,
        ))
        # All boards get only alpha_activity * activity_score
        assert math.isclose(scores[1], 0.1 * 0.1, abs_tol=1e-6)
        assert math.isclose(scores[2], 0.1 * 0.5, abs_tol=1e-6)
        assert math.isclose(scores[3], 0.0, abs_tol=1e-6)
    finally:
        cx.close()
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_classical_score.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/bbs_database/router/classical.py`**

```python
"""Classical (P1) direct + multi-hop expansion scoring."""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict


def classical_direct(
    cx: sqlite3.Connection,
    q_terms: list[str],
    q_entities: list[tuple[str, str]],
    *,
    alpha_declared: float,
    alpha_content: float,
    alpha_entity: float,
    alpha_activity: float,
) -> list[tuple[int, float]]:
    """Return [(board_node_id, score)] sorted desc, P1 spec §3.3."""
    profiles = {
        bid: (sig, act)
        for bid, sig, act in cx.execute(
            "SELECT board_node_id, content_signal_strength, activity_score FROM forum_profile"
        )
    }
    score: dict[int, float] = defaultdict(float)
    for bid, (_sig, act) in profiles.items():
        score[bid] = alpha_activity * act

    if q_terms:
        placeholders = ",".join("?" * len(q_terms))
        for bid, td, tc in cx.execute(
            f"SELECT board_node_id, SUM(tfidf_declared), SUM(tfidf_content) "
            f"FROM edge_forum_topic WHERE term IN ({placeholders}) GROUP BY board_node_id",
            q_terms,
        ):
            sig, _ = profiles.get(bid, (0.0, 0.0))
            score[bid] += alpha_declared * (td or 0.0) + alpha_content * (tc or 0.0) * sig

    for ent, ty in q_entities:
        for bid, cnt in cx.execute(
            "SELECT board_node_id, thread_count FROM edge_forum_entity "
            "WHERE entity=? AND entity_type=?",
            (ent, ty),
        ):
            score[bid] += alpha_entity * math.log(1 + cnt)

    return sorted(score.items(), key=lambda x: -x[1])


def classical_expansion(
    cx: sqlite3.Connection,
    seeds: list[int],
    q_terms: list[str],
    *,
    alpha_declared: float,
    alpha_content: float,
    beta: float,
    seed_top_terms: int,
    pmi_threshold: float,
    m_expansion: int,
) -> dict[int, float]:
    """Return {board_node_id: expansion_score} per spec §3.4."""
    if not seeds or not q_terms:
        return {}
    q_set = set(q_terms)

    # 1. collect top terms per seed (excluding q_terms)
    candidates: dict[str, float] = {}
    for bid in seeds:
        rows = cx.execute(
            f"""SELECT term, MAX(tfidf_declared, tfidf_content) AS w
                FROM edge_forum_topic
                WHERE board_node_id=?
                  AND term NOT IN ({",".join("?" * len(q_terms))})
                ORDER BY w DESC LIMIT ?""",
            (bid, *q_terms, seed_top_terms),
        ).fetchall()
        for term, w in rows:
            if term in q_set:
                continue
            if w > candidates.get(term, 0.0):
                candidates[term] = w

    # 2. filter by cooccur with any q_term
    expansion_terms: list[tuple[str, float]] = []
    for term, w in candidates.items():
        cooccur_w = 0.0
        for qt in q_terms:
            a, b = (term, qt) if term < qt else (qt, term)
            row = cx.execute(
                "SELECT weight FROM edge_topic_cooccur WHERE term_a=? AND term_b=?",
                (a, b),
            ).fetchone()
            if row and row[0] > cooccur_w:
                cooccur_w = row[0]
        if cooccur_w >= pmi_threshold:
            expansion_terms.append((term, w * cooccur_w))
    expansion_terms.sort(key=lambda x: -x[1])
    expansion_terms = expansion_terms[:m_expansion]

    if not expansion_terms:
        return {}

    # 3. score each board against expansion terms
    profiles = {
        bid: sig
        for bid, sig in cx.execute(
            "SELECT board_node_id, content_signal_strength FROM forum_profile"
        )
    }
    score: dict[int, float] = defaultdict(float)
    placeholders = ",".join("?" * len(expansion_terms))
    term_to_w = {t: w for t, w in expansion_terms}
    rows = cx.execute(
        f"""SELECT board_node_id, term, tfidf_declared, tfidf_content
            FROM edge_forum_topic
            WHERE term IN ({placeholders})""",
        [t for t, _ in expansion_terms],
    ).fetchall()
    for bid, term, td, tc in rows:
        sig = profiles.get(bid, 0.0)
        contrib = (alpha_declared * td + alpha_content * tc * sig) * term_to_w[term]
        score[bid] += beta * contrib
    return dict(score)
```

- [ ] **Step 4: Run test, verify it passes**

```
./.venv/Scripts/pytest.exe tests/test_classical_score.py -v
```
Expected: 3 pass.

- [ ] **Step 5: Commit**

```bash
git add src/bbs_database/router/classical.py tests/test_classical_score.py
git commit -m "feat(router): classical direct + expansion scoring"
```

---

## Task 12: Vector ranking (cosine top-K, in-memory)

**Files:**
- Create: `src/bbs_database/router/vector_rank.py`
- Test: `tests/test_vector_rank.py`

- [ ] **Step 1: Write the failing test**

`tests/test_vector_rank.py`:
```python
import math
import sqlite3

import numpy as np

from bbs_database.builder.schema import ALL_DDL
from bbs_database.embed.cache import encode_vec
from bbs_database.router.vector_rank import (
    load_board_vectors,
    load_thread_vectors,
    cosine_top_k,
)


def _seed(tmp_path):
    cx = sqlite3.connect(tmp_path / "index.db")
    for stmt in ALL_DDL:
        cx.execute(stmt)
    # board_vector
    cx.execute("INSERT INTO board_vector(board_node_id, vec, source_text, embed_model, built_at) "
               "VALUES (1, ?, 't', 'm', '2026-01-01')",
               (encode_vec([1.0] + [0.0] * 1023),))
    cx.execute("INSERT INTO board_vector(board_node_id, vec, source_text, embed_model, built_at) "
               "VALUES (2, ?, 't', 'm', '2026-01-01')",
               (encode_vec([0.0, 1.0] + [0.0] * 1022),))
    # thread_vector
    cx.execute("INSERT INTO thread_vector(board_node_id, thread_id, forum_db_file, vec, "
               "embed_model, built_at) VALUES (1, 10, 'forums/a.db', ?, 'm', '2026-01-01')",
               (encode_vec([1.0] + [0.0] * 1023),))
    cx.execute("INSERT INTO thread_vector(board_node_id, thread_id, forum_db_file, vec, "
               "embed_model, built_at) VALUES (2, 20, 'forums/b.db', ?, 'm', '2026-01-01')",
               (encode_vec([0.0, 1.0] + [0.0] * 1022),))
    cx.commit()
    return cx


def test_load_board_vectors(tmp_path):
    cx = _seed(tmp_path)
    try:
        bv = load_board_vectors(cx)
        assert set(bv.keys()) == {1, 2}
        assert bv[1].shape == (1024,)
        assert math.isclose(float(bv[1][0]), 1.0, abs_tol=1e-6)
    finally:
        cx.close()


def test_load_thread_vectors_filters_by_board_ids(tmp_path):
    cx = _seed(tmp_path)
    try:
        rows = load_thread_vectors(cx, board_ids=[1])
        assert len(rows) == 1
        bid, tid, fdb, vec = rows[0]
        assert (bid, tid, fdb) == (1, 10, "forums/a.db")
        assert vec.shape == (1024,)
    finally:
        cx.close()


def test_load_thread_vectors_no_filter_returns_all(tmp_path):
    cx = _seed(tmp_path)
    try:
        rows = load_thread_vectors(cx, board_ids=None)
        assert len(rows) == 2
    finally:
        cx.close()


def test_cosine_top_k_returns_sorted_indices_with_scores():
    q = np.array([1.0, 0.0, 0.0] + [0.0] * 1021, dtype=np.float32)
    items = [
        ("a", np.array([0.5, 0.0, 0.0] + [0.0] * 1021, dtype=np.float32)),
        ("b", np.array([1.0, 0.0, 0.0] + [0.0] * 1021, dtype=np.float32)),
        ("c", np.array([0.0, 1.0, 0.0] + [0.0] * 1021, dtype=np.float32)),
    ]
    out = cosine_top_k(q, items, k=2)
    assert [k for k, _ in out] == ["b", "a"]
    assert math.isclose(out[0][1], 1.0, abs_tol=1e-6)


def test_cosine_top_k_handles_zero_vectors():
    q = np.zeros(1024, dtype=np.float32)
    items = [("a", np.ones(1024, dtype=np.float32))]
    out = cosine_top_k(q, items, k=5)
    # Zero query produces zero cosine; we expect it to still return items (with 0 score)
    assert len(out) == 1
    assert math.isclose(out[0][1], 0.0, abs_tol=1e-6)
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_vector_rank.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/bbs_database/router/vector_rank.py`**

```python
"""In-memory cosine ranking over board/thread vectors loaded from index.db."""

from __future__ import annotations

import sqlite3
from typing import Iterable, TypeVar

import numpy as np

from bbs_database.embed.cache import decode_vec

K = TypeVar("K")


def load_board_vectors(cx: sqlite3.Connection) -> dict[int, np.ndarray]:
    out: dict[int, np.ndarray] = {}
    for bid, blob in cx.execute("SELECT board_node_id, vec FROM board_vector"):
        out[bid] = decode_vec(blob)
    return out


def load_thread_vectors(
    cx: sqlite3.Connection, board_ids: list[int] | None,
) -> list[tuple[int, int, str, np.ndarray]]:
    if board_ids is None:
        rows = cx.execute(
            "SELECT board_node_id, thread_id, forum_db_file, vec FROM thread_vector"
        )
    else:
        if not board_ids:
            return []
        placeholders = ",".join("?" * len(board_ids))
        rows = cx.execute(
            f"SELECT board_node_id, thread_id, forum_db_file, vec FROM thread_vector "
            f"WHERE board_node_id IN ({placeholders})",
            board_ids,
        )
    return [(b, t, f, decode_vec(v)) for b, t, f, v in rows]


def cosine_top_k(
    query: np.ndarray, items: Iterable[tuple[K, np.ndarray]], k: int,
) -> list[tuple[K, float]]:
    items_list = list(items)
    if not items_list:
        return []
    keys = [kk for kk, _ in items_list]
    mat = np.stack([v for _, v in items_list])
    qn = np.linalg.norm(query)
    mn = np.linalg.norm(mat, axis=1)
    denom = qn * mn
    safe = denom > 0
    cos = np.zeros(len(items_list), dtype=np.float32)
    if qn > 0:
        cos[safe] = (mat[safe] @ query) / denom[safe]
    order = np.argsort(-cos)[:k]
    return [(keys[i], float(cos[i])) for i in order]
```

- [ ] **Step 4: Run test, verify it passes**

```
./.venv/Scripts/pytest.exe tests/test_vector_rank.py -v
```
Expected: 5 pass.

- [ ] **Step 5: Commit**

```bash
git add src/bbs_database/router/vector_rank.py tests/test_vector_rank.py
git commit -m "feat(router): in-memory cosine top-K over board/thread vectors"
```

---

## Task 13: `find_forums` hybrid impl

**Files:**
- Create: `src/bbs_database/router/hybrid.py`
- Test: `tests/test_hybrid_find_forums.py`

This is the spec §4.1 algorithm. Combines classical_direct + classical_expansion (with vector-augmented seeds) + vector_cosine, with adaptive δ.

- [ ] **Step 1: Write the failing test**

`tests/test_hybrid_find_forums.py`:
```python
import sqlite3

import numpy as np
import pytest

from bbs_database.builder.schema import ALL_DDL
from bbs_database.builder.tokenize import Tokenizer
from bbs_database.embed.cache import encode_vec
from bbs_database.router.errors import IndexNotBuiltError
from bbs_database.router.hybrid import find_forums_impl


def _seed(tmp_path):
    cx = sqlite3.connect(tmp_path / "index.db")
    for stmt in ALL_DDL:
        cx.execute(stmt)
    # board A: classical-strong on term "考试", weak vector
    # board B: classical-weak, vector-strong (board.vec near query)
    # board C: nothing
    cx.execute("INSERT INTO forum_profile(board_node_id, site_key, forum_db_file, name, path, "
               "title_count, activity_score, content_signal_strength, vector_norm, built_at) "
               "VALUES (1,'s','f.db','A','A',100,0.1,0.5,1.0,'2026-01-01')")
    cx.execute("INSERT INTO forum_profile(board_node_id, site_key, forum_db_file, name, path, "
               "title_count, activity_score, content_signal_strength, vector_norm, built_at) "
               "VALUES (2,'s','f.db','B','B',100,0.1,0.5,1.0,'2026-01-01')")
    cx.execute("INSERT INTO forum_profile(board_node_id, site_key, forum_db_file, name, path, "
               "title_count, activity_score, content_signal_strength, vector_norm, built_at) "
               "VALUES (3,'s','f.db','C','C',100,0.1,0.5,1.0,'2026-01-01')")
    cx.execute("INSERT INTO edge_forum_topic(board_node_id, term, tfidf_declared, tfidf_content, "
               "source) VALUES (1, '考试', 2.0, 1.0, 'both')")
    cx.execute("INSERT INTO edge_forum_topic(board_node_id, term, tfidf_declared, tfidf_content, "
               "source) VALUES (2, '考试', 0.1, 0.0, 'declared')")
    # board vectors: A's vec is far from query; B's vec is close; C is far
    q_vec_components = [1.0] + [0.0] * 1023
    cx.execute("INSERT INTO board_vector(board_node_id, vec, source_text, embed_model, built_at) "
               "VALUES (1, ?, 'A', 'm', '2026-01-01')",
               (encode_vec([0.0] * 1024),))  # cosine 0
    cx.execute("INSERT INTO board_vector(board_node_id, vec, source_text, embed_model, built_at) "
               "VALUES (2, ?, 'B', 'm', '2026-01-01')",
               (encode_vec(q_vec_components),))  # cosine 1
    cx.execute("INSERT INTO board_vector(board_node_id, vec, source_text, embed_model, built_at) "
               "VALUES (3, ?, 'C', 'm', '2026-01-01')",
               (encode_vec([0.0, 1.0] + [0.0] * 1022),))  # cosine 0
    cx.commit()
    return cx, q_vec_components


def _cfg_routing():
    return {
        "alpha_declared": 1.0, "alpha_content": 1.5,
        "alpha_entity": 2.0, "alpha_activity": 0.1,
        "k1_seeds": 5, "seed_top_terms": 20,
        "m_expansion": 10, "beta_expansion": 0.5, "k_final": 8,
        "delta_vector_base": 0.5, "delta_vector_cold": 0.7,
        "delta_signal_threshold": 0.5,
    }


def test_hybrid_combines_classical_and_vector(tmp_path, fake_embed_api):
    cx, q_vec = _seed(tmp_path)
    try:
        # Set up fake embed: query "考试" returns the exact same vec as board B
        fake_embed_api.set("考试", q_vec)
        tok = Tokenizer(stopwords=set(), min_length=2)
        out = find_forums_impl(
            cx, query="考试", tokenizer=tok, embed_client=fake_embed_api,
            routing_cfg=_cfg_routing(), top_k=3,
        )
        by_id = {c.board_node_id: c for c in out}
        # Both A (classical strong) and B (vector strong) should make top-3
        assert 1 in by_id
        assert 2 in by_id
        # B's vector_cosine should be ~1.0
        import math
        assert math.isclose(by_id[2].vector_cosine, 1.0, abs_tol=1e-3)
        # A's vector_cosine should be 0
        assert math.isclose(by_id[1].vector_cosine, 0.0, abs_tol=1e-3)
    finally:
        cx.close()


def test_hybrid_marks_vector_disabled_on_embed_failure(tmp_path):
    cx, _ = _seed(tmp_path)
    try:
        class FailingClient:
            def embed(self, texts):
                from bbs_database.router.errors import EmbedAPIError
                raise EmbedAPIError("simulated failure")

        tok = Tokenizer(stopwords=set(), min_length=2)
        out = find_forums_impl(
            cx, query="考试", tokenizer=tok, embed_client=FailingClient(),
            routing_cfg=_cfg_routing(), top_k=3,
        )
        # Should still return results, marked vector_disabled
        assert all(c.vector_disabled for c in out)
        # Top-1 should be classical-strongest: board A
        assert out[0].board_node_id == 1
    finally:
        cx.close()


def test_hybrid_raises_when_no_board_vectors(tmp_path, fake_embed_api):
    cx = sqlite3.connect(tmp_path / "index.db")
    for stmt in ALL_DDL:
        cx.execute(stmt)
    # Have forum_profile but no board_vector
    cx.execute("INSERT INTO forum_profile(board_node_id, site_key, forum_db_file, name, path, "
               "title_count, activity_score, content_signal_strength, vector_norm, built_at) "
               "VALUES (1,'s','f.db','A','A',100,0.1,0.5,1.0,'2026-01-01')")
    cx.commit()
    try:
        tok = Tokenizer(stopwords=set(), min_length=2)
        with pytest.raises(IndexNotBuiltError):
            find_forums_impl(
                cx, query="x", tokenizer=tok, embed_client=fake_embed_api,
                routing_cfg=_cfg_routing(), top_k=3,
            )
    finally:
        cx.close()


def test_hybrid_returns_evidence_with_top_contributing_threads(tmp_path, fake_embed_api):
    cx, q_vec = _seed(tmp_path)
    try:
        # Add a thread_vector row whose vec matches q_vec, attached to board 2
        cx.execute(
            "INSERT INTO thread_vector(board_node_id, thread_id, forum_db_file, vec, "
            "embed_model, built_at) VALUES (2, 99, 'f.db', ?, 'm', '2026-01-01')",
            (encode_vec(q_vec),)
        )
        # Need the thread to exist in some forum.db for title lookup — skip lookup if not.
        # find_forums should still work; evidence threads may be empty if titles unresolvable
        cx.commit()
        fake_embed_api.set("考试", q_vec)
        tok = Tokenizer(stopwords=set(), min_length=2)
        out = find_forums_impl(
            cx, query="考试", tokenizer=tok, embed_client=fake_embed_api,
            routing_cfg=_cfg_routing(), top_k=3,
        )
        by_id = {c.board_node_id: c for c in out}
        # Just confirm evidence list type
        assert isinstance(by_id[2].top_vector_contributing_threads, list)
    finally:
        cx.close()
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_hybrid_find_forums.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/bbs_database/router/hybrid.py`**

```python
"""find_forums hybrid impl: classical + vector fusion via adaptive δ."""

from __future__ import annotations

import sqlite3

import numpy as np

from bbs_database.builder.tokenize import Tokenizer
from bbs_database.embed.cache import decode_vec
from bbs_database.router.classical import classical_direct, classical_expansion
from bbs_database.router.errors import EmbedAPIError, IndexNotBuiltError
from bbs_database.router.parse import parse_query
from bbs_database.router.types import (
    ForumCandidate,
    MatchedTerm,
    VectorContributingThread,
)
from bbs_database.router.vector_rank import load_board_vectors, load_thread_vectors


def _min_max(scores: dict[int, float]) -> dict[int, float]:
    if not scores:
        return {}
    vals = list(scores.values())
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return {k: 0.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def _delta(signal: float, base: float, cold: float, threshold: float) -> float:
    return cold if signal < threshold else base


def find_forums_impl(
    cx: sqlite3.Connection,
    *,
    query: str,
    tokenizer: Tokenizer,
    embed_client,
    routing_cfg: dict,
    top_k: int,
) -> list[ForumCandidate]:
    # 1. parse
    qrep = parse_query(query, tokenizer)

    # 2. classical direct
    classic_direct_pairs = classical_direct(
        cx, qrep.terms, qrep.entities,
        alpha_declared=routing_cfg["alpha_declared"],
        alpha_content=routing_cfg["alpha_content"],
        alpha_entity=routing_cfg["alpha_entity"],
        alpha_activity=routing_cfg["alpha_activity"],
    )
    classic_direct_map = dict(classic_direct_pairs)

    # 3. board vectors
    board_vecs = load_board_vectors(cx)
    if not board_vecs:
        raise IndexNotBuiltError(
            "board_vector table is empty; run rebuild_index.py --full first"
        )

    # 4. embed query (may fail → fallback)
    query_vec = None
    vector_disabled = False
    try:
        emb_list = embed_client.embed([query])
        if emb_list:
            query_vec = np.asarray(emb_list[0], dtype=np.float32)
    except EmbedAPIError:
        vector_disabled = True

    # 5. vector direct cosine
    vec_score: dict[int, float] = {}
    if query_vec is not None and not vector_disabled:
        qn = float(np.linalg.norm(query_vec))
        if qn > 0:
            for bid, bv in board_vecs.items():
                bn = float(np.linalg.norm(bv))
                if bn == 0:
                    continue
                cos = float(bv @ query_vec) / (qn * bn)
                vec_score[bid] = max(0.0, cos)

    # 6. classical expansion (with vector-augmented seeds)
    k1 = routing_cfg["k1_seeds"]
    classic_seeds = [bid for bid, _ in classic_direct_pairs[:k1]]
    vec_seeds = sorted(vec_score.items(), key=lambda x: -x[1])[:k1]
    vec_seed_ids = [bid for bid, _ in vec_seeds]
    seeds = list(dict.fromkeys(classic_seeds + vec_seed_ids))
    exp_map = classical_expansion(
        cx, seeds=seeds, q_terms=qrep.terms,
        alpha_declared=routing_cfg["alpha_declared"],
        alpha_content=routing_cfg["alpha_content"],
        beta=routing_cfg["beta_expansion"],
        seed_top_terms=routing_cfg["seed_top_terms"],
        pmi_threshold=routing_cfg["delta_signal_threshold"],  # reuse — note: actually PMI threshold
        m_expansion=routing_cfg["m_expansion"],
    )

    # 7. classical total + normalize
    classic_total: dict[int, float] = {}
    all_bids = set(classic_direct_map) | set(exp_map) | set(vec_score) | set(board_vecs)
    for bid in all_bids:
        classic_total[bid] = classic_direct_map.get(bid, 0.0) + exp_map.get(bid, 0.0)
    classic_norm = _min_max(classic_total)
    vec_norm = vec_score

    # 8. fetch profiles (for δ + evidence)
    profiles: dict[int, dict] = {}
    for row in cx.execute(
        "SELECT board_node_id, site_key, name, path, forum_db_file, "
        "activity_score, title_count, content_signal_strength FROM forum_profile"
    ):
        profiles[row[0]] = dict(
            site_key=row[1], name=row[2], path=row[3], forum_db_file=row[4],
            activity_score=row[5], title_count=row[6], content_signal_strength=row[7],
        )

    # 9. fusion
    db = routing_cfg["delta_vector_base"]
    dc = routing_cfg["delta_vector_cold"]
    th = routing_cfg["delta_signal_threshold"]
    candidates: list[ForumCandidate] = []
    for bid in all_bids:
        prof = profiles.get(bid)
        if prof is None:
            continue
        sig = prof["content_signal_strength"]
        delta = _delta(sig, db, dc, th)
        if vector_disabled:
            final = classic_norm.get(bid, 0.0)
            delta_used = 0.0
        else:
            final = delta * vec_norm.get(bid, 0.0) + (1 - delta) * classic_norm.get(bid, 0.0)
            delta_used = delta

        candidates.append(ForumCandidate(
            board_node_id=bid,
            site_key=prof["site_key"], name=prof["name"], path=prof["path"],
            forum_db_file=prof["forum_db_file"],
            final_score=final,
            classic_direct_score=classic_direct_map.get(bid, 0.0),
            classic_expansion_score=exp_map.get(bid, 0.0),
            vector_cosine=vec_score.get(bid, 0.0),
            delta_used=delta_used,
            activity_score=prof["activity_score"],
            title_count=prof["title_count"],
            content_signal_strength=sig,
            matched_terms=[],  # populated below
            expanded_via=[],   # left empty in P2; can be filled later
            top_vector_contributing_threads=[],
            vector_disabled=vector_disabled,
        ))

    # 10. populate matched_terms (lightweight: which q_terms have any tfidf edge)
    if qrep.terms:
        placeholders = ",".join("?" * len(qrep.terms))
        rows = cx.execute(
            f"SELECT board_node_id, term, tfidf_declared, tfidf_content, source "
            f"FROM edge_forum_topic WHERE term IN ({placeholders})",
            qrep.terms,
        ).fetchall()
        by_bid: dict[int, list[MatchedTerm]] = {}
        for bid, term, td, tc, source in rows:
            by_bid.setdefault(bid, []).append(MatchedTerm(
                term=term, source=source, contribution=td + tc,
            ))
        for c in candidates:
            c.matched_terms = by_bid.get(c.board_node_id, [])

    # 11. populate top_vector_contributing_threads (top-3 thread per board for top candidates)
    candidates.sort(key=lambda c: -c.final_score)
    top_candidates = candidates[:top_k]
    if query_vec is not None and not vector_disabled:
        top_bids = [c.board_node_id for c in top_candidates]
        thread_rows = load_thread_vectors(cx, board_ids=top_bids)
        qn = float(np.linalg.norm(query_vec))
        per_board: dict[int, list[tuple[float, int, str]]] = {}
        if qn > 0:
            for bid, tid, fdb, tv in thread_rows:
                tn = float(np.linalg.norm(tv))
                if tn == 0:
                    continue
                cos = float(tv @ query_vec) / (qn * tn)
                per_board.setdefault(bid, []).append((cos, tid, fdb))
        for c in top_candidates:
            triples = sorted(per_board.get(c.board_node_id, []), reverse=True)[:3]
            c.top_vector_contributing_threads = [
                VectorContributingThread(
                    thread_id=tid, forum_db_file=fdb, title="", cosine=cos,
                )
                for cos, tid, fdb in triples
            ]

    return top_candidates
```

> **Note on `pmi_threshold` re-use:** the implementation above passes `routing_cfg["delta_signal_threshold"]` as the PMI gate, which is a bug — see Task 14 self-check below. The fix is to read the right key.

- [ ] **Step 4: Run tests, verify they pass**

```
./.venv/Scripts/pytest.exe tests/test_hybrid_find_forums.py -v
```
Expected: 4 pass.

- [ ] **Step 5: Self-check — fix the pmi_threshold bug**

The implementation passes `routing_cfg["delta_signal_threshold"]` to `classical_expansion`'s `pmi_threshold` parameter. That's wrong — we should be reading a `pmi_threshold` from `routing_cfg` or fall back to the build-time PMI threshold from `cfg.build.pmi_threshold`.

For P2 we simplify: add `pmi_threshold` to `routing_cfg` defaulting to `0.3` (matches build-time default). Update the implementation:

Replace this line in `find_forums_impl`:
```python
        pmi_threshold=routing_cfg["delta_signal_threshold"],  # reuse — note: actually PMI threshold
```
with:
```python
        pmi_threshold=routing_cfg.get("pmi_threshold", 0.3),
```

Also add a key to `config/routing.yaml` under `routing:`:
```yaml
  pmi_threshold: 0.3
```

Run tests again to confirm green:
```
./.venv/Scripts/pytest.exe tests/test_hybrid_find_forums.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/bbs_database/router/hybrid.py config/routing.yaml tests/test_hybrid_find_forums.py
git commit -m "feat(router): find_forums hybrid impl with adaptive delta"
```

---

## Task 14: `search_threads` impl

**Files:**
- Create: `src/bbs_database/router/search.py`
- Test: `tests/test_search_threads.py`

- [ ] **Step 1: Write the failing test**

`tests/test_search_threads.py`:
```python
import math
import sqlite3
from pathlib import Path

import numpy as np

from bbs_database.builder.schema import ALL_DDL
from bbs_database.builder.tokenize import Tokenizer
from bbs_database.embed.cache import encode_vec
from bbs_database.router.search import search_threads_impl


def _seed(tmp_path):
    cx = sqlite3.connect(tmp_path / "index.db")
    for stmt in ALL_DDL:
        cx.execute(stmt)
    cx.execute("INSERT INTO forum_profile(board_node_id, site_key, forum_db_file, name, path, "
               "title_count, activity_score, content_signal_strength, vector_norm, built_at) "
               "VALUES (1,'s','forums/a.db','A','A',100,0.1,0.5,1.0,'2026-01-01')")
    cx.execute("INSERT INTO forum_profile(board_node_id, site_key, forum_db_file, name, path, "
               "title_count, activity_score, content_signal_strength, vector_norm, built_at) "
               "VALUES (2,'s','forums/a.db','B','B',100,0.1,0.5,1.0,'2026-01-01')")
    cx.execute("INSERT INTO board_vector(board_node_id, vec, source_text, embed_model, built_at) "
               "VALUES (1, ?, 'A', 'm', '2026-01-01')",
               (encode_vec([1.0] + [0.0] * 1023),))
    cx.execute("INSERT INTO board_vector(board_node_id, vec, source_text, embed_model, built_at) "
               "VALUES (2, ?, 'B', 'm', '2026-01-01')",
               (encode_vec([0.0, 1.0] + [0.0] * 1022),))
    # threads: t1 in board 1 (matches query), t2 in board 2 (doesn't match)
    cx.execute("INSERT INTO thread_vector(board_node_id, thread_id, forum_db_file, vec, "
               "embed_model, built_at) VALUES (1, 1, 'forums/a.db', ?, 'm', '2026-01-01')",
               (encode_vec([1.0] + [0.0] * 1023),))
    cx.execute("INSERT INTO thread_vector(board_node_id, thread_id, forum_db_file, vec, "
               "embed_model, built_at) VALUES (2, 2, 'forums/a.db', ?, 'm', '2026-01-01')",
               (encode_vec([0.0, 1.0] + [0.0] * 1022),))
    cx.commit()
    return cx


def _build_forum_db(tmp_path):
    """Build a tiny forums/a.db with 2 threads, so search can pull metadata."""
    forums_dir = tmp_path / "data" / "crawler.db" / "forums"
    forums_dir.mkdir(parents=True)
    fdb = forums_dir / "a.db"
    fcx = sqlite3.connect(fdb)
    fcx.execute("""CREATE TABLE threads (
        id INTEGER PRIMARY KEY, board_node_id INTEGER, url TEXT, title TEXT, author TEXT,
        posted_at TEXT, last_reply_at TEXT, reply_count INTEGER, view_count INTEGER,
        raw TEXT, is_pinned INTEGER NOT NULL DEFAULT 0,
        first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
        last_fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    fcx.executemany(
        "INSERT INTO threads(id, board_node_id, url, title, posted_at, is_pinned) VALUES (?,?,?,?,?,?)",
        [(1, 1, "u1", "标题A", "2026-05-01T00:00:00", 0),
         (2, 2, "u2", "标题B", "2026-05-01T00:00:00", 0)],
    )
    fcx.commit()
    fcx.close()
    return tmp_path / "data" / "crawler.db"


def _cfg_search():
    return {
        "gamma_vector": 0.6, "gamma_board": 0.3, "gamma_recency": 0.1,
        "recency_tau_days": 180, "per_board_limit": 20, "total_limit": 50,
    }


def test_search_returns_threads_ranked_by_vector(tmp_path, fake_embed_api):
    cx = _seed(tmp_path)
    data_root = _build_forum_db(tmp_path)
    try:
        # Query embedding aligned with board 1 / thread 1
        fake_embed_api.set("查询", [1.0] + [0.0] * 1023)
        out = search_threads_impl(
            cx, query="查询", board_node_ids=[1, 2],
            board_score={1: 1.0, 2: 1.0},
            embed_client=fake_embed_api,
            data_root=data_root,
            search_cfg=_cfg_search(),
        )
        assert len(out) >= 1
        # Top hit should be thread 1 (board 1)
        assert out[0].thread_id == 1
        assert out[0].board_node_id == 1
        assert out[0].vector_cosine > 0.9
    finally:
        cx.close()


def test_search_returns_empty_when_no_vectors(tmp_path, fake_embed_api):
    cx = sqlite3.connect(tmp_path / "index.db")
    for stmt in ALL_DDL:
        cx.execute(stmt)
    # No board_vector or thread_vector
    cx.execute("INSERT INTO forum_profile(board_node_id, site_key, forum_db_file, name, path, "
               "title_count, activity_score, content_signal_strength, vector_norm, built_at) "
               "VALUES (1,'s','forums/a.db','A','A',100,0.1,0.5,1.0,'2026-01-01')")
    cx.commit()
    data_root = _build_forum_db(tmp_path)
    try:
        out = search_threads_impl(
            cx, query="x", board_node_ids=[1], board_score={1: 1.0},
            embed_client=fake_embed_api, data_root=data_root,
            search_cfg=_cfg_search(),
        )
        assert out == []
    finally:
        cx.close()


def test_per_board_limit_caps_results(tmp_path, fake_embed_api):
    cx = _seed(tmp_path)
    # Add many more thread_vector rows to board 1
    for i in range(50):
        cx.execute("INSERT INTO thread_vector(board_node_id, thread_id, forum_db_file, vec, "
                   "embed_model, built_at) VALUES (1, ?, 'forums/a.db', ?, 'm', '2026-01-01')",
                   (100 + i, encode_vec([1.0] + [0.0] * 1023)))
    cx.commit()
    data_root = _build_forum_db(tmp_path)
    # Add corresponding threads to forum.db
    fdb = data_root / "forums" / "a.db"
    fcx = sqlite3.connect(fdb)
    fcx.executemany(
        "INSERT INTO threads(id, board_node_id, url, title, posted_at) VALUES (?,?,?,?,?)",
        [(100 + i, 1, f"u{i}", f"t{i}", "2026-05-01T00:00:00") for i in range(50)],
    )
    fcx.commit()
    fcx.close()
    try:
        cfg = _cfg_search()
        cfg["per_board_limit"] = 5
        cfg["total_limit"] = 50
        fake_embed_api.set("查询", [1.0] + [0.0] * 1023)
        out = search_threads_impl(
            cx, query="查询", board_node_ids=[1, 2],
            board_score={1: 1.0, 2: 1.0},
            embed_client=fake_embed_api, data_root=data_root,
            search_cfg=cfg,
        )
        board_1_count = sum(1 for h in out if h.board_node_id == 1)
        assert board_1_count <= 5
    finally:
        cx.close()
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_search_threads.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/bbs_database/router/search.py`**

```python
"""search_threads impl: vector cosine + board.score + recency."""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from bbs_database.reader import open_ro
from bbs_database.router.errors import EmbedAPIError
from bbs_database.router.types import ForumCandidate, ThreadHit
from bbs_database.router.vector_rank import load_thread_vectors


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _recency(posted_at: str | None, tau_days: float, now: datetime) -> float:
    pd = _parse_iso(posted_at)
    if pd is None:
        return 0.0
    if pd.tzinfo is None:
        pd = pd.replace(tzinfo=timezone.utc)
    delta_days = (now - pd).total_seconds() / 86400.0
    if delta_days < 0:
        delta_days = 0.0
    return math.exp(-delta_days / tau_days)


def search_threads_impl(
    cx: sqlite3.Connection,
    *,
    query: str,
    board_node_ids: list[int],
    board_score: dict[int, float],
    embed_client,
    data_root: Path,
    search_cfg: dict,
) -> list[ThreadHit]:
    # 1. embed query
    try:
        emb = embed_client.embed([query])
    except EmbedAPIError:
        return []
    if not emb:
        return []
    query_vec = np.asarray(emb[0], dtype=np.float32)
    qn = float(np.linalg.norm(query_vec))
    if qn == 0:
        return []

    # 2. load thread_vector rows in scope
    rows = load_thread_vectors(cx, board_ids=board_node_ids)
    if not rows:
        return []

    # 3. cosine all
    scored: list[tuple[float, int, int, str]] = []  # (cosine, bid, tid, fdb)
    for bid, tid, fdb, tv in rows:
        tn = float(np.linalg.norm(tv))
        if tn == 0:
            continue
        cos = float(tv @ query_vec) / (qn * tn)
        scored.append((cos, bid, tid, fdb))

    # 4. group by forum_db_file → pull thread metadata
    by_fdb: dict[str, list[int]] = defaultdict(list)
    for _, _, tid, fdb in scored:
        by_fdb[fdb].append(tid)
    meta: dict[tuple[str, int], dict] = {}
    for fdb, tids in by_fdb.items():
        fdb_path = Path(data_root) / fdb
        try:
            fcx = open_ro(fdb_path)
        except sqlite3.OperationalError:
            continue
        try:
            placeholders = ",".join("?" * len(tids))
            for row in fcx.execute(
                f"SELECT id, board_node_id, title, author, posted_at, last_reply_at, "
                f"reply_count, view_count, url, is_pinned "
                f"FROM threads WHERE id IN ({placeholders})",
                tids,
            ):
                meta[(fdb, row[0])] = dict(
                    board_node_id=row[1], title=row[2], author=row[3],
                    posted_at=row[4], last_reply_at=row[5],
                    reply_count=row[6], view_count=row[7], url=row[8],
                    is_pinned=bool(row[9]),
                )
        finally:
            fcx.close()

    # 5. load board profiles for evidence
    profiles = {}
    for row in cx.execute(
        "SELECT board_node_id, site_key, name, path, forum_db_file, "
        "activity_score, title_count, content_signal_strength FROM forum_profile"
    ):
        profiles[row[0]] = dict(
            site_key=row[1], name=row[2], path=row[3], forum_db_file=row[4],
            activity_score=row[5], title_count=row[6], content_signal_strength=row[7],
        )

    # 6. compose ThreadHit
    g_vec = search_cfg["gamma_vector"]
    g_board = search_cfg["gamma_board"]
    g_recency = search_cfg["gamma_recency"]
    tau = search_cfg["recency_tau_days"]
    per_board_limit = search_cfg["per_board_limit"]
    total_limit = search_cfg["total_limit"]
    now = datetime.now(timezone.utc)

    hits: list[ThreadHit] = []
    for cos, bid, tid, fdb in scored:
        m = meta.get((fdb, tid))
        if m is None:
            continue
        bs = board_score.get(bid, 0.0)
        rec = _recency(m["posted_at"], tau, now)
        combined = g_vec * cos + g_board * bs + g_recency * rec
        prof = profiles.get(bid, {})
        routing_evidence = ForumCandidate(
            board_node_id=bid,
            site_key=prof.get("site_key", ""),
            name=prof.get("name", ""),
            path=prof.get("path", ""),
            forum_db_file=fdb,
            final_score=bs,
            classic_direct_score=0.0,
            classic_expansion_score=0.0,
            vector_cosine=0.0,
            delta_used=0.0,
            activity_score=prof.get("activity_score", 0.0),
            title_count=prof.get("title_count", 0),
            content_signal_strength=prof.get("content_signal_strength", 0.0),
            matched_terms=[],
            expanded_via=[],
            top_vector_contributing_threads=[],
        )
        hits.append(ThreadHit(
            thread_id=tid,
            board_node_id=bid,
            board_name=prof.get("name", ""),
            board_path=prof.get("path", ""),
            forum_db_file=fdb,
            title=m["title"],
            author=m["author"],
            posted_at=m["posted_at"],
            last_reply_at=m["last_reply_at"],
            reply_count=m["reply_count"],
            view_count=m["view_count"],
            url=m["url"],
            is_pinned=m["is_pinned"],
            combined_score=combined,
            vector_cosine=cos,
            board_score=bs,
            recency_factor=rec,
            breakdown={"vector": g_vec * cos, "board": g_board * bs, "recency": g_recency * rec},
            routing_evidence=routing_evidence,
        ))

    # 7. group by board, per_board_limit, then total_limit
    hits.sort(key=lambda h: -h.combined_score)
    per_board_counts: dict[int, int] = defaultdict(int)
    final_hits: list[ThreadHit] = []
    for h in hits:
        if per_board_counts[h.board_node_id] >= per_board_limit:
            continue
        final_hits.append(h)
        per_board_counts[h.board_node_id] += 1
        if len(final_hits) >= total_limit:
            break
    return final_hits
```

- [ ] **Step 4: Run tests, verify they pass**

```
./.venv/Scripts/pytest.exe tests/test_search_threads.py -v
```
Expected: 3 pass.

- [ ] **Step 5: Commit**

```bash
git add src/bbs_database/router/search.py tests/test_search_threads.py
git commit -m "feat(router): search_threads with vector + board + recency"
```

---

## Task 15: `get_thread` impl

**Files:**
- Create: `src/bbs_database/router/thread_detail.py`
- Test: `tests/test_thread_detail.py`

- [ ] **Step 1: Write the failing test**

`tests/test_thread_detail.py`:
```python
import sqlite3
from pathlib import Path

import pytest

from bbs_database.router.errors import ForumDbNotFoundError, ThreadNotFoundError
from bbs_database.router.thread_detail import get_thread_impl


def _build(tmp_path):
    forums = tmp_path / "data" / "crawler.db" / "forums"
    forums.mkdir(parents=True)
    fdb = forums / "a.db"
    cx = sqlite3.connect(fdb)
    cx.executescript("""
        CREATE TABLE threads (id INTEGER PRIMARY KEY, board_node_id INTEGER, url TEXT, title TEXT,
            author TEXT, posted_at TEXT, last_reply_at TEXT, reply_count INTEGER,
            view_count INTEGER, raw TEXT, is_pinned INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_fetched_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE posts (id INTEGER PRIMARY KEY, thread_id INTEGER, floor INTEGER,
            author TEXT, posted_at TEXT, content_html TEXT NOT NULL,
            content_text TEXT NOT NULL, attachments TEXT, raw TEXT,
            UNIQUE(thread_id, floor));
    """)
    cx.execute(
        "INSERT INTO threads(id, board_node_id, url, title, author, posted_at) "
        "VALUES (1, 10, 'u', 't', 'a', '2026-01-01')"
    )
    cx.executemany(
        "INSERT INTO posts(thread_id, floor, author, posted_at, content_html, content_text) "
        "VALUES (?,?,?,?,?,?)",
        [(1, 0, "a", "2026-01-01", "<p>hi</p>", "hi"),
         (1, 1, "b", "2026-01-02", "<p>yo</p>", "yo")],
    )
    cx.commit()
    cx.close()
    return tmp_path / "data" / "crawler.db"


def test_get_thread_returns_thread_and_posts(tmp_path):
    data_root = _build(tmp_path)
    td = get_thread_impl(data_root, "forums/a.db", 1)
    assert td.thread_id == 1
    assert td.title == "t"
    assert len(td.posts) == 2
    assert td.posts[0].floor == 0
    assert td.posts[1].content_text == "yo"


def test_get_thread_missing_thread_raises(tmp_path):
    data_root = _build(tmp_path)
    with pytest.raises(ThreadNotFoundError):
        get_thread_impl(data_root, "forums/a.db", 999)


def test_get_thread_missing_forum_db_raises(tmp_path):
    data_root = tmp_path / "no" / "such" / "place"
    with pytest.raises(ForumDbNotFoundError):
        get_thread_impl(data_root, "forums/a.db", 1)
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_thread_detail.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/bbs_database/router/thread_detail.py`**

```python
"""get_thread: read a thread + all its posts from crawler forum.db."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from bbs_database.reader import open_ro
from bbs_database.router.errors import ForumDbNotFoundError, ThreadNotFoundError
from bbs_database.router.types import Post, ThreadDetail


def get_thread_impl(
    data_root: Path | str, forum_db_file: str, thread_id: int,
) -> ThreadDetail:
    fdb_path = Path(data_root) / forum_db_file
    if not fdb_path.exists():
        raise ForumDbNotFoundError(f"forum db not found: {fdb_path}")
    cx = open_ro(fdb_path)
    try:
        row = cx.execute(
            "SELECT id, board_node_id, title, author, posted_at, url, raw FROM threads "
            "WHERE id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            raise ThreadNotFoundError(
                f"thread_id={thread_id} not found in {forum_db_file}"
            )
        thread_id_db, board_node_id, title, author, posted_at, url, raw = row
        posts_rows = cx.execute(
            "SELECT floor, author, posted_at, content_text, attachments "
            "FROM posts WHERE thread_id = ? ORDER BY floor",
            (thread_id,),
        ).fetchall()
        posts = []
        for floor, p_author, p_posted_at, content_text, attachments in posts_rows:
            attach_parsed = None
            if attachments:
                try:
                    attach_parsed = json.loads(attachments)
                except json.JSONDecodeError:
                    attach_parsed = None
            posts.append(Post(
                floor=floor, author=p_author, posted_at=p_posted_at,
                content_text=content_text, attachments=attach_parsed,
            ))
        raw_parsed = None
        if raw:
            try:
                raw_parsed = json.loads(raw)
            except json.JSONDecodeError:
                raw_parsed = None
        return ThreadDetail(
            thread_id=thread_id_db, board_node_id=board_node_id,
            title=title, author=author, url=url, posted_at=posted_at,
            posts=posts, raw=raw_parsed,
        )
    finally:
        cx.close()
```

- [ ] **Step 4: Run test, verify it passes**

```
./.venv/Scripts/pytest.exe tests/test_thread_detail.py -v
```
Expected: 3 pass.

- [ ] **Step 5: Commit**

```bash
git add src/bbs_database/router/thread_detail.py tests/test_thread_detail.py
git commit -m "feat(router): get_thread reads thread + posts from forum.db"
```

---

## Task 16: `ingest_threads` impl

**Files:**
- Create: `src/bbs_database/ingest.py`
- Test: `tests/test_ingest_threads.py`

- [ ] **Step 1: Write the failing test**

`tests/test_ingest_threads.py`:
```python
import sqlite3
from pathlib import Path

from bbs_database.builder.schema import ALL_DDL
from bbs_database.ingest import ingest_threads_impl
from bbs_database.router.types import IngestResult


def _build_forum_db(tmp_path, threads):
    forums = tmp_path / "data" / "crawler.db" / "forums"
    forums.mkdir(parents=True)
    fdb = forums / "a.db"
    cx = sqlite3.connect(fdb)
    cx.executescript("""
        CREATE TABLE threads (id INTEGER PRIMARY KEY, board_node_id INTEGER, url TEXT,
            title TEXT, author TEXT, posted_at TEXT, last_reply_at TEXT,
            reply_count INTEGER, view_count INTEGER, raw TEXT,
            is_pinned INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_fetched_at TEXT NOT NULL DEFAULT (datetime('now')));
    """)
    cx.executemany(
        "INSERT INTO threads(id, board_node_id, url, title) VALUES (?,?,?,?)",
        threads,
    )
    cx.commit()
    cx.close()
    return tmp_path / "data" / "crawler.db"


def _empty_index_db(tmp_path):
    p = tmp_path / "index.db"
    cx = sqlite3.connect(p)
    for stmt in ALL_DDL:
        cx.execute(stmt)
    cx.commit()
    cx.close()
    return p


def test_ingest_threads_embeds_new_titles(tmp_path, fake_embed_api):
    threads = [
        (1, 10, "u1", "标题1"),
        (2, 10, "u2", "标题2"),
        (3, 10, "u3", "标题3"),
    ]
    data_root = _build_forum_db(tmp_path, threads)
    index_db = _empty_index_db(tmp_path)
    res = ingest_threads_impl(
        forum_db_file="forums/a.db",
        thread_ids=[1, 2, 3],
        index_db_path=index_db, data_root=data_root,
        embed_client=fake_embed_api, embed_model="m1",
    )
    assert isinstance(res, IngestResult)
    assert res.requested == 3
    assert res.newly_embedded == 3
    assert res.already_indexed == 0
    assert res.failed == 0
    # check index.db
    cx = sqlite3.connect(index_db)
    n = cx.execute("SELECT count(*) FROM thread_vector").fetchone()[0]
    assert n == 3
    cx.close()


def test_ingest_threads_idempotent(tmp_path, fake_embed_api):
    threads = [(1, 10, "u1", "x")]
    data_root = _build_forum_db(tmp_path, threads)
    index_db = _empty_index_db(tmp_path)
    ingest_threads_impl(
        forum_db_file="forums/a.db", thread_ids=[1],
        index_db_path=index_db, data_root=data_root,
        embed_client=fake_embed_api, embed_model="m1",
    )
    res2 = ingest_threads_impl(
        forum_db_file="forums/a.db", thread_ids=[1],
        index_db_path=index_db, data_root=data_root,
        embed_client=fake_embed_api, embed_model="m1",
    )
    assert res2.already_indexed == 1
    assert res2.newly_embedded == 0


def test_ingest_threads_thread_ids_none_pulls_all_missing(tmp_path, fake_embed_api):
    threads = [(1, 10, "u1", "x"), (2, 10, "u2", "y")]
    data_root = _build_forum_db(tmp_path, threads)
    index_db = _empty_index_db(tmp_path)
    res = ingest_threads_impl(
        forum_db_file="forums/a.db", thread_ids=None,
        index_db_path=index_db, data_root=data_root,
        embed_client=fake_embed_api, embed_model="m1",
    )
    assert res.newly_embedded == 2


def test_ingest_threads_partial_failure_marks_failed(tmp_path, monkeypatch, fake_embed_api):
    """Simulate api failure mid-batch."""
    threads = [(i, 10, f"u{i}", f"标题{i}") for i in range(1, 6)]
    data_root = _build_forum_db(tmp_path, threads)
    index_db = _empty_index_db(tmp_path)

    class FailingThenSucceedingClient:
        def __init__(self):
            self.calls = 0
        def embed(self, texts):
            self.calls += 1
            if self.calls == 1:
                from bbs_database.router.errors import EmbedAPIError
                raise EmbedAPIError("fail batch 1")
            return fake_embed_api.embed(texts)

    client = FailingThenSucceedingClient()
    res = ingest_threads_impl(
        forum_db_file="forums/a.db", thread_ids=[1, 2, 3, 4, 5],
        index_db_path=index_db, data_root=data_root,
        embed_client=client, embed_model="m1",
        batch_size=3,
    )
    # First batch (3 threads) failed; second batch (2 threads) succeeded
    assert res.failed == 3
    assert res.newly_embedded == 2
    assert set(res.failed_thread_ids) == {1, 2, 3}
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_ingest_threads.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/bbs_database/ingest.py`**

```python
"""ingest_threads: embed and write thread vectors for newly crawled threads."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from bbs_database.embed.cache import encode_vec
from bbs_database.reader import open_ro
from bbs_database.router.errors import (
    EmbedAPIError,
    ForumDbNotFoundError,
)
from bbs_database.router.types import IngestResult


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _estimate_cost_cny(num_threads: int, avg_tokens_per_title: int = 30,
                      price_per_million_tokens: float = 0.7) -> float:
    tokens = num_threads * avg_tokens_per_title
    return tokens / 1_000_000.0 * price_per_million_tokens


def ingest_threads_impl(
    *,
    forum_db_file: str,
    thread_ids: list[int] | None,
    index_db_path: Path,
    data_root: Path,
    embed_client,
    embed_model: str,
    batch_size: int = 25,
) -> IngestResult:
    started = time.monotonic()
    fdb_path = Path(data_root) / forum_db_file
    if not fdb_path.exists():
        raise ForumDbNotFoundError(f"forum db not found: {fdb_path}")

    icx = sqlite3.connect(index_db_path)
    fcx = open_ro(fdb_path)
    try:
        # 1. resolve which thread_ids to consider
        if thread_ids is None:
            rows = fcx.execute(
                "SELECT id, board_node_id, title FROM threads"
            ).fetchall()
        else:
            if not thread_ids:
                return IngestResult(
                    forum_db_file=forum_db_file, requested=0,
                    already_indexed=0, newly_embedded=0, failed=0,
                    failed_thread_ids=[],
                    elapsed_seconds=time.monotonic() - started,
                    estimated_cost_cny=0.0, embed_model=embed_model,
                )
            placeholders = ",".join("?" * len(thread_ids))
            rows = fcx.execute(
                f"SELECT id, board_node_id, title FROM threads WHERE id IN ({placeholders})",
                thread_ids,
            ).fetchall()
        requested = len(rows)

        # 2. diff against existing thread_vector for this forum_db_file
        existing_ids = {
            r[0] for r in icx.execute(
                "SELECT thread_id FROM thread_vector "
                "WHERE forum_db_file = ? AND embed_model = ?",
                (forum_db_file, embed_model),
            )
        }
        to_embed = [r for r in rows if r[0] not in existing_ids]
        already_indexed = requested - len(to_embed)

        # 3. embed in batches; on failure record the batch as failed and continue
        newly_embedded = 0
        failed_ids: list[int] = []
        for i in range(0, len(to_embed), batch_size):
            batch = to_embed[i : i + batch_size]
            titles = [r[2] for r in batch]
            try:
                vecs = embed_client.embed(titles)
            except EmbedAPIError:
                failed_ids.extend(r[0] for r in batch)
                continue
            now = _now_iso()
            rows_to_insert = [
                (board_node_id, tid, forum_db_file, encode_vec(vec), embed_model, now)
                for (tid, board_node_id, _), vec in zip(batch, vecs)
            ]
            with icx:
                icx.executemany(
                    "INSERT INTO thread_vector(board_node_id, thread_id, forum_db_file, "
                    "vec, embed_model, built_at) VALUES (?,?,?,?,?,?)",
                    rows_to_insert,
                )
            newly_embedded += len(rows_to_insert)

        return IngestResult(
            forum_db_file=forum_db_file,
            requested=requested,
            already_indexed=already_indexed,
            newly_embedded=newly_embedded,
            failed=len(failed_ids),
            failed_thread_ids=failed_ids,
            elapsed_seconds=time.monotonic() - started,
            estimated_cost_cny=_estimate_cost_cny(newly_embedded),
            embed_model=embed_model,
        )
    finally:
        fcx.close()
        icx.close()
```

- [ ] **Step 4: Run tests, verify they pass**

```
./.venv/Scripts/pytest.exe tests/test_ingest_threads.py -v
```
Expected: 4 pass.

- [ ] **Step 5: Commit**

```bash
git add src/bbs_database/ingest.py tests/test_ingest_threads.py
git commit -m "feat(ingest): ingest_threads with diff, batching, partial failure"
```

---

## Task 17: Public `api.py` (4 functions)

**Files:**
- Create: `src/bbs_database/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api.py`:
```python
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from bbs_database.config import load_config

from bbs_database.api import (
    find_forums,
    ingest_threads,
    search_threads,
    get_thread,
)


def _full_cfg(tmp_path, data_root, index_db, sw):
    p = tmp_path / "routing.yaml"
    p.write_text(
        f"""
data_root: {data_root.as_posix()}
index_db: {index_db.as_posix()}
site_key: school-bbs
build:
  min_token_length: 2
  stopwords_file: {sw.as_posix()}
  pmi_threshold: -1.0
  similar_top_n: 5
  seed_top_terms_for_cooccur: 20
  cooccur_min_df: 2
  content_signal_strength_full: 5
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
  pmi_threshold: 0.3
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
  base_url: https://example.test/v1
  model: text-embedding-v3
  dimensions: 1024
  api_key_env: TEST_EMBED_KEY
  batch_size: 25
  max_input_chars: 2000
  max_retries: 3
  request_timeout_s: 30
  pinned_only_at_full_build: true
""".strip(),
        encoding="utf-8",
    )
    return p


def test_find_forums_smoke(crawler_dataset, tmp_path, fake_embed_api, monkeypatch):
    monkeypatch.setenv("TEST_EMBED_KEY", "sk-test")
    sw = tmp_path / "sw.txt"
    sw.write_text("\n", encoding="utf-8")
    index_db = tmp_path / "index.db"
    cfg_path = _full_cfg(tmp_path, crawler_dataset["root"], index_db, sw)

    # Build the index first using fake embed
    from bbs_database.builder import pipeline as pipe_mod
    monkeypatch.setattr(pipe_mod, "_make_embed_client", lambda c: fake_embed_api)
    cfg = load_config(cfg_path)
    pipe_mod.build_index(cfg)

    # Now exercise find_forums with the same fake embed
    from bbs_database import api as api_mod
    monkeypatch.setattr(api_mod, "_make_embed_client", lambda c: fake_embed_api)
    out = find_forums("张三", config_path=cfg_path)
    assert len(out) > 0
    # all candidates have populated forum_db_file
    assert all(c.forum_db_file for c in out)


def test_ingest_threads_then_search(crawler_dataset, tmp_path, fake_embed_api, monkeypatch):
    monkeypatch.setenv("TEST_EMBED_KEY", "sk-test")
    sw = tmp_path / "sw.txt"
    sw.write_text("\n", encoding="utf-8")
    index_db = tmp_path / "index.db"
    cfg_path = _full_cfg(tmp_path, crawler_dataset["root"], index_db, sw)

    from bbs_database.builder import pipeline as pipe_mod
    from bbs_database import api as api_mod
    monkeypatch.setattr(pipe_mod, "_make_embed_client", lambda c: fake_embed_api)
    monkeypatch.setattr(api_mod, "_make_embed_client", lambda c: fake_embed_api)
    cfg = load_config(cfg_path)
    pipe_mod.build_index(cfg)

    # ingest all academic threads (the fixture has 9 in academic.db, 2 pinned were build-time)
    res = ingest_threads("forums/academic.db", thread_ids=None, config_path=cfg_path)
    assert res.newly_embedded >= 1
    assert res.failed == 0

    # search
    hits = search_threads("张三", board_node_ids=[10], config_path=cfg_path)
    assert isinstance(hits, list)


def test_get_thread_returns_detail(crawler_dataset, tmp_path):
    td = get_thread(
        forum_db_file="forums/academic.db",
        thread_id=1,
        data_root=str(crawler_dataset["root"]),
    )
    assert td.thread_id == 1
```

- [ ] **Step 2: Run test, verify it fails**

```
./.venv/Scripts/pytest.exe tests/test_api.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/bbs_database/api.py`**

```python
"""Public Python API. Four functions: find_forums / ingest_threads /
search_threads / get_thread.

This is the only module BBS_MCP should import. All other modules are
internal.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from bbs_database.builder.tokenize import Tokenizer, load_stopwords
from bbs_database.config import Config, EmbedConfig, load_config
from bbs_database.ingest import ingest_threads_impl
from bbs_database.reader import open_ro
from bbs_database.router.hybrid import find_forums_impl
from bbs_database.router.search import search_threads_impl
from bbs_database.router.thread_detail import get_thread_impl
from bbs_database.router.types import ForumCandidate, IngestResult, ThreadDetail, ThreadHit

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent.parent / "config" / "routing.yaml"


def _load(config_path: Path | str | None) -> Config:
    p = Path(config_path) if config_path else _DEFAULT_CONFIG
    return load_config(p.resolve(), root=p.parent.parent)


def _make_embed_client(cfg: EmbedConfig):
    """Factory for embed client. Patched in tests."""
    from bbs_database.embed.client import EmbedClient
    return EmbedClient(cfg)


def find_forums(
    query: str, *,
    site_key: str | None = None,
    top_k: int = 8,
    overrides: dict | None = None,
    config_path: Path | str | None = None,
) -> list[ForumCandidate]:
    cfg = _load(config_path)
    routing_cfg = dict(cfg.routing)
    if overrides:
        routing_cfg.update(overrides)
    tokenizer = Tokenizer(
        stopwords=load_stopwords(cfg.build.stopwords_path),
        min_length=cfg.build.min_token_length,
    )
    embed_client = _make_embed_client(cfg.embed)
    cx = sqlite3.connect(f"file:{cfg.index_db_path.as_posix()}?mode=ro", uri=True)
    try:
        return find_forums_impl(
            cx, query=query, tokenizer=tokenizer,
            embed_client=embed_client,
            routing_cfg=routing_cfg, top_k=top_k,
        )
    finally:
        cx.close()


def ingest_threads(
    forum_db_file: str,
    thread_ids: list[int] | None = None,
    *,
    overrides: dict | None = None,
    config_path: Path | str | None = None,
) -> IngestResult:
    cfg = _load(config_path)
    embed_client = _make_embed_client(cfg.embed)
    bs = cfg.embed.batch_size
    if overrides and "batch_size" in overrides:
        bs = overrides["batch_size"]
    return ingest_threads_impl(
        forum_db_file=forum_db_file,
        thread_ids=thread_ids,
        index_db_path=cfg.index_db_path,
        data_root=cfg.data_root_path,
        embed_client=embed_client,
        embed_model=cfg.embed.model,
        batch_size=bs,
    )


def search_threads(
    query: str, *,
    site_key: str | None = None,
    board_node_ids: list[int] | None = None,
    top_k_forums: int = 5,
    per_board_limit: int | None = None,
    total_limit: int | None = None,
    overrides: dict | None = None,
    config_path: Path | str | None = None,
) -> list[ThreadHit]:
    cfg = _load(config_path)
    search_cfg = dict(cfg.search)
    if per_board_limit is not None:
        search_cfg["per_board_limit"] = per_board_limit
    if total_limit is not None:
        search_cfg["total_limit"] = total_limit
    if overrides:
        search_cfg.update(overrides)
    embed_client = _make_embed_client(cfg.embed)
    cx = sqlite3.connect(f"file:{cfg.index_db_path.as_posix()}?mode=ro", uri=True)
    try:
        # decide board scope
        if board_node_ids is None:
            tokenizer = Tokenizer(
                stopwords=load_stopwords(cfg.build.stopwords_path),
                min_length=cfg.build.min_token_length,
            )
            forums = find_forums_impl(
                cx, query=query, tokenizer=tokenizer,
                embed_client=embed_client,
                routing_cfg=dict(cfg.routing), top_k=top_k_forums,
            )
            board_node_ids = [c.board_node_id for c in forums]
            board_score = {c.board_node_id: c.final_score for c in forums}
        else:
            board_score = {bid: 1.0 for bid in board_node_ids}
        return search_threads_impl(
            cx, query=query,
            board_node_ids=board_node_ids,
            board_score=board_score,
            embed_client=embed_client,
            data_root=cfg.data_root_path,
            search_cfg=search_cfg,
        )
    finally:
        cx.close()


def get_thread(
    forum_db_file: str,
    thread_id: int,
    *,
    data_root: Path | str | None = None,
    config_path: Path | str | None = None,
) -> ThreadDetail:
    if data_root is None:
        cfg = _load(config_path)
        data_root = cfg.data_root_path
    return get_thread_impl(data_root, forum_db_file, thread_id)
```

- [ ] **Step 4: Run tests, verify they pass**

```
./.venv/Scripts/pytest.exe tests/test_api.py -v
```
Expected: 3 pass.

- [ ] **Step 5: Commit**

```bash
git add src/bbs_database/api.py tests/test_api.py
git commit -m "feat(api): public Python API exposing four functions"
```

---

## Task 18: Golden queries starter + smoke marker

**Files:**
- Create: `tests/golden_queries.yaml`
- Create: `tests/test_golden.py`
- Modify: `pyproject.toml` (register `smoke` marker)

- [ ] **Step 1: Register the `smoke` marker**

Append to `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
markers = [
  "smoke: requires real embedding API key; skipped by default in CI"
]
```

- [ ] **Step 2: Write `tests/golden_queries.yaml`**

```yaml
# Hand-labeled queries → expected board path substring.
# Used by tests/test_golden.py with @pytest.mark.smoke (skipped without DASHSCOPE_API_KEY).
# Add more rows as we learn what queries the agent actually issues.
- query: "兼职招聘"
  expect_path_contains: "兼职"
- query: "情感困扰"
  expect_path_contains: "情感"
- query: "考试复习"
  expect_path_contains: "考试"
- query: "出二手书"
  expect_path_contains: "二手"
- query: "找房子"
  expect_path_contains: "租"
- query: "电脑配置推荐"
  expect_path_contains: "电脑"
- query: "求职面试经验"
  expect_path_contains: "求职"
- query: "校园活动"
  expect_path_contains: "校园"
- query: "毕业论文求助"
  expect_path_contains: "毕"
- query: "游戏开黑"
  expect_path_contains: "游戏"
```

- [ ] **Step 3: Write `tests/test_golden.py`**

```python
"""Golden query smoke test — requires DASHSCOPE_API_KEY in environment.

Skipped by default. Run with:
    DASHSCOPE_API_KEY=sk-... pytest -m smoke tests/test_golden.py
"""

import os
from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.smoke


@pytest.fixture
def golden():
    path = Path(__file__).parent / "golden_queries.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture
def real_api_key():
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        pytest.skip("DASHSCOPE_API_KEY not set")
    return key


def test_top3_hit_rate_at_least_50_percent(golden, real_api_key):
    from bbs_database.api import find_forums

    hits = 0
    for case in golden:
        query = case["query"]
        expect = case["expect_path_contains"]
        out = find_forums(query, top_k=3)
        if any(expect in c.path for c in out):
            hits += 1
    rate = hits / len(golden)
    assert rate >= 0.5, f"golden hit rate {rate:.2f} < 0.5; misses on {len(golden) - hits}/{len(golden)}"
```

- [ ] **Step 4: Sanity — confirm smoke marker hides test by default**

```
./.venv/Scripts/pytest.exe -q
```
Expected: 1 test "deselected" (or skipped) for `tests/test_golden.py`. Total count unchanged otherwise.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_queries.yaml tests/test_golden.py pyproject.toml
git commit -m "test(golden): 10-query smoke test + smoke marker"
```

---

## Task 19: Real-data smoke + record baseline

**Files:**
- Modify: `docs/superpowers/specs/2026-05-12-bbs-database-vector-routing.md` (append §7.2 baseline section)

This is a manual verification + observation task — not a TDD cycle.

- [ ] **Step 1: Ensure `.env` has a real key**

Create or update `.env` at repo root with a real DashScope key:

```
DASHSCOPE_API_KEY=sk-your-real-key
```

(Do not commit `.env`. It's already gitignored.)

- [ ] **Step 2: Rebuild with embeddings**

```bash
./.venv/Scripts/python.exe scripts/rebuild_index.py --full --config config/routing.yaml
```

Expected: completes in ~1 minute on the existing 259-board / 980-thread dataset. Verify `data/index.db` grew (should be ~3 MB classical + ~1 MB vector).

- [ ] **Step 3: Sanity SQL**

```bash
./.venv/Scripts/python.exe -c "
import sqlite3
cx = sqlite3.connect('file:data/index.db?mode=ro', uri=True)
print('board_vector:', cx.execute('SELECT count(*) FROM board_vector').fetchone()[0])
print('thread_vector:', cx.execute('SELECT count(*) FROM thread_vector').fetchone()[0])
print('meta:', dict(cx.execute('SELECT key, value FROM _meta')))
cx.close()
"
```

Expected: `board_vector ≈ 259`, `thread_vector ≈ 30-60` (only pinned threads at full build), `_meta` includes `embed_provider/model/dim`.

- [ ] **Step 4: Run golden smoke test**

```bash
./.venv/Scripts/pytest.exe -m smoke tests/test_golden.py -v
```

Record actual top-3 hit rate. If below 50%, do not block — inspect the misses, note them, and proceed (this is a starter golden set; threshold will firm up in P3).

- [ ] **Step 5: Append baseline to v2.0 spec**

Append to `docs/superpowers/specs/2026-05-12-bbs-database-vector-routing.md` at the end (after §7.1):

```markdown

### 7.2 P2-vector 首次基线（YYYY-MM-DD）

首次跑通 hybrid 路径后，在同一数据集（10 forums / 259 boards / 980 thread）上：

| 指标 | 值 | 备注 |
|---|---|---|
| board_vector 表行数 | <N> | 等于 forum_profile 行数 |
| thread_vector 表行数 | <N> | 初始仅 pinned 帖；后续靠 ingest_threads 增量 |
| build 耗时（全量） | ~<S> 秒 | 含 Phase 0 + 1 + 2 |
| golden top-3 hit rate | <R>% | 10 条 starter 查询 |
| 单次 find_forums 时延 | ~<MS> ms | 含 1 次 embed 调用 |

**何时重新 baseline：** 换 embedding model、调 δ / γ 权重、改 stopwords、改 prompt 风格的查询语料——任一改动后跑 `pytest -m smoke tests/test_golden.py` 重测。
```

Fill in the placeholders `<N>` / `<S>` / `<R>` / `<MS>` with the actual measured values from steps 3-4. Update the date to today.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-05-12-bbs-database-vector-routing.md
git commit -m "docs(spec): record P2-vector first baseline on real data"
```

---

## Self-Review checklist (run at end)

**Spec coverage:**
- v2.0 spec §2.1/§2.2/§2.3 (schema) → Task 1 ✓
- v2.0 spec §3.1 (3-phase build) → Tasks 6, 7 ✓
- v2.0 spec §3.2 (ingest_threads) → Task 16 ✓
- v2.0 spec §3.3 (error matrix) → Tasks 3, 8, 16 ✓
- v2.0 spec §4.1 (find_forums) → Task 13 ✓
- v2.0 spec §4.2 (search_threads) → Task 14 ✓
- v2.0 spec §4.3 (parameters) → Task 2 + Task 13 step 5 ✓
- v2.0 spec §4.4 (degradation) → covered in Task 13 (vector_disabled), Task 14 (empty vector) ✓
- v2.0 spec §4.5 (evidence) → Task 9 (types) + Task 13 (populate) ✓
- v2.0 spec §5.1 (4 functions) → Task 17 ✓
- v2.0 spec §5.2 (dataclasses) → Task 9 ✓
- v2.0 spec §5.3 (errors) → Task 8 ✓
- v2.0 spec §6.1 (deps) → Task 0 ✓
- v2.0 spec §6.2 (.env) → Task 0 ✓
- v2.0 spec §6.3 (routing.yaml) → Task 2 ✓
- v2.0 spec §6.4 (test strategy) → Tasks 5 (fake fixture) + 18 (golden+smoke) ✓
- v2.0 spec §7.1 (P2 task estimate 12-15) → 20 tasks delivered (close)
- v2.0 spec §7.2 (baseline record) → Task 19 ✓
- Not covered: MCP wrapper (P4), incremental --boards (P3), CI integration (P3) — out of P2 scope

**Placeholder scan:**
- No "TBD" / "TODO" in plan
- No "appropriate error handling" / "handle edge cases" generic phrasing
- Every test has actual code; every implementation has actual code

**Type consistency:**
- `BoardSpec.board_node_id: int` (Task 6) ↔ `forum_profile.board_node_id` (P1 schema) ↔ `ForumCandidate.board_node_id: int` (Task 9) — consistent
- `ThreadSpec.forum_db_file: str` (Task 6) ↔ `thread_vector.forum_db_file TEXT` (Task 1) ↔ `IngestResult.forum_db_file: str` (Task 9) — consistent
- `vec` blob: encoded as `np.float32.tobytes()` everywhere (Task 4, Task 6, Task 12, Task 13)
- `routing_cfg["pmi_threshold"]` introduced in Task 13 step 5; consumed by Task 13's hybrid impl
- `_make_embed_client(cfg)` factory pattern used in pipeline (Task 7) and api (Task 17) — both patchable in tests

---

## Execution Handoff

Plan saved to `docs/superpowers/plans/2026-05-12-p2-vector-routing.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review (spec compliance + code quality) between tasks, fast iteration with isolated context per task.

**2. Inline Execution** — execute in this session via executing-plans, batched with checkpoints for review.

Which approach?
