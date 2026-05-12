from bbs_database.builder.tokenize import Tokenizer
from bbs_database.router.parse import parse_query
from bbs_database.router.types import QueryRep


def test_parse_strips_stopwords_and_short_tokens():
    tok = Tokenizer(stopwords={"的", "了", "怎么样"}, min_length=2)
    q = parse_query("张三老师怎么样", tok)
    assert isinstance(q, QueryRep)
    assert "张三" in q.terms
    assert "老师" in q.terms
    assert "怎么样" not in q.terms


def test_parse_extracts_entities():
    tok = Tokenizer(stopwords=set(), min_length=2)
    q = parse_query("张三老师怎么样", tok)
    assert ("张三", "person") in q.entities


def test_parse_empty_query_returns_empty_repr():
    tok = Tokenizer(stopwords=set(), min_length=2)
    q = parse_query("", tok)
    assert q.terms == []
    assert q.entities == []
