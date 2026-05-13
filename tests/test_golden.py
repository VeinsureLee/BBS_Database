"""Golden query smoke test — requires DASHSCOPE_API_KEY in environment.

Skipped by default. Run with:
    DASHSCOPE_API_KEY=sk-... pytest -m smoke tests/test_golden.py
"""

import os
from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.smoke


@pytest.fixture
def golden():
    path = Path(__file__).parent / "golden_queries.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture
def real_api_key():
    # api.py loads .env on import; do the same here so smoke runs can pick up
    # DASHSCOPE_API_KEY from .env without requiring an exported shell env.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        pytest.skip("DASHSCOPE_API_KEY not set (checked .env and shell env)")
    return key


def test_top3_hit_rate_at_least_50_percent(golden, real_api_key):
    from bbs_database.api import find_forums

    hits = 0
    for case in golden:
        query = case["query"]
        expect = case["expect_path_contains"]
        out = find_forums(query, top_k=3)
        if any(expect in c.path for c in out):
            hits += 1
    rate = hits / len(golden)
    assert rate >= 0.5, f"golden hit rate {rate:.2f} < 0.5; misses on {len(golden) - hits}/{len(golden)}"
