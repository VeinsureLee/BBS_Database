import sqlite3
from pathlib import Path

from bbs_database.builder.schema import ALL_DDL
from bbs_database.ingest import ingest_threads_impl
from bbs_database.router.types import IngestResult


def _build_forum_db(tmp_path, threads):
    forums = tmp_path / "data" / "crawler.db" / "forums"
    forums.mkdir(parents=True)
    fdb = forums / "a.db"
    cx = sqlite3.connect(fdb)
    cx.executescript("""
        CREATE TABLE threads (id INTEGER PRIMARY KEY, board_node_id INTEGER, url TEXT,
            title TEXT, author TEXT, posted_at TEXT, last_reply_at TEXT,
            reply_count INTEGER, view_count INTEGER, raw TEXT,
            is_pinned INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_fetched_at TEXT NOT NULL DEFAULT (datetime('now')));
    """)
    cx.executemany(
        "INSERT INTO threads(id, board_node_id, url, title) VALUES (?,?,?,?)",
        threads,
    )
    cx.commit()
    cx.close()
    return tmp_path / "data" / "crawler.db"


def _empty_index_db(tmp_path):
    p = tmp_path / "index.db"
    cx = sqlite3.connect(p)
    for stmt in ALL_DDL:
        cx.execute(stmt)
    cx.commit()
    cx.close()
    return p


def test_ingest_threads_embeds_new_titles(tmp_path, fake_embed_api):
    threads = [
        (1, 10, "u1", "标题1"),
        (2, 10, "u2", "标题2"),
        (3, 10, "u3", "标题3"),
    ]
    data_root = _build_forum_db(tmp_path, threads)
    index_db = _empty_index_db(tmp_path)
    res = ingest_threads_impl(
        forum_db_file="forums/a.db",
        thread_ids=[1, 2, 3],
        index_db_path=index_db, data_root=data_root,
        embed_client=fake_embed_api, embed_model="m1",
    )
    assert isinstance(res, IngestResult)
    assert res.requested == 3
    assert res.newly_embedded == 3
    assert res.already_indexed == 0
    assert res.failed == 0
    # check index.db
    cx = sqlite3.connect(index_db)
    n = cx.execute("SELECT count(*) FROM thread_vector").fetchone()[0]
    assert n == 3
    cx.close()


def test_ingest_threads_idempotent(tmp_path, fake_embed_api):
    threads = [(1, 10, "u1", "x")]
    data_root = _build_forum_db(tmp_path, threads)
    index_db = _empty_index_db(tmp_path)
    ingest_threads_impl(
        forum_db_file="forums/a.db", thread_ids=[1],
        index_db_path=index_db, data_root=data_root,
        embed_client=fake_embed_api, embed_model="m1",
    )
    res2 = ingest_threads_impl(
        forum_db_file="forums/a.db", thread_ids=[1],
        index_db_path=index_db, data_root=data_root,
        embed_client=fake_embed_api, embed_model="m1",
    )
    assert res2.already_indexed == 1
    assert res2.newly_embedded == 0


def test_ingest_threads_thread_ids_none_pulls_all_missing(tmp_path, fake_embed_api):
    threads = [(1, 10, "u1", "x"), (2, 10, "u2", "y")]
    data_root = _build_forum_db(tmp_path, threads)
    index_db = _empty_index_db(tmp_path)
    res = ingest_threads_impl(
        forum_db_file="forums/a.db", thread_ids=None,
        index_db_path=index_db, data_root=data_root,
        embed_client=fake_embed_api, embed_model="m1",
    )
    assert res.newly_embedded == 2


def test_ingest_threads_partial_failure_marks_failed(tmp_path, monkeypatch, fake_embed_api):
    """Simulate api failure mid-batch."""
    threads = [(i, 10, f"u{i}", f"标题{i}") for i in range(1, 6)]
    data_root = _build_forum_db(tmp_path, threads)
    index_db = _empty_index_db(tmp_path)

    class FailingThenSucceedingClient:
        def __init__(self):
            self.calls = 0
        def embed(self, texts):
            self.calls += 1
            if self.calls == 1:
                from bbs_database.router.errors import EmbedAPIError
                raise EmbedAPIError("fail batch 1")
            return fake_embed_api.embed(texts)

    client = FailingThenSucceedingClient()
    res = ingest_threads_impl(
        forum_db_file="forums/a.db", thread_ids=[1, 2, 3, 4, 5],
        index_db_path=index_db, data_root=data_root,
        embed_client=client, embed_model="m1",
        batch_size=3,
    )
    # First batch (3 threads) failed; second batch (2 threads) succeeded
    assert res.failed == 3
    assert res.newly_embedded == 2
    assert set(res.failed_thread_ids) == {1, 2, 3}
