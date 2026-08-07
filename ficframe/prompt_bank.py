from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any

from .logging_utils import get_logger
from .models import CharacterCard, Scene
from .text_utils import compact, unique_keep_order


JSON_RULE = "Return JSON only. Do not include Markdown or explanations."
logger = get_logger("prompt_bank")


@dataclass(frozen=True)
class PromptBankBuildResult:
    mode: str
    llm_error: str | None = None


def analyze_reference_visuals(cards: list[CharacterCard], run_dir: Path, provider: Any | None, purpose: str = "pipeline:vlm_reference_visuals") -> None:
    if not provider:
        return
    for card in cards:
        paths = reference_paths_for_card(card, run_dir)
        if not paths:
            continue
        system = (
            "You are a character identity prompt builder for image generation. "
            "Use only stable visual facts visible in the supplied reference images. "
            "Build a reusable identity prompt and a negative identity prompt directly from the images. "
            "Keep identity_prompt and negative_identity_prompt separate: identity_prompt must contain only visible positive facts, and negative_identity_prompt must contain only visual negatives or drift blockers. "
            "Use the supplied character_profile only as disambiguation context for visible fixed props, weapons, accessories, outfit names, and known character design. "
            "If the image shows a held object and the profile explicitly says the character carries a staff or wand, prefer staff or wand over sword or katana unless the image clearly contradicts it. "
            "If a prop or weapon identity is still uncertain, describe its visible shape instead of guessing a named item, and list the uncertainty in variable_or_uncertain_traits. "
            "Do not invent story, personality, hidden traits, brand names, race, age, powers, or relationships. "
            "Write prompt content in English. " + JSON_RULE
        )
        prompt = json.dumps(
            {
                "character_name": card.name,
                "character_profile": character_profile_for_review(card),
                "task": "Create a reference-image grounded prompt bank for this character.",
                "profile_usage_rules": [
                    "Use character_profile to disambiguate visible props/weapons/outfit when the image is ambiguous.",
                    "Do not add profile-only details that are not visible in the reference images.",
                    "If profile and image conflict on a visible fixed prop, mention the profile-backed name and keep visible shape/color details.",
                ],
                "required_schema": {
                    "identity_prompt": "English reusable fixed identity prompt from reference images only. Include only visible positive facts: hair, eyes, face, body proportion, species traits, silhouette, baseline outfit, colors, key accessories.",
                    "negative_identity_prompt": "English comma-separated negative prompt preventing visual drift. Include only negatives such as wrong hair, wrong eyes, wrong face, wrong outfit, invented accessories, wrong body type, wrong species traits.",
                    "appearance_states": [
                        {
                            "label": "default",
                            "trigger": "Use unless story explicitly changes visible appearance.",
                            "prompt": "English visible state prompt fragment from the reference image baseline.",
                            "scene_ids": [],
                        }
                    ],
                    "stable_visual_traits": ["hair, eyes, face, body proportion, species traits, silhouette"],
                    "outfit_traits": ["stable clothing silhouette, colors, accessories"],
                    "variable_or_uncertain_traits": ["traits that may be image-specific and should not be treated as fixed"],
                    "reference_summary": "English concise visual summary",
                },
                "output_rules": [
                    "Return exactly one JSON object.",
                    "Do not wrap the JSON in markdown or prose.",
                    "Do not add commentary before or after the JSON.",
                    "Do not mix positive facts into negative_identity_prompt.",
                ],
            },
            ensure_ascii=False,
        )
        raw = ""
        mode = "json"
        try:
            raw = provider.vision(system, prompt, paths, purpose=f"{purpose}:{card.name}")
            data = parse_json_response(raw)
        except (RuntimeError, json.JSONDecodeError, TypeError, AttributeError) as exc:
            data = parse_visual_fact_prose(raw)
            if data:
                mode = "prose"
                logger.warning(
                    "vlm reference analysis recovered from prose character=%s image_count=%s error=%s raw_preview=%s",
                    card.name,
                    len(paths),
                    exc,
                    compact(raw, 240),
                )
            else:
                logger.warning(
                    "vlm reference analysis skipped character=%s image_count=%s error=%s raw_preview=%s",
                    card.name,
                    len(paths),
                    exc,
                    compact(raw, 240),
                )
                continue
        reviewed = review_reference_visual_prompt_bank(card, data, provider, purpose=f"{purpose}:{card.name}:llm_review")
        if reviewed:
            data = reviewed
            mode = f"{mode}+llm_review"
        card.reference_visuals.append(data)
        logger.info("vlm reference analysis applied character=%s image_count=%s mode=%s keys=%s", card.name, len(paths), mode, list(data.keys())[:8])


