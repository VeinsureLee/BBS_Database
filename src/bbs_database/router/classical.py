"""Classical (P1) direct + multi-hop expansion scoring."""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict


def classical_direct(
    cx: sqlite3.Connection,
    q_terms: list[str],
    q_entities: list[tuple[str, str]],
    *,
    alpha_declared: float,
    alpha_content: float,
    alpha_entity: float,
    alpha_activity: float,
) -> list[tuple[int, float]]:
    """Return [(board_node_id, score)] sorted desc, P1 spec §3.3."""
    profiles = {
        bid: (sig, act)
        for bid, sig, act in cx.execute(
            "SELECT board_node_id, content_signal_strength, activity_score FROM forum_profile"
        )
    }
    score: dict[int, float] = defaultdict(float)
    for bid, (_sig, act) in profiles.items():
        score[bid] = alpha_activity * act

    if q_terms:
        placeholders = ",".join("?" * len(q_terms))
        for bid, td, tc in cx.execute(
            f"SELECT board_node_id, SUM(tfidf_declared), SUM(tfidf_content) "
            f"FROM edge_forum_topic WHERE term IN ({placeholders}) GROUP BY board_node_id",
            q_terms,
        ):
            sig, _ = profiles.get(bid, (0.0, 0.0))
            score[bid] += alpha_declared * (td or 0.0) + alpha_content * (tc or 0.0) * sig

    for ent, ty in q_entities:
        for bid, cnt in cx.execute(
            "SELECT board_node_id, thread_count FROM edge_forum_entity "
            "WHERE entity=? AND entity_type=?",
            (ent, ty),
        ):
            score[bid] += alpha_entity * math.log(1 + cnt)

    return sorted(score.items(), key=lambda x: -x[1])


def classical_expansion(
    cx: sqlite3.Connection,
    seeds: list[int],
    q_terms: list[str],
    *,
    alpha_declared: float,
    alpha_content: float,
    beta: float,
    seed_top_terms: int,
    pmi_threshold: float,
    m_expansion: int,
) -> dict[int, float]:
    """Return {board_node_id: expansion_score} per spec §3.4."""
    if not seeds or not q_terms:
        return {}
    q_set = set(q_terms)

    # 1. collect top terms per seed (excluding q_terms)
    candidates: dict[str, float] = {}
    for bid in seeds:
        rows = cx.execute(
            f"""SELECT term, MAX(tfidf_declared, tfidf_content) AS w
                FROM edge_forum_topic
                WHERE board_node_id=?
                  AND term NOT IN ({",".join("?" * len(q_terms))})
                ORDER BY w DESC LIMIT ?""",
            (bid, *q_terms, seed_top_terms),
        ).fetchall()
        for term, w in rows:
            if term in q_set:
                continue
            if w > candidates.get(term, 0.0):
                candidates[term] = w

    # 2. filter by cooccur with any q_term
    expansion_terms: list[tuple[str, float]] = []
    for term, w in candidates.items():
        cooccur_w = 0.0
        for qt in q_terms:
            a, b = (term, qt) if term < qt else (qt, term)
            row = cx.execute(
                "SELECT weight FROM edge_topic_cooccur WHERE term_a=? AND term_b=?",
                (a, b),
            ).fetchone()
            if row and row[0] > cooccur_w:
                cooccur_w = row[0]
        if cooccur_w >= pmi_threshold:
            expansion_terms.append((term, w * cooccur_w))
    expansion_terms.sort(key=lambda x: -x[1])
    expansion_terms = expansion_terms[:m_expansion]

    if not expansion_terms:
        return {}

    # 3. score each board against expansion terms
    profiles = {
        bid: sig
        for bid, sig in cx.execute(
            "SELECT board_node_id, content_signal_strength FROM forum_profile"
        )
    }
    score: dict[int, float] = defaultdict(float)
    placeholders = ",".join("?" * len(expansion_terms))
    term_to_w = {t: w for t, w in expansion_terms}
    rows = cx.execute(
        f"""SELECT board_node_id, term, tfidf_declared, tfidf_content
            FROM edge_forum_topic
            WHERE term IN ({placeholders})""",
        [t for t, _ in expansion_terms],
    ).fetchall()
    for bid, term, td, tc in rows:
        sig = profiles.get(bid, 0.0)
        contrib = (alpha_declared * td + alpha_content * tc * sig) * term_to_w[term]
        score[bid] += beta * contrib
    return dict(score)
