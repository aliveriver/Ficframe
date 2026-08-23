from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Literal


SOURCE_REF_VERSION = 1
ANCHOR_LENGTH = 48


@dataclass
class SourceReference:
    """分镜所依据内容的稳定引用。"""

    version: int = SOURCE_REF_VERSION
    kind: Literal["novel", "description"] = "novel"
    document: str = "novel.md"
    start: int | None = None
    end: int | None = None
    quote: str = ""
    prefix: str = ""
    suffix: str = ""
    document_hash: str = ""
    quote_hash: str = ""
    status: Literal["exact", "relocated", "description", "unresolved"] = "unresolved"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_novel_source_ref(novel_text: str, start: int, end: int) -> dict[str, Any]:
    if not (0 <= start < end <= len(novel_text)):
        raise ValueError("原文引用区间无效")
    quote = novel_text[start:end]
    return asdict(SourceReference(
        kind="novel",
        start=start,
        end=end,
        quote=quote,
        prefix=novel_text[max(0, start - ANCHOR_LENGTH):start],
        suffix=novel_text[end:min(len(novel_text), end + ANCHOR_LENGTH)],
        document_hash=text_hash(novel_text),
        quote_hash=text_hash(quote),
        status="exact",
    ))


def build_description_source_ref(description: str) -> dict[str, Any]:
    quote = str(description or "").strip()
    return asdict(SourceReference(
        kind="description",
        document="",
        quote=quote,
        quote_hash=text_hash(quote) if quote else "",
        status="description",
    ))


def resolve_source_ref(novel_text: str, reference: Any) -> dict[str, Any]:
    """校验引用；坐标失效时使用原文和上下文锚点重新定位。"""
    if not isinstance(reference, dict):
        return asdict(SourceReference(status="unresolved"))
    if reference.get("kind") == "description":
        return build_description_source_ref(str(reference.get("quote") or ""))
    quote = str(reference.get("quote") or "")
    start = _optional_int(reference.get("start"))
    end = _optional_int(reference.get("end"))
    if quote and start is not None and end is not None and 0 <= start < end <= len(novel_text):
        if novel_text[start:end] == quote:
            resolved = build_novel_source_ref(novel_text, start, end)
            resolved["status"] = "exact"
            return resolved
    found = _find_with_anchors(
        novel_text,
        quote,
        str(reference.get("prefix") or ""),
        str(reference.get("suffix") or ""),
    )
    if found is not None:
        resolved = build_novel_source_ref(novel_text, found, found + len(quote))
        resolved["status"] = "relocated"
        return resolved
    unresolved = SourceReference(
        kind="novel",
        start=start,
        end=end,
        quote=quote,
        prefix=str(reference.get("prefix") or ""),
        suffix=str(reference.get("suffix") or ""),
        document_hash=str(reference.get("document_hash") or ""),
        quote_hash=str(reference.get("quote_hash") or (text_hash(quote) if quote else "")),
        status="unresolved",
    )
    return asdict(unresolved)


def source_ref_from_legacy(item: dict[str, Any], novel_text: str) -> dict[str, Any]:
    """将旧版 source_* 字段转换成 source_ref。"""
    if isinstance(item.get("source_ref"), dict):
        return resolve_source_ref(novel_text, item["source_ref"])
    if str(item.get("generation_mode") or "") == "description":
        return build_description_source_ref(str(item.get("generation_description") or item.get("source_excerpt") or ""))
    quote = str(item.get("source_text") or "")
    start = _optional_int(item.get("source_start"))
    end = _optional_int(item.get("source_end"))
    if start is not None and end is not None and 0 <= start < end <= len(novel_text):
        selected = novel_text[start:end]
        if not quote or quote == selected:
            return build_novel_source_ref(novel_text, start, end)
    candidate = quote or str(item.get("source_excerpt") or item.get("text") or "")
    found = novel_text.find(candidate) if candidate else -1
    if found >= 0:
        return build_novel_source_ref(novel_text, found, found + len(candidate))
    return resolve_source_ref(novel_text, {"kind": "novel", "quote": candidate})


def sync_legacy_source_fields(item: dict[str, Any], reference: dict[str, Any]) -> None:
    """在过渡期同步旧字段，供旧客户端和导出逻辑继续读取。"""
    item["source_ref"] = reference
    if reference.get("kind") == "novel" and reference.get("status") != "unresolved":
        item["source_start"] = reference.get("start")
        item["source_end"] = reference.get("end")
        item["source_text"] = reference.get("quote") or ""
    elif reference.get("kind") == "novel":
        item["source_start"] = None
        item["source_end"] = None
        item["source_text"] = reference.get("quote") or ""
    elif reference.get("kind") == "description":
        item["source_start"] = None
        item["source_end"] = None
        item["source_text"] = ""


def _find_with_anchors(novel_text: str, quote: str, prefix: str, suffix: str) -> int | None:
    if not quote:
        return None
    positions: list[int] = []
    cursor = 0
    while True:
        found = novel_text.find(quote, cursor)
        if found < 0:
            break
        positions.append(found)
        cursor = found + 1
    if not positions:
        return None
    if len(positions) == 1:
        return positions[0]
    scored = []
    for position in positions:
        before = novel_text[max(0, position - len(prefix)):position]
        after_start = position + len(quote)
        after = novel_text[after_start:after_start + len(suffix)]
        score = int(bool(prefix) and before == prefix) + int(bool(suffix) and after == suffix)
        scored.append((score, position))
    best_score = max(score for score, _ in scored)
    best = [position for score, position in scored if score == best_score]
    return best[0] if best_score > 0 and len(best) == 1 else None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
