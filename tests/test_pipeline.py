import json
import sqlite3
from pathlib import Path

from bbs_database.builder.pipeline import build_index
from bbs_database.config import load_config


def _write_config(tmp_path: Path, crawler_root: Path, index_db: Path, stopwords: Path) -> Path:
    cfg = tmp_path / "routing.yaml"
    cfg.write_text(
        f"""
data_root: {crawler_root.as_posix()}
index_db: {index_db.as_posix()}
site_key: school-bbs
build:
  min_token_length: 2
  stopwords_file: {stopwords.as_posix()}
  pmi_threshold: -1.0
  similar_top_n: 5
  seed_top_terms_for_cooccur: 20
  cooccur_min_df: 2
  content_signal_strength_full: 5
routing: {{}}
search: {{}}
""".strip(),
        encoding="utf-8",
    )
    return cfg


def test_build_index_end_to_end(crawler_dataset, tmp_path: Path):
    sw = tmp_path / "sw.txt"
    sw.write_text("的\n了\n", encoding="utf-8")
    index_db = tmp_path / "index.db"
    cfg_path = _write_config(tmp_path, crawler_dataset["root"], index_db, sw)
    cfg = load_config(cfg_path)
    build_index(cfg)

    cx = sqlite3.connect(index_db)
    try:
        boards = {row[0] for row in cx.execute("SELECT board_node_id FROM forum_profile")}
        assert boards == {10, 11, 20}

        a = cx.execute(
            "SELECT name, path, title_count, content_signal_strength, activity_score, pinned_titles "
            "FROM forum_profile WHERE board_node_id=10"
        ).fetchone()
        assert a[0] == "学院A"
        assert "学术" in a[1]
        assert a[2] >= 1
        assert 0.0 <= a[3] <= 1.0
        assert 0.0 <= a[4] <= 1.0
        assert json.loads(a[5])  # pinned_titles is JSON

        # edges populated
        assert cx.execute("SELECT count(*) FROM edge_forum_topic").fetchone()[0] > 0
        assert cx.execute(
            "SELECT count(*) FROM edge_forum_entity WHERE entity='张三' AND entity_type='person'"
        ).fetchone()[0] >= 2  # academic + anonymous

        # FTS works
        rows = list(cx.execute(
            "SELECT m.thread_id FROM thread_title_fts JOIN fts_map m ON m.rowid = thread_title_fts.rowid "
            "WHERE thread_title_fts MATCH '张三'"
        ))
        assert len(rows) >= 2

        # meta
        meta = dict(cx.execute("SELECT key, value FROM _meta"))
        assert "schema_version" in meta and "built_at" in meta
    finally:
        cx.close()


def test_build_index_is_idempotent(crawler_dataset, tmp_path: Path):
    sw = tmp_path / "sw.txt"
    sw.write_text("\n", encoding="utf-8")
    index_db = tmp_path / "index.db"
    cfg = load_config(_write_config(tmp_path, crawler_dataset["root"], index_db, sw))
    build_index(cfg)
    n1 = sqlite3.connect(index_db).execute("SELECT count(*) FROM forum_profile").fetchone()[0]
    build_index(cfg)
    n2 = sqlite3.connect(index_db).execute("SELECT count(*) FROM forum_profile").fetchone()[0]
    assert n1 == n2
