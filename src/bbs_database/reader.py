"""Read-only access to BBS_Crawler data per data-contract v1.0.0."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


def open_ro(path: Path | str) -> sqlite3.Connection:
    """Open a SQLite file in strict read-only mode via URI."""
    p = Path(path).as_posix()
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


@dataclass
class BoardInfo:
    board_node_id: int
    site_key: str
    name: str
    path: str               # e.g. "学术 > 学院A"
    forum_db_file: str      # relative to data_root, e.g. "forums/academic.db"
    stats_json: str | None


@dataclass
class ThreadRow:
    thread_id: int
    board_node_id: int
    title: str
    url: str
    posted_at: str | None
    is_pinned: bool


def _ancestor_chain(cx: sqlite3.Connection, node_id: int) -> list[tuple[int, str, str, str | None]]:
    """Walk from a board node up to its forum ancestor; return [(id,name,type,db_file)] root-first."""
    rows = cx.execute(
        """
        WITH RECURSIVE up(node_id, depth) AS (
          SELECT ?, 0
          UNION ALL
          SELECT n.parent_id, u.depth + 1
            FROM up u JOIN nodes n ON n.id = u.node_id
           WHERE n.parent_id IS NOT NULL
             AND n.parent_id <> u.node_id
             AND u.depth < 20
        )
        SELECT n.id, n.name, n.type, n.db_file
          FROM up u JOIN nodes n ON n.id = u.node_id
         ORDER BY u.depth DESC
        """,
        (node_id,),
    ).fetchall()
    return rows


def iter_boards(data_root: Path | str, site_key: str) -> Iterator[BoardInfo]:
    structure = Path(data_root) / "structure.db"
    cx = open_ro(structure)
    try:
        boards = cx.execute(
            "SELECT id, name, stats FROM nodes WHERE site_key=? AND type='board' ORDER BY id",
            (site_key,),
        ).fetchall()
        for board_id, name, stats in boards:
            chain = _ancestor_chain(cx, board_id)
            if not chain:
                continue
            db_file = None
            for _id, _name, _type, _db in chain:
                if _type == "forum":
                    db_file = _db
                    break
            if db_file is None:
                continue
            path = " > ".join(n for (_id, n, _type, _db) in chain)
            yield BoardInfo(
                board_node_id=board_id,
                site_key=site_key,
                name=name,
                path=path,
                forum_db_file=db_file,
                stats_json=stats,
            )
    finally:
        cx.close()


def iter_threads(
    data_root: Path | str,
    forum_db_file: str,
    board_node_id: int | None = None,
) -> Iterator[ThreadRow]:
    forum_path = Path(data_root) / forum_db_file
    cx = open_ro(forum_path)
    try:
        if board_node_id is None:
            rows = cx.execute(
                "SELECT id, board_node_id, title, url, posted_at, is_pinned FROM threads"
            )
        else:
            rows = cx.execute(
                "SELECT id, board_node_id, title, url, posted_at, is_pinned "
                "FROM threads WHERE board_node_id=?",
                (board_node_id,),
            )
        for tid, bid, title, url, posted_at, is_pinned in rows:
            yield ThreadRow(
                thread_id=tid,
                board_node_id=bid,
                title=title,
                url=url,
                posted_at=posted_at,
                is_pinned=bool(is_pinned),
            )
    finally:
        cx.close()
