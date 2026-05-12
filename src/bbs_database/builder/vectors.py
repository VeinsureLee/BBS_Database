"""Build board-level and thread-level embeddings into index.db.

Pure functions: take an open sqlite3 connection + an embed-client-like object
(must expose .embed(texts) -> list[list[float]]) + config knobs. Caller owns
the connection lifecycle and commits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import sqlite3

from bbs_database.embed.cache import encode_vec


@dataclass
class BoardSpec:
    board_node_id: int
    name: str
    path: str
    pinned_titles: list[str] = field(default_factory=list)


@dataclass
class ThreadSpec:
    board_node_id: int
    thread_id: int
    title: str
    forum_db_file: str


@dataclass
class BuildVectorsResult:
    newly_embedded: int = 0
    already_indexed: int = 0
    failed: int = 0
    failed_keys: list = field(default_factory=list)


def build_board_source_text(spec: BoardSpec) -> str:
    parts = [spec.name, spec.path, *spec.pinned_titles]
    return " ".join(p for p in parts if p)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_board_vectors(
    cx: sqlite3.Connection,
    specs: list[BoardSpec],
    embed_client,
    *,
    model: str,
) -> BuildVectorsResult:
    # purge any rows under a different embed_model
    cx.execute("DELETE FROM board_vector WHERE embed_model != ?", (model,))
    existing = {
        row[0]
        for row in cx.execute("SELECT board_node_id FROM board_vector WHERE embed_model = ?",
                              (model,))
    }
    to_embed = [s for s in specs if s.board_node_id not in existing]
    result = BuildVectorsResult(already_indexed=len(specs) - len(to_embed))
    if not to_embed:
        return result
    texts = [build_board_source_text(s) for s in to_embed]
    vecs = embed_client.embed(texts)
    now = _now_iso()
    rows = [
        (s.board_node_id, encode_vec(v), txt, model, now)
        for s, v, txt in zip(to_embed, vecs, texts)
    ]
    cx.executemany(
        "INSERT INTO board_vector(board_node_id, vec, source_text, embed_model, built_at) "
        "VALUES (?,?,?,?,?)",
        rows,
    )
    result.newly_embedded = len(rows)
    return result


def build_thread_vectors(
    cx: sqlite3.Connection,
    specs: list[ThreadSpec],
    embed_client,
    *,
    model: str,
) -> BuildVectorsResult:
    cx.execute("DELETE FROM thread_vector WHERE embed_model != ?", (model,))
    existing = set(cx.execute(
        "SELECT forum_db_file, thread_id FROM thread_vector WHERE embed_model = ?",
        (model,),
    ).fetchall())
    to_embed = [s for s in specs if (s.forum_db_file, s.thread_id) not in existing]
    result = BuildVectorsResult(already_indexed=len(specs) - len(to_embed))
    if not to_embed:
        return result
    titles = [s.title for s in to_embed]
    vecs = embed_client.embed(titles)
    now = _now_iso()
    rows = [
        (s.board_node_id, s.thread_id, s.forum_db_file, encode_vec(v), model, now)
        for s, v in zip(to_embed, vecs)
    ]
    cx.executemany(
        "INSERT INTO thread_vector(board_node_id, thread_id, forum_db_file, "
        "vec, embed_model, built_at) VALUES (?,?,?,?,?,?)",
        rows,
    )
    result.newly_embedded = len(rows)
    return result
