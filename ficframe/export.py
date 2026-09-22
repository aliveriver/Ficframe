from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .io import write_json, write_text
from .models import Shot
from .render import extract_title, normalize_html_settings, render_html_document, render_illustrated_html, render_illustrated_novel


EXPORT_SCHEMA_VERSION = 1


THEME_JSON: dict[str, Any] = {
    "schema_version": 1,
    "name": "FicFrame 默认图文主题",
    "font_family": ["Noto Sans CJK SC", "Microsoft YaHei", "Segoe UI", "sans-serif"],
    "heading_font_family": ["Noto Serif CJK SC", "SimSun", "STSong", "serif"],
    "image_max_width": "100%",
    "image_alignment": "center",
    "note": "字体使用阅读设备或 Markdown/HTML 渲染器中的可用字体，不在导出包中嵌入字体文件。",
}


THEME_MARKDOWN = """# FicFrame 图文导出主题说明

## 字体

本导出包不嵌入字体文件，以避免字体授权和跨平台兼容问题。建议正文优先使用 `Noto Sans CJK SC`、`Microsoft YaHei` 或系统无衬线字体，标题优先使用 `Noto Serif CJK SC`、`SimSun` 或其他中文衬线字体。

## 图片

- 图片位于 `images/` 目录。
- Markdown 中的图片引用使用相对路径，移动整个导出目录后仍可正常显示。
- HTML 中的图片位置、宽度、图注和正文排版由当前 run 的 HTML 导出设置控制。
- 默认图片宽度为容器宽度的 `100%`，建议在阅读器中居中显示。

## 使用方式

请将 `illustrated_novel.md`、`illustrated_novel.html`、`images/`、`manifest.json` 和本说明文件保存在同一目录。需要迁移、备份或发布时，优先使用 ZIP 成品包以确保目录结构完整。
"""


@dataclass(frozen=True)
class ExportBundle:
    run_id: str
    markdown: str
    html: str
    markdown_path: Path
    html_path: Path
    export_dir: Path
    images_dir: Path
    manifest_path: Path
    theme_path: Path
    theme_json_path: Path
    zip_path: Path
    manifest: dict[str, Any]

    def info(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "markdown_path": str(self.markdown_path),
            "markdown_url": f"/runs/{self.run_id}/illustrated_novel.md",
            "export_markdown_url": f"/runs/{self.run_id}/export/illustrated_novel.md",
            "html_path": str(self.html_path),
            "html_url": f"/runs/{self.run_id}/illustrated_novel.html",
            "export_html_url": f"/runs/{self.run_id}/export/illustrated_novel.html",
            "export_dir": str(self.export_dir),
            "images_dir": str(self.images_dir),
            "images_url": f"/runs/{self.run_id}/export/images/",
            "manifest_path": str(self.manifest_path),
            "manifest_url": f"/runs/{self.run_id}/export/manifest.json",
            "theme_path": str(self.theme_path),
            "theme_url": f"/runs/{self.run_id}/export/THEME.md",
            "theme_json_path": str(self.theme_json_path),
            "zip_path": str(self.zip_path),
            "zip_url": f"/api/export/{self.run_id}.zip",
            "html_settings": self.manifest.get("html_settings", {}),
            "manifest": self.manifest,
        }


def build_export_bundle(
    run_dir: str | Path,
    run_id: str,
    novel_text: str,
    scenes: list[dict[str, Any]],
    shots: list[Shot],
    html_settings: dict[str, Any] | None = None,
) -> ExportBundle:
    """Build the portable Markdown directory and ZIP from one run snapshot."""
    run_root = Path(run_dir).resolve()
    export_dir = run_root / "export"
    images_dir = export_dir / "images"
    export_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    markdown = render_illustrated_novel(novel_text, scenes, shots, run_id)
    normalized_html_settings = normalize_html_settings(html_settings)
    html_document = render_illustrated_html(
        novel_text, scenes, shots, run_id, html_settings=normalized_html_settings
    )
    markdown_path = run_root / "illustrated_novel.md"
    html_path = run_root / "illustrated_novel.html"
    write_text(markdown_path, markdown)
    write_text(html_path, html_document)
    write_text(export_dir / "illustrated_novel.md", markdown)
    write_text(export_dir / "illustrated_novel.html", html_document)

    image_entries: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for shot in shots:
        entry = _copy_current_image(run_root, images_dir, run_id, shot, used_names)
        image_entries.append(entry)
    expected_names = {
        Path(str(item["path"])).name
        for item in image_entries
        if item.get("available") and item.get("path")
    }
    # `export/` is a generated projection. Remove stale generated images so
    # the directory and the manifest always describe the same artifact.
    for existing in images_dir.iterdir():
        if existing.is_file() and existing.name not in expected_names:
            existing.unlink()

    # A collision is unusual for generated shot files, but can happen after a
    # user imports assets. Keep Markdown links aligned with the copied names.
    replacements = [
        item for item in image_entries
        if item.get("shot_id") and item.get("original_markdown_path") and item.get("path")
        and item["original_markdown_path"] != item["path"]
    ]
    if replacements:
        for item in replacements:
            old = str(item["original_markdown_path"])
            new = str(item["path"])
            marker = f"![{item['shot_id']}]({old})"
            markdown = markdown.replace(marker, f"![{item['shot_id']}]({new})", 1)
        write_text(markdown_path, markdown)
        write_text(export_dir / "illustrated_novel.md", markdown)
        layouts = {shot.id: shot.html_layout for shot in shots}
        html_document = render_html_document(
            markdown,
            extract_title(novel_text),
            normalized_html_settings,
            layouts,
        )
        write_text(html_path, html_document)
        write_text(export_dir / "illustrated_novel.html", html_document)

    manifest = _build_manifest(run_id, novel_text, shots, image_entries, normalized_html_settings)
    manifest_path = export_dir / "manifest.json"
    theme_path = export_dir / "THEME.md"
    theme_json_path = export_dir / "theme.json"
    write_json(manifest_path, manifest)
    write_text(theme_path, THEME_MARKDOWN)
    write_json(theme_json_path, THEME_JSON)

    zip_path = export_dir / f"illustrated_novel-{run_id}.zip"
    _write_zip(zip_path, export_dir, manifest)
    return ExportBundle(
        run_id=run_id,
        markdown=markdown,
        html=html_document,
        markdown_path=markdown_path,
        html_path=html_path,
        export_dir=export_dir,
        images_dir=images_dir,
        manifest_path=manifest_path,
        theme_path=theme_path,
        theme_json_path=theme_json_path,
        zip_path=zip_path,
        manifest=manifest,
    )


