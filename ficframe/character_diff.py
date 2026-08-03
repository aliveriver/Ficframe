from __future__ import annotations

import json
from itertools import combinations
from typing import Any

from .models import CharacterCard
from .text_utils import compact, unique_keep_order


FEATURE_BUCKETS = {
    "身份": {
        "工程师": ["工程师", "engineer", "技术"],
        "研究员": ["研究员", "研究者", "scientist", "researcher"],
        "学者": ["学者", "scholar"],
        "指挥者": ["指挥", "strategist", "commander"],
        "战斗者": ["战士", "护卫", "骑士", "guard", "fighter", "operator"],
        "学生": ["学生", "student"],
    },
    "气质": {
        "锐利行动派": ["锐利", "行动派", "直接", "固执", "sharper", "action-oriented", "stubborn", "direct"],
        "温柔照顾型": ["温柔", "照顾", "gentle", "warm", "caretaker"],
        "优雅安静": ["优雅", "安静", "graceful", "composed", "quiet"],
        "冷静克制": ["冷静", "克制", "calm", "restrained"],
        "活泼外向": ["活泼", "外向", "cheerful", "outgoing"],
    },
    "外观": {
        "短发": ["短发", "short hair", "shorter hairstyle"],
        "长发": ["长发", "long hair", "longer hairstyle"],
        "锐利眼神": ["锐利眼神", "sharper eyes"],
        "柔和眼神": ["柔和眼神", "soft eyes"],
        "白大褂": ["白大褂", "laboratory coat", "lab outfit"],
        "兜帽": ["兜帽", "hood"],
        "制服": ["制服", "uniform"],
    },
    "道具": {
        "工具": ["工具", "tools"],
        "数据设备": ["数据板", "终端", "tablet", "terminal"],
        "饮品": ["咖啡", "茶", "coffee", "tea"],
        "武器": ["剑", "枪", "刀", "weapon", "sword", "gun"],
        "书本记录": ["书", "笔记", "记录", "book", "notes"],
    },
    "关系": {
        "双胞胎": ["双胞胎", "双生", "twin", "twins"],
        "兄弟姐妹": ["姐姐", "妹妹", "哥哥", "弟弟", "sister", "brother", "sibling"],
        "搭档": ["搭档", "伙伴", "partner"],
    },
}

HIGH_RISK_WORDS = {"双胞胎", "双生", "twin", "twins", "兄弟姐妹", "相似", "same", "identical"}


def analyze_character_differences(cards: list[CharacterCard], provider: Any | None = None) -> dict[str, Any]:
    if provider and len(cards) >= 2:
        llm_result = analyze_character_differences_with_llm(cards, provider)
        if llm_result:
            return llm_result
    return analyze_character_differences_locally(cards)


def analyze_character_differences_with_llm(cards: list[CharacterCard], provider: Any) -> dict[str, Any] | None:
    system = (
        "你是通用角色差异分析器，服务于小说配图和文生图 prompt。"
        "请只根据用户提供的人设文本分析，不要引入任何外部作品设定或默认角色印象。"
        "目标是找出容易被生图模型画混的角色，并给出可直接写入 prompt 的差异约束。"
        "只输出 JSON，不要 Markdown，不要解释。"
    )
    user = json.dumps(
        {
            "characters": [
                {
                    "name": card.name,
                    "aliases": card.aliases,
                    "role": card.role,
                    "visual_traits": card.visual_traits,
                    "personality_traits": card.personality_traits,
                    "fixed_traits": card.fixed_traits,
                    "variable_states": card.variable_states,
                    "relationships": card.relationships,
                    "source_text": compact(card.source_text, 2200),
                }
                for card in cards
            ],
            "required_schema": {
                "profiles": [
                    {
                        "name": "string",
                        "features": ["identity / appearance / temperament / props / relationship features"],
                        "positive_tags": ["short prompt tags that describe this character only"],
                    }
                ],
                "pairs": [
                    {
                        "left": "character name",
                        "right": "character name",
                        "risk_score": "0-100 integer",
                        "risk_level": "无 | 低 | 中 | 高",
                        "risk_reasons": ["why image models may confuse them"],
                        "shared_features": ["features shared by both"],
                        "left_unique": ["features that distinguish left"],
                        "right_unique": ["features that distinguish right"],
                        "positive_rule": "English prompt sentence that forces these two characters to be distinguishable",
                        "negative_rule": "English negative prompt fragment preventing identity confusion",
                    }
                ],
                "prompt_rules": ["global positive rules for risky pairs"],
            },
        },
        ensure_ascii=False,
    )
    try:
        data = json.loads(provider.text(system, user))
    except (RuntimeError, json.JSONDecodeError, TypeError, AttributeError):
        return None
    normalized = normalize_llm_analysis(data, cards)
    if not normalized["profiles"] and not normalized["pairs"]:
        return None
    normalized["source"] = "llm"
    return normalized


