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
