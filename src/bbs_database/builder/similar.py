"""Cosine top-N neighbors per board using the keywords result's vectors."""

from __future__ import annotations

from collections import defaultdict


def compute_similar(
    vectors: dict[int, dict[str, float]],
    norms: dict[int, float],
    *,
    top_n: int,
) -> list[tuple[int, int, float]]:
    """Return list of (board_a, board_b, cosine). Both directions are emitted."""
    inv: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for bid, vec in vectors.items():
        for term, w in vec.items():
            inv[term].append((bid, w))

    edges: list[tuple[int, int, float]] = []
    for bid, vec in vectors.items():
        if norms.get(bid, 0.0) == 0.0:
            continue
        dot: dict[int, float] = defaultdict(float)
        for term, w in vec.items():
            for other, other_w in inv[term]:
                if other == bid:
                    continue
                dot[other] += w * other_w
        scored: list[tuple[int, float]] = []
        for other, prod in dot.items():
            denom = norms[bid] * norms.get(other, 0.0)
            if denom == 0:
                continue
            scored.append((other, prod / denom))
        scored.sort(key=lambda x: x[1], reverse=True)
        for other, cos in scored[:top_n]:
            if cos <= 0:
                continue
            edges.append((bid, other, cos))
    return edges
