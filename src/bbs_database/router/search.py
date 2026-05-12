"""search_threads impl: vector cosine + board.score + recency."""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from bbs_database.reader import open_ro
from bbs_database.router.errors import EmbedAPIError
from bbs_database.router.types import ForumCandidate, ThreadHit
from bbs_database.router.vector_rank import load_thread_vectors


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _recency(posted_at: str | None, tau_days: float, now: datetime) -> float:
    pd = _parse_iso(posted_at)
    if pd is None:
        return 0.0
    if pd.tzinfo is None:
        pd = pd.replace(tzinfo=timezone.utc)
    delta_days = (now - pd).total_seconds() / 86400.0
    if delta_days < 0:
        delta_days = 0.0
    return math.exp(-delta_days / tau_days)


def search_threads_impl(
    cx: sqlite3.Connection,
    *,
    query: str,
    board_node_ids: list[int],
    board_score: dict[int, float],
    embed_client,
    data_root: Path,
    search_cfg: dict,
) -> list[ThreadHit]:
    # 1. embed query
    try:
        emb = embed_client.embed([query])
    except EmbedAPIError:
        return []
    if not emb:
        return []
    query_vec = np.asarray(emb[0], dtype=np.float32)
    qn = float(np.linalg.norm(query_vec))
    if qn == 0:
        return []

    # 2. load thread_vector rows in scope
    rows = load_thread_vectors(cx, board_ids=board_node_ids)
    if not rows:
        return []

    # 3. cosine all
    scored: list[tuple[float, int, int, str]] = []  # (cosine, bid, tid, fdb)
    for bid, tid, fdb, tv in rows:
        tn = float(np.linalg.norm(tv))
        if tn == 0:
            continue
        cos = float(tv @ query_vec) / (qn * tn)
        scored.append((cos, bid, tid, fdb))

    # 4. group by forum_db_file → pull thread metadata
    by_fdb: dict[str, list[int]] = defaultdict(list)
    for _, _, tid, fdb in scored:
        by_fdb[fdb].append(tid)
    meta: dict[tuple[str, int], dict] = {}
    for fdb, tids in by_fdb.items():
        fdb_path = Path(data_root) / fdb
        try:
            fcx = open_ro(fdb_path)
        except sqlite3.OperationalError:
            continue
        try:
            placeholders = ",".join("?" * len(tids))
            for row in fcx.execute(
                f"SELECT id, board_node_id, title, author, posted_at, last_reply_at, "
                f"reply_count, view_count, url, is_pinned "
                f"FROM threads WHERE id IN ({placeholders})",
                tids,
            ):
                meta[(fdb, row[0])] = dict(
                    board_node_id=row[1], title=row[2], author=row[3],
                    posted_at=row[4], last_reply_at=row[5],
                    reply_count=row[6], view_count=row[7], url=row[8],
                    is_pinned=bool(row[9]),
                )
        finally:
            fcx.close()

    # 5. load board profiles for evidence
    profiles = {}
    for row in cx.execute(
        "SELECT board_node_id, site_key, name, path, forum_db_file, "
        "activity_score, title_count, content_signal_strength FROM forum_profile"
    ):
        profiles[row[0]] = dict(
            site_key=row[1], name=row[2], path=row[3], forum_db_file=row[4],
            activity_score=row[5], title_count=row[6], content_signal_strength=row[7],
        )

    # 6. compose ThreadHit
    g_vec = search_cfg["gamma_vector"]
    g_board = search_cfg["gamma_board"]
    g_recency = search_cfg["gamma_recency"]
    tau = search_cfg["recency_tau_days"]
    per_board_limit = search_cfg["per_board_limit"]
    total_limit = search_cfg["total_limit"]
    now = datetime.now(timezone.utc)

    hits: list[ThreadHit] = []
    for cos, bid, tid, fdb in scored:
        m = meta.get((fdb, tid))
        if m is None:
            continue
        bs = board_score.get(bid, 0.0)
        rec = _recency(m["posted_at"], tau, now)
        combined = g_vec * cos + g_board * bs + g_recency * rec
        prof = profiles.get(bid, {})
        routing_evidence = ForumCandidate(
            board_node_id=bid,
            site_key=prof.get("site_key", ""),
            name=prof.get("name", ""),
            path=prof.get("path", ""),
            forum_db_file=fdb,
            final_score=bs,
            classic_direct_score=0.0,
            classic_expansion_score=0.0,
            vector_cosine=0.0,
            delta_used=0.0,
            activity_score=prof.get("activity_score", 0.0),
            title_count=prof.get("title_count", 0),
            content_signal_strength=prof.get("content_signal_strength", 0.0),
            matched_terms=[],
            expanded_via=[],
            top_vector_contributing_threads=[],
        )
        hits.append(ThreadHit(
            thread_id=tid,
            board_node_id=bid,
            board_name=prof.get("name", ""),
            board_path=prof.get("path", ""),
            forum_db_file=fdb,
            title=m["title"],
            author=m["author"],
            posted_at=m["posted_at"],
            last_reply_at=m["last_reply_at"],
            reply_count=m["reply_count"],
            view_count=m["view_count"],
            url=m["url"],
            is_pinned=m["is_pinned"],
            combined_score=combined,
            vector_cosine=cos,
            board_score=bs,
            recency_factor=rec,
            breakdown={"vector": g_vec * cos, "board": g_board * bs, "recency": g_recency * rec},
            routing_evidence=routing_evidence,
        ))

    # 7. group by board, per_board_limit, then total_limit
    hits.sort(key=lambda h: -h.combined_score)
    per_board_counts: dict[int, int] = defaultdict(int)
    final_hits: list[ThreadHit] = []
    for h in hits:
        if per_board_counts[h.board_node_id] >= per_board_limit:
            continue
        final_hits.append(h)
        per_board_counts[h.board_node_id] += 1
        if len(final_hits) >= total_limit:
            break
    return final_hits
