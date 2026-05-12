"""PMI-based topic co-occurrence over boards.

Per spec §2.5 step 3, but enumerated per-board (avoids O(T^2) cross-product).
"""

from __future__ import annotations

import math
from collections import Counter
from itertools import combinations


def compute_cooccur(
    vectors: dict[int, dict[str, float]],
    *,
    df: dict[str, int],
    total_boards: int,
    pmi_threshold: float,
    top_terms_per_board: int,
    min_df: int,
) -> list[tuple[str, str, float]]:
    """Return list of (term_a, term_b, pmi) with term_a < term_b."""
    co: Counter[tuple[str, str]] = Counter()
    for _board_id, vec in vectors.items():
        candidates = [t for t in vec if df.get(t, 0) >= min_df]
        candidates.sort(key=lambda t: vec[t], reverse=True)
        top = candidates[:top_terms_per_board]
        top.sort()
        for a, b in combinations(top, 2):
            co[(a, b)] += 1

    n = total_boards
    out: list[tuple[str, str, float]] = []
    for (a, b), ab in co.items():
        p_ab = ab / n
        p_a = df[a] / n
        p_b = df[b] / n
        if p_a == 0 or p_b == 0:
            continue
        pmi = math.log(p_ab / (p_a * p_b))
        if pmi > pmi_threshold:
            out.append((a, b, pmi))
    out.sort()
    return out
