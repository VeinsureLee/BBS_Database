import sqlite3

import jieba

from bbs_database.builder.fts import populate_fts
from bbs_database.builder.schema import (
    DDL_FTS, DDL_FTS_MAP, DDL_FTS_MAP_IDX,
)


def _fresh_index_db(tmp_path):
    db = sqlite3.connect(tmp_path / "index.db")
    db.execute(DDL_FTS)
    db.execute(DDL_FTS_MAP)
    db.execute(DDL_FTS_MAP_IDX)
    db.commit()
    return db


def test_populate_fts_inserts_one_row_per_thread(tmp_path):
    db = _fresh_index_db(tmp_path)
    threads = [
        (10, 1, "张三老师讲课", "forums/academic.db"),
        (10, 2, "李四老师考试", "forums/academic.db"),
        (20, 3, "悄悄话 张三 老师", "forums/anonymous.db"),
    ]
    populate_fts(db, threads)
    db.commit()
    n_fts = db.execute("SELECT count(*) FROM thread_title_fts").fetchone()[0]
    n_map = db.execute("SELECT count(*) FROM fts_map").fetchone()[0]
    assert n_fts == 3 and n_map == 3
    db.close()


def test_fts_match_finds_terms(tmp_path):
    db = _fresh_index_db(tmp_path)
    threads = [
        (10, 1, "张三老师讲课", "forums/academic.db"),
        (10, 2, "李四老师考试", "forums/academic.db"),
    ]
    populate_fts(db, threads)
    db.commit()
    rows = list(db.execute(
        "SELECT m.thread_id FROM thread_title_fts JOIN fts_map m ON m.rowid = thread_title_fts.rowid "
        "WHERE thread_title_fts MATCH '张三'"
    ))
    assert rows == [(1,)]
    db.close()


def test_fts_map_carries_board_and_forum_path(tmp_path):
    db = _fresh_index_db(tmp_path)
    populate_fts(db, [(20, 99, "测试标题", "forums/anonymous.db")])
    db.commit()
    row = db.execute(
        "SELECT board_node_id, thread_id, forum_db_file FROM fts_map"
    ).fetchone()
    assert row == (20, 99, "forums/anonymous.db")
    db.close()
