from __future__ import annotations

import html
import json
import re
from typing import Any

from .models import Shot


DEFAULT_HTML_SETTINGS: dict[str, Any] = {
    "font_family": "sans",
    "heading_font_family": "serif",
    "body_font_name": "",
    "heading_font_name": "",
    "font_size": 18,
    "line_height": 1.9,
    "content_width": 920,
    "text_align": "left",
    "paragraph_spacing": 1.0,
}

HTML_IMAGE_POSITIONS = {"before", "after", "left", "right", "inline"}
HTML_IMAGE_ALIGNMENTS = {"left", "center", "right"}
HTML_IMAGE_WRAPS = {"none", "left", "right"}
HTML_IMAGE_WIDTHS = {"auto", "35%", "50%", "65%", "80%", "100%"}
HTML_IMAGE_CUSTOM_WIDTH = re.compile(r"^(?:\d{1,4}(?:\.\d+)?)(?:%|px|rem|em|vw)$")


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
                        f"![{shot.id}]({image_ref})",
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
            lines.extend([f"![{shot.id}]({image_ref})", "", shot.source_excerpt, ""])

    return "\n".join(lines).strip() + "\n"


def render_illustrated_html(
    novel_text: str,
    scenes: list[dict[str, Any]],
    shots: list[Shot],
    run_id: str,
    title: str | None = None,
    html_settings: dict[str, Any] | None = None,
) -> str:
    """Render the same illustrated document as a portable, dependency-free HTML file."""
    markdown = render_illustrated_novel(novel_text, scenes, shots, run_id, title=title)
    document_title = title or extract_title(novel_text)
    layouts = {shot.id: normalize_html_layout(shot.html_layout) for shot in shots}
    return render_html_document(markdown, document_title, html_settings, layouts)


def render_html_document(
    markdown: str,
    title: str,
    html_settings: dict[str, Any] | None = None,
    image_layouts: dict[str, dict[str, Any]] | None = None,
) -> str:
    settings = normalize_html_settings(html_settings)
    body = markdown_to_html(markdown, image_layouts=image_layouts)
    font_family = _font_family_css(settings["font_family"], settings["body_font_name"])
    heading_font_family = _font_family_css(settings["heading_font_family"], settings["heading_font_name"])
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --paper: #f7f8f6;
      --ink: #202629;
      --muted: #687276;
      --rule: #d9dfdd;
      --accent: #267b7c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      background: var(--paper);
      color: var(--ink);
      font-family: {font_family};
      font-size: {settings["font_size"]}px;
      line-height: {settings["line_height"]};
      margin: 0;
    }}
    main {{ margin: 0 auto; max-width: {settings["content_width"]}px; padding: 48px 24px 72px; }}
    h1, h2, h3, h4, h5, h6 {{
      color: var(--ink);
      font-family: {heading_font_family};
      line-height: 1.35;
      margin: 1.8em 0 .7em;
    }}
    h1 {{ border-bottom: 1px solid var(--rule); font-size: 2.2rem; margin-top: 0; padding-bottom: .45em; }}
    h2 {{ font-size: 1.7rem; }}
    h3 {{ font-size: 1.35rem; }}
    p {{ margin: {settings["paragraph_spacing"]}em 0; white-space: pre-wrap; }}
    p, ul, blockquote {{ text-align: {settings["text_align"]}; }}
    ul {{ padding-left: 1.5em; }}
    blockquote {{ border-left: 4px solid var(--accent); color: var(--muted); margin: 1.2em 0; padding: .2em 1em; }}
    figure {{ margin: 2em 0; text-align: center; }}
    figure.image-align-left {{ margin-left: 0; margin-right: auto; text-align: left; }}
    figure.image-align-center {{ margin-left: auto; margin-right: auto; text-align: center; }}
    figure.image-align-right {{ margin-left: auto; margin-right: 0; text-align: right; }}
    figure.image-wrap-left {{ float: left; margin: .6em 1.5em 1em 0; }}
    figure.image-wrap-right {{ float: right; margin: .6em 0 1em 1.5em; }}
    figure.image-inline {{ display: block; }}
    figure.image-after {{ clear: both; }}
    figure img {{ border-radius: 6px; display: block; height: auto; margin: 0 auto; max-width: 100%; }}
    figcaption {{ color: var(--muted); font-size: .9rem; margin-top: .55em; }}
    @media (max-width: 640px) {{
      main {{ padding: 28px 16px 48px; }}
      h1 {{ font-size: 1.8rem; }}
      figure.image-wrap-left, figure.image-wrap-right {{ float: none; margin: 1.4em auto; max-width: 100%; width: 100% !important; }}
    }}
  </style>
