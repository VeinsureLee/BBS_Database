import math

from bbs_database.builder.similar import compute_similar


def test_cosine_for_identical_vectors_is_one():
    vectors = {1: {"a": 1.0, "b": 1.0}, 2: {"a": 1.0, "b": 1.0}}
    norms = {1: math.sqrt(2), 2: math.sqrt(2)}
    edges = compute_similar(vectors, norms, top_n=5)
    by_pair = {(a, b): c for (a, b, c) in edges}
    assert math.isclose(by_pair[(1, 2)], 1.0)
    assert math.isclose(by_pair[(2, 1)], 1.0)


def test_orthogonal_vectors_are_skipped():
    vectors = {1: {"a": 1.0}, 2: {"b": 1.0}}
    norms = {1: 1.0, 2: 1.0}
    edges = compute_similar(vectors, norms, top_n=5)
    assert edges == []


def test_top_n_limits_neighbors():
    vectors = {
        1: {"a": 1.0},
        2: {"a": 1.0, "b": 0.5},
        3: {"a": 1.0, "c": 0.3},
        4: {"a": 1.0, "d": 0.1},
        5: {"a": 0.9},
    }
    norms = {k: math.sqrt(sum(v * v for v in vec.values())) for k, vec in vectors.items()}
    edges = compute_similar(vectors, norms, top_n=2)
    neighbors_of_1 = [b for (a, b, _c) in edges if a == 1]
    assert len(neighbors_of_1) == 2


def test_zero_norm_board_yields_no_edges():
    vectors = {1: {}, 2: {"a": 1.0}}
    norms = {1: 0.0, 2: 1.0}
    edges = compute_similar(vectors, norms, top_n=5)
    assert all(a != 1 for (a, _b, _c) in edges)
