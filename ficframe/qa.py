from __future__ import annotations

from .models import CharacterCard, Shot


def check_shot(shot: Shot, cards: list[CharacterCard]) -> list[str]:
    notes: list[str] = []
    known = {card.name: card for card in cards}
    if not shot.characters:
        notes.append("未检测到明确角色，建议人工确认是否为纯环境图。")
    for name in shot.characters:
        if name in known:
            card = known[name]
            missing_fixed = [trait for trait in card.fixed_traits if trait not in shot.positive_prompt]
            if missing_fixed:
                notes.append(f"{name} 的固定特征需要在生图后重点检查：{'; '.join(missing_fixed)}")
        elif name != "博士":
            notes.append(f"角色 {name} 没有角色卡，容易发生外貌漂移。")
    if "extra people" not in shot.negative_prompt:
        notes.append("负向 prompt 缺少 extra people，可能生成多余角色。")
    if len(shot.characters) >= 2 and "two-shot" not in shot.positive_prompt and "exactly" not in shot.positive_prompt:
        notes.append("多人画面建议明确 two-shot / group composition。")
    if "consistent character design" not in shot.positive_prompt:
        notes.append("prompt 缺少角色一致性约束。")
    return notes or ["基础检查通过；生成后仍建议用参考图比对脸、服装、道具和人物数量。"]


def annotate_shots(shots: list[Shot], cards: list[CharacterCard]) -> list[Shot]:
    for shot in shots:
        shot.qa_notes = check_shot(shot, cards)
    return shots
