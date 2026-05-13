"""Acceptance demo — try arbitrary queries against the four public APIs.

Run: ./.venv/Scripts/python.exe acceptance_demo.py
Requires: .env with DASHSCOPE_API_KEY; index.db already built.
"""
import time
from dotenv import load_dotenv

load_dotenv()

from bbs_database.api import find_forums, search_threads, get_thread, ingest_threads


# Edit this list to test any queries you want.
QUERIES = [
    "张三老师讲课怎么样",
    "宿舍丢东西怎么办",
    "考研经验",
    "周末去哪玩",
    "推荐一款电脑",
]


def demo_find_forums():
    print("=" * 80)
    print("DEMO 1 · find_forums (predict which boards are relevant)")
    print("=" * 80)
    for q in QUERIES:
        t0 = time.monotonic()
        out = find_forums(q, top_k=3)
        elapsed = (time.monotonic() - t0) * 1000
        print(f"\nquery: {q!r}  ({elapsed:.0f}ms)")
        for i, c in enumerate(out, 1):
            evidence = []
            if c.vector_cosine > 0:
                evidence.append(f"vec={c.vector_cosine:.2f}")
            if c.classic_direct_score > 0:
                evidence.append(f"clf={c.classic_direct_score:.2f}")
            print(f"  {i}. score={c.final_score:.3f}  {c.path[:60]}  ({', '.join(evidence)})")


def demo_search_threads():
    print("\n" + "=" * 80)
    print("DEMO 2 · search_threads (find specific threads via vector cosine)")
    print("=" * 80)
    q = "推荐一款电脑"
    print(f"\nquery: {q!r}")
    hits = search_threads(q, top_k_forums=3, total_limit=5)
    for i, h in enumerate(hits, 1):
        print(f"  {i}. cos={h.vector_cosine:.3f}  [{h.board_name[:10]}] {h.title[:50]}")
        print(f"     url={h.url}  posted={h.posted_at}")


def demo_get_thread():
    print("\n" + "=" * 80)
    print("DEMO 3 · get_thread (read full content of a thread)")
    print("=" * 80)
    hits = search_threads("考研经验", top_k_forums=2, total_limit=1)
    if not hits:
        print("  (search returned no hits to demo get_thread)")
        return
    h = hits[0]
    td = get_thread(h.forum_db_file, h.thread_id)
    print(f"\nthread #{td.thread_id} '{td.title}' by {td.author}")
    print(f"posted: {td.posted_at}  url: {td.url}")
    print(f"posts: {len(td.posts)} floor(s)")
    if td.posts:
        first = td.posts[0]
        snippet = (first.content_text or "")[:200]
        print(f"floor 0 by {first.author}: {snippet!r}...")


def demo_ingest_threads():
    print("\n" + "=" * 80)
    print("DEMO 4 · ingest_threads (idempotent — should report mostly already_indexed)")
    print("=" * 80)
    # Pick first forum db file we have
    from pathlib import Path
    forum_files = list(Path("data/crawler.db/forums").glob("*.db"))
    if not forum_files:
        print("  (no forum.db files to ingest from)")
        return
    fdb = "forums/" + forum_files[0].name
    res = ingest_threads(fdb, thread_ids=None)
    print(f"\ningest({fdb})")
    print(f"  requested:        {res.requested}")
    print(f"  already_indexed:  {res.already_indexed}")
    print(f"  newly_embedded:   {res.newly_embedded}")
    print(f"  failed:           {res.failed}")
    print(f"  elapsed:          {res.elapsed_seconds:.2f}s")
    print(f"  estimated cost:   ¥{res.estimated_cost_cny:.4f}")
    print(f"  model:            {res.embed_model}")


if __name__ == "__main__":
    demo_find_forums()
    demo_search_threads()
    demo_get_thread()
    demo_ingest_threads()
