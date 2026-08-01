from __future__ import annotations

from .models import CharacterCard, ContinuityState, Scene, Shot
from .style import DEFAULT_STYLE


def initial_state(cards: list[CharacterCard], style: dict | None = None) -> ContinuityState:
    characters = {}
    for card in cards:
        characters[card.name] = {
            "fixed_traits": card.fixed_traits,
            "reference_images": card.reference_images,
            "current_outfit": card.variable_states.get("outfit", "未指定"),
            "current_emotion": card.variable_states.get("emotion", "未指定"),
            "current_props": card.variable_states.get("props", "未指定"),
            "last_seen_scene": None,
            "reference_image": None,
            "seed": None,
        }
    return ContinuityState(characters=characters, scenes=[], style=style or DEFAULT_STYLE)


def notes_for_scene(scene: Scene, state: ContinuityState) -> list[str]:
    notes = []
    for name in scene.characters:
        if name in state.characters:
            data = state.characters[name]
            notes.append(f"{name}：保持 {', '.join(data.get('fixed_traits', []))}")
            notes.append(f"{name} 当前服装/道具不得无故脱离：{data.get('current_outfit')}；{data.get('current_props')}")
    if state.scenes:
        previous = state.scenes[-1]
        notes.append(f"承接上一张图的时间与情绪：{previous.get('time')}，{', '.join(previous.get('mood', []))}")
    return notes


def update_state_from_shot(state: ContinuityState, shot: Shot) -> ContinuityState:
    for name in shot.characters:
        if name in state.characters:
            state.characters[name]["last_seen_scene"] = shot.scene_id
            if "白大褂从肩膀" in shot.source_excerpt or "搭在椅背" in shot.source_excerpt:
                state.characters[name]["current_outfit"] = "白大褂已脱下，夜间休息状态"
            elif "白大褂" in shot.source_excerpt:
                state.characters[name]["current_outfit"] = "白大褂，实验室状态"
            elif "浅米色的毛衣" in shot.source_excerpt:
                state.characters[name]["current_outfit"] = "浅米色毛衣，外套，清晨状态"
            elif "风把她的头发吹" in shot.source_excerpt:
                state.characters[name]["current_outfit"] = "夜间观景台状态，头发被风吹乱"
    state.scenes.append(
        {
            "shot_id": shot.id,
            "scene_id": shot.scene_id,
            "location": shot.location,
            "time": shot.time,
            "mood": shot.mood,
            "characters": shot.characters,
        }
    )
    return state
