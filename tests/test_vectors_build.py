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
