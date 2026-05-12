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
