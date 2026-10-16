from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .characters import build_character_cards
from .character_diff import analyze_character_differences
from .continuity import initial_state
from .io import read_text, write_json, write_text
from .llm_pipeline import enhance_character_cards_with_llm, polish_shot_prompt, refine_scenes_with_llm
from .logging_utils import get_logger
from .models import CharacterCard, Shot, to_dict
from .payloads import safe_int
from .providers import OpenAICompatibleProvider
from .prompt_bank import build_character_prompt_bank
from .qa import annotate_shots
from .render import render_prompts, render_storyboard
from .segmenter import segment_novel
from .storyboard import build_storyboard


logger = get_logger("pipeline")


def polish_shots_with_llm(
    shots: list[Shot], cards: list[CharacterCard], provider: OpenAICompatibleProvider,
    concurrency: int = 1, run_id: str = "cli",
) -> list[Shot]:
    """Keep shot order and isolate individual failures in both execution modes."""
    workers = max(1, min(8, safe_int(concurrency, 3)))

    def polish_one(shot: Shot) -> Shot:
        try:
            return polish_shot_prompt(shot, cards, provider, purpose=f"pipeline:{run_id}:polish_shot:{shot.id}")
        except Exception as exc:
            logger.warning("shot polish failed run_id=%s shot_id=%s error=%s", run_id, shot.id, exc)
            shot.qa_notes.append(f"LLM 分镜精修失败，已保留本地 prompt：{exc}")
            return shot

    if workers == 1 or len(shots) <= 1:
        return [polish_one(shot) for shot in shots]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(polish_one, shots))


def build_story_payload(
    novel: str, cards: list[CharacterCard], *, max_shots: int = 8,
    provider: OpenAICompatibleProvider | None = None, run_id: str = "cli",
    llm_concurrency: int = 1, fast_llm: bool = False,
) -> dict[str, Any]:
    """Shared scene-to-storyboard workflow for Web uploads and the CLI."""
    scenes = segment_novel(novel, cards)
    if provider:
        scenes = refine_scenes_with_llm(scenes, cards, provider, purpose=f"pipeline:{run_id}:refine_scenes")
    result = build_character_prompt_bank(cards, scenes, provider, purpose=f"pipeline:{run_id}:prompt_bank")
    logger.info("prompt bank completed run_id=%s mode=%s character_count=%s scene_count=%s",
                run_id, result.mode, len(cards), len(scenes))
    difference_analysis = analyze_character_differences(cards, provider, purpose=f"pipeline:{run_id}:character_diff")
    shots, state = build_storyboard(scenes, cards, initial_state(cards), max_shots=max_shots,
                                    difference_analysis=difference_analysis)
    for shot in shots:
        if shot.source_start is not None and shot.source_end is not None:
            shot.source_text = novel[shot.source_start:shot.source_end]
    annotate_shots(shots, cards)
    if provider:
        shots = polish_shots_with_llm(shots, cards, provider, llm_concurrency, run_id)
    elif fast_llm:
        for shot in shots:
            shot.qa_notes.append("快速 LLM 模式：已跳过逐张 Prompt 精修，可在右侧手动编辑或使用独立 LLM 按钮增强角色。")
    return {"characters": to_dict(cards), "difference_analysis": difference_analysis,
            "scenes": to_dict(scenes), "shots": to_dict(shots), "continuity": to_dict(state)}


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
    payload = build_story_payload(novel, cards, max_shots=max_shots, provider=provider)
    shots = [Shot(**item) for item in payload["shots"]]

    out = Path(out_dir)
    write_json(out / "pipeline.json", payload)
    write_json(out / "continuity.json", payload["continuity"])
    write_text(out / "storyboard.md", render_storyboard(shots))
    write_text(out / "prompts.md", render_prompts(shots))
    return payload
