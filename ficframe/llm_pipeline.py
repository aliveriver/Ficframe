from __future__ import annotations

import json
import re

from .logging_utils import get_logger
from .models import CharacterCard, Scene, Shot
from .providers import OpenAICompatibleProvider, ProviderError
from .text_utils import compact


JSON_RULE = "只输出 JSON，不要 Markdown，不要解释。"
logger = get_logger("llm_pipeline")


def polish_shot_prompt(
    shot: Shot,
    cards: list[CharacterCard],
    provider: OpenAICompatibleProvider,
    purpose: str | None = None,
    feedback_history: list[dict] | None = None,
) -> Shot:
    feedback_context = [
        {
            "role": str(message.get("role") or ""),
            "content": compact(str(message.get("content") or ""), 1200),
            "action": message.get("action"),
            "shot_ids": message.get("shot_ids"),
        }
        for message in (feedback_history or [])[-20:]
        if isinstance(message, dict) and str(message.get("content") or "").strip()
    ]
    system = (
        "你是小说插画分镜与文生图提示词专家。你的任务是把已有 prompt 精修得更适合生图，"
        "重点保持角色一致性、剧情准确、相邻画面连续。"
        "如果提供了用户反馈，必须将其中针对当前分镜的问题落实到 Prompt，同时保留用户明确认可的优点；"
        "不能因为反馈只讨论其他分镜，就无依据地改变当前分镜。"
        "positive_prompt 和 negative_prompt 必须主要使用英文，只有角色名、地名、作品内专有名词可以保留原文或中英并列。"
        "必须按 Scene, Composition, Characters, Relationships, Style, Negative constraints 的结构输出。"
        "如果画面有多名角色，必须明确 exactly N visible characters，并为每个角色写清楚独立身份、外观差异、动作和情绪功能。"
        "如果存在双胞胎、姐妹、相似角色，必须强化“相似但可区分”：不同发型、眼神、姿态、道具、气质，禁止同脸和角色复制。"
        "同时判断当前镜头是否需要 IP-Adapter 区域约束。多人近景、中景或身份容易串线时 regional_guidance=true，"
        "并为每名可见角色返回归一化 region=[left, top, right, bottom]；区域可以不等宽、前后景重叠。"
        "单人、远景、背影，或原文没有明确站位且自由构图更重要时 regional_guidance=false，character_layout 可以为空。"
        "只根据传入的人设文本和当前分镜写，不要引入外部作品设定或默认角色印象。"
        "不要把某个角色的人设词套到另一个角色身上。不要新增原文没有出现的人物。"
        + JSON_RULE
    )
    user = json.dumps(
        {
            "shot": {
                "id": shot.id,
                "title": shot.title,
                "excerpt": shot.source_excerpt,
                "source_text": shot.source_text,
                "characters": shot.characters,
                "location": shot.location,
                "time": shot.time,
                "mood": shot.mood,
                "camera": shot.camera,
                "composition": shot.composition,
                "positive_prompt": shot.positive_prompt,
                "negative_prompt": shot.negative_prompt,
                "continuity_notes": shot.continuity_notes,
            },
            "characters": [
                {
                    "name": card.name,
                    "role": card.role,
                    "fixed_traits": card.fixed_traits,
                    "variable_states": card.variable_states,
                    "relationships": card.relationships,
                    "source_text": compact(card.source_text, 1200),
                    "prompt_cn": card.prompt_cn,
                    "prompt_en": card.prompt_en,
                    "has_reference_images": bool(card.reference_images),
                }
                for card in cards
            ],
            "user_feedback_history": feedback_context,
            "required_schema": {
                "source_excerpt": "verbatim substring copied from shot.source_text, identifying the novel passage this shot is based on",
                "positive_prompt": "English string, structured with Scene, Composition, Characters, Relationships, Style",
                "negative_prompt": "English string, must include extra people, duplicate character, same face between different characters, merged characters, wrong character identity",
                "visual_goal": "string",
                "regional_guidance": "boolean; true only when per-character regional identity control is useful",
                "character_layout": [
                    {
                        "character": "exact character name from shot.characters",
                        "position": "short semantic position such as foreground left or background center",
                        "depth": "foreground | midground | background",
                        "region": ["left 0..1", "top 0..1", "right 0..1", "bottom 0..1"],
                    }
                ],
                "qa_notes": ["string"],
            },
        },
        ensure_ascii=False,
    )
    try:
        raw = provider.text(system, user, purpose=purpose or f"pipeline:polish_shot_prompt:{shot.id}")
        data = parse_llm_json(raw)
    except (ProviderError, json.JSONDecodeError, TypeError) as exc:
        shot.qa_notes.append(f"LLM 增强失败，已保留本地 prompt：{exc}")
        return shot

    positive_prompt = data.get("positive_prompt") or shot.positive_prompt
    negative_prompt = data.get("negative_prompt") or shot.negative_prompt
    if not is_english_structured_prompt(positive_prompt):
        repaired = repair_prompt_with_llm(
            shot,
            cards,
            provider,
            positive_prompt,
            negative_prompt,
            purpose=f"{purpose or 'pipeline:polish_shot_prompt'}:repair:{shot.id}",
            feedback_history=feedback_history,
        )
        if repaired:
            positive_prompt = repaired.get("positive_prompt") or positive_prompt
            negative_prompt = repaired.get("negative_prompt") or negative_prompt
            shot.qa_notes.append("LLM prompt 已二次统一为英文结构化格式。")
        else:
            shot.qa_notes.append("LLM 返回了可解析 JSON，但 prompt 未完全符合英文结构化格式，已保留返回内容。")

    shot.positive_prompt = positive_prompt
    shot.negative_prompt = negative_prompt
    excerpt = str(data.get("source_excerpt") or "").strip()
    if excerpt and (not shot.source_text or excerpt in shot.source_text):
        shot.source_excerpt = excerpt
    shot.visual_goal = data.get("visual_goal") or shot.visual_goal
    layout = normalize_character_layout(data.get("character_layout"), shot.characters)
    if "character_layout" in data:
        shot.character_layout = layout
    if isinstance(data.get("regional_guidance"), bool):
        shot.regional_guidance = data["regional_guidance"]
    elif layout:
        shot.regional_guidance = True
    shot.qa_notes.extend(data.get("qa_notes") or [])
    return shot


