"""TF-IDF computation over boards.

Inputs: each board's declared_tokens (name+path+pinned_titles) and content_tokens (all titles).
Outputs: edges, df, idf, per-board vectors, per-board L2 norms.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class BoardTokens:
    board_node_id: int
    declared_tokens: list[str]
    content_tokens: list[str]


@dataclass
class KeywordsResult:
    edges: list[tuple[int, str, float, float, str]]
    """Each entry: (board_node_id, term, tfidf_declared, tfidf_content, source)."""

    df: dict[str, int]
    idf: dict[str, float]
    vectors: dict[int, dict[str, float]]
    """board_node_id → {term: tfidf_declared + tfidf_content}."""

    vector_norm: dict[int, float]


def compute_keywords(boards: list[BoardTokens]) -> KeywordsResult:
    n = len(boards) if boards else 1
    declared_tf: dict[int, Counter[str]] = {}
    content_tf: dict[int, Counter[str]] = {}
    for b in boards:
        declared_tf[b.board_node_id] = Counter(b.declared_tokens)
        content_tf[b.board_node_id] = Counter(b.content_tokens)

    df: Counter[str] = Counter()
    for b in boards:
        terms_here = set(declared_tf[b.board_node_id]) | set(content_tf[b.board_node_id])
        for t in terms_here:
            df[t] += 1
    # Spec formula log(N/(1+DF)) goes non-positive when DF >= N (very common terms).
    # Clamp at 0 so common terms contribute 0 weight rather than negative — this
    # preserves the "common terms have no discrimination power" intent without
    # the perverse penalty of negative TF-IDF.
    idf = {t: max(0.0, math.log(n / (1 + d))) for t, d in df.items()}

    edges: list[tuple[int, str, float, float, str]] = []
    vectors: dict[int, dict[str, float]] = {}
    vector_norm: dict[int, float] = {}

    for b in boards:
        bid = b.board_node_id
        dtf = declared_tf[bid]
        ctf = content_tf[bid]
        terms_union = set(dtf) | set(ctf)
        vec: dict[str, float] = {}
        sq_sum = 0.0
        for term in terms_union:
            td = dtf.get(term, 0) * idf[term]
            tc = ctf.get(term, 0) * idf[term]
            total = td + tc
            if total <= 0:
                continue
            in_d = term in dtf
            in_c = term in ctf
            source = "both" if (in_d and in_c) else ("declared" if in_d else "content")
            edges.append((bid, term, td, tc, source))
            vec[term] = total
            sq_sum += total * total
        vectors[bid] = vec
        vector_norm[bid] = math.sqrt(sq_sum)

    return KeywordsResult(edges=edges, df=dict(df), idf=idf, vectors=vectors, vector_norm=vector_norm)
