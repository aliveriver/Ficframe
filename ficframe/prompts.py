from __future__ import annotations

from .character_diff import difference_rules_for_names
from .models import CharacterCard, Scene
from .style import DEFAULT_STYLE
from .text_utils import compact


CAMERA_BY_TYPE = {
    "双人情绪特写": "close-up two-shot, shallow depth of field",
    "双人对话中景": "medium two-shot, eye-level camera",
    "多人关系中景": "medium group shot, eye-level camera",
    "剧情动作瞬间": "dynamic medium shot, decisive moment, slight motion blur",
    "环境氛围图": "wide cinematic shot with characters integrated into the environment",
    "单人氛围图": "single-character portrait, quiet cinematic framing",
}

COMPOSITION_BY_TYPE = {
    "双人情绪特写": "两人距离很近，表情和手部动作是画面中心",
    "双人对话中景": "人物分居画面两侧，中间保留情绪张力",
    "多人关系中景": "多名角色形成清晰的三角或层次构图，每个人都有独立轮廓、动作和视线方向",
    "剧情动作瞬间": "动作发生在画面中央，装置警报或道具作为视觉焦点",
    "环境氛围图": "环境占主要面积，人物较小但情绪清晰",
    "单人氛围图": "角色位于三分线附近，背景服务于情绪",
}


def character_prompt(names: list[str], cards: list[CharacterCard]) -> str:
    by_name = {card.name: card for card in cards}
    prompts = []
    for index, name in enumerate(names, start=1):
        card = by_name.get(name)
        if card:
            prompt = f"Character {index}: {card.prompt_en}"
            if card.role:
                prompt += f"; role: {card.role}"
            if card.fixed_traits:
                prompt += f"; fixed traits: {'; '.join(card.fixed_traits)}"
            prompts.append(prompt)
            if card.reference_images:
                prompts.append(f"visual reference images for Character {index} {card.name}: {', '.join(card.reference_images)}")
        else:
            prompts.append(f"Character {index}: {name}")
    return "\n".join(prompts)


def relationship_prompt(scene: Scene) -> str:
    if len(scene.characters) >= 3:
        return (
            f"exactly {len(scene.characters)} visible characters, no extra people. "
            "Arrange them with clear separation and readable silhouettes; each character has a distinct pose, expression, and story role."
        )
    if len(scene.characters) == 2:
        return (
            "exactly two visible characters, no extra people. "
            "Keep both characters visually distinct with different posture, gaze direction, and emotional function."
        )
    if len(scene.characters) == 1:
        return "exactly one visible character, no extra people."
    return "no extra people unless explicitly required by the story."


def duplicate_risk_prompt(names: list[str]) -> str:
    if len(names) >= 2:
        return "Each named character must be individually recognizable; avoid duplicate faces, merged bodies, or swapped outfits."
    return ""


def build_positive_prompt(
    scene: Scene,
    cards: list[CharacterCard],
    notes: list[str],
    style: dict | None = None,
    difference_analysis: dict | None = None,
) -> str:
    style = style or DEFAULT_STYLE
    diff_rules = difference_rules_for_names(scene.characters, cards, difference_analysis)
    pieces = [
        style["medium"],
        "",
        "Scene:",
        f"{scene.location}, {scene.time}. {compact(scene.summary, 220)}",
        f"Mood: {', '.join(scene.mood)}.",
        "",
        "Composition:",
        f"{CAMERA_BY_TYPE.get(scene.visual_type, 'cinematic shot')}. {COMPOSITION_BY_TYPE.get(scene.visual_type, 'clear readable composition')}.",
        relationship_prompt(scene),
        duplicate_risk_prompt(scene.characters),
        "\n".join(diff_rules["positive"]),
        "",
        "Characters:",
        character_prompt(scene.characters, cards),
        "",
        "Continuity:",
        "Keep each individual character consistent with their own reference design, age, outfit logic, and body proportions. "
        "For multi-character scenes, do not copy one character's face, hairstyle, clothes, or temperament onto another character.",
    ]
    if notes:
        pieces.append("Continuity notes: " + " | ".join(notes))
    pieces.extend(
        [
            "",
            "Lighting and style:",
            f"{style['lighting']}, {style['palette']}, {style['line']}.",
            "quiet emotional storytelling, professional science fiction atmosphere, detailed character design",
        ]
    )
    return "\n".join(piece for piece in pieces if piece is not None)


def build_negative_prompt(style: dict | None = None) -> str:
    style = style or DEFAULT_STYLE
    return (
        style["negative_prompt"]
        + ", duplicate character, duplicate face, same face between different characters, same hairstyle between twins, "
        "merged characters, wrong character identity, swapped outfits, extra characters, extra people, "
        "romantic exaggeration when not in story, overly dramatic posing, chibi, childlike appearance"
    )


def build_negative_prompt_for_scene(
    scene: Scene,
    cards: list[CharacterCard],
    style: dict | None = None,
    difference_analysis: dict | None = None,
) -> str:
    diff_rules = difference_rules_for_names(scene.characters, cards, difference_analysis)
    pieces = [build_negative_prompt(style)]
    pieces.extend(diff_rules["negative"])
    return ", ".join(piece for piece in pieces if piece)