def normalize_llm_analysis(data: dict[str, Any], cards: list[CharacterCard]) -> dict[str, Any]:
    names = {card.name for card in cards}
    profiles = []
    for item in data.get("profiles", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if name not in names:
            continue
        profiles.append(
            {
                "name": name,
                "features": stringify_list(item.get("features")),
                "positive_tags": stringify_list(item.get("positive_tags")),
            }
        )

    pairs = []
    for item in data.get("pairs", []):
        if not isinstance(item, dict):
            continue
        left = str(item.get("left") or "")
        right = str(item.get("right") or "")
        if left not in names or right not in names or left == right:
            continue
        score = clamp_score(item.get("risk_score"))
        pairs.append(
            {
                "left": left,
                "right": right,
                "risk_score": score,
                "risk_level": str(item.get("risk_level") or risk_level(score)),
                "risk_reasons": stringify_list(item.get("risk_reasons")),
                "shared_features": stringify_list(item.get("shared_features")),
                "left_unique": stringify_list(item.get("left_unique")),
                "right_unique": stringify_list(item.get("right_unique")),
                "positive_rule": str(item.get("positive_rule") or build_fallback_positive_rule(left, right)),
                "negative_rule": str(item.get("negative_rule") or build_fallback_negative_rule(left, right)),
            }
        )
    pairs = sorted(pairs, key=lambda item: (-item["risk_score"], item["left"], item["right"]))
    prompt_rules = stringify_list(data.get("prompt_rules")) or [pair["positive_rule"] for pair in pairs if pair["risk_score"] >= 40]
    return {"profiles": profiles, "pairs": pairs, "prompt_rules": prompt_rules[:8]}


def analyze_character_differences_locally(cards: list[CharacterCard]) -> dict[str, Any]:
    profiles = [character_profile(card) for card in cards]
    pairs = [compare_profiles(left, right) for left, right in combinations(profiles, 2)]
    pairs = sorted(pairs, key=lambda item: (-item["risk_score"], item["left"], item["right"]))
    return {
        "source": "local",
        "profiles": profiles,
        "pairs": pairs,
        "prompt_rules": global_prompt_rules(pairs),
    }


def character_profile(card: CharacterCard) -> dict[str, Any]:
    text = "\n".join(
        [
            card.name,
            " ".join(card.aliases),
            card.role,
            card.source_text,
            " ".join(card.visual_traits),
            " ".join(card.personality_traits),
            " ".join(card.fixed_traits),
            " ".join(card.variable_states.values()),
            " ".join(card.relationships.values()),
            card.prompt_cn,
            card.prompt_en,
        ]
    )
    buckets = {
        bucket: [label for label, keywords in labels.items() if contains_any(text, keywords)]
        for bucket, labels in FEATURE_BUCKETS.items()
    }
    all_features = [feature for values in buckets.values() for feature in values]
    return {
        "name": card.name,
        "aliases": card.aliases,
        "role": card.role,
        "buckets": buckets,
        "features": unique_keep_order(all_features),
        "positive_tags": positive_tags(card, buckets),
    }


def compare_profiles(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    shared = sorted(set(left["features"]) & set(right["features"]))
    left_unique = [item for item in left["features"] if item not in shared]
    right_unique = [item for item in right["features"] if item not in shared]
    risk_reasons = risk_reason(left, right, shared)
    risk_score = min(100, 20 * len(shared) + 18 * len(risk_reasons))
    if any(word in " ".join(shared + risk_reasons) for word in HIGH_RISK_WORDS):
        risk_score = max(risk_score, 75)
    return {
        "left": left["name"],
        "right": right["name"],
        "risk_score": risk_score,
        "risk_level": risk_level(risk_score),
        "risk_reasons": risk_reasons,
        "shared_features": shared,
        "left_unique": left_unique[:8],
        "right_unique": right_unique[:8],
        "positive_rule": build_pair_positive_rule(left["name"], right["name"], left_unique, right_unique),
        "negative_rule": build_fallback_negative_rule(left["name"], right["name"]),
    }


def risk_reason(left: dict[str, Any], right: dict[str, Any], shared: list[str]) -> list[str]:
    reasons: list[str] = []
    if shared:
        reasons.append("共享特征：" + "、".join(shared[:6]))
    if "双胞胎" in shared or "兄弟姐妹" in shared:
        reasons.append("亲缘或相似关系容易导致同脸、同发型、同气质")
    if "白大褂" in shared or "制服" in shared:
        reasons.append("服装语境接近，模型可能复用同一套造型")
    if not left["features"] or not right["features"]:
        reasons.append("角色差异信息不足，建议补充外观、道具、姿态或气质差异")
    return unique_keep_order(reasons)


def positive_tags(card: CharacterCard, buckets: dict[str, list[str]]) -> list[str]:
    tags = [card.role]
    tags.extend(feature for values in buckets.values() for feature in values)
    tags.extend(card.fixed_traits)
    return unique_keep_order([tag for tag in tags if tag])[:12]


def build_pair_positive_rule(left: str, right: str, left_unique: list[str], right_unique: list[str]) -> str:
    left_tags = "、".join(left_unique[:5]) or "independent identity, appearance, props, and emotional function"
    right_tags = "、".join(right_unique[:5]) or "independent identity, appearance, props, and emotional function"
    return (
        f"{left} and {right} must be clearly distinguishable. "
        f"{left}: {left_tags}. {right}: {right_tags}. "
        "Use different silhouette, hairstyle, gaze, posture, props, and emotional function."
    )


def build_fallback_positive_rule(left: str, right: str) -> str:
    return (
        f"{left} and {right} must remain individually recognizable with different silhouettes, "
        "hairstyles, outfits, props, poses, and emotional functions."
    )


def build_fallback_negative_rule(left: str, right: str) -> str:
    return (
        f"{left} looking like {right}, {right} looking like {left}, duplicate {left}, duplicate {right}, "
        "same face, same hairstyle, swapped outfits, merged characters"
    )


def global_prompt_rules(pairs: list[dict[str, Any]]) -> list[str]:
    return [pair["positive_rule"] for pair in pairs if pair["risk_score"] >= 40][:6]


def difference_rules_for_names(
    names: list[str],
    cards: list[CharacterCard],
    analysis: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    name_set = set(names)
    source = analysis or analyze_character_differences_locally([card for card in cards if card.name in name_set])
    pairs = [
        pair
        for pair in source.get("pairs", [])
        if pair.get("risk_score", 0) >= 30 and pair.get("left") in name_set and pair.get("right") in name_set
    ]
    return {
        "positive": [str(pair["positive_rule"]) for pair in pairs if pair.get("positive_rule")],
        "negative": [str(pair["negative_rule"]) for pair in pairs if pair.get("negative_rule")],
    }


def contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def stringify_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [compact(str(item), 180) for item in value if str(item).strip()]


def clamp_score(value: Any) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 0


def risk_level(score: int) -> str:
    if score >= 75:
        return "高"
    if score >= 40:
        return "中"
    if score > 0:
        return "低"
    return "无"
