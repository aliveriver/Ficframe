from __future__ import annotations

import re


PUNCTUATION_SPLIT = re.compile(r"(?<=[。！？!?])")


def clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]


def split_sentences(text: str) -> list[str]:
    parts = []
    for piece in PUNCTUATION_SPLIT.split(text):
        piece = piece.strip()
        if piece:
            parts.append(piece)
    return parts


def compact(text: str, limit: int = 120) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
