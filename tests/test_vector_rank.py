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


def test_cosine_top_k_returns_top_k_by_cosine():
    # Use non-parallel vectors so cosine values are distinct and ordering is unambiguous.
    q = np.array([1.0, 0.0, 0.0] + [0.0] * 1021, dtype=np.float32)
    items = [
        ("strong", np.array([1.0, 0.0, 0.0] + [0.0] * 1021, dtype=np.float32)),  # cos 1.0
        ("medium", np.array([1.0, 1.0, 0.0] + [0.0] * 1021, dtype=np.float32)),  # cos ~0.707
        ("orthogonal", np.array([0.0, 1.0, 0.0] + [0.0] * 1021, dtype=np.float32)),  # cos 0
    ]
    out = cosine_top_k(q, items, k=2)
    assert [k for k, _ in out] == ["strong", "medium"]
    assert math.isclose(out[0][1], 1.0, abs_tol=1e-6)
    assert math.isclose(out[1][1], 1.0 / math.sqrt(2), abs_tol=1e-6)


def test_cosine_top_k_handles_zero_vectors():
    q = np.zeros(1024, dtype=np.float32)
    items = [("a", np.ones(1024, dtype=np.float32))]
    out = cosine_top_k(q, items, k=5)
    # Zero query produces zero cosine; we expect it to still return items (with 0 score)
    assert len(out) == 1
    assert math.isclose(out[0][1], 0.0, abs_tol=1e-6)
