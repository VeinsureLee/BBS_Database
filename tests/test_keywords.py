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
    # 张三 appears in boards 1 and 3 → DF=2
    assert res.df["张三"] == 2
    # 老师 appears in all three boards → DF=3
    assert res.df["老师"] == 3
    # 学院 only in declared of boards 1 and 2 → DF=2
    assert res.df["学院"] == 2


def test_idf_formula_is_log_of_n_over_one_plus_df():
    boards = [_bt(1, [], ["a"]), _bt(2, [], ["a"])]
    res = compute_keywords(boards)
    assert math.isclose(res.idf["a"], math.log(2 / (1 + 2)))


def test_edge_forum_topic_source_classification():
    boards = [_bt(1, ["x"], ["y", "z"]), _bt(2, [], ["x", "y"])]
    res = compute_keywords(boards)
    rows = {(b, t): src for (b, t, _td, _tc, src) in res.edges}
    assert rows[(1, "x")] == "declared"
    assert rows[(1, "y")] == "content"
    assert rows[(2, "x")] == "content"
    assert rows[(2, "y")] == "content"


def test_only_emits_edges_with_positive_weight():
    # term in declared only with IDF=0 (DF == N) should be dropped
    boards = [_bt(1, ["common"], []), _bt(2, ["common"], [])]
    res = compute_keywords(boards)
    # log(N/(1+DF)) = log(2/3) < 0 → tfidf is negative, edge still positive-weight rule excludes
    # We exclude only when (declared + content) <= 0.
    for (_b, t, td, tc, _s) in res.edges:
        assert td + tc > 0


def test_vector_norm_is_l2_of_summed_weights():
    boards = [_bt(1, ["x"], ["y"]), _bt(2, [], ["x", "y"])]
    res = compute_keywords(boards)
    # for board 1: weights {x: tfidf_declared_x, y: tfidf_content_y}; both DF=2 → IDF=log(2/3) < 0
    # vector_norm = sqrt(sum(w^2))
    sq = sum((td + tc) ** 2 for (b, _t, td, tc, _s) in res.edges if b == 1)
    assert math.isclose(res.vector_norm[1], math.sqrt(sq))


def test_vectors_dict_includes_summed_weight_per_term_per_board():
    boards = [_bt(1, ["x"], ["x"]), _bt(2, [], ["x"])]
    res = compute_keywords(boards)
    # board 1 has term x in both declared and content
    assert "x" in res.vectors[1]