def generate_or_revise_shot_with_llm(
    shot: Shot,
    cards: list[CharacterCard],
    provider: OpenAICompatibleProvider,
    feedback_history: list[dict] | None = None,
    purpose: str | None = None,
) -> Shot:
    """Generate/revise the complete storyboard record while keeping source and image identity stable."""
    system = (
        "你是小说插画分镜 Agent。根据用户指定的小说原文或画面描述，输出一条完整、可执行的分镜。"
        "必须尊重历次反馈：做得好的地方继续保留，不妥之处明确修正。"
        "若提供 source_text，source_excerpt 必须逐字摘自 source_text，不能改写或杜撰，以便界面回到原文高亮。"
        "characters 只能使用 character_names 中的精确名称，不能新增原文没有的人。"
        "positive_prompt 与 negative_prompt 主要使用英文，并保持角色身份清楚、画面人数准确。"
        "只输出 JSON，不要 Markdown，不要解释。"
    )
    user = json.dumps(
        {
            "task": "revise" if feedback_history else "generate",
            "source_text": shot.source_text,
            "generation_description": shot.generation_description,
            "current_shot": {
                "id": shot.id,
                "title": shot.title,
                "source_excerpt": shot.source_excerpt,
                "characters": shot.characters,
                "location": shot.location,
                "time": shot.time,
                "mood": shot.mood,
                "camera": shot.camera,
                "composition": shot.composition,
                "visual_goal": shot.visual_goal,
                "continuity_notes": shot.continuity_notes,
                "positive_prompt": shot.positive_prompt,
                "negative_prompt": shot.negative_prompt,
            },
            "character_names": [card.name for card in cards],
            "character_profiles": [
                {
                    "name": card.name,
                    "identity_prompt": card.identity_prompt or card.prompt_en,
                    "fixed_traits": card.fixed_traits,
                    "relationships": card.relationships,
                }
                for card in cards
            ],
            "feedback_history": feedback_history or [],
            "required_schema": {
                "title": "string",
                "source_excerpt": "verbatim substring of source_text, or concise basis when source_text is empty",
                "characters": ["exact character name"],
                "location": "string",
                "time": "string",
                "mood": ["string"],
                "camera": "string",
                "composition": "string",
                "visual_goal": "string",
                "continuity_notes": ["string"],
                "positive_prompt": "English structured image prompt",
                "negative_prompt": "English negative prompt",
                "regional_guidance": "boolean",
                "character_layout": [],
                "change_summary": "Chinese string",
            },
        },
        ensure_ascii=False,
    )
    data = parse_llm_json(provider.text(system, user, purpose=purpose or f"storyboard:revise:{shot.id}"))
    for field in ["title", "location", "time", "camera", "composition", "visual_goal", "positive_prompt", "negative_prompt"]:
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            setattr(shot, field, value.strip())
    excerpt = str(data.get("source_excerpt") or "").strip()
    if excerpt and (not shot.source_text or excerpt in shot.source_text):
        shot.source_excerpt = excerpt
    allowed_names = {card.name for card in cards}
    if isinstance(data.get("characters"), list):
        shot.characters = [str(name) for name in data["characters"] if str(name) in allowed_names]
    for field in ["mood", "continuity_notes"]:
        value = data.get(field)
        if isinstance(value, list):
            setattr(shot, field, [str(item).strip() for item in value if str(item).strip()])
    layout = normalize_character_layout(data.get("character_layout"), shot.characters)
    if "character_layout" in data:
        shot.character_layout = layout
    if isinstance(data.get("regional_guidance"), bool):
        shot.regional_guidance = data["regional_guidance"]
    summary = str(data.get("change_summary") or "").strip()
    if summary:
        shot.qa_notes.append(summary)
    return shot