</head>
<body>
  <main>
{body}
  </main>
</body>
</html>
'''


def normalize_html_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else {}
    result = dict(DEFAULT_HTML_SETTINGS)
    if source.get("font_family") in {"sans", "serif", "system"}:
        result["font_family"] = source["font_family"]
    if source.get("heading_font_family") in {"sans", "serif", "system"}:
        result["heading_font_family"] = source["heading_font_family"]
    result["body_font_name"] = _safe_font_name(source.get("body_font_name"))
    result["heading_font_name"] = _safe_font_name(source.get("heading_font_name"))
    if source.get("text_align") in {"left", "justify", "center"}:
        result["text_align"] = source["text_align"]
    result["font_size"] = _bounded_number(source.get("font_size"), 14, 30, 18, integer=True)
    result["line_height"] = _bounded_number(source.get("line_height"), 1.3, 2.6, 1.9)
    result["content_width"] = _bounded_number(source.get("content_width"), 560, 1400, 920, integer=True)
    result["paragraph_spacing"] = _bounded_number(source.get("paragraph_spacing"), 0.4, 2.4, 1.0)
    return result


def _safe_font_name(value: Any) -> str:
    name = str(value or "").strip()[:80]
    return name if re.fullmatch(r"[\w .+\-]{1,80}", name) else ""


def _font_family_css(preset: str, custom_name: str = "") -> str:
    stacks = {
        "sans": '"Noto Sans CJK SC", "Microsoft YaHei", "Segoe UI", sans-serif',
        "serif": '"Noto Serif CJK SC", SimSun, STSong, serif',
        "system": 'system-ui, sans-serif',
    }
    fallback = stacks.get(preset, stacks["sans"])
    return f"{json.dumps(custom_name, ensure_ascii=False)}, {fallback}" if custom_name else fallback


def normalize_html_layout(layout: dict[str, Any] | None = None) -> dict[str, Any]:
    source = layout if isinstance(layout, dict) else {}
    raw_position = source.get("position") if source.get("position") in HTML_IMAGE_POSITIONS else "before"
    position = "before" if raw_position in {"left", "right"} else raw_position
    alignment = source.get("alignment") if source.get("alignment") in HTML_IMAGE_ALIGNMENTS else "center"
    legacy_wrap = raw_position if raw_position in {"left", "right"} else "none"
    wrap = source.get("wrap") if source.get("wrap") in HTML_IMAGE_WRAPS else legacy_wrap
    width = str(source.get("width") or "100%")
    if width not in HTML_IMAGE_WIDTHS and not HTML_IMAGE_CUSTOM_WIDTH.fullmatch(width):
        width = "100%"
    caption = str(source.get("caption") or "").strip()[:200]
    return {"position": position, "alignment": alignment, "wrap": wrap, "width": width, "caption": caption}


def _bounded_number(value: Any, minimum: float, maximum: float, fallback: float, integer: bool = False) -> int | float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    number = max(minimum, min(maximum, number))
    return int(number) if integer else round(number, 2)


def markdown_to_html(markdown: str, image_layouts: dict[str, dict[str, Any]] | None = None) -> str:
    """Convert the small Markdown subset produced by the exporter to safe HTML."""
    lines = markdown.replace("\r\n", "\n").split("\n")
    output: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    pending_after: list[str] = []
    layouts = image_layouts or {}
    image_pattern = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)$")
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")
    list_pattern = re.compile(r"^[-*+]\s+(.+)$")

    def flush_paragraph() -> None:
        if paragraph:
            content = "\n".join(paragraph)
            output.append(f"<p>{html.escape(content)}</p>")
            paragraph.clear()
            flush_pending_after()

    def flush_list() -> None:
        if list_items:
            output.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_items) + "</ul>")
            list_items.clear()
            flush_pending_after()

    def flush_pending_after() -> None:
        if pending_after:
            output.extend(pending_after)
            pending_after.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue
        image_match = image_pattern.fullmatch(line)
        if image_match:
            flush_paragraph()
            flush_list()
            alt, source = image_match.groups()
            layout = normalize_html_layout(layouts.get(alt))
            caption = layout["caption"]
            caption_html = f"<figcaption>{html.escape(caption)}</figcaption>" if caption else ""
            alignment_class = f"image-align-{layout['alignment']}"
            wrap_class = f"image-wrap-{layout['wrap']}" if layout["wrap"] != "none" else ""
            figure = (
                '<figure class="image-{position} {alignment_class} {wrap_class}" data-shot-id="{shot_id}" '
                'data-position="{position}" data-alignment="{alignment}" data-wrap="{wrap}" '
                'style="width: {width}"><img src="{source}" alt="{alt}" '
                'loading="lazy">{caption_html}</figure>'
            ).format(
                position=layout["position"],
                alignment=layout["alignment"],
                wrap=layout["wrap"],
                alignment_class=alignment_class,
                wrap_class=wrap_class,
                width=html.escape(layout["width"], quote=True),
                source=html.escape(source, quote=True),
                alt=html.escape(alt, quote=True),
                shot_id=html.escape(alt, quote=True),
                caption_html=caption_html,
            )
            if layout["position"] == "after":
                pending_after.append(figure)
            else:
                output.append(figure)
            continue
        heading_match = heading_pattern.fullmatch(line)
        if heading_match:
            flush_paragraph()
            flush_list()
            level = len(heading_match.group(1))
            output.append(f"<h{level}>{html.escape(heading_match.group(2))}</h{level}>")
            flush_pending_after()
            continue
        list_match = list_pattern.fullmatch(line)
        if list_match:
            flush_paragraph()
            list_items.append(html.escape(list_match.group(1)))
            continue
        if line.startswith("> "):
            flush_paragraph()
            flush_list()
            output.append(f"<blockquote>{html.escape(line[2:])}</blockquote>")
            flush_pending_after()
            continue
        flush_list()
        paragraph.append(raw_line.strip())

    flush_paragraph()
    flush_list()
    flush_pending_after()
    return "\n".join(output)


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
    trailing_blocks: list[str] = []
    scenes_by_id = {str(scene.get("id", "")): scene for scene in scenes}
    for shot in shots:
        image_ref = image_markdown_ref(shot, run_id)
        if not image_ref:
            continue
        scene = scenes_by_id.get(shot.scene_id, {})
        needle = first_scene_anchor(str(scene.get("text", ""))) or first_scene_anchor(shot.source_excerpt)
        if not needle:
            trailing_blocks.append(f"\n\n![{shot.id}]({image_ref})\n\n{shot.source_excerpt}\n")
            continue
        position = body.find(needle)
        if position < 0:
            trailing_blocks.append(f"\n\n![{shot.id}]({image_ref})\n\n{shot.source_excerpt}\n")
            continue
        block = f"\n\n![{shot.id}]({image_ref})\n\n"
        insertions.append((position, block))

    if not insertions:
        return (body + "".join(trailing_blocks)).strip() + "\n"

    result = body
    for position, block in sorted(insertions, reverse=True):
        result = result[:position] + block + result[position:]
    result += "".join(trailing_blocks)
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
        image_url = shot.image_url.split("?", 1)[0]
        prefix = f"/runs/{run_id}/"
        if image_url.startswith(prefix):
            return image_url.removeprefix(prefix)
        return image_url
    if shot.image_path:
        return shot.image_path
    return ""