def build_character_prompt_bank(
    cards: list[CharacterCard],
    scenes: list[Scene],
    provider: Any | None,
    purpose: str = "llm:prompt_bank",
) -> PromptBankBuildResult:
    baselines = {card.name: local_prompt_bank_values(card) for card in cards}
    apply_prompt_bank_values(cards, baselines)
    if baselines and all(str(values.get("vlm_identity_prompt") or "") for values in baselines.values()):
        mode = "vlm_llm_reviewed" if any(
            any(isinstance(item, dict) and item.get("llm_reviewed") for item in card.reference_visuals)
            for card in cards
        ) else "vlm"
        return PromptBankBuildResult(mode=mode)
    if provider:
        success, error = build_prompt_bank_with_llm(cards, scenes, provider, baselines, purpose=purpose)
        if success:
            mode = "llm_guarded" if error else "llm"
            return PromptBankBuildResult(mode=mode, llm_error=error)
        apply_prompt_bank_values(cards, baselines)
        return PromptBankBuildResult(mode="local_fallback", llm_error=error)
    return PromptBankBuildResult(mode="local")


def review_reference_visual_prompt_bank(card: CharacterCard, data: dict[str, Any], provider: Any, purpose: str) -> dict[str, Any]:
    if not getattr(getattr(provider, "config", None), "llm", None) or not provider.config.llm.api_key:
        return data
    identity = normalize_prompt_text(str(data.get("identity_prompt") or ""))
    negative = normalize_prompt_text(str(data.get("negative_identity_prompt") or ""))
    if not identity and not negative:
        return data
    try:
        reviewed_identity = review_vlm_identity_prompt(card, data, provider, purpose=f"{purpose}:identity")
    except (RuntimeError, json.JSONDecodeError, TypeError, AttributeError) as exc:
        reviewed_identity = identity
        logger.warning("vlm identity review failed character=%s error=%s", card.name, exc)
    try:
        reviewed_negative = review_vlm_negative_prompt(card, data, reviewed_identity, provider, purpose=f"{purpose}:negative")
    except (RuntimeError, json.JSONDecodeError, TypeError, AttributeError) as exc:
        reviewed_negative = negative
        logger.warning("vlm negative review failed character=%s error=%s", card.name, exc)
    try:
        reviewed_states = build_vlm_appearance_states(card, reviewed_identity, data, provider, purpose=f"{purpose}:states")
    except (RuntimeError, json.JSONDecodeError, TypeError, AttributeError) as exc:
        reviewed_states = normalize_appearance_states(data.get("appearance_states")) or default_appearance_states(reviewed_identity)
        logger.warning("vlm appearance state review failed character=%s error=%s", card.name, exc)

    result = dict(data)
    result["identity_prompt"] = reviewed_identity or identity
    result["negative_identity_prompt"] = join_prompt_parts([reviewed_negative or negative])
    result["appearance_states"] = reviewed_states
    result["llm_reviewed"] = True
    return result


