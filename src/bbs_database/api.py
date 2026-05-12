"""Public Python API. Four functions: find_forums / ingest_threads /
search_threads / get_thread.

This is the only module BBS_MCP should import. All other modules are
internal.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from bbs_database.builder.tokenize import Tokenizer, load_stopwords
from bbs_database.config import Config, EmbedConfig, load_config
from bbs_database.ingest import ingest_threads_impl
from bbs_database.reader import open_ro
from bbs_database.router.hybrid import find_forums_impl
from bbs_database.router.search import search_threads_impl
from bbs_database.router.thread_detail import get_thread_impl
from bbs_database.router.types import ForumCandidate, IngestResult, ThreadDetail, ThreadHit

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent.parent / "config" / "routing.yaml"


def _load(config_path: Path | str | None) -> Config:
    p = Path(config_path) if config_path else _DEFAULT_CONFIG
    return load_config(p.resolve(), root=p.parent.parent)


def _make_embed_client(cfg: EmbedConfig):
    """Factory for embed client. Patched in tests."""
    from bbs_database.embed.client import EmbedClient
    return EmbedClient(cfg)


def find_forums(
    query: str, *,
    site_key: str | None = None,
    top_k: int = 8,
    overrides: dict | None = None,
    config_path: Path | str | None = None,
) -> list[ForumCandidate]:
    cfg = _load(config_path)
    routing_cfg = dict(cfg.routing)
    if overrides:
        routing_cfg.update(overrides)
    tokenizer = Tokenizer(
        stopwords=load_stopwords(cfg.build.stopwords_path),
        min_length=cfg.build.min_token_length,
    )
    embed_client = _make_embed_client(cfg.embed)
    cx = sqlite3.connect(f"file:{cfg.index_db_path.as_posix()}?mode=ro", uri=True)
    try:
        return find_forums_impl(
            cx, query=query, tokenizer=tokenizer,
            embed_client=embed_client,
            routing_cfg=routing_cfg, top_k=top_k,
        )
    finally:
        cx.close()


def ingest_threads(
    forum_db_file: str,
    thread_ids: list[int] | None = None,
    *,
    overrides: dict | None = None,
    config_path: Path | str | None = None,
) -> IngestResult:
    cfg = _load(config_path)
    embed_client = _make_embed_client(cfg.embed)
    bs = cfg.embed.batch_size
    if overrides and "batch_size" in overrides:
        bs = overrides["batch_size"]
    return ingest_threads_impl(
        forum_db_file=forum_db_file,
        thread_ids=thread_ids,
        index_db_path=cfg.index_db_path,
        data_root=cfg.data_root_path,
        embed_client=embed_client,
        embed_model=cfg.embed.model,
        batch_size=bs,
    )


def search_threads(
    query: str, *,
    site_key: str | None = None,
    board_node_ids: list[int] | None = None,
    top_k_forums: int = 5,
    per_board_limit: int | None = None,
    total_limit: int | None = None,
    overrides: dict | None = None,
    config_path: Path | str | None = None,
) -> list[ThreadHit]:
    cfg = _load(config_path)
    search_cfg = dict(cfg.search)
    if per_board_limit is not None:
        search_cfg["per_board_limit"] = per_board_limit
    if total_limit is not None:
        search_cfg["total_limit"] = total_limit
    if overrides:
        search_cfg.update(overrides)
    embed_client = _make_embed_client(cfg.embed)
    cx = sqlite3.connect(f"file:{cfg.index_db_path.as_posix()}?mode=ro", uri=True)
    try:
        # decide board scope
        if board_node_ids is None:
            tokenizer = Tokenizer(
                stopwords=load_stopwords(cfg.build.stopwords_path),
                min_length=cfg.build.min_token_length,
            )
            forums = find_forums_impl(
                cx, query=query, tokenizer=tokenizer,
                embed_client=embed_client,
                routing_cfg=dict(cfg.routing), top_k=top_k_forums,
            )
            board_node_ids = [c.board_node_id for c in forums]
            board_score = {c.board_node_id: c.final_score for c in forums}
        else:
            board_score = {bid: 1.0 for bid in board_node_ids}
        return search_threads_impl(
            cx, query=query,
            board_node_ids=board_node_ids,
            board_score=board_score,
            embed_client=embed_client,
            data_root=cfg.data_root_path,
            search_cfg=search_cfg,
        )
    finally:
        cx.close()


def get_thread(
    forum_db_file: str,
    thread_id: int,
    *,
    data_root: Path | str | None = None,
    config_path: Path | str | None = None,
) -> ThreadDetail:
    if data_root is None:
        cfg = _load(config_path)
        data_root = cfg.data_root_path
    return get_thread_impl(data_root, forum_db_file, thread_id)
