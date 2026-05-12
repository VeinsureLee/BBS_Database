"""Populate FTS5 thread_title_fts + fts_map."""

from __future__ import annotations

import sqlite3
from typing import Iterable

import jieba


def populate_fts(
    cx: sqlite3.Connection,
    threads: Iterable[tuple[int, int, str, str]],
) -> None:
    """Insert one row per thread into thread_title_fts and fts_map.

    threads yields (board_node_id, thread_id, title, forum_db_file).
    rowid in both tables matches.
    """
    cx.execute("DELETE FROM thread_title_fts")
    cx.execute("DELETE FROM fts_map")
    for board, tid, title, db_file in threads:
        segs = [s for s in jieba.cut(title) if not s.isspace()]
        segmented = " ".join(segs) if segs else title
        cur = cx.execute(
            "INSERT INTO thread_title_fts(title) VALUES (?)",
            (segmented,),
        )
        rowid = cur.lastrowid
        cx.execute(
            "INSERT INTO fts_map(rowid, board_node_id, thread_id, forum_db_file) VALUES (?,?,?,?)",
            (rowid, board, tid, db_file),
        )
