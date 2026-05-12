import math

from bbs_database.builder.cooccur import compute_cooccur


def test_pmi_for_perfectly_co_occurring_pair():
    vectors = {
        1: {"a": 1.0, "b": 1.0},
        2: {"a": 1.0, "b": 1.0},
        3: {"c": 1.0},
    }
    df = {"a": 2, "b": 2, "c": 1}
    edges = compute_cooccur(
        vectors,
        df=df,
        total_boards=3,
        pmi_threshold=-1.0,
        top_terms_per_board=10,
        min_df=2,
    )
    by_pair = {(a, b): w for (a, b, w) in edges}
    # P(a,b)=2/3, P(a)=P(b)=2/3 → PMI = log((2/3) / ((2/3)*(2/3))) = log(3/2)
    assert ("a", "b") in by_pair
    assert math.isclose(by_pair[("a", "b")], math.log((2/3) / ((2/3) * (2/3))))


def test_min_df_filter_excludes_rare_terms():
    vectors = {
        1: {"a": 1.0, "b": 1.0, "rare": 1.0},
        2: {"a": 1.0, "b": 1.0},
    }
    df = {"a": 2, "b": 2, "rare": 1}
    edges = compute_cooccur(
        vectors, df=df, total_boards=2,
        pmi_threshold=-10.0, top_terms_per_board=10, min_df=2,
    )
    pairs = {(a, b) for (a, b, _w) in edges}
    assert ("a", "rare") not in pairs
    assert ("b", "rare") not in pairs


def test_pmi_threshold_filters_weak_associations():
    vectors = {1: {"a": 1.0}, 2: {"b": 1.0}, 3: {"a": 1.0, "b": 1.0}}
    df = {"a": 2, "b": 2}
    edges = compute_cooccur(
        vectors, df=df, total_boards=3,
        pmi_threshold=0.5, top_terms_per_board=10, min_df=2,
    )
    # P(ab)=1/3, P(a)*P(b) = 4/9 → PMI = log(3/4) < 0 → drop with threshold 0.5
    assert edges == []


def test_pair_ordering_is_lexicographic():
    vectors = {1: {"b": 1.0, "a": 1.0}, 2: {"a": 1.0, "b": 1.0}}
    df = {"a": 2, "b": 2}
    edges = compute_cooccur(
        vectors, df=df, total_boards=2,
        pmi_threshold=-10.0, top_terms_per_board=10, min_df=2,
    )
    assert all(a < b for (a, b, _w) in edges)


def test_top_terms_caps_per_board_pair_enumeration():
    vectors = {1: {"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}}
    df = {t: 1 for t in "abcde"}
    df.update({t: 2 for t in "ab"})  # only a,b survive min_df=2
    edges = compute_cooccur(
        vectors, df=df, total_boards=1,
        pmi_threshold=-10.0, top_terms_per_board=2, min_df=2,
    )
    assert len(edges) == 1
    assert edges[0][:2] == ("a", "b")
