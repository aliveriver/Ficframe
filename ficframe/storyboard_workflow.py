from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .io import write_json, write_text
from .models import CharacterCard, Shot, to_dict
from .render import render_prompts, render_storyboard
from .segmenter import locate_source_span


MAX_STORYBOARD_VERSIONS = 50
IMAGE_FIELDS = {"image_path", "image_url", "image_versions"}


def normalize_novel_text(text: str) -> str:
    """Use the browser textarea's LF coordinate system everywhere."""
    # Some older Windows runs contain CRCRLF after being written more than once.
    # Treat any CR run immediately before LF as one logical newline.
    normalized = re.sub(r"\r+\n", "\n", text).replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", normalized)


class StoryboardRevisionError(RuntimeError):
    def __init__(self, shot_id: str, cause: Exception):
        super().__init__(f"{shot_id} 重新生成失败：{cause}")
        self.shot_id = shot_id
        self.cause = cause


def persist_storyboard_payload(pipeline_path: Path, payload: dict[str, Any]) -> None:
    """Persist the canonical run payload and its human-readable projections."""
    write_json(pipeline_path, payload)
    shots = [Shot(**item) for item in payload.get("shots", [])]
    write_text(pipeline_path.parent / "storyboard.md", render_storyboard(shots))
    write_text(pipeline_path.parent / "prompts.md", render_prompts(shots))


def storyboard_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    """Copy storyboard data without coupling text history to image history."""
    snapshot = {key: value for key, value in item.items() if key not in IMAGE_FIELDS}
    return json.loads(json.dumps(snapshot, ensure_ascii=False))


def archive_storyboard_versions(
    payload: dict[str, Any],
    items: list[dict[str, Any]],
    reason: str,
    source: str,
) -> None:
    histories = payload.setdefault("storyboard_versions", {})
    for item in items:
        shot_id = str(item.get("id") or "")
        if not shot_id:
            continue
        history = histories.setdefault(shot_id, [])
        history.append(
            {
                "version_id": f"sv_{time.time_ns()}",
                "created_at": int(time.time()),
                "reason": reason,
                "source": source,
                "shot": storyboard_snapshot(item),
            }
        )
        if len(history) > MAX_STORYBOARD_VERSIONS:
            del history[:-MAX_STORYBOARD_VERSIONS]


def revise_storyboard_items(
    items: list[dict[str, Any]],
    target_ids: set[str],
    cards: list[CharacterCard],
    provider: Any,
    feedback_history: list[dict[str, Any]],
    purpose_prefix: str,
    revise_shot: Callable[..., Shot],
) -> list[dict[str, Any]]:
    """Revise selected shots while enforcing image preservation at the domain boundary."""
    revised: list[dict[str, Any]] = []
    for item in items:
        if item.get("id") not in target_ids:
            revised.append(item)
            continue
        shot = Shot(**item)
        preserved_images = {field: to_dict(getattr(shot, field)) for field in IMAGE_FIELDS}
        try:
            shot = revise_shot(
                shot,
                cards,
                provider,
                feedback_history=feedback_history,
                purpose=f"{purpose_prefix}:{shot.id}",
            )
        except Exception as exc:
            raise StoryboardRevisionError(shot.id, exc) from exc
        for field, value in preserved_images.items():
            setattr(shot, field, value)
        revised.append(to_dict(shot))
    return revised


def normalize_requested_source(
    novel_text: str,
    source_text: str,
    source_start: int | None,
    source_end: int | None,
) -> tuple[str, int | None, int | None]:
    if source_start is not None and source_end is not None and 0 <= source_start < source_end <= len(novel_text):
        selected = novel_text[source_start:source_end]
        if not source_text.strip() or selected == source_text:
            return selected, source_start, source_end
    cleaned = source_text.strip()
    if not cleaned:
        return "", None, None
    found = novel_text.find(cleaned)
    if found < 0:
        raise ValueError("选中的文字不属于当前小说原文")
    return cleaned, found, found + len(cleaned)


def backfill_storyboard_sources(payload: dict[str, Any], novel_text: str) -> bool:
    """Migrate older runs so their shots can use the novel highlighter."""
    changed = False
    scenes = {str(item.get("id")): item for item in payload.get("scenes", []) if isinstance(item, dict)}
    cursor = 0
    for shot in payload.get("shots", []):
        if not isinstance(shot, dict):
            continue
        existing_source = normalize_novel_text(str(shot.get("source_text") or ""))
        if existing_source:
            start = _optional_int(shot.get("source_start"))
            end = _optional_int(shot.get("source_end"))
            if start is None or end is None or novel_text[start:end] != existing_source:
                found = novel_text.find(existing_source, cursor)
                if found < 0:
                    found = novel_text.find(existing_source)
                if found >= 0:
                    shot["source_start"] = found
                    shot["source_end"] = found + len(existing_source)
                    shot["source_text"] = existing_source
                    changed = True
                    cursor = found + len(existing_source)
            elif shot.get("source_text") != existing_source:
                shot["source_text"] = existing_source
                changed = True
            continue
        scene = scenes.get(str(shot.get("scene_id")))
        if not scene:
            continue
        start = _optional_int(scene.get("source_start"))
        end = _optional_int(scene.get("source_end"))
        if start is None or end is None or not (0 <= start < end <= len(novel_text)):
            start, end = locate_source_span(novel_text, str(scene.get("text") or ""), cursor)
        if start is None or end is None:
            continue
        cursor = end
        scene["source_start"] = start
        scene["source_end"] = end
        shot["source_start"] = start
        shot["source_end"] = end
        shot["source_text"] = novel_text[start:end]
        shot.setdefault("generation_mode", "novel")
        changed = True
    return changed


def storyboard_message(role: str, content: str) -> dict[str, Any]:
    return {
        "id": f"msg_{time.time_ns()}",
        "role": role,
        "content": content,
        "created_at": int(time.time()),
    }


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
