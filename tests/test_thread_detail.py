import sqlite3
from pathlib import Path

import pytest

from bbs_database.router.errors import ForumDbNotFoundError, ThreadNotFoundError
from bbs_database.router.thread_detail import get_thread_impl


def _build(tmp_path):
    forums = tmp_path / "data" / "crawler.db" / "forums"
    forums.mkdir(parents=True)
    fdb = forums / "a.db"
    cx = sqlite3.connect(fdb)
    cx.executescript("""
        CREATE TABLE threads (id INTEGER PRIMARY KEY, board_node_id INTEGER, url TEXT, title TEXT,
            author TEXT, posted_at TEXT, last_reply_at TEXT, reply_count INTEGER,
            view_count INTEGER, raw TEXT, is_pinned INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_fetched_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE posts (id INTEGER PRIMARY KEY, thread_id INTEGER, floor INTEGER,
            author TEXT, posted_at TEXT, content_html TEXT NOT NULL,
            content_text TEXT NOT NULL, attachments TEXT, raw TEXT,
            UNIQUE(thread_id, floor));
    """)
    cx.execute(
        "INSERT INTO threads(id, board_node_id, url, title, author, posted_at) "
        "VALUES (1, 10, 'u', 't', 'a', '2026-01-01')"
    )
    cx.executemany(
        "INSERT INTO posts(thread_id, floor, author, posted_at, content_html, content_text) "
        "VALUES (?,?,?,?,?,?)",
        [(1, 0, "a", "2026-01-01", "<p>hi</p>", "hi"),
         (1, 1, "b", "2026-01-02", "<p>yo</p>", "yo")],
    )
    cx.commit()
    cx.close()
    return tmp_path / "data" / "crawler.db"


def test_get_thread_returns_thread_and_posts(tmp_path):
    data_root = _build(tmp_path)
    td = get_thread_impl(data_root, "forums/a.db", 1)
    assert td.thread_id == 1
    assert td.title == "t"
    assert len(td.posts) == 2
    assert td.posts[0].floor == 0
    assert td.posts[1].content_text == "yo"


def test_get_thread_missing_thread_raises(tmp_path):
    data_root = _build(tmp_path)
    with pytest.raises(ThreadNotFoundError):
        get_thread_impl(data_root, "forums/a.db", 999)


def test_get_thread_missing_forum_db_raises(tmp_path):
    data_root = tmp_path / "no" / "such" / "place"
    with pytest.raises(ForumDbNotFoundError):
        get_thread_impl(data_root, "forums/a.db", 1)
