from __future__ import annotations

from .continuity import notes_for_scene, update_state_from_shot
from .models import CharacterCard, ContinuityState, Scene, Shot
from .prompts import CAMERA_BY_TYPE, COMPOSITION_BY_TYPE, build_negative_prompt, build_positive_prompt
from .text_utils import compact


def scene_to_shot(scene: Scene, cards: list[CharacterCard], state: ContinuityState, shot_number: int) -> Shot:
    notes = notes_for_scene(scene, state)
    title = f"{scene.time} - {scene.location} - {scene.visual_type}"
    return Shot(
        id=f"shot_{shot_number:02d}",
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


def pick_evenly_from_group(group: list[Scene], count: int) -> list[Scene]:
    if count <= 0:
        return []
    if count >= len(group):
        return group[:]

    picked: dict[int, Scene] = {}
    total = len(group)
    for bucket_index in range(count):
        start = bucket_index * total // count
        end = (bucket_index + 1) * total // count
        bucket = group[start:end] or group[start : start + 1]
        center = (start + max(end - 1, start)) / 2
        best = max(
            enumerate(bucket, start=start),
            key=lambda pair: (pair[1].visual_priority, -abs(pair[0] - center), -pair[1].index),
        )[1]
        picked[best.index] = best
    return sorted(picked.values(), key=lambda item: item.index)


def allocate_by_chapter(groups: list[list[Scene]], max_shots: int) -> list[int]:
    if max_shots <= 0:
        return [0 for _ in groups]
    if max_shots < len(groups):
        return []

    total_scenes = sum(len(group) for group in groups)
    quotas = [1 for _ in groups]
    remaining = max_shots - len(groups)
    fractions: list[tuple[float, int]] = []

    for index, group in enumerate(groups):
        raw_quota = len(group) * max_shots / total_scenes
        extra = max(0, int(raw_quota) - 1)
        extra = min(extra, len(group) - quotas[index])
        quotas[index] += extra
        remaining -= extra
        fractions.append((raw_quota - int(raw_quota), index))

    for _, index in sorted(fractions, reverse=True):
        if remaining <= 0:
            break
        if quotas[index] < len(groups[index]):
            quotas[index] += 1
            remaining -= 1

    while remaining > 0:
        changed = False
        for index, group in enumerate(groups):
            if quotas[index] < len(group):
                quotas[index] += 1
                remaining -= 1
                changed = True
                if remaining <= 0:
                    break
        if not changed:
            break

    return quotas


def select_balanced_scenes(scenes: list[Scene], max_shots: int) -> list[Scene]:
    ordered = sorted(scenes, key=lambda item: item.index)
    if max_shots <= 0:
        return []
    if len(ordered) <= max_shots:
        return ordered

    groups: list[list[Scene]] = []
    for scene in ordered:
        if not groups or groups[-1][0].chapter != scene.chapter:
            groups.append([])
        groups[-1].append(scene)

    quotas = allocate_by_chapter(groups, max_shots)
    if quotas:
        selected: list[Scene] = []
        for group, quota in zip(groups, quotas):
            selected.extend(pick_evenly_from_group(group, quota))
        return sorted(selected, key=lambda item: item.index)[:max_shots]

    return pick_evenly_from_group(ordered, max_shots)


def build_storyboard(
    scenes: list[Scene],
    cards: list[CharacterCard],
    state: ContinuityState,
    max_shots: int = 8,
) -> tuple[list[Shot], ContinuityState]:
    selected = select_balanced_scenes(scenes, max_shots)
    shots: list[Shot] = []
    for shot_number, scene in enumerate(selected, start=1):
        shot = scene_to_shot(scene, cards, state, shot_number)
        shots.append(shot)
        update_state_from_shot(state, shot)
    return shots, state
