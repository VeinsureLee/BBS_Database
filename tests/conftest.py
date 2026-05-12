"""Synthetic BBS_Crawler fixtures for unit tests.

Builds a tiny structure.db + 1–2 forum.db files matching the data-contract v1.0.0.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


_STRUCTURE_DDL = """
CREATE TABLE sites (
  site_key TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE nodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  parent_id INTEGER,
  site_key TEXT NOT NULL,
  node_key TEXT NOT NULL,
  name TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('forum','sub_forum','board')),
  level INTEGER NOT NULL,
  db_file TEXT,
  moderators TEXT,
  stats TEXT,
  raw TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  last_crawled_at TEXT,
  FOREIGN KEY (parent_id) REFERENCES nodes(id) ON DELETE CASCADE,
  FOREIGN KEY (site_key) REFERENCES sites(site_key) ON DELETE CASCADE
);
"""

_FORUM_DDL = """
CREATE TABLE threads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  board_node_id INTEGER NOT NULL,
  url TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  author TEXT,
  posted_at TEXT,
  last_reply_at TEXT,
  reply_count INTEGER,
  view_count INTEGER,
  raw TEXT,
  is_pinned INTEGER NOT NULL DEFAULT 0,
  first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
  last_fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  floor INTEGER NOT NULL,
  author TEXT NOT NULL,
  posted_at TEXT,
  content_html TEXT NOT NULL,
  content_text TEXT NOT NULL,
  attachments TEXT,
  raw TEXT,
  UNIQUE(thread_id, floor)
);
"""


def _exec_script(cx: sqlite3.Connection, script: str) -> None:
    cx.executescript(script)


@pytest.fixture
def crawler_dataset(tmp_path: Path):
    """Build a tiny crawler dataset and return a dict describing it.

    Layout:
      <tmp>/crawler/structure.db
      <tmp>/crawler/forums/academic.db   (boards: 学院A, 学院B)
      <tmp>/crawler/forums/anonymous.db  (boards: 悄悄话)

    Boards and titles are seeded so:
      - "学院A" mentions 张三 老师 讲课 课程
      - "学院B" mentions 李四 老师 考试
      - "悄悄话" mentions 张三 老师 讲课 (anonymous topical drift)
    """
    crawler = tmp_path / "crawler"
    forums = crawler / "forums"
    forums.mkdir(parents=True)
    structure = crawler / "structure.db"
    cx = sqlite3.connect(structure)
    _exec_script(cx, _STRUCTURE_DDL)
    cx.execute(
        "INSERT INTO sites(site_key, display_name, base_url) VALUES (?,?,?)",
        ("school-bbs", "Test BBS", "https://example.test"),
    )

    # forum nodes
    cx.execute(
        "INSERT INTO nodes(id, parent_id, site_key, node_key, name, type, level, db_file, stats) "
        "VALUES (1, NULL, 'school-bbs', 'academic', '学术', 'forum', 0, 'forums/academic.db', NULL)"
    )
    cx.execute(
        "INSERT INTO nodes(id, parent_id, site_key, node_key, name, type, level, db_file, stats) "
        "VALUES (2, NULL, 'school-bbs', 'anonymous', '匿名', 'forum', 0, 'forums/anonymous.db', NULL)"
    )
    # board nodes under academic
    cx.execute(
        "INSERT INTO nodes(id, parent_id, site_key, node_key, name, type, level, stats) "
        "VALUES (10, 1, 'school-bbs', 'academic-a', '学院A', 'board', 1, "
        "'{\"online\":100,\"today\":50,\"threads\":1000,\"posts\":5000}')"
    )
    cx.execute(
        "INSERT INTO nodes(id, parent_id, site_key, node_key, name, type, level, stats) "
        "VALUES (11, 1, 'school-bbs', 'academic-b', '学院B', 'board', 1, "
        "'{\"online\":80,\"today\":30,\"threads\":500,\"posts\":2000}')"
    )
    # board under anonymous
    cx.execute(
        "INSERT INTO nodes(id, parent_id, site_key, node_key, name, type, level, stats) "
        "VALUES (20, 2, 'school-bbs', 'whisper', '悄悄话', 'board', 1, "
        "'{\"online\":200,\"today\":150,\"threads\":3000,\"posts\":12000}')"
    )
    cx.commit()
    cx.close()

    # academic.db
    academic_db = forums / "academic.db"
    fa = sqlite3.connect(academic_db)
    _exec_script(fa, _FORUM_DDL)
    threads_a = [
        (10, "https://x/1", "张三老师讲课如何", 0),
        (10, "https://x/2", "求张三老师的课程资料", 0),
        (10, "https://x/3", "学院A置顶通知", 1),
        (10, "https://x/4", "张三老师作业讨论", 0),
        (10, "https://x/5", "考试范围请教", 0),
        (11, "https://x/6", "李四老师讲课怎么样", 0),
        (11, "https://x/7", "李四老师考试复习", 0),
        (11, "https://x/8", "学院B置顶公告", 1),
        (11, "https://x/9", "考试技巧分享", 0),
    ]
    fa.executemany(
        "INSERT INTO threads(board_node_id, url, title, is_pinned) VALUES (?,?,?,?)",
        threads_a,
    )
    fa.commit()
    fa.close()

    # anonymous.db
    anon_db = forums / "anonymous.db"
    fb = sqlite3.connect(anon_db)
    _exec_script(fb, _FORUM_DDL)
    threads_b = [
        (20, "https://y/1", "悄悄话置顶 - 注意保密", 1),
        (20, "https://y/2", "张三老师真的很好", 0),
        (20, "https://y/3", "张三老师讲课吐槽", 0),
        (20, "https://y/4", "李四老师课程考试", 0),
        (20, "https://y/5", "今天食堂吃啥", 0),
        (20, "https://y/6", "感情问题求助", 0),
    ]
    fb.executemany(
        "INSERT INTO threads(board_node_id, url, title, is_pinned) VALUES (?,?,?,?)",
        threads_b,
    )
    fb.commit()
    fb.close()

    return {
        "root": crawler,
        "structure_db": structure,
        "site_key": "school-bbs",
        "boards": {
            10: {"name": "学院A", "forum_db_file": "forums/academic.db", "path": "学术 > 学院A"},
            11: {"name": "学院B", "forum_db_file": "forums/academic.db", "path": "学术 > 学院B"},
            20: {"name": "悄悄话", "forum_db_file": "forums/anonymous.db", "path": "匿名 > 悄悄话"},
        },
    }


import hashlib

import numpy as np


class FakeEmbedClient:
    """Deterministic fake EmbedClient for unit tests.

    By default produces hash-based vectors (same text → same vector).
    Tests can call .set(text, vec) to override specific texts with controlled vectors.
    """

    def __init__(self, dimensions: int = 1024):
        self.dimensions = dimensions
        self._overrides: dict[str, list[float]] = {}
        self.call_log: list[list[str]] = []

    def set(self, text: str, vec: list[float]) -> None:
        assert len(vec) == self.dimensions
        self._overrides[text] = vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.call_log.append(list(texts))
        out: list[list[float]] = []
        for t in texts:
            if t in self._overrides:
                out.append(list(self._overrides[t]))
            else:
                out.append(self._hash_vec(t))
        return out

    def _hash_vec(self, text: str) -> list[float]:
        # Use the digest as a seed for a deterministic RNG, then draw `dimensions`
        # float32 samples. (The prior approach interpreted raw bytes as float32
        # bits, which both produced a 4× larger vector than intended AND risked
        # NaN/Inf payloads from random bit patterns.)
        h = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(h[:8], "big")
        rng = np.random.default_rng(seed)
        arr = rng.standard_normal(self.dimensions).astype(np.float32)
        return arr.tolist()


@pytest.fixture
def fake_embed_api():
    return FakeEmbedClient(dimensions=1024)
