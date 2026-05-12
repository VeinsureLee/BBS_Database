import math
import sqlite3

from bbs_database.builder.schema import ALL_DDL
from bbs_database.router.classical import classical_direct, classical_expansion


def _seed_index(tmp_path):
    cx = sqlite3.connect(tmp_path / "index.db")
    for stmt in ALL_DDL:
        cx.execute(stmt)
    # 3 boards, simple data
    profiles = [
        # board, name, path, content_signal, activity
        (1, "A", "A", 0.5, 0.1),
        (2, "B", "B", 0.0, 0.5),
        (3, "C", "C", 0.5, 0.0),
    ]
    for bid, name, path, sig, act in profiles:
        cx.execute(
            "INSERT INTO forum_profile(board_node_id, site_key, forum_db_file, name, path, "
            "title_count, activity_score, content_signal_strength, vector_norm, built_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (bid, "s", f"forums/{name}.db", name, path, 100, act, sig, 1.0, "2026-01-01"),
        )
    # edge_forum_topic
    topic_edges = [
        (1, "x", 0.5, 0.0, "declared"),
        (1, "y", 0.0, 0.4, "content"),
        (2, "x", 0.0, 0.3, "content"),
        (3, "z", 0.0, 0.2, "content"),
    ]
    cx.executemany(
        "INSERT INTO edge_forum_topic(board_node_id, term, tfidf_declared, tfidf_content, source) "
        "VALUES (?,?,?,?,?)", topic_edges,
    )
    cx.execute(
        "INSERT INTO edge_forum_entity(board_node_id, entity, entity_type, thread_count) "
        "VALUES (1, 'foo', 'person', 5)"
    )
    # cooccur
    cx.execute(
        "INSERT INTO edge_topic_cooccur(term_a, term_b, weight) VALUES ('x', 'y', 0.5)"
    )
    cx.commit()
    return cx


def test_classical_direct_with_entity(tmp_path):
    cx = _seed_index(tmp_path)
    try:
        scores = dict(classical_direct(
            cx, q_terms=["x"], q_entities=[("foo", "person")],
            alpha_declared=1.0, alpha_content=1.5,
            alpha_entity=2.0, alpha_activity=0.1,
        ))
        # board 1: declared(x)=0.5*1.0 + entity(foo,person, count 5)=2*ln(6) + act=0.01
        expected_1 = 0.5 + 2.0 * math.log(1 + 5) + 0.1 * 0.1
        assert math.isclose(scores[1], expected_1, abs_tol=1e-6)
    finally:
        cx.close()


def test_classical_expansion_via_cooccur(tmp_path):
    cx = _seed_index(tmp_path)
    try:
        seeds = [1]  # board with high x weight
        scores = classical_expansion(
            cx, seeds=seeds, q_terms=["x"],
            alpha_declared=1.0, alpha_content=1.5,
            beta=0.5,
            seed_top_terms=20, pmi_threshold=0.3, m_expansion=10,
        )
        # 'y' should expand because cooccur(x,y)=0.5 > 0.3 threshold
        # board 1 has y in content → gets expansion contribution
        assert scores[1] > 0
    finally:
        cx.close()


def test_classical_direct_empty_terms_and_entities_returns_only_activity(tmp_path):
    cx = _seed_index(tmp_path)
    try:
        scores = dict(classical_direct(
            cx, q_terms=[], q_entities=[],
            alpha_declared=1.0, alpha_content=1.5,
            alpha_entity=2.0, alpha_activity=0.1,
        ))
        # All boards get only alpha_activity * activity_score
        assert math.isclose(scores[1], 0.1 * 0.1, abs_tol=1e-6)
        assert math.isclose(scores[2], 0.1 * 0.5, abs_tol=1e-6)
        assert math.isclose(scores[3], 0.0, abs_tol=1e-6)
    finally:
        cx.close()
