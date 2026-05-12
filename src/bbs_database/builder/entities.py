"""Title-level entity extraction (person / course / place / org)."""

from __future__ import annotations

import re

import jieba.posseg as pseg


_PERSON_RE = re.compile(r"([一-龥]{2,4})(?=老师|教授|导师|学长|学姐)")
_COURSE_RE = re.compile(r"([一-龥A-Za-z]{2,}(?:课|学|实验))")


def extract_entities(text: str) -> list[tuple[str, str]]:
    """Return list of (entity, type) pairs. Duplicates removed within a single text."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []

    for match in _PERSON_RE.finditer(text):
        item = (match.group(1), "person")
        if item not in seen:
            seen.add(item)
            out.append(item)

    for match in _COURSE_RE.finditer(text):
        item = (match.group(1), "course")
        if item not in seen:
            seen.add(item)
            out.append(item)

    for word, flag in pseg.cut(text):
        word = word.strip()
        if len(word) < 2:
            continue
        if flag == "nr":
            item = (word, "person")
        elif flag == "ns":
            item = (word, "place")
        elif flag == "nt":
            item = (word, "org")
        else:
            continue
        if item not in seen:
            seen.add(item)
            out.append(item)

    return out
