"""find_forums hybrid impl: classical + vector fusion via adaptive δ."""

from __future__ import annotations

import sqlite3

import numpy as np

from bbs_database.builder.tokenize import Tokenizer
from bbs_database.embed.cache import decode_vec
from bbs_database.router.classical import classical_direct, classical_expansion
from bbs_database.router.errors import EmbedAPIError, IndexNotBuiltError
from bbs_database.router.parse import parse_query
from bbs_database.router.types import (
    ForumCandidate,
    MatchedTerm,
    VectorContributingThread,
)
from bbs_database.router.vector_rank import load_board_vectors, load_thread_vectors


def _min_max(scores: dict[int, float]) -> dict[int, float]:
    if not scores:
        return {}
    vals = list(scores.values())
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return {k: 0.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def _delta(signal: float, base: float, cold: float, threshold: float) -> float:
    return cold if signal < threshold else base


def find_forums_impl(
    cx: sqlite3.Connection,
    *,
    query: str,
    tokenizer: Tokenizer,
    embed_client,
    routing_cfg: dict,
    top_k: int,
) -> list[ForumCandidate]:
    # 1. parse
    qrep = parse_query(query, tokenizer)

    # 2. classical direct
    classic_direct_pairs = classical_direct(
        cx, qrep.terms, qrep.entities,
        alpha_declared=routing_cfg["alpha_declared"],
        alpha_content=routing_cfg["alpha_content"],
        alpha_entity=routing_cfg["alpha_entity"],
        alpha_activity=routing_cfg["alpha_activity"],
    )
    classic_direct_map = dict(classic_direct_pairs)

    # 3. board vectors
    board_vecs = load_board_vectors(cx)
    if not board_vecs:
        raise IndexNotBuiltError(
            "board_vector table is empty; run rebuild_index.py --full first"
        )

    # 4. embed query (may fail → fallback)
    query_vec = None
    vector_disabled = False
    try:
        emb_list = embed_client.embed([query])
        if emb_list:
            query_vec = np.asarray(emb_list[0], dtype=np.float32)
    except EmbedAPIError:
        vector_disabled = True

    # 5. vector direct cosine
    vec_score: dict[int, float] = {}
    if query_vec is not None and not vector_disabled:
        qn = float(np.linalg.norm(query_vec))
        if qn > 0:
            for bid, bv in board_vecs.items():
                bn = float(np.linalg.norm(bv))
                if bn == 0:
                    continue
                cos = float(bv @ query_vec) / (qn * bn)
                vec_score[bid] = max(0.0, cos)

    # 6. classical expansion (with vector-augmented seeds)
    k1 = routing_cfg["k1_seeds"]
    classic_seeds = [bid for bid, _ in classic_direct_pairs[:k1]]
    vec_seeds = sorted(vec_score.items(), key=lambda x: -x[1])[:k1]
    vec_seed_ids = [bid for bid, _ in vec_seeds]
    seeds = list(dict.fromkeys(classic_seeds + vec_seed_ids))
    exp_map = classical_expansion(
        cx, seeds=seeds, q_terms=qrep.terms,
        alpha_declared=routing_cfg["alpha_declared"],
        alpha_content=routing_cfg["alpha_content"],
        beta=routing_cfg["beta_expansion"],
        seed_top_terms=routing_cfg["seed_top_terms"],
        pmi_threshold=routing_cfg.get("pmi_threshold", 0.3),
        m_expansion=routing_cfg["m_expansion"],
    )

    # 7. classical total + normalize
    classic_total: dict[int, float] = {}
    all_bids = set(classic_direct_map) | set(exp_map) | set(vec_score) | set(board_vecs)
    for bid in all_bids:
        classic_total[bid] = classic_direct_map.get(bid, 0.0) + exp_map.get(bid, 0.0)
    classic_norm = _min_max(classic_total)
    vec_norm = vec_score

    # 8. fetch profiles (for δ + evidence)
    profiles: dict[int, dict] = {}
    for row in cx.execute(
        "SELECT board_node_id, site_key, name, path, forum_db_file, "
        "activity_score, title_count, content_signal_strength FROM forum_profile"
    ):
        profiles[row[0]] = dict(
            site_key=row[1], name=row[2], path=row[3], forum_db_file=row[4],
            activity_score=row[5], title_count=row[6], content_signal_strength=row[7],
        )

    # 9. fusion
    db = routing_cfg["delta_vector_base"]
    dc = routing_cfg["delta_vector_cold"]
    th = routing_cfg["delta_signal_threshold"]
    candidates: list[ForumCandidate] = []
    for bid in all_bids:
        prof = profiles.get(bid)
        if prof is None:
            continue
        sig = prof["content_signal_strength"]
        delta = _delta(sig, db, dc, th)
        if vector_disabled:
            final = classic_norm.get(bid, 0.0)
            delta_used = 0.0
        else:
            final = delta * vec_norm.get(bid, 0.0) + (1 - delta) * classic_norm.get(bid, 0.0)
            delta_used = delta

        candidates.append(ForumCandidate(
            board_node_id=bid,
            site_key=prof["site_key"], name=prof["name"], path=prof["path"],
            forum_db_file=prof["forum_db_file"],
            final_score=final,
            classic_direct_score=classic_direct_map.get(bid, 0.0),
            classic_expansion_score=exp_map.get(bid, 0.0),
            vector_cosine=vec_score.get(bid, 0.0),
            delta_used=delta_used,
            activity_score=prof["activity_score"],
            title_count=prof["title_count"],
            content_signal_strength=sig,
            matched_terms=[],  # populated below
            expanded_via=[],   # left empty in P2; can be filled later
            top_vector_contributing_threads=[],
            vector_disabled=vector_disabled,
        ))

    # 10. populate matched_terms (lightweight: which q_terms have any tfidf edge)
    if qrep.terms:
        placeholders = ",".join("?" * len(qrep.terms))
        rows = cx.execute(
            f"SELECT board_node_id, term, tfidf_declared, tfidf_content, source "
            f"FROM edge_forum_topic WHERE term IN ({placeholders})",
            qrep.terms,
        ).fetchall()
        by_bid: dict[int, list[MatchedTerm]] = {}
        for bid, term, td, tc, source in rows:
            by_bid.setdefault(bid, []).append(MatchedTerm(
                term=term, source=source, contribution=td + tc,
            ))
        for c in candidates:
            c.matched_terms = by_bid.get(c.board_node_id, [])

    # 11. populate top_vector_contributing_threads (top-3 thread per board for top candidates)
    candidates.sort(key=lambda c: -c.final_score)
    top_candidates = candidates[:top_k]
    if query_vec is not None and not vector_disabled:
        top_bids = [c.board_node_id for c in top_candidates]
        thread_rows = load_thread_vectors(cx, board_ids=top_bids)
        qn = float(np.linalg.norm(query_vec))
        per_board: dict[int, list[tuple[float, int, str]]] = {}
        if qn > 0:
            for bid, tid, fdb, tv in thread_rows:
                tn = float(np.linalg.norm(tv))
                if tn == 0:
                    continue
                cos = float(tv @ query_vec) / (qn * tn)
                per_board.setdefault(bid, []).append((cos, tid, fdb))
        for c in top_candidates:
            triples = sorted(per_board.get(c.board_node_id, []), reverse=True)[:3]
            c.top_vector_contributing_threads = [
                VectorContributingThread(
                    thread_id=tid, forum_db_file=fdb, title="", cosine=cos,
                )
                for cos, tid, fdb in triples
            ]

    return top_candidates
