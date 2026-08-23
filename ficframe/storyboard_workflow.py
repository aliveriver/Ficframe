from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

from .models import CharacterCard, Shot, to_dict
from .segmenter import locate_source_span
from .source_reference import (
    build_description_source_ref,
    build_novel_source_ref,
    resolve_source_ref,
    source_ref_from_legacy,
    sync_legacy_source_fields,
)


MAX_STORYBOARD_VERSIONS = 50
IMAGE_FIELDS = {"image_path", "image_url", "image_versions"}


def normalize_novel_text(text: str) -> str:
    """统一使用浏览器 textarea 的 LF 坐标系。"""
    # 某些旧 Windows run 经多次写入后会包含 CRCRLF。
    # 将 LF 前连续出现的 CR 视为一个逻辑换行。
    normalized = re.sub(r"\r+\n", "\n", text).replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", normalized)


class StoryboardRevisionError(RuntimeError):
    def __init__(self, shot_id: str, cause: Exception):
        super().__init__(f"{shot_id} 重新生成失败：{cause}")
        self.shot_id = shot_id
        self.cause = cause


def storyboard_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    """复制分镜数据，同时保持文本历史与图片历史相互独立。"""
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
        unique_history: list[dict[str, Any]] = []
        known_snapshots: set[str] = set()
        for version in history:
            if not isinstance(version, dict) or not isinstance(version.get("shot"), dict):
                unique_history.append(version)
                continue
            snapshot_key = storyboard_snapshot_key(version["shot"])
            if snapshot_key in known_snapshots:
                continue
            known_snapshots.add(snapshot_key)
            unique_history.append(version)
        if len(unique_history) != len(history):
            history[:] = unique_history

        snapshot = storyboard_snapshot(item)
        snapshot_key = storyboard_snapshot_key(snapshot)
        if snapshot_key in known_snapshots:
            continue
        history.append(
            {
                "version_id": f"sv_{time.time_ns()}",
                "created_at": int(time.time()),
                "reason": reason,
                "source": source,
                "shot": snapshot,
            }
        )
        if len(history) > MAX_STORYBOARD_VERSIONS:
            del history[:-MAX_STORYBOARD_VERSIONS]


def storyboard_snapshot_key(snapshot: dict[str, Any]) -> str:
    """生成稳定的文本版本标识，用于避免恢复操作制造重复历史。"""
    return json.dumps(storyboard_snapshot(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def revise_storyboard_items(
    items: list[dict[str, Any]],
    target_ids: set[str],
    cards: list[CharacterCard],
    provider: Any,
    feedback_history: list[dict[str, Any]],
    purpose_prefix: str,
    revise_shot: Callable[..., Shot],
) -> list[dict[str, Any]]:
    """重建选中的分镜，并在业务边界上强制保留已有图片。"""
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
    source_ref: dict[str, Any] | None = None,
) -> tuple[str, int | None, int | None]:
    reference = normalize_source_reference(novel_text, source_text, source_start, source_end, source_ref)
    if reference.get("kind") == "description":
        return "", None, None
    return str(reference.get("quote") or ""), reference.get("start"), reference.get("end")


def normalize_source_reference(
    novel_text: str,
    source_text: str,
    source_start: int | None,
    source_end: int | None,
    source_ref: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """将旧版选择字段或规范引用转换为可验证的 source_ref。"""
    if isinstance(source_ref, dict) and source_ref:
        resolved = resolve_source_ref(novel_text, source_ref)
        if resolved.get("kind") == "novel" and resolved.get("status") == "unresolved":
            raise ValueError("选中的文字无法在当前小说原文中定位")
        return resolved
    if source_start is not None and source_end is not None and 0 <= source_start < source_end <= len(novel_text):
        selected = novel_text[source_start:source_end]
        if not source_text.strip() or selected == source_text:
            return build_novel_source_ref(novel_text, source_start, source_end)
    cleaned = source_text.strip()
    if not cleaned:
        return build_description_source_ref("")
    found = novel_text.find(cleaned)
    if found < 0:
        raise ValueError("选中的文字不属于当前小说原文")
    return build_novel_source_ref(novel_text, found, found + len(cleaned))


def backfill_storyboard_sources(payload: dict[str, Any], novel_text: str) -> bool:
    """迁移并校验旧 run 的原文引用，同时刷新兼容字段。"""
    changed = False
    scenes = {str(item.get("id")): item for item in payload.get("scenes", []) if isinstance(item, dict)}
    for scene in scenes.values():
        before = json.dumps(scene, ensure_ascii=False, sort_keys=True)
        for field in ("text", "source_text", "source_excerpt"):
            if field in scene:
                scene[field] = normalize_novel_text(str(scene.get(field) or ""))
        reference = source_ref_from_legacy(scene, novel_text)
        scene["source_ref"] = reference
        if reference.get("kind") == "novel" and reference.get("status") != "unresolved":
            scene["source_start"] = reference.get("start")
            scene["source_end"] = reference.get("end")
        after = json.dumps(scene, ensure_ascii=False, sort_keys=True)
        changed = changed or before != after
    for shot in payload.get("shots", []):
        if not isinstance(shot, dict):
            continue
        before = json.dumps(shot, ensure_ascii=False, sort_keys=True)
        for field in ("source_text", "source_excerpt"):
            if field in shot:
                shot[field] = normalize_novel_text(str(shot.get(field) or ""))
        legacy_source = str(shot.get("source_text") or "").strip()
        if not shot.get("source_ref") and not legacy_source:
            scene = scenes.get(str(shot.get("scene_id")))
            if scene and isinstance(scene.get("source_ref"), dict):
                shot["source_ref"] = scene["source_ref"]
        reference = source_ref_from_legacy(shot, novel_text)
        sync_legacy_source_fields(shot, reference)
        if reference.get("kind") == "novel":
            shot.setdefault("generation_mode", "novel")
        after = json.dumps(shot, ensure_ascii=False, sort_keys=True)
        changed = changed or before != after
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
