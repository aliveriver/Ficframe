from __future__ import annotations

from pathlib import Path

from .characters import build_character_cards
from .character_diff import analyze_character_differences
from .continuity import initial_state
from .io import read_text, write_json, write_text
from .llm_pipeline import enhance_character_cards_with_llm, polish_shot_prompt, refine_scenes_with_llm
from .models import to_dict
from .providers import OpenAICompatibleProvider
from .prompt_bank import build_character_prompt_bank
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
    provider = OpenAICompatibleProvider() if use_llm else None
    if provider:
        cards = enhance_character_cards_with_llm(cards, provider)
    scenes = segment_novel(novel, cards)
    if provider:
        scenes = refine_scenes_with_llm(scenes, cards, provider)
    build_character_prompt_bank(cards, scenes, provider)
    difference_analysis = analyze_character_differences(cards, provider)
    state = initial_state(cards)
    shots, state = build_storyboard(scenes, cards, state, max_shots=max_shots, difference_analysis=difference_analysis)
    annotate_shots(shots, cards)
    if provider:
        shots = [polish_shot_prompt(shot, cards, provider) for shot in shots]

    payload = {
        "characters": to_dict(cards),
        "difference_analysis": difference_analysis,
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
