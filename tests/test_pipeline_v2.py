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
        # fixture has 3 pinned threads: 1 in board 10, 1 in board 11 (academic.db),
        # and 1 in board 20 (anonymous.db)
        assert tv == 3
        meta = dict(cx.execute("SELECT key, value FROM _meta"))
        assert meta["embed_provider"] == "dashscope"
        assert meta["embed_model"] == "text-embedding-v3"
        assert meta["embed_dim"] == "1024"
    finally:
        cx.close()


def test_build_index_embed_disabled_classical_tables_complete(crawler_dataset, tmp_path):
    """Verify classical tables are fully populated even when embed is disabled."""
    sw = tmp_path / "sw.txt"
    sw.write_text("\n", encoding="utf-8")
    index_db = tmp_path / "index.db"
    cfg = load_config(_write_config(tmp_path, crawler_dataset["root"], index_db, sw,
                                    embed_enabled=False))
    build_index(cfg)
    cx = sqlite3.connect(index_db)
    try:
        # FTS and edges still work
        assert cx.execute("SELECT count(*) FROM edge_forum_topic").fetchone()[0] > 0
        # meta has classical keys
        meta = dict(cx.execute("SELECT key, value FROM _meta"))
        assert "schema_version" in meta
        assert "built_at" in meta
        # no embed meta keys
        assert "embed_provider" not in meta
        assert "embed_model" not in meta
    finally:
        cx.close()
