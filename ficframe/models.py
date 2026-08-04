from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class CharacterCard:
    name: str
    aliases: list[str] = field(default_factory=list)
    role: str = ""
    source_text: str = ""
    manual: bool = False
    visual_traits: list[str] = field(default_factory=list)
    personality_traits: list[str] = field(default_factory=list)
    fixed_traits: list[str] = field(default_factory=list)
    variable_states: dict[str, str] = field(default_factory=dict)
    relationships: dict[str, str] = field(default_factory=dict)
    reference_images: list[str] = field(default_factory=list)
    reference_visuals: list[dict[str, Any]] = field(default_factory=list)
    identity_prompt: str = ""
    negative_identity_prompt: str = ""
    appearance_states: list[dict[str, Any]] = field(default_factory=list)
    prompt_cn: str = ""
    prompt_en: str = ""


@dataclass
class Scene:
    id: str
    chapter: str
    index: int
    text: str
    summary: str
    characters: list[str]
    location: str
    time: str
    mood: list[str]
    visual_type: str
    visual_priority: int


@dataclass
class Shot:
    id: str
    scene_id: str
    title: str
    source_excerpt: str
    characters: list[str]
    location: str
    time: str
    mood: list[str]
    camera: str
    composition: str
    visual_goal: str
    continuity_notes: list[str]
    positive_prompt: str
    negative_prompt: str
    qa_notes: list[str] = field(default_factory=list)
    image_path: str | None = None
    image_url: str | None = None
    image_versions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ContinuityState:
    characters: dict[str, dict[str, Any]] = field(default_factory=dict)
    scenes: list[dict[str, Any]] = field(default_factory=list)
    style: dict[str, Any] = field(default_factory=dict)


def to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    return value
