"""In-memory cosine ranking over board/thread vectors loaded from index.db."""

from __future__ import annotations

import sqlite3
from typing import Iterable, TypeVar

import numpy as np

from bbs_database.embed.cache import decode_vec

K = TypeVar("K")


def load_board_vectors(cx: sqlite3.Connection) -> dict[int, np.ndarray]:
    out: dict[int, np.ndarray] = {}
    for bid, blob in cx.execute("SELECT board_node_id, vec FROM board_vector"):
        out[bid] = decode_vec(blob)
    return out


def load_thread_vectors(
    cx: sqlite3.Connection, board_ids: list[int] | None,
) -> list[tuple[int, int, str, np.ndarray]]:
    if board_ids is None:
        rows = cx.execute(
            "SELECT board_node_id, thread_id, forum_db_file, vec FROM thread_vector"
        )
    else:
        if not board_ids:
            return []
        placeholders = ",".join("?" * len(board_ids))
        rows = cx.execute(
            f"SELECT board_node_id, thread_id, forum_db_file, vec FROM thread_vector "
            f"WHERE board_node_id IN ({placeholders})",
            board_ids,
        )
    return [(b, t, f, decode_vec(v)) for b, t, f, v in rows]


def cosine_top_k(
    query: np.ndarray, items: Iterable[tuple[K, np.ndarray]], k: int,
) -> list[tuple[K, float]]:
    items_list = list(items)
    if not items_list:
        return []
    keys = [kk for kk, _ in items_list]
    mat = np.stack([v for _, v in items_list])
    qn = float(np.linalg.norm(query))
    mn = np.linalg.norm(mat, axis=1)
    dots = mat @ query
    denom = qn * mn
    safe = denom > 0
    cos = np.zeros(len(items_list), dtype=np.float64)
    if qn > 0:
        cos[safe] = dots[safe] / denom[safe]
    # Primary sort: cosine descending; tiebreaker: dot product descending (stable).
    order = np.lexsort((-dots, -cos))[:k]
    return [(keys[i], float(cos[i])) for i in order]
