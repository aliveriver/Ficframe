from __future__ import annotations

import re

from .models import CharacterCard, Scene
from .text_utils import clean_lines, compact, split_sentences, unique_keep_order


LOCATION_HINTS = {
    "实验室": ["实验室", "实验台", "源石技艺应用科"],
    "罗德岛走廊": ["走廊", "本舰"],
    "休息区": ["休息区", "舰桥"],
    "观景台": ["观景台", "舰尾", "夜风", "星云", "栏杆"],
    "宿舍门口": ["门外", "敲门声"],
}

TIME_HINTS = {
    "清晨": ["清晨", "早安", "晨光", "早餐"],
    "傍晚": ["傍晚"],
    "下午": ["下午"],
    "夜晚": ["夜", "夜空", "灯火", "星云"],
}

MOOD_HINTS = {
    "温柔": ["温柔", "轻轻", "柔和", "照顾"],
    "亲密": ["靠", "指尖", "肩膀", "一起", "陪"],
    "不安": ["害怕", "不安", "颤抖", "偏差", "危险"],
    "疲惫": ["累", "黑眼圈", "忘了", "休息"],
    "希望": ["家", "路", "星云", "灯火", "幸福"],
}


def split_chapter(raw_text: str) -> tuple[str, list[str]]:
    lines = clean_lines(raw_text)
    if not lines:
        return "未命名章节", []
    title = lines[0].strip("《》")
    chunks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            chunks.append("\n".join(current).strip())
            current.clear()

    for line in lines[1:]:
        if re.fullmatch(r"——+", line):
            flush()
            continue
        current.append(line)
        if sum(len(item) for item in current) >= 900:
            flush()
    flush()
    return title, chunks


def detect_characters(text: str, cards: list[CharacterCard]) -> list[str]:
    found = []
    for card in cards:
        names = [card.name, *card.aliases]
        if any(name and name in text for name in names):
            found.append(card.name)
    if "博士" in text:
        found.append("博士")
    return unique_keep_order(found)


def detect_location(text: str) -> str:
    for location, hints in LOCATION_HINTS.items():
        if any(hint in text for hint in hints):
            return location
    return "未明确地点"


def detect_time(text: str) -> str:
    for label, hints in TIME_HINTS.items():
        if any(hint in text for hint in hints):
            return label
    return "未明确时间"


def detect_mood(text: str) -> list[str]:
    moods = [label for label, hints in MOOD_HINTS.items() if any(hint in text for hint in hints)]
    return moods or ["平静"]


def visual_type(text: str, characters: list[str]) -> str:
    if "共振装置" in text or "急停" in text or "警报" in text:
        return "剧情动作瞬间"
    if "星云" in text or "灯火" in text or "舷窗" in text:
        return "环境氛围图"
    if len(characters) >= 2 and any(word in text for word in ["靠", "指尖", "闭上眼睛", "拉住"]):
        return "双人情绪特写"
    if len(characters) >= 2:
        return "双人对话中景"
    return "单人氛围图"


def priority(text: str) -> int:
    score = 1
    for word in ["闭上眼睛", "早餐", "急停", "银鞋子", "家", "靠在他的肩膀", "灯火"]:
        if word in text:
            score += 1
    return min(score, 5)


def make_summary(text: str) -> str:
    sentences = split_sentences(text)
    if len(sentences) <= 2:
        return compact(text, 100)
    return compact("".join(sentences[:2]), 120)


def segment_novel(raw_text: str, cards: list[CharacterCard]) -> list[Scene]:
    chapter, chunks = split_chapter(raw_text)
    scenes: list[Scene] = []
    for index, chunk in enumerate(chunks, start=1):
        chars = detect_characters(chunk, cards)
        scenes.append(
            Scene(
                id=f"ch01_scene_{index:02d}",
                chapter=chapter,
                index=index,
                text=chunk,
                summary=make_summary(chunk),
                characters=chars,
                location=detect_location(chunk),
                time=detect_time(chunk),
                mood=detect_mood(chunk),
                visual_type=visual_type(chunk, chars),
                visual_priority=priority(chunk),
            )
        )
    return scenes
