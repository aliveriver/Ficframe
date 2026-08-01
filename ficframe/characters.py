from __future__ import annotations

import re

from .models import CharacterCard
from .text_utils import clean_lines, unique_keep_order


VISUAL_WORDS = [
    "温柔",
    "亲切",
    "大姐姐",
    "笑容",
    "眼睛",
    "头发",
    "白大褂",
    "毛衣",
    "外套",
    "身高",
    "札拉克",
    "咖啡",
]

PERSONALITY_WORDS = [
    "温柔",
    "照顾",
    "理想主义",
    "偏执",
    "救赎欲",
    "聪明",
    "勤奋",
    "共情",
    "外柔内刚",
    "伦理边界模糊",
]


def infer_primary_name(text: str) -> str:
    heading = re.search(r"(?m)^#{1,3}\s+(.+?)\s*$", text.strip())
    if heading and heading.group(1).strip() not in {"角色总览", "人物总览"}:
        return heading.group(1).strip()
    match = re.search(r"(?m)^([^，,\n]+)，本名\s*([^，,\n]+)", text.strip())
    if match:
        return match.group(1).strip()
    lines = clean_lines(text)
    for line in lines:
        if line.endswith("人设一句话") and len(lines) > lines.index(line) + 1:
            candidate = lines[lines.index(line) + 1].split("是", 1)[0].strip()
            if candidate:
                return candidate
    first_line = lines[0] if lines else "未命名角色"
    if "：" in first_line:
        return first_line.split("：", 1)[0].strip()
    return first_line[:12].strip() or "未命名角色"


def extract_relationships(lines: list[str]) -> dict[str, str]:
    relationships: dict[str, str] = {}
    relation_names = ["博士", "赫默", "星源", "埃琳娜", "塞雷娅", "斐尔迪南", "克丽斯腾"]
    for line in lines:
        for name in relation_names:
            if line.startswith(f"{name}：") or line.startswith(f"{name}:"):
                relationships[name] = line.split("：", 1)[-1].strip()
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

    identity_matches = list(re.finditer(r"(?m)^([^，,\n]{1,30})，本名\s*[^，,\n]+", raw_text))
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
    aliases = []
    alias_match = re.search(r"本名\s*([^，,\n]+)", whole)
    if alias_match:
        aliases.append(alias_match.group(1).strip())

    visual_traits = unique_keep_order([word for word in VISUAL_WORDS if word in whole])
    personality_traits = unique_keep_order([word for word in PERSONALITY_WORDS if word in whole])

    fixed_traits = [
        "同一张脸与年龄感",
        "温柔、亲切但带有隐藏执念的气质",
        "研究者身份与罗德岛/莱茵生命语境",
    ]
    if "身高 170cm" in whole or "身高170cm" in whole:
        fixed_traits.append("170cm 左右的修长身形")
    if "白大褂" in whole:
        fixed_traits.append("实验室场景中常穿白大褂")

    variable_states = {
        "outfit": "根据剧情在白大褂、浅米色毛衣、罗德岛外套之间变化",
        "emotion": "温柔关心、轻微不好意思、理想主义的不安、安静依赖",
        "props": "咖啡、实验记录、共振装置、保温袋、童话书或银鞋子意象",
    }

    prompt_cn = "，".join(
        [
            name,
            "温柔的女性研究者",
            "莱茵生命源石技艺应用科主任",
            "亲切的大姐姐气质",
            "笑容柔和",
            "带有理想主义与隐约危险感",
            "干净细致的实验室服装",
        ]
    )
    prompt_en = (
        f"{name}, gentle female researcher, warm elder-sister aura, soft smile, "
        "Rhine Lab scientist, idealistic and quietly intense, clean detailed lab outfit, "
        "consistent face and body proportions"
    )

    return CharacterCard(
        name=name,
        aliases=aliases,
        role="源石技艺应用科主任 / 温柔但危险的理想主义科学家",
        visual_traits=visual_traits,
        personality_traits=personality_traits,
        fixed_traits=fixed_traits,
        variable_states=variable_states,
        relationships=extract_relationships(lines),
        reference_images=extract_reference_images(whole, name),
        prompt_cn=prompt_cn,
        prompt_en=prompt_en,
    )


def build_character_cards(raw_text: str) -> list[CharacterCard]:
    cards = [build_one_character_card(block) for block in split_character_blocks(raw_text) if block.strip()]
    unique: list[CharacterCard] = []
    seen: set[str] = set()
    for card in cards:
        if card.name not in seen:
            seen.add(card.name)
            unique.append(card)
    return unique or [build_one_character_card(raw_text)]
