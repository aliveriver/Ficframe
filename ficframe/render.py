from __future__ import annotations

from typing import Any

from .models import Shot


def render_storyboard(shots: list[Shot]) -> str:
    lines = ["# 分镜表", ""]
    for shot in shots:
        lines.extend(
            [
                f"## {shot.id} {shot.title}",
                "",
                f"- 场景：`{shot.scene_id}`",
                f"- 角色：{', '.join(shot.characters) if shot.characters else '无明确角色'}",
                f"- 地点 / 时间：{shot.location} / {shot.time}",
                f"- 情绪：{', '.join(shot.mood)}",
                f"- 镜头：{shot.camera}",
                f"- 构图：{shot.composition}",
                f"- 画面目标：{shot.visual_goal}",
                f"- 原文摘录：{shot.source_excerpt}",
                "",
            ]
        )
    return "\n".join(lines)


def render_prompts(shots: list[Shot]) -> str:
    lines = ["# 生图 Prompts", ""]
    for shot in shots:
        lines.extend(
            [
                f"## {shot.id} {shot.title}",
                "",
                "### Positive",
                "",
                shot.positive_prompt,
                "",
                "### Negative",
                "",
                shot.negative_prompt,
                "",
                "### Continuity",
                "",
                "\n".join(f"- {note}" for note in shot.continuity_notes) or "- 无",
                "",
                "### QA",
                "",
                "\n".join(f"- {note}" for note in shot.qa_notes) or "- 无",
                "",
            ]
        )
    return "\n".join(lines)


def render_illustrated_markdown(shots: list[Shot], title: str = "FicFrame 图文导出") -> str:
    lines = [f"# {title}", ""]
    for shot in shots:
        lines.extend([f"## {shot.id} {shot.title}", ""])
        if shot.image_url:
            lines.extend([f"![{shot.id}]({shot.image_url})", ""])
        elif shot.image_path:
            lines.extend([f"![{shot.id}]({shot.image_path})", ""])
        else:
            lines.extend(["> 未生成图片", ""])
        lines.extend(
            [
                f"**角色**：{', '.join(shot.characters) if shot.characters else '无明确角色'}",
                "",
                f"**场景**：{shot.location} / {shot.time}",
                "",
                f"**画面目标**：{shot.visual_goal}",
                "",
                f"**原文摘录**：{shot.source_excerpt}",
                "",
                "<details>",
                "<summary>Prompt</summary>",
                "",
                "```text",
                shot.positive_prompt,
                "```",
                "",
                "</details>",
                "",
            ]
        )
    return "\n".join(lines)


def render_illustrated_novel(
    novel_text: str,
    scenes: list[dict[str, Any]],
    shots: list[Shot],
    run_id: str,
    title: str | None = None,
) -> str:
    inserted = insert_images_into_original_text(novel_text, scenes, shots, run_id)
    if inserted:
        return inserted

    lines = [f"# {title or extract_title(novel_text)}", ""]
    shots_by_scene = {shot.scene_id: shot for shot in shots}
    used_scene_ids: set[str] = set()

    for scene in sorted(scenes, key=lambda item: item.get("index", 0)):
        scene_id = str(scene.get("id", ""))
        shot = shots_by_scene.get(scene_id)
        if shot:
            image_ref = image_markdown_ref(shot, run_id)
            if image_ref:
                lines.extend(
                    [
                        f"![{shot.id} {shot.title}]({image_ref})",
                        "",
                        f"*{shot.visual_goal}*",
                        "",
                    ]
                )
            used_scene_ids.add(scene_id)
        text = str(scene.get("text", "")).strip()
        if text:
            lines.extend([text, ""])

    for shot in shots:
        if shot.scene_id in used_scene_ids:
            continue
        image_ref = image_markdown_ref(shot, run_id)
        if image_ref:
            lines.extend([f"![{shot.id} {shot.title}]({image_ref})", "", shot.source_excerpt, ""])

    return "\n".join(lines).strip() + "\n"


def insert_images_into_original_text(
    novel_text: str,
    scenes: list[dict[str, Any]],
    shots: list[Shot],
    run_id: str,
) -> str:
    body = novel_text.replace("\r\n", "\n").strip()
    if not body:
        return ""
    insertions: list[tuple[int, str]] = []
    scenes_by_id = {str(scene.get("id", "")): scene for scene in scenes}
    for shot in shots:
        image_ref = image_markdown_ref(shot, run_id)
        if not image_ref:
            continue
        scene = scenes_by_id.get(shot.scene_id, {})
        needle = first_scene_anchor(str(scene.get("text", ""))) or first_scene_anchor(shot.source_excerpt)
        if not needle:
            continue
        position = body.find(needle)
        if position < 0:
            continue
        block = f"\n\n![{shot.id} {shot.title}]({image_ref})\n\n*{shot.visual_goal}*\n\n"
        insertions.append((position, block))

    if not insertions:
        return body.strip() + "\n"

    result = body
    for position, block in sorted(insertions, reverse=True):
        result = result[:position] + block + result[position:]
    return result.strip() + "\n"


def first_scene_anchor(text: str) -> str:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return ""
    for line in normalized.split("\n"):
        stripped = line.strip()
        if len(stripped) >= 12:
            return stripped[: min(len(stripped), 80)]
    return normalized[: min(len(normalized), 80)]


def extract_title(novel_text: str) -> str:
    for line in novel_text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip().strip("《》")
        if stripped:
            return stripped
    return "FicFrame 图文小说"


def image_markdown_ref(shot: Shot, run_id: str) -> str:
    if shot.image_url:
        prefix = f"/runs/{run_id}/"
        if shot.image_url.startswith(prefix):
            return shot.image_url.removeprefix(prefix)
        return shot.image_url
    if shot.image_path:
        return shot.image_path
    return ""
