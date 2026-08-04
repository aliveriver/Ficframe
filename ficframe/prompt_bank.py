from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import CharacterCard, Scene
from .text_utils import compact


JSON_RULE = "Return JSON only. Do not include Markdown or explanations."


def analyze_reference_visuals(cards: list[CharacterCard], run_dir: Path, provider: Any | None) -> None:
    if not provider:
        return
    for card in cards:
        paths = reference_paths_for_card(card, run_dir)
        if not paths:
            continue
        system = (
            "You are a visual fact extractor for character reference images. "
            "Extract only stable visual facts visible in the supplied images. "
            "Do not invent story, personality, or hidden traits. " + JSON_RULE
        )
        prompt = json.dumps(
            {
                "character_name": card.name,
                "task": "Identify the character's stable visual identity from the reference images.",
                "required_schema": {
                    "stable_visual_traits": ["hair, eyes, face, body proportion, species traits, silhouette"],
                    "outfit_traits": ["stable clothing silhouette, colors, accessories"],
                    "variable_or_uncertain_traits": ["traits that may be image-specific and should not be treated as fixed"],
                    "negative_identity_prompt": "English negative prompt preventing visual drift",
                    "reference_summary": "English concise visual summary",
                },
            },
            ensure_ascii=False,
        )
        try:
            data = json.loads(provider.vision(system, prompt, paths))
        except (RuntimeError, json.JSONDecodeError, TypeError, AttributeError):
            continue
        card.reference_visuals.append(data)


def build_character_prompt_bank(
    cards: list[CharacterCard],
    scenes: list[Scene],
    provider: Any | None,
) -> None:
    if provider:
        if build_prompt_bank_with_llm(cards, scenes, provider):
            return
    build_prompt_bank_locally(cards)


def build_prompt_bank_with_llm(
    cards: list[CharacterCard],
    scenes: list[Scene],
    provider: Any,
) -> bool:
    system = (
        "You are building a reusable Character Prompt Bank for image generation. "
        "Use the character profile text, VLM visual facts, and novel scenes to decide which appearance traits are fixed "
        "and whether each character has appearance/state changes across the story. "
        "The identity_prompt must be reusable across shots unless a listed appearance state says otherwise. "
        "Write image-generation prompt content in English. Character names and proper nouns may remain unchanged. "
        + JSON_RULE
    )
    user = json.dumps(
        {
            "characters": [
                {
                    "name": card.name,
                    "aliases": card.aliases,
                    "role": card.role,
                    "source_text": compact(card.source_text, 2200),
                    "visual_traits": card.visual_traits,
                    "personality_traits": card.personality_traits,
                    "fixed_traits": card.fixed_traits,
                    "variable_states": card.variable_states,
                    "reference_visuals": card.reference_visuals,
                }
                for card in cards
            ],
            "story_scenes": [
                {
                    "id": scene.id,
                    "chapter": scene.chapter,
                    "index": scene.index,
                    "characters": scene.characters,
                    "summary": compact(scene.summary, 220),
                    "text": compact(scene.text, 500),
                }
                for scene in scenes[:80]
            ],
            "required_schema": {
                "characters": [
                    {
                        "name": "string",
                        "identity_prompt": "English reusable fixed character identity prompt",
                        "negative_identity_prompt": "English negative identity prompt",
                        "appearance_states": [
                            {
                                "label": "default / state name",
                                "trigger": "when this state applies in story text",
                                "prompt": "English prompt fragment for current outfit, expression, props, visible injuries, etc.",
                                "scene_ids": ["scene ids where this state appears"],
                            }
                        ],
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    try:
        data = json.loads(provider.text(system, user))
    except (RuntimeError, json.JSONDecodeError, TypeError, AttributeError):
        return False
    by_name = {card.name: card for card in cards}
    changed = False
    for item in data.get("characters", []):
        if not isinstance(item, dict):
            continue
        card = by_name.get(str(item.get("name") or ""))
        if not card:
            continue
        card.identity_prompt = str(item.get("identity_prompt") or card.identity_prompt)
        card.negative_identity_prompt = str(item.get("negative_identity_prompt") or card.negative_identity_prompt)
        states = item.get("appearance_states")
        if isinstance(states, list):
            card.appearance_states = [state for state in states if isinstance(state, dict)]
        changed = True
    if changed:
        for card in cards:
            if not card.identity_prompt:
                fill_local_prompt_bank(card)
    return changed


def build_prompt_bank_locally(cards: list[CharacterCard]) -> None:
    for card in cards:
        fill_local_prompt_bank(card)


def fill_local_prompt_bank(card: CharacterCard) -> None:
    visual_summary = "; ".join(
        compact(str(item.get("reference_summary") or ""), 240)
        for item in card.reference_visuals
        if isinstance(item, dict) and item.get("reference_summary")
    )
    card.identity_prompt = "; ".join(
        item
        for item in [
            card.prompt_en,
            f"reference visual facts: {visual_summary}" if visual_summary else "",
            "reuse this identity across shots unless the story explicitly changes outfit, injury, or visible state",
        ]
        if item
    )
    visual_negative = ", ".join(
        str(item.get("negative_identity_prompt") or "")
        for item in card.reference_visuals
        if isinstance(item, dict) and item.get("negative_identity_prompt")
    )
    card.negative_identity_prompt = ", ".join(
        item
        for item in [
            visual_negative,
            f"{card.name} visual drift, wrong identity, inconsistent face, inconsistent hairstyle, wrong outfit",
        ]
        if item
    )
    if not card.appearance_states:
        card.appearance_states = [
            {
                "label": "default",
                "trigger": "Use unless the story explicitly states a visible appearance change.",
                "prompt": "; ".join(card.variable_states.values()) or "default visible state from character profile",
                "scene_ids": [],
            }
        ]


def reference_paths_for_card(card: CharacterCard, run_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for reference in card.reference_images:
        url = str(reference).split(" (", 1)[0]
        if not url.startswith("/runs/"):
            continue
        parts = url.strip("/").split("/")
        try:
            index = parts.index("references")
        except ValueError:
            continue
        path = run_dir / "references" / parts[index + 1]
        if path.exists():
            paths.append(path)
    return paths