def review_vlm_identity_prompt(card: CharacterCard, data: dict[str, Any], provider: Any, purpose: str) -> str:
    system = (
        "You are auditing a VLM-generated character identity prompt for image generation. "
        "Use the character profile as a canonical consistency source. The VLM draft describes what it thinks it saw, but it may misname fixed props, weapons, accessories, or outfit details. "
        "When the VLM draft conflicts with explicit profile facts about fixed visible design, named outfit, or canonical props, correct the prompt to match the profile. For example, if the profile says staff/wand and the VLM says katana/sword, use staff/wand. "
        "Preserve concrete non-conflicting visible traits from the VLM draft, but remove instructions, reasoning, schema labels, lore, personality, uncertainty, and unsupported story facts. "
        "Return a clean English identity_prompt containing only positive visible facts: hair, eyes, face, body/silhouette, outfit, colors, and key accessories. "
        "Do not add new details except profile-backed corrections of VLM mistakes. " + JSON_RULE
    )
    user = json.dumps(
        {
            "character_name": card.name,
            "character_profile": character_profile_for_review(card),
            "vlm_identity_prompt": data.get("identity_prompt", ""),
            "stable_visual_traits": data.get("stable_visual_traits", []),
            "outfit_traits": data.get("outfit_traits", []),
            "reference_summary": data.get("reference_summary", ""),
            "required_schema": {"identity_prompt": "clean English positive visible prompt only"},
        },
        ensure_ascii=False,
    )
    parsed = parse_json_response(provider.text(system, user, purpose=purpose))
    return normalize_prompt_text(str(parsed.get("identity_prompt") or ""))


def review_vlm_negative_prompt(card: CharacterCard, data: dict[str, Any], identity_prompt: str, provider: Any, purpose: str) -> str:
    system = (
        "You are auditing a negative identity prompt for image generation. "
        "Return only comma-separated negative constraints that prevent visual drift. "
        "Use the character profile and audited identity_prompt to identify VLM mistakes. If the VLM misidentified a profile-fixed prop or weapon, add the wrong item as a negative constraint. For example, if the profile/audited identity says staff or wand but the VLM says katana or sword, include katana, sword, wrong weapon. "
        "Keep wrong hair/eyes/face/outfit/colors/accessories/body type/style terms. Remove positive descriptions, labels, explanations, reasoning, and anything that contradicts the audited identity_prompt. "
        "Do not invent highly specific negatives unless they directly guard the profile-backed identity. " + JSON_RULE
    )
    user = json.dumps(
        {
            "character_name": card.name,
            "character_profile": character_profile_for_review(card),
            "audited_identity_prompt": identity_prompt,
            "vlm_identity_prompt": data.get("identity_prompt", ""),
            "vlm_negative_identity_prompt": data.get("negative_identity_prompt", ""),
            "existing_negative_identity_prompt": card.negative_identity_prompt,
            "required_schema": {"negative_identity_prompt": "clean English comma-separated negatives only"},
        },
        ensure_ascii=False,
    )
    parsed = parse_json_response(provider.text(system, user, purpose=purpose))
    return join_prompt_parts([str(parsed.get("negative_identity_prompt") or "")])


