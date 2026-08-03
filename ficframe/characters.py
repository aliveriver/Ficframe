from __future__ import annotations

import re

from .models import CharacterCard
from .text_utils import clean_lines, compact, unique_keep_order


VISUAL_WORDS = [
    "短发",
    "长发",
    "卷发",
    "直发",
    "眼睛",
    "眼神",
    "笑容",
    "身高",
    "体型",
    "制服",
    "外套",
    "斗篷",
    "白大褂",
    "盔甲",
    "帽子",
    "兜帽",
    "手套",
    "疤痕",
    "耳饰",
    "发饰",
    "纹身",
]

PERSONALITY_WORDS = [
    "温柔",
    "冷静",
    "活泼",
    "沉默",
    "直接",
    "固执",
    "理性",
    "感性",
    "优雅",
    "可靠",
    "谨慎",
    "冲动",
    "行动派",
    "照顾",
    "克制",
    "锐利",
]

ROLE_HINTS = ["身份", "职业", "职位", "阵营", "所属", "角色", "定位", "代号"]
APPEARANCE_HINTS = ["外貌", "发型", "发色", "眼睛", "服装", "穿着", "体型", "身高", "标志"]
PERSONALITY_HINTS = ["性格", "气质", "说话", "口吻", "习惯", "态度"]
FIXED_HINTS = ["固定", "禁止变化", "不能变", "必须", "始终", "保持"]
PROP_HINTS = ["道具", "武器", "装备", "工具", "随身", "拿着", "持有"]
RELATION_HINTS = ["关系", "亲属", "朋友", "同事", "恋人", "姐姐", "妹妹", "哥哥", "弟弟", "双胞胎", "搭档"]


def infer_primary_name(text: str) -> str:
    heading = re.search(r"(?m)^#{1,3}\s+(.+?)\s*$", text.strip())
    if heading and heading.group(1).strip() not in {"角色总览", "人物总览"}:
        return heading.group(1).strip()
    match = re.search(r"(?m)^([^，,\n：:]{1,30})[，,：:]\s*(?:本名|真名|代号)\s*([^，,\n]+)", text.strip())
    if match:
        return match.group(1).strip()
    lines = clean_lines(text)
    first_line = lines[0] if lines else "未命名角色"
    if "：" in first_line:
        return first_line.split("：", 1)[0].strip()
    if ":" in first_line:
        return first_line.split(":", 1)[0].strip()
    return first_line[:12].strip() or "未命名角色"


def extract_aliases(text: str, name: str) -> list[str]:
    aliases: list[str] = []
    for pattern in [r"本名\s*([^，,\n]+)", r"真名\s*([^，,\n]+)", r"别名\s*([^，,\n]+)", r"代号\s*([^，,\n]+)"]:
        for match in re.findall(pattern, text):
            aliases.extend(split_inline_values(match))
    return [alias for alias in unique_keep_order(aliases) if alias != name]


def extract_relationships(lines: list[str]) -> dict[str, str]:
    relationships: dict[str, str] = {}
    for line in lines:
        key, value = split_labeled_line(line)
        if not key or not value:
            continue
        if any(hint in key or hint in value for hint in RELATION_HINTS):
            relationships[key] = value
    return relationships


def extract_reference_images(text: str, name: str) -> list[str]:
    images: list[str] = []
    for alt, target in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", text):
        if not alt or name in alt or alt in name or "参考" in alt or "人设" in alt:
            images.append(target.strip())
    return unique_keep_order(images)


def split_character_blocks(raw_text: str) -> list[str]:
    heading_matches = [
        match
        for match in re.finditer(r"(?m)^#{1,3}\s+(.+?)\s*$", raw_text)
        if match.group(1).strip() not in {"角色总览", "人物总览"}
    ]
    if len(heading_matches) > 1:
        blocks = []
        for index, match in enumerate(heading_matches):
            end = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(raw_text)
            blocks.append(raw_text[match.start() : end].strip())
        return blocks

    identity_matches = list(re.finditer(r"(?m)^([^，,\n：:]{1,30})[，,：:]\s*(?:本名|真名|代号)\s*[^，,\n]+", raw_text))
    if len(identity_matches) > 1:
        blocks = []
        for index, match in enumerate(identity_matches):
            end = identity_matches[index + 1].start() if index + 1 < len(identity_matches) else len(raw_text)
            blocks.append(raw_text[match.start() : end].strip())
        return blocks

    return [raw_text]