def respond_to_storyboard_feedback(
    shots: list[Shot],
    messages: list[dict],
    cards: list[CharacterCard],
    provider: OpenAICompatibleProvider,
    purpose: str = "storyboard:feedback",
) -> dict[str, object]:
    system = (
        "你是可以自主决定是否执行修改的小说分镜 Agent。结合当前分镜、角色约束和完整对话历史分析最新反馈。"
        "若用户提出了明确的分镜修改、纠错或优化要求，action=regenerate，并只选择实际需要修改的 shot_ids；"
        "若反馈针对整版且无法缩小范围，选择全部分镜。纯表扬、提问、信息不足或明确要求保留现状时 action=none。"
        "混合反馈中，被表扬且无需修改的分镜不要重生成，但要把优点作为其他分镜的修改原则。"
        "reply 要简洁说明你的判断；需要重生成时说明将立即处理哪些分镜，无需修改时说明原因或提出必要追问。"
        "只能输出 JSON，不要 Markdown。"
    )
    user = json.dumps(
        {
            "storyboard": [
                {
                    "id": shot.id,
                    "title": shot.title,
                    "source_excerpt": shot.source_excerpt,
                    "visual_goal": shot.visual_goal,
                    "camera": shot.camera,
                    "composition": shot.composition,
                    "characters": shot.characters,
                }
                for shot in shots
            ],
            "character_names": [card.name for card in cards],
            "conversation": messages,
            "required_schema": {
                "reply": "Chinese string",
                "action": "none | regenerate",
                "shot_ids": ["existing shot id"],
                "reason": "Chinese string explaining why this action and scope were chosen",
            },
        },
        ensure_ascii=False,
    )
    data = parse_llm_json(provider.text(system, user, purpose=purpose))
    if not isinstance(data, dict):
        raise TypeError("storyboard feedback decision must be a JSON object")
    valid_ids = {shot.id for shot in shots}
    requested_ids = data.get("shot_ids") if isinstance(data.get("shot_ids"), list) else []
    shot_ids = [str(shot_id) for shot_id in requested_ids if str(shot_id) in valid_ids]
    action = "regenerate" if data.get("action") == "regenerate" and shot_ids else "none"
    reply = str(data.get("reply") or data.get("reason") or "已记录这条反馈。").strip()
    reason = str(data.get("reason") or "").strip()
    return {"reply": reply, "action": action, "shot_ids": shot_ids if action == "regenerate" else [], "reason": reason}


