"""get_thread: read a thread + all its posts from crawler forum.db."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from bbs_database.reader import open_ro
from bbs_database.router.errors import ForumDbNotFoundError, ThreadNotFoundError
from bbs_database.router.types import Post, ThreadDetail


def get_thread_impl(
    data_root: Path | str, forum_db_file: str, thread_id: int,
) -> ThreadDetail:
    fdb_path = Path(data_root) / forum_db_file
    if not fdb_path.exists():
        raise ForumDbNotFoundError(f"forum db not found: {fdb_path}")
    cx = open_ro(fdb_path)
    try:
        row = cx.execute(
            "SELECT id, board_node_id, title, author, posted_at, url, raw FROM threads "
            "WHERE id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            raise ThreadNotFoundError(
                f"thread_id={thread_id} not found in {forum_db_file}"
            )
        thread_id_db, board_node_id, title, author, posted_at, url, raw = row
        posts_rows = cx.execute(
            "SELECT floor, author, posted_at, content_text, attachments "
            "FROM posts WHERE thread_id = ? ORDER BY floor",
            (thread_id,),
        ).fetchall()
        posts = []
        for floor, p_author, p_posted_at, content_text, attachments in posts_rows:
            attach_parsed = None
            if attachments:
                try:
                    attach_parsed = json.loads(attachments)
                except json.JSONDecodeError:
                    attach_parsed = None
            posts.append(Post(
                floor=floor, author=p_author, posted_at=p_posted_at,
                content_text=content_text, attachments=attach_parsed,
            ))
        raw_parsed = None
        if raw:
            try:
                raw_parsed = json.loads(raw)
            except json.JSONDecodeError:
                raw_parsed = None
        return ThreadDetail(
            thread_id=thread_id_db, board_node_id=board_node_id,
            title=title, author=author, url=url, posted_at=posted_at,
            posts=posts, raw=raw_parsed,
        )
    finally:
        cx.close()
