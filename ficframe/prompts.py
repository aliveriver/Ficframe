from __future__ import annotations

from .models import CharacterCard, Scene
from .style import DEFAULT_STYLE
from .text_utils import compact


CAMERA_BY_TYPE = {
    "双人情绪特写": "close-up two-shot, shallow depth of field",
    "双人对话中景": "medium two-shot, eye-level camera",
    "剧情动作瞬间": "dynamic medium shot, decisive moment, slight motion blur",
    "环境氛围图": "wide cinematic shot with characters integrated into the environment",
    "单人氛围图": "single-character portrait, quiet cinematic framing",
}

COMPOSITION_BY_TYPE = {
    "双人情绪特写": "两人距离很近，表情和手部动作是画面中心",
    "双人对话中景": "人物分居画面两侧，中间保留情绪张力",
    "剧情动作瞬间": "动作发生在画面中央，装置警报或道具作为视觉焦点",
    "环境氛围图": "环境占主要面积，人物较小但情绪清晰",
    "单人氛围图": "角色位于三分线附近，背景服务于情绪",
}


def character_prompt(names: list[str], cards: list[CharacterCard]) -> str:
    by_name = {card.name: card for card in cards}
    prompts = []
    for name in names:
        card = by_name.get(name)
        if card:
            prompts.append(card.prompt_en)
            if card.reference_images:
                prompts.append(f"visual reference images for {card.name}: {', '.join(card.reference_images)}")
        elif name == "博士":
            prompts.append("Doctor from Rhodes Island, calm composed figure, dark coat, face partly obscured, gentle restraint")
        else:
            prompts.append(name)
    return "; ".join(prompts)


def build_positive_prompt(scene: Scene, cards: list[CharacterCard], notes: list[str], style: dict | None = None) -> str:
    style = style or DEFAULT_STYLE
    pieces = [
        style["medium"],
        character_prompt(scene.characters, cards),
        f"scene: {scene.location}, {scene.time}",
        f"mood: {', '.join(scene.mood)}",
        f"story moment: {compact(scene.summary, 160)}",
        f"camera: {CAMERA_BY_TYPE.get(scene.visual_type, 'cinematic shot')}",
        f"composition: {COMPOSITION_BY_TYPE.get(scene.visual_type, 'clear readable composition')}",
        f"lighting and palette: {style['lighting']}, {style['palette']}",
        "consistent character design, same face, same body proportions, coherent outfit continuity",
    ]
    if len(scene.characters) >= 2:
        pieces.append(f"exactly {len(scene.characters)} visible characters, no extra people, clear relationship staging")
    if notes:
        pieces.append("continuity constraints: " + " | ".join(notes))
    return ", ".join(piece for piece in pieces if piece)


def build_negative_prompt(style: dict | None = None) -> str:
    style = style or DEFAULT_STYLE
    return style["negative_prompt"]
