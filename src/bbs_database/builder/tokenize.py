"""Jieba-based tokenization with stopword + length filtering."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import jieba


def load_stopwords(path: Path) -> set[str]:
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        token = line.strip()
        if not token or token.startswith("#"):
            continue
        out.add(token)
    return out


@dataclass(frozen=True)
class Tokenizer:
    stopwords: set[str]
    min_length: int = 2

    def cut(self, text: str) -> list[str]:
        return [
            t for t in jieba.cut(text)
            if len(t) >= self.min_length and t not in self.stopwords and not t.isspace()
        ]

    def cut_search(self, text: str) -> list[str]:
        return [
            t for t in jieba.cut_for_search(text)
            if len(t) >= self.min_length and t not in self.stopwords and not t.isspace()
        ]