def normalize_character_layout(value: object, character_names: list[str]) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    allowed = set(character_names)
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        character = str(item.get("character") or "").strip()
        region = item.get("region")
        if character not in allowed or character in seen or not isinstance(region, list) or len(region) != 4:
            continue
        try:
            left, top, right, bottom = [float(part) for part in region]
        except (TypeError, ValueError):
            continue
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            continue
        seen.add(character)
        result.append(
            {
                "character": character,
                "position": str(item.get("position") or "").strip(),
                "depth": str(item.get("depth") or "").strip(),
                "region": [left, top, right, bottom],
            }
        )
    return result


def extract_character_cards_with_llm(raw_text: str, provider: OpenAICompatibleProvider, purpose: str = "llm:extract_character_cards") -> list[CharacterCard]:
    cards, _ = extract_character_cards_with_llm_detailed(raw_text, provider, purpose=purpose)
    return cards


def extract_character_cards_with_llm_detailed(raw_text: str, provider: OpenAICompatibleProvider, purpose: str = "llm:extract_character_cards") -> tuple[list[CharacterCard], str]:
    system = (
        "You are a character profile splitter and extractor for illustrated fiction. "
        "Read the supplied character notes and identify every distinct character that has its own profile. "
        "The source may use Markdown headings, bold section labels, standalone name lines followed by paragraphs, "
        "or a long profile where one character starts after a '角色总览/人物总览' label. "
        "Do not treat topic section titles such as abilities, relationships, events, personality, or writing advice as characters. "
        "Use only the supplied text; do not add outside canon. "
        "Return exactly one JSON object. The top-level object must have exactly one key named characters. "
        "Never return a schema, examples, Markdown, explanations, or a nested field by itself."
    )
    user = json.dumps(
        {
            "raw_character_notes": compact(raw_text, 16000),
            "output_contract": [
                "Return a single JSON object shaped as {\"characters\": [...]}",
                "characters must be an array.",
                "Each character item must be an object.",
                "Required item key: name.",
                "Optional item keys: aliases, role, source_text, visual_traits, personality_traits, fixed_traits, variable_states, relationships, prompt_cn, prompt_en.",
                "aliases, visual_traits, personality_traits, fixed_traits must be arrays of strings.",
                "variable_states and relationships must be objects whose keys and values are strings.",
            ],
            "empty_result": {"characters": []},
        },
        ensure_ascii=False,
    )
    try:
        raw = provider.text(system, user, purpose=purpose)
        data = parse_llm_json(raw)
    except ProviderError as exc:
        logger.warning("llm character extraction provider_error=%s", exc)
        return [], f"LLM 请求失败：{exc}"
    except json.JSONDecodeError as exc:
        logger.warning("llm character extraction invalid_json error=%s preview=%s", exc, compact(raw if "raw" in locals() else "", 500))
        return [], f"LLM 返回不是合法 JSON：{exc}；返回开头：{compact(raw if 'raw' in locals() else '', 160)}"
    except TypeError as exc:
        logger.warning("llm character extraction invalid_payload error=%s", exc)
        return [], f"LLM 返回结构异常：{exc}"
    if not isinstance(data.get("characters"), list):
        logger.warning("llm character extraction missing_characters keys=%s", list(data.keys())[:12])
        return [], "LLM JSON 中缺少 characters 数组"
    cards = []
    for item in data.get("characters", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        cards.append(
            CharacterCard(
                name=name,
                aliases=string_list(item.get("aliases")),
                role=str(item.get("role") or "").strip(),
                source_text=compact(str(item.get("source_text") or raw_text), 3000),
                visual_traits=string_list(item.get("visual_traits")),
                personality_traits=string_list(item.get("personality_traits")),
                fixed_traits=string_list(item.get("fixed_traits")),
                variable_states=string_dict(item.get("variable_states")),
                relationships=string_dict(item.get("relationships")),
                prompt_cn=str(item.get("prompt_cn") or "").strip(),
                prompt_en=str(item.get("prompt_en") or "").strip(),
            )
        )
    cards = dedupe_cards(cards)
    if not cards:
        logger.warning("llm character extraction empty_valid_cards item_count=%s", len(data.get("characters", [])))
        return [], "LLM 返回了 characters，但没有可用角色名"
    return cards, f"LLM 返回 {len(cards)} 个可用角色"


def enhance_character_cards_with_llm(cards: list[CharacterCard], provider: OpenAICompatibleProvider, purpose: str = "llm:enhance_character_cards") -> list[CharacterCard]:
    system = (
        "You are a character profile extraction assistant for image generation. "
        "Use only the supplied character profile text. Extract stable identity, appearance, personality, fixed traits, "
        "variable visible states, relationships, and English prompt fragments. Do not add outside canon. "
        "Return JSON only."
    )
    user = json.dumps(
        {
            "characters": [
                {
                    "name": card.name,
                    "aliases": card.aliases,
                    "role": card.role,
                    "source_text": compact(card.source_text, 2600),
                    "local_visual_traits": card.visual_traits,
                    "local_personality_traits": card.personality_traits,
                    "local_fixed_traits": card.fixed_traits,
                    "local_variable_states": card.variable_states,
                    "local_relationships": card.relationships,
                }
                for card in cards
            ],
            "required_schema": {
                "characters": [
                    {
                        "name": "string",
                        "aliases": ["string"],
                        "role": "string",
                        "visual_traits": ["string"],
                        "personality_traits": ["string"],
                        "fixed_traits": ["string"],
                        "variable_states": {"outfit": "string", "emotion": "string", "props": "string"},
                        "relationships": {"name or relation": "description"},
                        "prompt_en": "English image-generation character description",
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    try:
        data = parse_llm_json(provider.text(system, user, purpose=purpose))
    except (ProviderError, json.JSONDecodeError, TypeError):
        return cards
    by_name = {card.name: card for card in cards}
    for item in data.get("characters", []):
        if not isinstance(item, dict):
            continue
        card = by_name.get(str(item.get("name") or ""))
        if not card:
            continue
        if isinstance(item.get("aliases"), list):
            card.aliases = [str(value) for value in item["aliases"] if str(value).strip()]
        for field in ["role", "prompt_en"]:
            value = item.get(field)
            if isinstance(value, str) and value.strip():
                setattr(card, field, value.strip())
        for field in ["visual_traits", "personality_traits", "fixed_traits"]:
            value = item.get(field)
            if isinstance(value, list):
                setattr(card, field, [str(part) for part in value if str(part).strip()])
        for field in ["variable_states", "relationships"]:
            value = item.get(field)
            if isinstance(value, dict):
                setattr(card, field, {str(key): str(val) for key, val in value.items() if str(val).strip()})
    return cards


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key).strip(): str(item).strip() for key, item in value.items() if str(key).strip() and str(item).strip()}


def dedupe_cards(cards: list[CharacterCard]) -> list[CharacterCard]:
    unique: list[CharacterCard] = []
    seen: set[str] = set()
    for card in cards:
        if card.name in seen:
            continue
        seen.add(card.name)
        unique.append(card)
    return unique


def repair_prompt_with_llm(
    shot: Shot,
    cards: list[CharacterCard],
    provider: OpenAICompatibleProvider,
    positive_prompt: str,
    negative_prompt: str,
    purpose: str = "llm:repair_prompt",
    feedback_history: list[dict] | None = None,
) -> dict | None:
    system = (
        "Rewrite this image-generation prompt into a consistent English prompt. "
        "Keep all story facts and character identities. Use exactly these sections: "
        "Scene, Composition, Characters, Relationships, Style. "
        "Use English for all descriptive text; character names and proper nouns may remain unchanged. "
        "Return JSON only."
    )
    user = json.dumps(
        {
            "shot": {
                "id": shot.id,
                "excerpt": shot.source_excerpt,
                "characters": shot.characters,
                "positive_prompt": positive_prompt,
                "negative_prompt": negative_prompt,
            },
            "characters": [
                {
                    "name": card.name,
                    "role": card.role,
                    "source_text": compact(card.source_text, 1000),
                    "prompt_en": card.prompt_en,
                }
                for card in cards
            ],
            "required_schema": {
                "positive_prompt": "English string with Scene, Composition, Characters, Relationships, Style sections",
                "negative_prompt": "English negative prompt string",
            },
            "user_feedback_history": feedback_history or [],
        },
        ensure_ascii=False,
    )
    try:
        data = parse_llm_json(provider.text(system, user, purpose=purpose))
    except (ProviderError, json.JSONDecodeError, TypeError):
        return None
    if is_english_structured_prompt(str(data.get("positive_prompt") or "")):
        return data
    return None


def is_english_structured_prompt(prompt: str) -> bool:
    text = prompt or ""
    required_sections = ["Scene", "Composition", "Characters"]
    if not all(section in text for section in required_sections):
        return False
    letters = sum(1 for char in text if char.isascii() and char.isalpha())
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return letters >= max(80, cjk * 3)


def summarize_scene_with_llm(scene: Scene, provider: OpenAICompatibleProvider, purpose: str | None = None) -> Scene:
    system = (
        "你是小说章节分析工具。提取这个场景的可视化摘要、地点、时间、情绪和镜头类型。"
        "summary、location、time、mood 请优先输出英文，角色名和专有名词可以保留原文。"
        + JSON_RULE
    )
    user = json.dumps(
        {
            "scene_id": scene.id,
            "text": compact(scene.text, 2400),
            "required_schema": {
                "summary": "string",
                "location": "string",
                "time": "string",
                "mood": ["string"],
                "visual_type": "双人情绪特写 | 双人对话中景 | 多人关系中景 | 剧情动作瞬间 | 环境氛围图 | 单人氛围图",
            },
        },
        ensure_ascii=False,
    )
    try:
        data = parse_llm_json(provider.text(system, user, purpose=purpose or f"pipeline:summarize_scene:{scene.id}"))
    except (ProviderError, json.JSONDecodeError, TypeError):
        return scene
    scene.summary = data.get("summary") or scene.summary
    scene.location = data.get("location") or scene.location
    scene.time = data.get("time") or scene.time
    if isinstance(data.get("mood"), list):
        scene.mood = [str(item) for item in data["mood"]]
    scene.visual_type = data.get("visual_type") or scene.visual_type
    return scene


def refine_scenes_with_llm(scenes: list[Scene], cards: list[CharacterCard], provider: OpenAICompatibleProvider, purpose: str = "pipeline:refine_scenes") -> list[Scene]:
    by_id = {scene.id: scene for scene in scenes}
    system = (
        "You are a story structure analyzer for illustrated fiction. "
        "Given rule-based scene chunks, improve each scene's visual summary, character list, location, time, mood, "
        "visual type, and visual priority. Preserve the original scene ids and do not invent new scene ids. "
        "Return JSON only."
    )
    user = json.dumps(
        {
            "characters": [{"name": card.name, "aliases": card.aliases, "role": card.role} for card in cards],
            "scenes": [
                {
                    "id": scene.id,
                    "chapter": scene.chapter,
                    "index": scene.index,
                    "text": compact(scene.text, 1200),
                    "local_characters": scene.characters,
                }
                for scene in scenes
            ],
            "required_schema": {
                "scenes": [
                    {
                        "id": "existing scene id",
                        "summary": "English visual summary",
                        "characters": ["names from provided character list"],
                        "location": "English location",
                        "time": "English time",
                        "mood": ["English mood tags"],
                        "visual_type": "双人情绪特写 | 双人对话中景 | 多人关系中景 | 剧情动作瞬间 | 环境氛围图 | 单人氛围图",
                        "visual_priority": "1-5 integer",
                    }
                ]
            },
        },
        ensure_ascii=False,
    )
    try:
        data = parse_llm_json(provider.text(system, user, purpose=purpose))
    except (ProviderError, json.JSONDecodeError, TypeError):
        return scenes
    valid_names = {card.name for card in cards}
    for item in data.get("scenes", []):
        if not isinstance(item, dict):
            continue
        scene = by_id.get(str(item.get("id") or ""))
        if not scene:
            continue
        scene.summary = str(item.get("summary") or scene.summary)
        scene.location = str(item.get("location") or scene.location)
        scene.time = str(item.get("time") or scene.time)
        if isinstance(item.get("mood"), list):
            scene.mood = [str(value) for value in item["mood"] if str(value).strip()]
        if isinstance(item.get("characters"), list):
            names = [str(value) for value in item["characters"] if str(value) in valid_names]
            if names:
                scene.characters = names
        scene.visual_type = str(item.get("visual_type") or scene.visual_type)
        try:
            scene.visual_priority = max(1, min(5, int(item.get("visual_priority"))))
        except (TypeError, ValueError):
            pass
    return scenes


def parse_llm_json(raw: str) -> dict:
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