def build_one_character_card(raw_text: str) -> CharacterCard:
    lines = clean_lines(raw_text)
    whole = "\n".join(lines)
    name = infer_primary_name(whole)
    aliases = extract_aliases(whole, name)
    role = extract_role(lines, name)
    visual_traits = extract_bucket(lines, APPEARANCE_HINTS, VISUAL_WORDS)
    personality_traits = extract_bucket(lines, PERSONALITY_HINTS, PERSONALITY_WORDS)
    fixed_traits = extract_fixed_traits(lines)
    variable_states = extract_variable_states(lines)
    prompt_cn = build_prompt_cn(name, role, visual_traits, personality_traits, fixed_traits, variable_states)
    prompt_en = build_prompt_en(name, role, visual_traits, personality_traits, fixed_traits, variable_states)

    return CharacterCard(
        name=name,
        aliases=aliases,
        role=role,
        source_text=compact(whole, 3000),
        visual_traits=visual_traits,
        personality_traits=personality_traits,
        fixed_traits=fixed_traits,
        variable_states=variable_states,
        relationships=extract_relationships(lines),
        reference_images=extract_reference_images(whole, name),
        prompt_cn=prompt_cn,
        prompt_en=prompt_en,
    )


def extract_role(lines: list[str], name: str) -> str:
    role_parts: list[str] = []
    for line in lines:
        key, value = split_labeled_line(line)
        if value and any(hint in key for hint in ROLE_HINTS):
            role_parts.extend(split_inline_values(value))
    if role_parts:
        return " / ".join(unique_keep_order(role_parts)[:4])
    for line in lines[:3]:
        if name in line and len(line) <= 160:
            return compact(line.replace(name, "").strip(" ，,:：-"), 80)
    return f"{name} 的角色卡"


def extract_bucket(lines: list[str], label_hints: list[str], keyword_hints: list[str]) -> list[str]:
    traits: list[str] = []
    whole = "\n".join(lines)
    for line in lines:
        key, value = split_labeled_line(line)
        if value and any(hint in key for hint in label_hints):
            traits.extend(split_inline_values(value))
    traits.extend(word for word in keyword_hints if word in whole)
    return unique_keep_order([compact(trait, 40) for trait in traits if trait])[:16]


def extract_fixed_traits(lines: list[str]) -> list[str]:
    traits: list[str] = []
    for line in lines:
        key, value = split_labeled_line(line)
        if value and any(hint in key for hint in FIXED_HINTS):
            traits.extend(split_inline_values(value))
        elif any(hint in line for hint in FIXED_HINTS):
            traits.append(line.strip("-• "))
    return unique_keep_order([compact(trait, 70) for trait in traits if trait])[:12]


def extract_variable_states(lines: list[str]) -> dict[str, str]:
    states: dict[str, str] = {}
    appearance = extract_labeled_values(lines, APPEARANCE_HINTS)
    personality = extract_labeled_values(lines, PERSONALITY_HINTS)
    props = extract_labeled_values(lines, PROP_HINTS)
    if appearance:
        states["appearance"] = compact("；".join(appearance), 180)
    if personality:
        states["personality"] = compact("；".join(personality), 180)
    if props:
        states["props"] = compact("；".join(props), 180)
    return states


def extract_labeled_values(lines: list[str], hints: list[str]) -> list[str]:
    values: list[str] = []
    for line in lines:
        key, value = split_labeled_line(line)
        if value and any(hint in key for hint in hints):
            values.append(value)
    return unique_keep_order(values)


def build_prompt_cn(
    name: str,
    role: str,
    visual_traits: list[str],
    personality_traits: list[str],
    fixed_traits: list[str],
    variable_states: dict[str, str],
) -> str:
    parts = [name, role, *visual_traits[:8], *personality_traits[:6], *fixed_traits[:5], *variable_states.values()]
    return "，".join(unique_keep_order([part for part in parts if part]))


def build_prompt_en(
    name: str,
    role: str,
    visual_traits: list[str],
    personality_traits: list[str],
    fixed_traits: list[str],
    variable_states: dict[str, str],
) -> str:
    parts = [
        name,
        f"role: {role}" if role else "",
        "visual traits: " + ", ".join(visual_traits[:8]) if visual_traits else "",
        "personality: " + ", ".join(personality_traits[:6]) if personality_traits else "",
        "fixed design: " + ", ".join(fixed_traits[:5]) if fixed_traits else "",
        "state details: " + "; ".join(variable_states.values()) if variable_states else "",
        "consistent individual character design",
    ]
    return "; ".join(part for part in parts if part)


def split_labeled_line(line: str) -> tuple[str, str]:
    normalized = line.strip().lstrip("-•").strip()
    for separator in ["：", ":"]:
        if separator in normalized:
            key, value = normalized.split(separator, 1)
            return key.strip(), value.strip()
    return "", ""


def split_inline_values(text: str) -> list[str]:
    values = re.split(r"[、,，;；/｜|]", text)
    return [value.strip() for value in values if value.strip()]


def build_character_cards(raw_text: str) -> list[CharacterCard]:
    cards = [build_one_character_card(block) for block in split_character_blocks(raw_text) if block.strip()]
    unique: list[CharacterCard] = []
    seen: set[str] = set()
    for card in cards:
        if card.name not in seen:
            seen.add(card.name)
            unique.append(card)
    return unique or [build_one_character_card(raw_text)]
