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
    "双人情绪特写": "close two-character framing; faces and hands are the emotional focus",
    "双人对话中景": "two characters staged on opposite sides of the frame, leaving emotional tension in the space between them",
    "多人关系中景": "clear triangular or layered group composition; every character has a readable silhouette, action, and gaze direction",
    "剧情动作瞬间": "the key action happens at the center of the frame; the device, warning light, prop, or gesture is the visual focus",
    "环境氛围图": "the environment occupies most of the frame while the character remains emotionally readable",
    "单人氛围图": "the character is placed near a rule-of-thirds point, with the background supporting the emotion",
}

EN_LABELS = {
    "实验室": "laboratory",
    "走廊": "corridor",
    "休息区": "rest area",
    "观景台": "observation deck",
    "宿舍门口": "dormitory doorway",
    "未明确地点": "unspecified location",
    "清晨": "early morning",
    "傍晚": "dusk",
    "下午": "afternoon",
    "夜晚": "night",
    "未明确时间": "unspecified time",
    "温柔": "gentle",
    "亲密": "intimate",
    "不安": "uneasy",
    "疲惫": "tired",
    "希望": "hopeful",
    "平静": "calm",
}


def character_prompt(names: list[str], cards: list[CharacterCard]) -> str:
    by_name = {card.name: card for card in cards}
    prompts = []
    for index, name in enumerate(names, start=1):
        card = by_name.get(name)
        if card:
            prompt = f"Character {index}: {card.identity_prompt or card.prompt_en}"
            if card.source_text:
                prompt += f"; source profile notes: {compact(card.source_text, 420)}"
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
        f"{en_label(scene.location)}, {en_label(scene.time)}. Story moment from source text: {compact(scene.summary, 260)}",
        f"Mood: {', '.join(en_label(item) for item in scene.mood)}.",
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
            "quiet emotional storytelling, professional science fiction atmosphere, detailed character design, high quality anime light novel illustration",
        ]
    )
    return "\n".join(piece for piece in pieces if piece is not None)


def en_label(value: str) -> str:
    return EN_LABELS.get(value, value)


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
    by_name = {card.name: card for card in cards}
    for name in scene.characters:
        card = by_name.get(name)
        if card and card.negative_identity_prompt:
            pieces.append(card.negative_identity_prompt)
    return ", ".join(piece for piece in pieces if piece)
