from __future__ import annotations

import re

from .models import CharacterCard, Scene
from .text_utils import clean_lines, compact, split_sentences, unique_keep_order


CHAPTER_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s*)?(?:"
    r"第[一二三四五六七八九十百千万零〇两\d]+[章节卷回幕部篇].*"
    r"|Chapter\s+\d+.*"
    r"|CHAPTER\s+\d+.*"
    r")$"
)

LOCATION_HINTS = {
    "实验室": ["实验室", "实验台", "研究室", "工作台"],
    "走廊": ["走廊", "过道"],
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


def is_chapter_heading(line: str) -> bool:
    text = line.strip()
    return bool(text and CHAPTER_HEADING_RE.match(text))


def normalize_heading(line: str) -> str:
    return line.strip().lstrip("#").strip(" 《》")


def split_chunks(lines: list[str], target_chars: int = 900) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            chunks.append("\n".join(current).strip())
            current.clear()

    for line in lines:
        if re.fullmatch(r"[-—=]{3,}", line):
            flush()
            continue
        current.append(line)
        if sum(len(item) for item in current) >= target_chars:
            flush()
    flush()
    return chunks


def split_novel_chapters(raw_text: str) -> list[tuple[str, list[str]]]:
    lines = clean_lines(raw_text)
    if not lines:
        return []

    chapters: list[tuple[str, list[str]]] = []
    current_title = "未命名章节"
    current_lines: list[str] = []
    found_heading = False

    def flush() -> None:
        nonlocal current_lines
        if current_lines:
            chapters.append((current_title, split_chunks(current_lines)))
            current_lines = []

    for line in lines:
        if is_chapter_heading(line):
            if found_heading:
                flush()
            elif current_lines:
                chapters.append(("序章", split_chunks(current_lines)))
                current_lines = []
            current_title = normalize_heading(line)
            found_heading = True
            continue
        current_lines.append(line)

    if found_heading:
        flush()
        return chapters

    return [(normalize_heading(lines[0]), split_chunks(lines[1:]))]


def split_chapter(raw_text: str) -> tuple[str, list[str]]:
    chapters = split_novel_chapters(raw_text)
    if not chapters:
        return "未命名章节", []
    return chapters[0]


def detect_characters(text: str, cards: list[CharacterCard]) -> list[str]:
    found = []
    for card in cards:
        names = [card.name, *card.aliases]
        if any(name and name in text for name in names):
            found.append(card.name)
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
    if len(characters) >= 3:
        return "多人关系中景"
    if len(characters) >= 2 and any(word in text for word in ["靠", "指尖", "闭上眼睛", "拉住"]):
        return "双人情绪特写"
    if len(characters) >= 2:
        return "双人对话中景"
    return "单人氛围图"


def priority(text: str) -> int:
    score = 1
    for word in ["闭上眼睛", "早餐", "急停", "银靴子", "家", "靠在他的肩膀", "灯火"]:
        if word in text:
            score += 1
    return min(score, 5)


def make_summary(text: str) -> str:
    sentences = split_sentences(text)
    if len(sentences) <= 2:
        return compact(text, 100)
    return compact("".join(sentences[:2]), 120)


def segment_novel(raw_text: str, cards: list[CharacterCard]) -> list[Scene]:
    scenes: list[Scene] = []
    scene_index = 1
    for chapter_index, (chapter, chunks) in enumerate(split_novel_chapters(raw_text), start=1):
        for chunk_index, chunk in enumerate(chunks, start=1):
            chars = detect_characters(chunk, cards)
            scenes.append(
                Scene(
                    id=f"ch{chapter_index:02d}_scene_{chunk_index:02d}",
                    chapter=chapter,
                    index=scene_index,
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
            scene_index += 1
    return scenes
