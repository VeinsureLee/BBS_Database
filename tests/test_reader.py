import json

from bbs_database.reader import (
    BoardInfo,
    ThreadRow,
    iter_boards,
    iter_threads,
    open_ro,
)


def test_iter_boards_walks_to_forum_and_yields_db_file(crawler_dataset):
    boards = list(iter_boards(crawler_dataset["root"], site_key="school-bbs"))
    by_id = {b.board_node_id: b for b in boards}
    assert set(by_id) == {10, 11, 20}
    a = by_id[10]
    assert a.name == "学院A"
    assert a.path == "学术 > 学院A"
    assert a.forum_db_file == "forums/academic.db"
    assert a.site_key == "school-bbs"
    stats = json.loads(a.stats_json)
    assert stats["online"] == 100


def test_iter_threads_returns_titles_grouped_by_board(crawler_dataset):
    threads_10 = list(iter_threads(crawler_dataset["root"], "forums/academic.db", board_node_id=10))
    titles = [t.title for t in threads_10]
    assert "张三老师讲课如何" in titles
    pinned = [t.title for t in threads_10 if t.is_pinned]
    assert pinned == ["学院A置顶通知"]


def test_open_ro_is_readonly(crawler_dataset):
    cx = open_ro(crawler_dataset["structure_db"])
    try:
        try:
            cx.execute("INSERT INTO sites(site_key, display_name, base_url) VALUES ('x','x','x')")
            cx.commit()
            assert False, "expected readonly write to fail"
        except Exception:
            pass
    finally:
        cx.close()


def test_open_ro_does_not_create_wal_or_shm_sidecars(crawler_dataset, tmp_path):
    """Regression: reading a WAL-mode db must not leave -shm/-wal files behind."""
    import sqlite3

    # Build a WAL-mode db (mimicking crawler's PRAGMA journal_mode = WAL).
    wal_db = tmp_path / "wal_mode.db"
    w = sqlite3.connect(wal_db)
    w.execute("PRAGMA journal_mode = WAL")
    w.execute("CREATE TABLE t (x INTEGER)")
    w.execute("INSERT INTO t VALUES (1)")
    w.commit()
    w.close()

    # Sanity: WAL writer may have left sidecars; clean them so we test reader cleanly.
    for suffix in ("-shm", "-wal"):
        sidecar = wal_db.with_name(wal_db.name + suffix)
        if sidecar.exists():
            sidecar.unlink()
    assert not wal_db.with_name(wal_db.name + "-shm").exists()
    assert not wal_db.with_name(wal_db.name + "-wal").exists()

    # Read via open_ro — must not regenerate sidecars.
    cx = open_ro(wal_db)
    try:
        rows = list(cx.execute("SELECT x FROM t"))
        assert rows == [(1,)]
    finally:
        cx.close()
    assert not wal_db.with_name(wal_db.name + "-shm").exists(), \
        "open_ro must not create -shm sidecar"
    assert not wal_db.with_name(wal_db.name + "-wal").exists(), \
        "open_ro must not create -wal sidecar"
