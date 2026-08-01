from __future__ import annotations

from .continuity import notes_for_scene, update_state_from_shot
from .models import CharacterCard, ContinuityState, Scene, Shot
from .prompts import CAMERA_BY_TYPE, COMPOSITION_BY_TYPE, build_negative_prompt, build_positive_prompt
from .text_utils import compact


def scene_to_shot(scene: Scene, cards: list[CharacterCard], state: ContinuityState) -> Shot:
    notes = notes_for_scene(scene, state)
    title = f"{scene.time} · {scene.location} · {scene.visual_type}"
    return Shot(
        id=f"shot_{scene.index:02d}",
        scene_id=scene.id,
        title=title,
        source_excerpt=compact(scene.text, 220),
        characters=scene.characters,
        location=scene.location,
        time=scene.time,
        mood=scene.mood,
        camera=CAMERA_BY_TYPE.get(scene.visual_type, "cinematic shot"),
        composition=COMPOSITION_BY_TYPE.get(scene.visual_type, "清晰稳定构图"),
        visual_goal=scene.summary,
        continuity_notes=notes,
        positive_prompt=build_positive_prompt(scene, cards, notes, state.style),
        negative_prompt=build_negative_prompt(state.style),
    )


def build_storyboard(
    scenes: list[Scene],
    cards: list[CharacterCard],
    state: ContinuityState,
    max_shots: int = 8,
) -> tuple[list[Shot], ContinuityState]:
    selected = sorted(scenes, key=lambda item: (-item.visual_priority, item.index))[:max_shots]
    selected = sorted(selected, key=lambda item: item.index)
    shots: list[Shot] = []
    for scene in selected:
        shot = scene_to_shot(scene, cards, state)
        shots.append(shot)
        update_state_from_shot(state, shot)
    return shots, state
