from __future__ import annotations

from pathlib import Path

from .characters import build_character_cards
from .continuity import initial_state
from .io import read_text, write_json, write_text
from .llm_pipeline import polish_shot_prompt, summarize_scene_with_llm
from .models import to_dict
from .providers import OpenAICompatibleProvider
from .qa import annotate_shots
from .render import render_prompts, render_storyboard
from .segmenter import segment_novel
from .storyboard import build_storyboard


def run_pipeline(
    novel_path: str | Path,
    characters_path: str | Path,
    out_dir: str | Path,
    max_shots: int = 8,
    use_llm: bool = False,
) -> dict:
    novel = read_text(novel_path)
    character_notes = read_text(characters_path)
    cards = build_character_cards(character_notes)
    scenes = segment_novel(novel, cards)
    provider = OpenAICompatibleProvider() if use_llm else None
    if provider:
        scenes = [summarize_scene_with_llm(scene, provider) for scene in scenes]
    state = initial_state(cards)
    shots, state = build_storyboard(scenes, cards, state, max_shots=max_shots)
    annotate_shots(shots, cards)
    if provider:
        shots = [polish_shot_prompt(shot, cards, provider) for shot in shots]

    payload = {
        "characters": to_dict(cards),
        "scenes": to_dict(scenes),
        "shots": to_dict(shots),
        "continuity": to_dict(state),
    }

    out = Path(out_dir)
    write_json(out / "pipeline.json", payload)
    write_json(out / "continuity.json", payload["continuity"])
    write_text(out / "storyboard.md", render_storyboard(shots))
    write_text(out / "prompts.md", render_prompts(shots))
    return payload
