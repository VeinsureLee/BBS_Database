from bbs_database.router.types import (
    MatchedTerm,
    ExpansionLink,
    VectorContributingThread,
    ForumCandidate,
    ThreadHit,
    IngestResult,
    Post,
    ThreadDetail,
    QueryRep,
)


def test_matched_term_dataclass():
    m = MatchedTerm(term="x", source="declared", contribution=1.2)
    assert m.term == "x" and m.source == "declared"


def test_forum_candidate_minimum_fields():
    c = ForumCandidate(
        board_node_id=1, site_key="s", name="n", path="p", forum_db_file="f",
        final_score=1.0, classic_direct_score=0.5, classic_expansion_score=0.0,
        vector_cosine=0.7, delta_used=0.5,
        activity_score=0.1, title_count=10, content_signal_strength=0.05,
        matched_terms=[], expanded_via=[],
        top_vector_contributing_threads=[],
    )
    assert c.vector_disabled is False  # default


def test_thread_hit_with_evidence():
    routing = ForumCandidate(
        board_node_id=1, site_key="s", name="n", path="p", forum_db_file="f",
        final_score=1.0, classic_direct_score=0.5, classic_expansion_score=0.0,
        vector_cosine=0.7, delta_used=0.5,
        activity_score=0.1, title_count=10, content_signal_strength=0.05,
        matched_terms=[], expanded_via=[], top_vector_contributing_threads=[],
    )
    hit = ThreadHit(
        thread_id=1, board_node_id=1, board_name="n", board_path="p",
        forum_db_file="f", title="t", author=None, posted_at=None,
        last_reply_at=None, reply_count=None, view_count=None,
        url="u", is_pinned=False,
        combined_score=1.5, vector_cosine=0.8, board_score=1.0,
        recency_factor=0.5, breakdown={"vector": 0.48, "board": 0.3, "recency": 0.05},
        routing_evidence=routing,
    )
    assert hit.routing_evidence.vector_cosine == 0.7


def test_ingest_result_partial():
    r = IngestResult(
        forum_db_file="f", requested=10, already_indexed=2,
        newly_embedded=5, failed=3, failed_thread_ids=[101, 102, 103],
        elapsed_seconds=1.2, estimated_cost_cny=0.001,
        embed_model="text-embedding-v3",
    )
    assert r.newly_embedded + r.failed + r.already_indexed == r.requested


def test_query_rep_holds_terms_and_entities():
    q = QueryRep(terms=["a", "b"], entities=[("张三", "person")])
    assert q.entities[0] == ("张三", "person")


def test_thread_detail_with_posts():
    td = ThreadDetail(
        thread_id=1, board_node_id=1, title="t", author="u", url="x",
        posted_at=None,
        posts=[Post(floor=0, author="u", posted_at=None, content_text="hi",
                    attachments=None)],
        raw=None,
    )
    assert td.posts[0].floor == 0
