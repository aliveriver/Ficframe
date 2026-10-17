"""Normalize character/scene payloads and uploaded reference bindings at the input boundary."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import CharacterCard, Scene


def parse_manual_characters(raw: str | None) -> list[CharacterCard]:
    return parse_character_payload(parse_json_list(raw), manual=True, deduplicate=False)


def parse_prepared_characters(raw: str | None) -> list[CharacterCard]:
    return parse_character_payload(parse_json_list(raw))


def parse_json_list(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def prompt_bank_status_text(result: Any, character_count: int) -> str:
    if result.mode == "vlm_llm_reviewed":
        return f"已由 VLM 提取并经 LLM 审查生成 {character_count} 个角色 Prompt Bank"
    if result.mode == "vlm":
        return f"已由 VLM 参考图结果生成 {character_count} 个角色 Prompt Bank"
    if result.mode == "llm":
        return f"LLM 已生成 {character_count} 个角色 Prompt Bank"
    if result.mode == "llm_guarded":
        return f"LLM 已生成 {character_count} 个角色 Prompt Bank，但{result.llm_error}"
    detail = f"：{result.llm_error}" if result.llm_error else ""
    return f"LLM 生成 Prompt Bank 失败{detail}，已改用本地规则生成 {character_count} 个角色 Prompt Bank"


def parse_character_payload(items: list[dict[str, Any]], *, manual: bool = False, deduplicate: bool = True) -> list[CharacterCard]:
    cards: list[CharacterCard] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        cards.append(
            CharacterCard(
                name=name,
                aliases=safe_string_list(item.get("aliases")),
                role=str(item.get("role") or "").strip(),
                source_text=str(item.get("source_text") or (item.get("role") if manual else "") or "").strip(),
                manual=manual or bool(item.get("manual", False)),
                visual_traits=safe_string_list(item.get("visual_traits")),
                personality_traits=safe_string_list(item.get("personality_traits")),
                fixed_traits=safe_string_list(item.get("fixed_traits")),
                variable_states=safe_string_dict(item.get("variable_states")),
                relationships=safe_string_dict(item.get("relationships")),
                reference_images=safe_string_list(item.get("reference_images")),
                reference_visuals=item.get("reference_visuals") if isinstance(item.get("reference_visuals"), list) else [],
                identity_prompt=str(item.get("identity_prompt") or "").strip(),
                negative_identity_prompt=str(item.get("negative_identity_prompt") or "").strip(),
                appearance_states=item.get("appearance_states") if isinstance(item.get("appearance_states"), list) else [],
                prompt_cn=str(item.get("prompt_cn") or "").strip(),
                prompt_en=str(item.get("prompt_en") or "").strip(),
            )
        )
    return dedupe_cards(cards) if deduplicate else cards


def parse_scene_payload(items: list[dict[str, Any]]) -> list[Scene]:
    scenes: list[Scene] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        scenes.append(
            Scene(
                id=str(item.get("id") or ""),
                chapter=str(item.get("chapter") or ""),
                index=safe_int(item.get("index"), len(scenes) + 1),
                text=str(item.get("text") or ""),
                summary=str(item.get("summary") or ""),
                characters=safe_string_list(item.get("characters")),
                location=str(item.get("location") or ""),
                time=str(item.get("time") or ""),
                mood=safe_string_list(item.get("mood")),
                visual_type=str(item.get("visual_type") or ""),
                visual_priority=safe_int(item.get("visual_priority"), 1),
                source_start=safe_optional_int(item.get("source_start")),
                source_end=safe_optional_int(item.get("source_end")),
            )
        )
    return scenes


def safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def safe_optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def safe_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def safe_string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key).strip(): str(item).strip() for key, item in value.items() if str(key).strip() and str(item).strip()}


def dedupe_cards(cards: list[CharacterCard]) -> list[CharacterCard]:
    unique: list[CharacterCard] = []
    seen: set[str] = set()
    for card in cards:
        if card.name in seen:
            continue
        seen.add(card.name)
        unique.append(card)
    return unique


def parse_reference_bindings(raw: str | None) -> dict[str, list[dict[str, str]]]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, list):
        return {}
    result: dict[str, list[dict[str, str]]] = {}
    for item in data:
        if isinstance(item, dict) and item.get("filename"):
            filename = Path(str(item["filename"])).name
            binding = {str(key): str(value) for key, value in item.items() if value is not None}
            result.setdefault(filename, []).append(binding)
    return result


def take_reference_binding(
    bindings: dict[str, list[dict[str, str]]],
    filename: str,
) -> dict[str, str]:
    queue = bindings.get(Path(filename).name, [])
    return queue.pop(0) if queue else {}


def available_reference_filename(directory: Path, filename: str) -> str:
    safe_name = Path(filename).name or "reference.png"
    candidate = directory / safe_name
    if not candidate.exists():
        return safe_name
    stem = Path(safe_name).stem or "reference"
    suffix = Path(safe_name).suffix
    index = 2
    while True:
        unique_name = f"{stem}_{index}{suffix}"
        if not (directory / unique_name).exists():
            return unique_name
        index += 1


def bind_reference_image(cards: list[Any], filename: str, url: str, binding: dict[str, str]) -> None:
    enabled = binding.get("enabled", "true").lower() != "false"
    if not enabled:
        return
    target_name = binding.get("character", "").strip()
    ref_type = binding.get("type", "").strip()
    note = binding.get("note", "").strip()
    value = url
    if ref_type or note:
        meta = "；".join(item for item in [ref_type, note] if item)
        value = f"{url} ({meta})"
    if target_name:
        for card in cards:
            if card.name == target_name:
                card.reference_images.append(value)
                return
    stem = Path(filename).stem.lower()
    for card in cards:
        names = [card.name, *card.aliases]
        if any(name and name.lower() in stem for name in names):
            card.reference_images.append(value)
            return
    if len(cards) == 1:
        cards[0].reference_images.append(value)
