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
