"""Text-only storyboard guidance; never delete narrative text to remove style."""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .models import Shot

STYLE_UPDATE_MESSAGE = "画风已调整，当前 Prompt 可能仍含旧画风。建议点击「LLM 重建」更新；会基于当前 Prompt 保留手工修改，并归档更新前版本。"

# Validation signals only: mixed sections must be rewritten, never sliced out.
STYLE_SECTION = re.compile(r"(?:^|[\n.!?]\s*)(?:lighting\s+and\s+style|style(?:\s+guide|\s+details|\s+priority)?|画风|绘画风格)\s*:", re.I)
RENDERING = re.compile(
    r"\b(?:chibi|cel[- ]shad(?:ing|ed)|flat\s+colou?rs?|watercolou?r|oil\s+painting|"
    r"painterly|photorealis\w*|anime\s+style|manga\s+(?:style|lines)|linework|"
    r"cross[- ]hatching|pixel\s+art|3d\s+render\w*)\b", re.I)


def text_only_guides(guides: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(guides)
    for guide in result.values():
        if guide.get("reference_mode") != "image":
            continue
        context = {key: guide.pop(key, None) for key in ("positive", "negative", "structured")}
        guide.update(image_indices=[], guidance_mode="compatibility_only")
        guide["compatibility_context"] = {key: value for key, value in context.items() if value}
    return result


def style_neutral_errors(data: dict[str, Any]) -> list[str]:
    errors = []
    if not isinstance(data.get("positive_prompt"), str) or not data["positive_prompt"].strip():
        errors.append("Return a complete nonempty positive_prompt; do not fall back to the old styled prompt.")
    if not isinstance(data.get("negative_prompt"), str):
        errors.append("Return negative_prompt as a string (it may be empty); do not inherit old style exclusions.")
    positive = str(data.get("positive_prompt") or "")
    negative = str(data.get("negative_prompt") or "")
    if STYLE_SECTION.search(positive):
        errors.append("Move physical lighting, actions and other scene facts into their own sections; omit Style / Lighting and style sections.")
    # A watercolor on the wall or a chibi doll can be a scene prop. Do not
    # reject narrative occurrences merely because they name an art medium.
    if any(RENDERING.fullmatch(term.strip()) for term in re.split(r"[,;\n]", negative)):
        errors.append("Remove drawing/rendering definitions and style exclusions from both prompts, including chibi, flat colors and cel shading; preserve physical scene facts.")
    return errors


def effective_style(shot: Shot) -> dict[str, Any]:
    return deepcopy(shot.style_preset_snapshot) if shot.style_preset_mode != "none" else {}


def prompt_style_pending(shot: Shot) -> bool:
    return shot.prompt_style_snapshot is not None and shot.prompt_style_snapshot != effective_style(shot)


def remember_prompt_style(shot: Shot) -> Shot:
    shot.prompt_style_snapshot = effective_style(shot)
    shot.prompt_generation_baseline = {"positive_prompt": shot.positive_prompt, "negative_prompt": shot.negative_prompt}
    return shot
