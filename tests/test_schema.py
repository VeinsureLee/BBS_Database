import sqlite3

from bbs_database.builder.schema import (
    ALL_DDL,
    META_INSERTS,
    SCHEMA_VERSION,
    ALGORITHM_VERSION,
)


def test_apply_all_ddl_creates_expected_tables(tmp_path):
    db_path = tmp_path / "index.db"
    cx = sqlite3.connect(db_path)
    try:
        for stmt in ALL_DDL:
            cx.execute(stmt)
        cx.commit()
        tables = {
            row[0]
            for row in cx.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','virtual')"
            )
        }
    finally:
        cx.close()
    assert {
        "_meta",
        "forum_profile",
        "edge_forum_topic",
        "edge_forum_entity",
        "edge_topic_cooccur",
        "edge_forum_similar",
        "thread_title_fts",
        "fts_map",
    }.issubset(tables)


def test_meta_inserts_set_versions(tmp_path):
    db_path = tmp_path / "index.db"
    cx = sqlite3.connect(db_path)
    try:
        for stmt in ALL_DDL:
            cx.execute(stmt)
        for sql, params in META_INSERTS:
            cx.execute(sql, params)
        cx.commit()
        rows = dict(cx.execute("SELECT key, value FROM _meta"))
    finally:
        cx.close()
    assert rows["schema_version"] == SCHEMA_VERSION
    assert rows["algorithm_version"] == ALGORITHM_VERSION


def test_cooccur_check_constraint_rejects_unordered(tmp_path):
    db_path = tmp_path / "index.db"
    cx = sqlite3.connect(db_path)
    try:
        for stmt in ALL_DDL:
            cx.execute(stmt)
        cx.commit()
        try:
            cx.execute(
                "INSERT INTO edge_topic_cooccur(term_a, term_b, weight) VALUES (?, ?, ?)",
                ("z", "a", 0.5),
            )
            cx.commit()
            assert False, "expected CHECK constraint failure"
        except sqlite3.IntegrityError:
            pass
    finally:
        cx.close()
