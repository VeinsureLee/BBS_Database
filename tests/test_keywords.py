import math

from bbs_database.builder.keywords import (
    BoardTokens,
    KeywordsResult,
    compute_keywords,
)


def _bt(board_id, declared, content):
    return BoardTokens(board_node_id=board_id, declared_tokens=declared, content_tokens=content)


def test_idf_counts_dfs_across_declared_and_content():
    boards = [
        _bt(1, ["学院"], ["张三", "张三", "老师"]),
        _bt(2, ["学院"], ["李四", "老师"]),
        _bt(3, ["匿名"], ["张三", "老师"]),
    ]
    res = compute_keywords(boards)
    # 张三 in boards 1, 3 → DF=2; 老师 in all three → DF=3; 学院 in 1, 2 → DF=2.
    assert res.df["张三"] == 2
    assert res.df["老师"] == 3
    assert res.df["学院"] == 2


def test_idf_formula_log_of_n_over_one_plus_df_clamped_at_zero():
    # DF < N → IDF is the raw log
    boards = [_bt(1, [], ["a"]), _bt(2, [], []), _bt(3, [], [])]
    res = compute_keywords(boards)
    assert math.isclose(res.idf["a"], math.log(3 / (1 + 1)))

    # DF == N → log goes non-positive; we clamp to 0
    boards = [_bt(1, [], ["b"]), _bt(2, [], ["b"])]
    res = compute_keywords(boards)
    assert res.idf["b"] == 0.0


def test_edge_forum_topic_source_classification():
    # N=4 so DF=2 terms have IDF=log(4/3)>0 → edges actually get emitted
    boards = [
        _bt(1, ["x"], ["y", "z"]),
        _bt(2, [], ["x", "y"]),
        _bt(3, [], ["z"]),
        _bt(4, [], []),
    ]
    res = compute_keywords(boards)
    rows = {(b, t): src for (b, t, _td, _tc, src) in res.edges}
    assert rows[(1, "x")] == "declared"
    assert rows[(1, "y")] == "content"
    assert rows[(2, "x")] == "content"
    assert rows[(2, "y")] == "content"


def test_only_emits_edges_with_positive_weight():
    # term in declared-only with DF == N → IDF clamped to 0 → tfidf=0 → no edge.
    boards = [_bt(1, ["common"], []), _bt(2, ["common"], [])]
    res = compute_keywords(boards)
    for (_b, _t, td, tc, _s) in res.edges:
        assert td + tc > 0


def test_vector_norm_is_l2_of_summed_weights():
    # use N=3 so DF=2 terms produce IDF>0 and we get real weights
    boards = [_bt(1, ["x"], ["y"]), _bt(2, [], ["x", "y"]), _bt(3, [], [])]
    res = compute_keywords(boards)
    sq = sum((td + tc) ** 2 for (b, _t, td, tc, _s) in res.edges if b == 1)
    assert math.isclose(res.vector_norm[1], math.sqrt(sq))


def test_vectors_dict_includes_summed_weight_per_term_per_board():
    # board 1 has term x in BOTH declared and content; DF=1, N=3 so IDF>0
    boards = [_bt(1, ["x"], ["x"]), _bt(2, [], []), _bt(3, [], [])]
    res = compute_keywords(boards)
    assert "x" in res.vectors[1]
    src_for_1_x = next(s for (b, t, _td, _tc, s) in res.edges if (b, t) == (1, "x"))
    assert src_for_1_x == "both"
