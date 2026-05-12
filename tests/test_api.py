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