def _copy_current_image(
    run_root: Path,
    images_dir: Path,
    run_id: str,
    shot: Shot,
    used_names: set[str],
) -> dict[str, Any]:
    source = _local_image_path(run_root, run_id, shot)
    original_ref = _markdown_image_ref(shot, run_id)
    relative_source = ""
    if source is not None:
        try:
            relative_source = source.relative_to(run_root).as_posix()
        except ValueError:
            relative_source = source.name
    item: dict[str, Any] = {
        "shot_id": shot.id,
        "image_url": shot.image_url or "",
        "source_path": relative_source,
        "original_markdown_path": f"images/{Path(original_ref).name}" if original_ref and not original_ref.startswith(("http://", "https://")) else "",
        "path": "",
        "available": False,
    }
    if source is None or not source.is_file():
        item["warning"] = "当前图片文件不存在，Markdown 保留原始引用。"
        return item

    filename = source.name
    if filename in used_names:
        filename = f"{shot.id}-{filename}"
    used_names.add(filename)
    target = images_dir / filename
    shutil.copy2(source, target)
    item.update({
        "path": f"images/{filename}",
        "available": True,
        "size_bytes": target.stat().st_size,
        "sha256": _sha256(target),
        "mime_type": _guess_mime(target),
    })
    return item


def _local_image_path(run_root: Path, run_id: str, shot: Shot) -> Path | None:
    candidates: list[Path] = []
    if shot.image_path:
        raw = Path(str(shot.image_path))
        candidates.append(raw if raw.is_absolute() else run_root / raw)
    if shot.image_url:
        parsed = urlparse(str(shot.image_url))
        path = parsed.path
        prefix = f"/runs/{run_id}/"
        if path.startswith(prefix):
            candidates.append(run_root / path.removeprefix(prefix))
        elif path and not parsed.scheme and not path.startswith("/api/"):
            candidates.append(run_root / path.lstrip("/"))
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if run_root == resolved or run_root in resolved.parents:
            if resolved.is_file():
                return resolved
    return None


def _markdown_image_ref(shot: Shot, run_id: str) -> str:
    if shot.image_url:
        image_url = str(shot.image_url).split("?", 1)[0]
        prefix = f"/runs/{run_id}/"
        if image_url.startswith(prefix):
            return image_url.removeprefix(prefix)
        return image_url
    return str(shot.image_path or "")


def _build_manifest(
    run_id: str,
    novel_text: str,
    shots: list[Shot],
    image_entries: list[dict[str, Any]],
    html_settings: dict[str, Any],
) -> dict[str, Any]:
    available = [item for item in image_entries if item.get("available")]
    missing = [item["shot_id"] for item in image_entries if not item.get("available")]
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "format": "ficframe-export",
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "title": extract_title(novel_text),
        "files": {
            "markdown": "illustrated_novel.md",
            "html": "illustrated_novel.html",
            "images_dir": "images/",
            "manifest": "manifest.json",
            "theme": "THEME.md",
            "theme_json": "theme.json",
        },
        "shot_count": len(shots),
        "image_count": len(available),
        "missing_image_shot_ids": missing,
        "images": available,
        "missing_images": [item for item in image_entries if not item.get("available")],
        "html_settings": html_settings,
        "theme": THEME_JSON,
    }


def _write_zip(zip_path: Path, export_dir: Path, manifest: dict[str, Any]) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in ("illustrated_novel.md", "illustrated_novel.html", "manifest.json", "THEME.md", "theme.json"):
            path = export_dir / relative
            if path.is_file():
                archive.write(path, arcname=relative)
        for item in manifest.get("images", []):
            relative = str(item.get("path") or "")
            path = export_dir / relative
            if relative and path.is_file():
                archive.write(path, arcname=relative)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".avif": "image/avif",
        ".png": "image/png",
    }.get(suffix, "application/octet-stream")