def build_vlm_appearance_states(card: CharacterCard, identity_prompt: str, data: dict[str, Any], provider: Any, purpose: str) -> list[dict[str, Any]]:
    system = (
        "You are generating appearance_states JSON for a reusable character Prompt Bank. "
        "Use the audited identity_prompt as the default visible state. "
        "Use the character profile to preserve profile-corrected fixed props, weapons, outfit names, and visible state changes. "
        "Return appearance_states only. The default state must be a clean English visible prompt fragment, not instructions, analysis, personality, relationships, backstory, motivation, fate, beliefs, or plot summary. "
        "Only add extra states if the character profile explicitly describes visible alternate outfits, injuries, props, or transformations. "
        "Do not invent story changes or internal states. " + JSON_RULE
    )
    user = json.dumps(
        {
            "character_name": card.name,
            "character_profile": character_profile_for_review(card),
            "audited_identity_prompt": identity_prompt,
            "profile_variable_states": card.variable_states,
            "vlm_appearance_states": data.get("appearance_states", []),
            "required_schema": {
                "appearance_states": [
                    {
                        "label": "default",
                        "trigger": "Use unless story explicitly changes visible appearance.",
                        "prompt": "clean English visible state prompt fragment",
                        "scene_ids": [],
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    parsed = parse_json_response(provider.text(system, user, purpose=purpose))
    states = visual_appearance_states(normalize_appearance_states(parsed.get("appearance_states")))
    return states or default_appearance_states(identity_prompt)


def character_profile_for_review(card: CharacterCard) -> dict[str, Any]:
    return {
        "name": card.name,
        "aliases": card.aliases,
        "role": card.role,
        "prompt_en": card.prompt_en,
        "source_text": compact(card.source_text, 3000),
        "visual_traits": card.visual_traits,
        "fixed_traits": card.fixed_traits,
        "variable_states": card.variable_states,
        "relationships": card.relationships,
    }


def default_appearance_states(identity_prompt: str) -> list[dict[str, Any]]:
    prompt = normalize_prompt_text(identity_prompt) or "default visible state from reference images"
    return [
        {
            "label": "default",
            "trigger": "Use unless story explicitly changes visible appearance.",
            "prompt": prompt,
            "scene_ids": [],
        }
    ]


def build_prompt_bank_with_llm(
    cards: list[CharacterCard],
    scenes: list[Scene],
    provider: Any,
    baselines: dict[str, dict[str, Any]],
    purpose: str = "llm:prompt_bank",
) -> tuple[bool, str | None]:
    system = (
        "You are building a reusable Character Prompt Bank for image generation. "
        "Use the provided local_baseline as the source of truth. "
        "If local_baseline.vlm_identity_prompt is present, keep it unchanged as the canonical identity prompt. "
        "Do not replace VLM identity with lore or source-text guesses. "
        "Reference-image facts are canonical: preserve visible hair, eyes, face, species/body traits, outfit silhouette, colors, and accessories exactly as described. "
        "Do not invent age, race, hairstyle, clothing, props, personality, relationships, powers, locations, or plot events that are not present in the inputs. "
        "Use novel scenes only to add appearance_states for visible temporary changes; never rewrite fixed identity from scenes. "
        "If evidence is weak, keep the local_baseline wording instead of adding detail. "
        "Keep identity_prompt, negative_identity_prompt, and appearance_states as separate fields. Do not move positive facts into negative_identity_prompt. "
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
                    "source_text": card.source_text,
                    "visual_traits": card.visual_traits,
                    "personality_traits": card.personality_traits,
                    "fixed_traits": card.fixed_traits,
                    "variable_states": card.variable_states,
                    "reference_visuals": card.reference_visuals,
                    "local_baseline": baselines.get(card.name, {}),
                    "current_identity_prompt": card.identity_prompt,
                    "current_negative_identity_prompt": card.negative_identity_prompt,
                    "current_appearance_states": card.appearance_states,
                }
                for card in cards
            ],
            "story_scenes": [
                {
                    "id": scene.id,
                    "chapter": scene.chapter,
                    "index": scene.index,
                    "characters": scene.characters,
                    "summary": scene.summary,
                    "text": scene.text,
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
        data = parse_json_response(provider.text(system, user, purpose=purpose))
    except (RuntimeError, json.JSONDecodeError, TypeError, AttributeError) as exc:
        logger.warning("prompt bank llm failed purpose=%s character_count=%s scene_count=%s error=%s", purpose, len(cards), len(scenes), exc)
        return False, str(exc)
    by_name = {card.name: card for card in cards}
    changed = False
    rejected: list[str] = []
    for item in data.get("characters", []):
        if not isinstance(item, dict):
            continue
        card = by_name.get(str(item.get("name") or ""))
        if not card:
            continue
        accepted, reason = validate_llm_prompt_bank_item(card, item, baselines.get(card.name, {}))
        if not accepted:
            rejected.append(f"{card.name}: {reason}")
            continue
        baseline = baselines.get(card.name, {})
        card.identity_prompt = merge_identity_prompt(str(item.get("identity_prompt") or ""), baseline)
        card.negative_identity_prompt = merge_negative_prompt(str(item.get("negative_identity_prompt") or ""), baseline)
        if baseline.get("vlm_identity_prompt"):
            states = baseline.get("appearance_states", [])
        else:
            states = normalize_appearance_states(item.get("appearance_states")) or baseline.get("appearance_states", [])
        if isinstance(states, list):
            card.appearance_states = states
        changed = True
    logger.info(
        "prompt bank llm applied purpose=%s changed=%s character_count=%s reference_visual_count=%s",
        purpose,
        changed,
        len(cards),
        sum(len(card.reference_visuals) for card in cards),
    )
    if changed:
        for card in cards:
            if not card.identity_prompt:
                fill_local_prompt_bank(card)
    if not changed:
        reason = "; ".join(rejected[:4]) if rejected else "LLM response did not include matching character Prompt Bank data"
        return False, reason
    if rejected:
        logger.warning("prompt bank llm partially rejected purpose=%s rejected=%s", purpose, rejected[:8])
        return True, "Some LLM Prompt Bank items failed reference/baseline validation; kept local rules: " + "; ".join(rejected[:4])
    return True, None


def build_prompt_bank_locally(cards: list[CharacterCard]) -> None:
    for card in cards:
        fill_local_prompt_bank(card)


def fill_local_prompt_bank(card: CharacterCard) -> None:
    values = local_prompt_bank_values(card)
    card.identity_prompt = str(values["identity_prompt"])
    card.negative_identity_prompt = str(values["negative_identity_prompt"])
    if not card.appearance_states:
        card.appearance_states = list(values["appearance_states"])


def apply_prompt_bank_values(cards: list[CharacterCard], values_by_name: dict[str, dict[str, Any]]) -> None:
    for card in cards:
        values = values_by_name.get(card.name)
        if not values:
            continue
        card.identity_prompt = str(values["identity_prompt"])
        card.negative_identity_prompt = str(values["negative_identity_prompt"])
        card.appearance_states = list(values["appearance_states"])


def local_prompt_bank_values(card: CharacterCard) -> dict[str, Any]:
    vlm_identity = join_identity_parts(
        str(item.get("identity_prompt") or "")
        for item in card.reference_visuals
        if isinstance(item, dict) and item.get("identity_prompt")
    )
    visual_summary = "; ".join(
        compact(str(item.get("reference_summary") or ""), 240)
        for item in card.reference_visuals
        if isinstance(item, dict) and item.get("reference_summary")
    )
    stable_visual_traits = flatten_reference_values(card.reference_visuals, "stable_visual_traits")
    outfit_traits = flatten_reference_values(card.reference_visuals, "outfit_traits")
    positive_fallback = join_identity_parts(
        [
            f"reference-image identity for {card.name}" if card.name else "reference-image identity",
            f"visible traits: {', '.join(stable_visual_traits[:12])}" if stable_visual_traits else "",
            f"outfit and accessories: {', '.join(outfit_traits[:10])}" if outfit_traits else "",
            f"reference visual facts: {visual_summary}" if visual_summary else "",
        ]
    )
    identity_prompt = vlm_identity or card.identity_prompt or card.prompt_en or positive_fallback
    if identity_prompt:
        identity_prompt = join_identity_parts([identity_prompt])

    visual_negative = join_prompt_parts(
        str(item.get("negative_identity_prompt") or "")
        for item in card.reference_visuals
        if isinstance(item, dict) and item.get("negative_identity_prompt")
    )
    negative_identity_prompt = join_prompt_parts(
        [
            visual_negative,
            card.negative_identity_prompt,
            f"{card.name} visual drift, wrong identity, inconsistent face, inconsistent hairstyle, wrong outfit",
            "invented reference details, invented clothing, invented accessories, unsupported design changes",
        ]
    )
    existing_states = visual_appearance_states(card.appearance_states)
    vlm_states = first_vlm_appearance_states(card.reference_visuals)
    fallback_state_prompt = first_visual_text(
        [
            *card.variable_states.values(),
            *card.visual_traits,
            *card.fixed_traits,
            identity_prompt,
        ]
    ) or "default visible state from character profile"
    appearance_states = existing_states or vlm_states or [
        {
            "label": "default",
            "trigger": "Use unless the story explicitly states a visible appearance change.",
            "prompt": fallback_state_prompt,
            "scene_ids": [],
        }
    ]
    return {
        "identity_prompt": identity_prompt,
        "negative_identity_prompt": negative_identity_prompt,
        "appearance_states": appearance_states,
        "reference_terms": stable_visual_traits + outfit_traits + ([visual_summary] if visual_summary else []),
        "vlm_identity_prompt": vlm_identity,
    }


def flatten_reference_values(reference_visuals: list[dict[str, Any]], key: str) -> list[str]:
    values: list[str] = []
    for item in reference_visuals:
        if not isinstance(item, dict):
            continue
        raw = item.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(str(value) for value in raw if value)
    return [normalize_prompt_text(value) for value in values if value]


def first_vlm_appearance_states(reference_visuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in reference_visuals:
        if isinstance(item, dict):
            states = visual_appearance_states(normalize_appearance_states(item.get("appearance_states")))
            if states:
                return states
    return []


def validate_llm_prompt_bank_item(card: CharacterCard, item: dict[str, Any], baseline: dict[str, Any]) -> tuple[bool, str]:
    identity = str(item.get("identity_prompt") or "").strip()
    negative = str(item.get("negative_identity_prompt") or "").strip()
    if identity and card.reference_visuals and not overlaps_reference_terms(identity, baseline):
        return False, "identity_prompt does not preserve reference-image facts"
    if negative and not looks_like_negative_prompt(negative):
        return False, "negative_identity_prompt contains positive or descriptive content"
    if not identity and not negative and not normalize_appearance_states(item.get("appearance_states")):
        return False, "prompt bank item is empty"
    return True, ""


def overlaps_reference_terms(identity: str, baseline: dict[str, Any]) -> bool:
    terms = [
        token
        for text in baseline.get("reference_terms", [])
        for token in re.split(r"[,;\uFF0C\uFF1B\u3001\s]+", str(text).lower())
        if len(token) >= 3
    ]
    if not terms:
        return True
    identity_lower = identity.lower()
    return sum(1 for token in set(terms) if token in identity_lower) >= min(3, len(set(terms)))


def looks_like_negative_prompt(text: str) -> bool:
    lowered = text.lower()
    positive_markers = [
        "hair:",
        "eyes:",
        "face:",
        "outfit:",
        "wearing",
        "holding",
        "reference-image identity",
        "visible traits",
        "canonical visible traits",
        "outfit and accessories",
    ]
    return not any(marker in lowered for marker in positive_markers)


def normalize_appearance_states(states: Any) -> list[dict[str, Any]]:
    if not isinstance(states, list):
        return []
    normalized = []
    for state in states:
        if not isinstance(state, dict):
            continue
        prompt = str(state.get("prompt") or "").strip()
        if not prompt:
            continue
        normalized.append(
            {
                "label": str(state.get("label") or "default").strip() or "default",
                "trigger": str(state.get("trigger") or "Use when this visible state applies.").strip(),
                "prompt": prompt,
                "scene_ids": state.get("scene_ids") if isinstance(state.get("scene_ids"), list) else [],
            }
        )
    return normalized


def visual_appearance_states(states: Any) -> list[dict[str, Any]]:
    normalized = normalize_appearance_states(states)
    return [state for state in normalized if is_visual_appearance_text(str(state.get("prompt") or ""))]


def first_visual_text(values: Any) -> str:
    for value in values or []:
        text = normalize_prompt_text(str(value or ""))
        if is_visual_appearance_text(text):
            return text
    return ""


def is_visual_appearance_text(text: str) -> bool:
    normalized = normalize_prompt_text(text).lower()
    if not normalized:
        return False
    visible_markers = [
        "hair",
        "eyes",
        "face",
        "skin",
        "body",
        "build",
        "silhouette",
        "outfit",
        "wearing",
        "dress",
        "coat",
        "shirt",
        "skirt",
        "pants",
        "boots",
        "shoes",
        "gloves",
        "hat",
        "armor",
        "uniform",
        "accessory",
        "weapon",
        "staff",
        "wand",
        "sword",
        "prop",
        "wings",
        "tail",
        "ears",
        "expression",
        "injury",
        "blood",
        "外貌",
        "头发",
        "发色",
        "发型",
        "眼",
        "脸",
        "肤",
        "身高",
        "体型",
        "服",
        "裙",
        "裤",
        "靴",
        "鞋",
        "帽",
        "披风",
        "盔甲",
        "制服",
        "道具",
        "武器",
        "法杖",
        "剑",
        "刀",
        "翅",
        "尾",
        "耳",
        "表情",
        "伤",
        "血",
    ]
    if any(marker in normalized for marker in visible_markers):
        return True
    nonvisual_markers = [
        "believe",
        "belief",
        "personality",
        "relationship",
        "backstory",
        "motivation",
        "fate",
        "destiny",
        "future",
        "power",
        "相信",
        "命运",
        "未来",
        "亲情",
        "权威",
        "压迫",
        "力量",
        "性格",
        "关系",
        "经历",
        "资料来源",
        "页面节选",
        "语音记录",
    ]
    return not any(marker in normalized for marker in nonvisual_markers)


def merge_identity_prompt(identity_prompt: str, baseline: dict[str, Any]) -> str:
    baseline_identity = str(baseline.get("identity_prompt") or "")
    vlm_identity = str(baseline.get("vlm_identity_prompt") or "")
    if vlm_identity:
        return baseline_identity or vlm_identity
    if baseline_identity:
        return baseline_identity
    return normalize_prompt_text(identity_prompt)


def merge_negative_prompt(negative_prompt: str, baseline: dict[str, Any]) -> str:
    baseline_negative = str(baseline.get("negative_identity_prompt") or "")
    if baseline_negative:
        return baseline_negative
    return join_prompt_parts([negative_prompt])


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


def parse_json_response(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise json.JSONDecodeError("empty response", raw or "", 0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1))

    extracted = extract_first_json_object(text)
    if extracted:
        return json.loads(extracted)
    raise json.JSONDecodeError("no JSON object found", raw, 0)


def parse_visual_fact_prose(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    cleaned = text.replace("**", "")
    lines = [line.strip(" -*•\t") for line in cleaned.splitlines() if line.strip()]
    stable_visual_traits: list[str] = []
    outfit_traits: list[str] = []
    uncertain_traits: list[str] = []
    negative_identity_prompt: list[str] = []
    identity_prompt_lines: list[str] = []
    summary_bits: list[str] = []
    for line in lines:
        if len(line) < 3:
            continue
        if should_skip_visual_fact_line(line):
            continue
        label, value = extract_prompt_label_value(line)
        if label == "identity" and value:
            identity_prompt_lines.append(value)
            summary_bits.append(value)
            continue
        if label == "negative" and value:
            negative_identity_prompt.append(value)
            continue
        summary_bits.append(line)
        lower = line.lower()
        if is_negative_fact_line(line):
            negative_identity_prompt.append(strip_fact_label(line))
            continue
        if any(word in lower for word in ["uncertain", "possible", "likely", "may", "might", "not sure", "varia"]):
            uncertain_traits.append(line)
        if any(word in lower for word in ["hair", "eyes", "face", "body", "height", "build", "silhouette", "skin", "ear", "expression"]):
            stable_visual_traits.append(line)
        if any(word in lower for word in ["outfit", "clothing", "dress", "coat", "uniform", "armor", "accessory", "accessories", "wearing"]):
            outfit_traits.append(line)
    stable_visual_traits = unique_keep_order([normalize_prompt_text(item) for item in stable_visual_traits])
    outfit_traits = unique_keep_order([normalize_prompt_text(item) for item in outfit_traits])
    uncertain_traits = unique_keep_order([normalize_prompt_text(item) for item in uncertain_traits])
    negative_identity_prompt_text = join_prompt_parts(unique_keep_order([normalize_prompt_text(item) for item in negative_identity_prompt]))
    summary = normalize_prompt_text(" ".join(summary_bits))
    identity_prompt = join_identity_parts(identity_prompt_lines) or join_identity_parts(
        [
            "reference-image identity",
            "visible traits: " + "; ".join(stable_visual_traits) if stable_visual_traits else "",
            "outfit and accessories: " + "; ".join(outfit_traits) if outfit_traits else "",
        ]
    )
    if not (stable_visual_traits or outfit_traits or summary):
        return {}
    return {
        "identity_prompt": identity_prompt,
        "stable_visual_traits": stable_visual_traits,
        "outfit_traits": outfit_traits,
        "variable_or_uncertain_traits": uncertain_traits,
        "negative_identity_prompt": negative_identity_prompt_text,
        "appearance_states": [
            {
                "label": "default",
                "trigger": "Use unless story explicitly changes visible appearance.",
                "prompt": identity_prompt or summary,
                "scene_ids": [],
            }
        ],
        "reference_summary": summary,
        "source_format": "prose",
    }


def should_skip_visual_fact_line(line: str) -> bool:
    lower = line.lower()
    instructional_markers = [
        "this needs to be",
        "specifically the",
        "identifying clothing",
        "based on the image",
        "the user wants",
        "analyze the image",
        "output containing",
        "required schema",
    ]
    if any(marker in lower for marker in instructional_markers):
        return True
    return bool(re.match(r"^\d+\.\s*(identity prompt|appearance states?|outfit traits?|stable visual traits?)\s*:\s*$", lower))


def extract_prompt_label_value(line: str) -> tuple[str, str]:
    match = re.match(r"^\s*(?:\d+\.\s*)?(identity prompt|negative identity prompt)\*?\s*[:：]\s*(.+)$", line, flags=re.IGNORECASE)
    if not match:
        return "", ""
    label = match.group(1).lower()
    value = normalize_prompt_text(match.group(2))
    if "->" in value:
        value = normalize_prompt_text(value.split("->", 1)[1])
    if "this needs to be" in value.lower():
        return "", ""
    return ("negative" if label.startswith("negative") else "identity", value)


def is_negative_fact_line(line: str) -> bool:
    lower = line.strip().lower()
    if re.match(r"^(negative|negative prompt|negative_identity_prompt|avoid|do not|don't|exclude|wrong|bad)\b\s*[:\uFF1A-]?", lower):
        return True
    return bool(re.search(r"\b(visual drift|wrong identity|inconsistent face|inconsistent hairstyle|wrong outfit|wrong colors)\b", lower))


def strip_fact_label(line: str) -> str:
    stripped = line.strip()
    return re.sub(r"^(negative(?: prompt)?|negative_identity_prompt|avoid|exclude)\s*[:\uFF1A-]\s*", "", stripped, flags=re.IGNORECASE).strip()


def join_prompt_parts(values: Any) -> str:
    if isinstance(values, str):
        values = [values]
    parts: list[str] = []
    for value in values:
        if not value:
            continue
        for piece in re.split(r"[,;\uFF0C\uFF1B\u3001\n]+", str(value)):
            cleaned = sanitize_negative_prompt_part(piece)
            if cleaned:
                parts.append(cleaned)
    return ", ".join(unique_keep_order(parts))


def join_identity_parts(values: Any) -> str:
    if isinstance(values, str):
        values = [values]
    parts = [normalize_prompt_text(str(value)).strip(" ;,\uFF0C\uFF1B\u3001") for value in values if str(value or "").strip()]
    return "; ".join(unique_keep_order(parts))


def normalize_prompt_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def sanitize_negative_prompt_part(part: str) -> str:
    cleaned = re.sub(r"\s+", " ", part).strip(" .;,\uFF0C\uFF1B\u3001")
    if not cleaned:
        return ""
    if re.match(r"^(hair|eyes|eye|face|body|outfit|clothing|dress|coat|accessor(?:y|ies)|character|name)\s*[:\uFF1A]", cleaned, flags=re.IGNORECASE):
        return ""
    return cleaned


def extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None
