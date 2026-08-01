from __future__ import annotations

import json

from .models import CharacterCard, Scene, Shot
from .providers import OpenAICompatibleProvider, ProviderError
from .text_utils import compact


JSON_RULE = "只输出 JSON，不要 Markdown，不要解释。"


def polish_shot_prompt(shot: Shot, cards: list[CharacterCard], provider: OpenAICompatibleProvider) -> Shot:
    system = (
        "你是小说插画分镜与文生图提示词专家。你的任务是把已有 prompt 精修得更适合生图，"
        "重点保持角色一致性、剧情准确、相邻画面连续。"
        + JSON_RULE
    )
    user = json.dumps(
        {
            "shot": {
                "id": shot.id,
                "title": shot.title,
                "excerpt": shot.source_excerpt,
                "characters": shot.characters,
                "location": shot.location,
                "time": shot.time,
                "mood": shot.mood,
                "positive_prompt": shot.positive_prompt,
                "negative_prompt": shot.negative_prompt,
                "continuity_notes": shot.continuity_notes,
            },
            "characters": [
                {
                    "name": card.name,
                    "role": card.role,
                    "fixed_traits": card.fixed_traits,
                    "prompt_cn": card.prompt_cn,
                    "prompt_en": card.prompt_en,
                }
                for card in cards
            ],
            "required_schema": {
                "positive_prompt": "string",
                "negative_prompt": "string",
                "visual_goal": "string",
                "qa_notes": ["string"],
            },
        },
        ensure_ascii=False,
    )
    try:
        raw = provider.text(system, user)
        data = json.loads(raw)
    except (ProviderError, json.JSONDecodeError, TypeError) as exc:
        shot.qa_notes.append(f"LLM 增强失败，已保留本地 prompt：{exc}")
        return shot

    shot.positive_prompt = data.get("positive_prompt") or shot.positive_prompt
    shot.negative_prompt = data.get("negative_prompt") or shot.negative_prompt
    shot.visual_goal = data.get("visual_goal") or shot.visual_goal
    shot.qa_notes.extend(data.get("qa_notes") or [])
    return shot


def summarize_scene_with_llm(scene: Scene, provider: OpenAICompatibleProvider) -> Scene:
    system = "你是小说章节分析工具。提取这个场景的可视化摘要、地点、时间、情绪和镜头类型。" + JSON_RULE
    user = json.dumps(
        {
            "scene_id": scene.id,
            "text": compact(scene.text, 2400),
            "required_schema": {
                "summary": "string",
                "location": "string",
                "time": "string",
                "mood": ["string"],
                "visual_type": "双人情绪特写 | 双人对话中景 | 剧情动作瞬间 | 环境氛围图 | 单人氛围图",
            },
        },
        ensure_ascii=False,
    )
    try:
        data = json.loads(provider.text(system, user))
    except (ProviderError, json.JSONDecodeError, TypeError):
        return scene
    scene.summary = data.get("summary") or scene.summary
    scene.location = data.get("location") or scene.location
    scene.time = data.get("time") or scene.time
    if isinstance(data.get("mood"), list):
        scene.mood = [str(item) for item in data["mood"]]
    scene.visual_type = data.get("visual_type") or scene.visual_type
    return scene
