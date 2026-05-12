"""parse_query — jieba tokenization + entity extraction."""

from __future__ import annotations

from bbs_database.builder.entities import extract_entities
from bbs_database.builder.tokenize import Tokenizer
from bbs_database.router.types import QueryRep


def parse_query(query: str, tokenizer: Tokenizer) -> QueryRep:
    terms = tokenizer.cut(query) if query else []
    entities = extract_entities(query) if query else []
    return QueryRep(terms=terms, entities=entities)
