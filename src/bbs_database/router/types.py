"""Dataclasses for BBS_Database public API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class MatchedTerm:
    term: str
    source: Literal["declared", "content", "entity"]
    contribution: float


@dataclass
class ExpansionLink:
    expanded_term: str
    via_query_term: str
    cooccur_weight: float
    contribution: float


@dataclass
class VectorContributingThread:
    thread_id: int
    forum_db_file: str
    title: str
    cosine: float


@dataclass
class QueryRep:
    terms: list[str]
    entities: list[tuple[str, str]]


@dataclass
class ForumCandidate:
    board_node_id: int
    site_key: str
    name: str
    path: str
    forum_db_file: str

    final_score: float
    classic_direct_score: float
    classic_expansion_score: float
    vector_cosine: float
    delta_used: float

    activity_score: float
    title_count: int
    content_signal_strength: float

    matched_terms: list[MatchedTerm]
    expanded_via: list[ExpansionLink]
    top_vector_contributing_threads: list[VectorContributingThread]

    vector_disabled: bool = False


@dataclass
class ThreadHit:
    thread_id: int
    board_node_id: int
    board_name: str
    board_path: str
    forum_db_file: str

    title: str
    author: str | None
    posted_at: str | None
    last_reply_at: str | None
    reply_count: int | None
    view_count: int | None
    url: str
    is_pinned: bool

    combined_score: float
    vector_cosine: float
    board_score: float
    recency_factor: float
    breakdown: dict[str, float]

    routing_evidence: ForumCandidate


@dataclass
class Post:
    floor: int
    author: str
    posted_at: str | None
    content_text: str
    attachments: list[dict] | None


@dataclass
class ThreadDetail:
    thread_id: int
    board_node_id: int
    title: str
    author: str | None
    url: str
    posted_at: str | None
    posts: list[Post]
    raw: dict | None


@dataclass
class IngestResult:
    forum_db_file: str
    requested: int
    already_indexed: int
    newly_embedded: int
    failed: int
    failed_thread_ids: list[int]
    elapsed_seconds: float
    estimated_cost_cny: float
    embed_model: str
