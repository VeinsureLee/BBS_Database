"""ingest_threads: embed and write thread vectors for newly crawled threads."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from bbs_database.embed.cache import encode_vec
from bbs_database.reader import open_ro
from bbs_database.router.errors import (
    EmbedAPIError,
    ForumDbNotFoundError,
)
from bbs_database.router.types import IngestResult


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _estimate_cost_cny(num_threads: int, avg_tokens_per_title: int = 30,
                      price_per_million_tokens: float = 0.7) -> float:
    tokens = num_threads * avg_tokens_per_title
    return tokens / 1_000_000.0 * price_per_million_tokens


def ingest_threads_impl(
    *,
    forum_db_file: str,
    thread_ids: list[int] | None,
    index_db_path: Path,
    data_root: Path,
    embed_client,
    embed_model: str,
    batch_size: int = 25,
) -> IngestResult:
    started = time.monotonic()
    fdb_path = Path(data_root) / forum_db_file
    if not fdb_path.exists():
        raise ForumDbNotFoundError(f"forum db not found: {fdb_path}")

    icx = sqlite3.connect(index_db_path)
    fcx = open_ro(fdb_path)
    try:
        # 1. resolve which thread_ids to consider
        if thread_ids is None:
            rows = fcx.execute(
                "SELECT id, board_node_id, title FROM threads"
            ).fetchall()
        else:
            if not thread_ids:
                return IngestResult(
                    forum_db_file=forum_db_file, requested=0,
                    already_indexed=0, newly_embedded=0, failed=0,
                    failed_thread_ids=[],
                    elapsed_seconds=time.monotonic() - started,
                    estimated_cost_cny=0.0, embed_model=embed_model,
                )
            placeholders = ",".join("?" * len(thread_ids))
            rows = fcx.execute(
                f"SELECT id, board_node_id, title FROM threads WHERE id IN ({placeholders})",
                thread_ids,
            ).fetchall()
        requested = len(rows)

        # 2. diff against existing thread_vector for this forum_db_file
        existing_ids = {
            r[0] for r in icx.execute(
                "SELECT thread_id FROM thread_vector "
                "WHERE forum_db_file = ? AND embed_model = ?",
                (forum_db_file, embed_model),
            )
        }
        to_embed = [r for r in rows if r[0] not in existing_ids]
        already_indexed = requested - len(to_embed)

        # 3. embed in batches; on failure record the batch as failed and continue
        newly_embedded = 0
        failed_ids: list[int] = []
        for i in range(0, len(to_embed), batch_size):
            batch = to_embed[i : i + batch_size]
            titles = [r[2] for r in batch]
            try:
                vecs = embed_client.embed(titles)
            except EmbedAPIError:
                failed_ids.extend(r[0] for r in batch)
                continue
            now = _now_iso()
            rows_to_insert = [
                (board_node_id, tid, forum_db_file, encode_vec(vec), embed_model, now)
                for (tid, board_node_id, _), vec in zip(batch, vecs)
            ]
            with icx:
                icx.executemany(
                    "INSERT INTO thread_vector(board_node_id, thread_id, forum_db_file, "
                    "vec, embed_model, built_at) VALUES (?,?,?,?,?,?)",
                    rows_to_insert,
                )
            newly_embedded += len(rows_to_insert)

        return IngestResult(
            forum_db_file=forum_db_file,
            requested=requested,
            already_indexed=already_indexed,
            newly_embedded=newly_embedded,
            failed=len(failed_ids),
            failed_thread_ids=failed_ids,
            elapsed_seconds=time.monotonic() - started,
            estimated_cost_cny=_estimate_cost_cny(newly_embedded),
            embed_model=embed_model,
        )
    finally:
        fcx.close()
        icx.close()
