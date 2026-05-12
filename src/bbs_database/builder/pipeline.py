"""End-to-end builder: read crawler → compute → write index.db.

Drops and recreates index.db each call.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from bbs_database.config import Config
from bbs_database.builder import (
    cooccur as cooccur_mod,
    entities as entities_mod,
    fts as fts_mod,
    keywords as keywords_mod,
    similar as similar_mod,
    tokenize as tokenize_mod,
)
from bbs_database.builder.schema import (
    ALL_DDL,
    meta_inserts,
)
from bbs_database.reader import iter_boards, iter_threads


def _activity_score(stats_json: str | None) -> float:
    if not stats_json:
        return 0.0
    try:
        s = json.loads(stats_json)
    except json.JSONDecodeError:
        return 0.0
    online = float(s.get("online") or 0)
    today = float(s.get("today") or 0)
    threads = float(s.get("threads") or 0)
    return math.log1p(online) + math.log1p(today) + 0.1 * math.log1p(threads)


def _init_index_db(path: Path) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(path)
    cx.execute("PRAGMA foreign_keys = ON")
    for stmt in ALL_DDL:
        cx.execute(stmt)
    cx.commit()
    return cx


def build_index(cfg: Config) -> None:
    data_root = cfg.data_root_path
    index_db = cfg.index_db_path
    tokenizer = tokenize_mod.Tokenizer(
        stopwords=tokenize_mod.load_stopwords(cfg.build.stopwords_path),
        min_length=cfg.build.min_token_length,
    )

    # --- Phase 1: collect per-board data from crawler ---
    boards = list(iter_boards(data_root, site_key=cfg.site_key))
    board_records: list[dict] = []
    board_tokens: list[keywords_mod.BoardTokens] = []
    entity_counts: dict[tuple[int, str, str], int] = defaultdict(int)
    fts_rows: list[tuple[int, int, str, str]] = []
    raw_activity: list[float] = []
    by_board_threads: dict[int, list] = defaultdict(list)

    for b in boards:
        for t in iter_threads(data_root, b.forum_db_file, board_node_id=b.board_node_id):
            by_board_threads[b.board_node_id].append(t)

    for b in boards:
        threads = by_board_threads[b.board_node_id]
        pinned_titles = [t.title for t in threads if t.is_pinned]
        all_titles = [t.title for t in threads]
        declared_text = " ".join([b.name, b.path, *pinned_titles])
        declared_tokens = tokenizer.cut(declared_text)
        content_tokens: list[str] = []
        for title in all_titles:
            content_tokens.extend(tokenizer.cut_search(title))
        board_tokens.append(
            keywords_mod.BoardTokens(
                board_node_id=b.board_node_id,
                declared_tokens=declared_tokens,
                content_tokens=content_tokens,
            )
        )

        # Count threads (not occurrences) where each entity appears
        for title in all_titles:
            local_seen: set[tuple[str, str]] = set()
            for ent, ty in entities_mod.extract_entities(title):
                if (ent, ty) in local_seen:
                    continue
                local_seen.add((ent, ty))
                entity_counts[(b.board_node_id, ent, ty)] += 1

        for t in threads:
            fts_rows.append((b.board_node_id, t.thread_id, t.title, b.forum_db_file))

        raw = _activity_score(b.stats_json)
        raw_activity.append(raw)
        board_records.append(
            dict(
                board_node_id=b.board_node_id,
                site_key=b.site_key,
                forum_db_file=b.forum_db_file,
                name=b.name,
                path=b.path,
                pinned_titles=json.dumps(pinned_titles, ensure_ascii=False),
                title_count=len(all_titles),
                raw_activity=raw,
            )
        )

    max_raw = max(raw_activity) if raw_activity else 1.0
    if max_raw <= 0:
        max_raw = 1.0
    full_threshold = cfg.build.content_signal_strength_full

    # --- Phase 2: compute keywords / cooccur / similar ---
    kw = keywords_mod.compute_keywords(board_tokens)
    coo = cooccur_mod.compute_cooccur(
        kw.vectors,
        df=kw.df,
        total_boards=max(len(board_tokens), 1),
        pmi_threshold=cfg.build.pmi_threshold,
        top_terms_per_board=cfg.build.seed_top_terms_for_cooccur,
        min_df=cfg.build.cooccur_min_df,
    )
    sim = similar_mod.compute_similar(
        kw.vectors, kw.vector_norm, top_n=cfg.build.similar_top_n,
    )

    # --- Phase 3: write index.db ---
    cx = _init_index_db(index_db)
    try:
        now = datetime.now(timezone.utc).isoformat()
        with cx:
            for sql, params in meta_inserts(now):
                cx.execute(sql, params)

            for rec in board_records:
                bid = rec["board_node_id"]
                activity = rec["raw_activity"] / max_raw
                signal = min(1.0, rec["title_count"] / full_threshold) if full_threshold else 1.0
                cx.execute(
                    """INSERT INTO forum_profile(
                          board_node_id, site_key, forum_db_file, name, path,
                          pinned_titles, title_count, activity_score,
                          content_signal_strength, vector_norm, built_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        bid, rec["site_key"], rec["forum_db_file"], rec["name"], rec["path"],
                        rec["pinned_titles"], rec["title_count"], activity,
                        signal, kw.vector_norm.get(bid, 0.0), now,
                    ),
                )

            cx.executemany(
                "INSERT INTO edge_forum_topic(board_node_id, term, tfidf_declared, tfidf_content, source) "
                "VALUES (?,?,?,?,?)",
                kw.edges,
            )

            entity_rows = [
                (bid, ent, ty, cnt) for ((bid, ent, ty), cnt) in entity_counts.items() if cnt > 0
            ]
            cx.executemany(
                "INSERT INTO edge_forum_entity(board_node_id, entity, entity_type, thread_count) "
                "VALUES (?,?,?,?)",
                entity_rows,
            )

            cx.executemany(
                "INSERT INTO edge_topic_cooccur(term_a, term_b, weight) VALUES (?,?,?)",
                coo,
            )

            cx.executemany(
                "INSERT INTO edge_forum_similar(board_a, board_b, cosine) VALUES (?,?,?)",
                sim,
            )

            fts_mod.populate_fts(cx, fts_rows)
    finally:
        cx.close()
