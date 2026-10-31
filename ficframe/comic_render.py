"""Pillow comic rendering and portable, validated project archives.

Resolvers receive a validated relative POSIX asset path and return bytes, a local
Path, a binary stream, or a PIL image (images are accepted for rendering only).
Preview callers should encode ``render_page`` directly; text inspection uses the
same layout routine. No function modifies the supplied project or layout.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import stat
import zlib
import unicodedata
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps, PngImagePlugin

from .runtime_paths import web_root

SCHEMA_VERSION = 1
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_FILES = 4096
MAX_PAGE_PIXELS = 32_000_000
STRIP_MAX_HEIGHT = 8192
_MODES = {"text", "blank", "clean"}
_KINDS = {"dialogue", "narration", "sfx"}


def _number(value: Any, default: float = 0) -> float:
    number = float(default if value is None else value)
    if not math.isfinite(number):
        raise ValueError("Non-finite layout number")
    return number


def _path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("Invalid asset/archive path")
    if value.startswith("/") or "\\" in value or ":" in value:
        raise ValueError("Only relative POSIX paths are allowed")
    parts = value.split("/")
    for part in parts:
        if part in {"", ".", ".."} or part.endswith((" ", ".")):
            raise ValueError("Unsafe path component")
        if any(ord(c) < 32 or c in '<>\"|?*' for c in part):
            raise ValueError("Unsafe path character")
        if part.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
            raise ValueError("Reserved path component")
    return value


def _validate_project(project: dict) -> None:
    if not isinstance(project, dict) or type(project.get("schema_version")) is not int or project["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported project schema_version")
    if not isinstance(project.get("pages"), list):
        raise ValueError("Project pages must be a list")
    ids = []
    for page in project["pages"]:
        if not isinstance(page, dict) or not isinstance(page.get("panels", []), list):
            raise ValueError("Invalid page")
        if not isinstance(page.get("id"), str) or not page["id"]:
            raise ValueError("Page id is required")
        ids.append(page["id"])
        _size(page)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate page ids")


def _size(page: dict) -> tuple[int, int]:
    width, height = int(_number(page.get("width"), 1200)), int(_number(page.get("height"), 1700))
    if width < 1 or height < 1 or width * height > MAX_PAGE_PIXELS or max(width, height) > 32768:
        raise ValueError("Page dimensions exceed rendering limits")
    return width, height


def _rect(rect: dict, width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = (_number(rect.get(k), d) for k, d in (("x", 0), ("y", 0), ("w", 1), ("h", 1)))
    if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1.000001 or y + h > 1.000001:
        raise ValueError("Rect must fit in normalized parent coordinates")
    return round(x * width), round(y * height), max(1, round(w * width)), max(1, round(h * height))


def _mode(project: dict, page: dict, panel: dict, override: str | None) -> str:
    if override is not None:
        if override not in _MODES:
            raise ValueError("Unknown lettering mode")
        return override
    result = "text"
    for obj in (project, page, panel):
        value = obj.get("lettering_mode", "inherit")
        if value != "inherit":
            if value not in _MODES:
                raise ValueError("Unknown lettering mode")
            result = value
    return result


@lru_cache(maxsize=64)
def _font(size: int, variant: str = "noto") -> ImageFont.FreeTypeFont:
    path = web_root() / "fonts" / "NotoSansSC.ttf"
    if not path.is_file():
        raise ValueError(f"缺少内置中文字体 Noto Sans SC，请确认字体资源完整：{path}")
    font = ImageFont.truetype(str(path), size=size)
    if variant not in {"noto", "noto-bold"}:
        raise ValueError("不支持的漫画字体")
    font.set_variation_by_name("Bold" if variant == "noto-bold" else "Regular")
    return font


def _layout(balloon: dict, width: int, height: int) -> dict:
    size = int(_number(balloon.get("font_size"), 28))
    if not 1 <= size <= 512:
        raise ValueError("Font size must be between 1 and 512")
    spacing = _number(balloon.get("line_spacing"), 1.3)
    if not 0.5 <= spacing <= 5:
        raise ValueError("Invalid line spacing")
    font = _font(size, balloon.get("font", "noto"))
    pad = max(4, round(size * 0.5))
    available_w, available_h = max(0, width - 2 * pad), max(0, height - 2 * pad)
    text = str(balloon.get("text", "")).replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > 100000:
        raise ValueError("Balloon text exceeds limit")
    writing = balloon.get("writing_mode", "horizontal")
    positions: list[tuple[str, float, float]] = []
    lines: list[str] = []
    overflow = False
    step = max(1, round(size * spacing))
    if writing == "horizontal":
        # Character wrapping supports CJK without requiring spaces. Explicit blank
        # lines survive, and long Latin words wrap using the same glyph metrics.
        for paragraph in text.split("\n"):
            line = ""
            for char in paragraph:
                if line and font.getlength(line + char) > available_w:
                    lines.append(line)
                    line = ""
                line += char
            lines.append(line)
        for i, line in enumerate(lines):
            bbox = font.getbbox(line or "国")
            glyph_h = bbox[3] - bbox[1]
            positions.append((line, pad, pad + i * step - bbox[1]))
            overflow |= font.getlength(line) > available_w or i * step + glyph_h > available_h
    elif writing == "vertical":
        # Traditional columns: top to bottom, then right to left. Explicit
        # vertical punctuation forms work on Pillow builds without libraqm.
        vertical_forms = str.maketrans("，、。：；！？（）［］｛｝《》〈〉「」『』【】…—", "︐︑︒︓︔︕︖︵︶﹇﹈︷︸︽︾︿﹀﹁﹂﹃﹄︻︼︙︱")
        rows = max(1, available_h // size)
        for paragraph in text.split("\n"):
            lines.extend([paragraph[i:i + rows] for i in range(0, len(paragraph), rows)] or [""])
        for col, line in enumerate(lines):
            x = width - pad - size - col * step
            overflow |= x < pad or bool(line) and available_h < size
            for row, char in enumerate(line):
                char = char.translate(vertical_forms)
                bbox = font.getbbox(char)
                positions.append((char, x + (size - font.getlength(char)) / 2, pad + row * size - bbox[1]))
    else:
        raise ValueError("Unknown writing_mode")
    return {"font": font, "positions": positions, "lines": lines, "overflow": bool(overflow), "padding": pad}


def _panel_size(page: dict, panel: dict) -> tuple[int, int, int, int]:
    x, y, w, h = _rect(panel.get("rect", {}), *_size(page))
    inset = max(0, round(_number(page.get("gutter"), 16) / 2))
    inset = min(inset, (min(w, h) - 1) // 2)
    return x + inset, y + inset, w - inset * 2, h - inset * 2


def inspect_text(project: dict, page: dict, mode: str | None = None) -> list[dict]:
    """Return overflow warnings with page/panel/balloon ids and wrapped lines."""
    _validate_project(project)
    warnings = []
    for panel in page.get("panels", []):
        _, _, pw, ph = _panel_size(page, panel)
        if _mode(project, page, panel, mode) != "text":
            continue
        for balloon in panel.get("balloons", []):
            if not _visible(project, balloon):
                continue
            _, _, w, h = _rect(balloon.get("rect", {}), pw, ph)
            layout = _layout(balloon, w, h)
            if layout["overflow"]:
                warnings.append({"code": "text_overflow", "severity": "warning", "message": "文字超出气泡范围，请调整字号或气泡尺寸", "page_id": page.get("id"), "panel_id": panel.get("id"), "balloon_id": balloon.get("id"), "lines": layout["lines"], "writing_mode": balloon.get("writing_mode", "horizontal")})
    return warnings


def _visible(project: dict, balloon: dict) -> bool:
    kind = balloon.get("kind", "dialogue")
    if kind not in _KINDS:
        raise ValueError("Unknown balloon kind")
    return bool(balloon.get("show", True)) and bool(project.get("text_settings", {}).get(kind, True))


def _resolve(resolver: Any, path: str) -> Any:
    path = _path(path)
    try:
        return resolver(path) if callable(resolver) else resolver[path]
    except (KeyError, FileNotFoundError) as exc:
        raise ValueError(f"找不到漫画素材：{path}") from exc


def _image(resolver: Any, path: str) -> Image.Image:
    source = _resolve(resolver, path)
    if isinstance(source, Image.Image):
        if source.width * source.height > MAX_PAGE_PIXELS:
            raise ValueError("漫画素材图片尺寸超过渲染上限")
        return ImageOps.exif_transpose(source).convert("RGB")
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    try:
        with Image.open(source) as image:
            if image.width * image.height > MAX_PAGE_PIXELS:
                raise ValueError("漫画素材图片尺寸超过渲染上限")
            return ImageOps.exif_transpose(image).convert("RGB")
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"无法读取漫画素材图片：{path}") from exc


def _crop(image: Image.Image, width: int, height: int, crop: dict) -> Image.Image:
    zoom = _number(crop.get("zoom"), 1)
    if not 1 <= zoom <= 100:
        raise ValueError("Crop zoom must be between 1 and 100")
    cx, cy = (_number(crop.get(k), 0.5) for k in ("x", "y"))
    if not 0 <= cx <= 1 or not 0 <= cy <= 1:
        raise ValueError("Crop center must be normalized")
    scale = max(width / image.width, height / image.height) * zoom
    sw, sh = width / scale, height / scale
    left = min(max(0, cx * image.width - sw / 2), image.width - sw)
    top = min(max(0, cy * image.height - sh / 2), image.height - sh)
    return image.resize((width, height), Image.Resampling.LANCZOS, box=(left, top, left + sw, top + sh))


def render_page(project: dict, page: dict, asset_resolver: Any, mode: str | None = None) -> Image.Image:
    """Render RGB pixels without altering layout; blank keeps empty balloons,
    clean removes balloons, text draws lettering. Explicit mode overrides all
    inherited modes. Disabled text_settings kinds and show=False are omitted.
    Gutter is split evenly inside each panel rect; tails use panel coordinates.
    """
    _validate_project(project)
    canvas = Image.new("RGB", _size(page), "white")
    for panel in page.get("panels", []):
        x, y, width, height = _panel_size(page, panel)
        tile = Image.new("RGB", (width, height), "white")
        if panel.get("current_image"):
            tile = _crop(_image(asset_resolver, panel["current_image"]), width, height, panel.get("crop", {}))
        lettering = _mode(project, page, panel, mode)
        if lettering != "clean":
            for balloon in panel.get("balloons", []):
                if not _visible(project, balloon):
                    continue
                bx, by, bw, bh = _rect(balloon.get("rect", {}), width, height)
                draw = ImageDraw.Draw(tile)
                kind = balloon.get("kind", "dialogue")
                stroke = max(1, round(min(width, height) / 400))
                if kind == "dialogue":
                    tail = balloon.get("tail")
                    if tail:
                        tx, ty = _number(tail.get("x"), 0.5), _number(tail.get("y"), 0.8)
                        if not 0 <= tx <= 1 or not 0 <= ty <= 1:
                            raise ValueError("Tail must use normalized panel coordinates")
                        center = (bx + bw / 2, by + bh / 2)
                        tip = (round(tx * width), round(ty * height))
                        dx, dy = tip[0] - center[0], tip[1] - center[1]
                        length = max(1, math.hypot(dx, dy))
                        spread = min(bw, bh) * 0.13
                        points = [(center[0] - dy / length * spread, center[1] + dx / length * spread), tip, (center[0] + dy / length * spread, center[1] - dx / length * spread)]
                        draw.polygon(points, fill="white")
                        draw.line(points, fill="black", width=stroke)
                    draw.ellipse((bx, by, bx + bw - 1, by + bh - 1), fill="white", outline="black", width=stroke)
                elif kind == "narration":
                    draw.rectangle((bx, by, bx + bw - 1, by + bh - 1), fill="white", outline="black", width=stroke)
                if lettering == "text":
                    layout = _layout(balloon, bw, bh)
                    layer = Image.new("RGBA", (bw, bh))
                    ink = ImageDraw.Draw(layer)
                    for text, lx, ly in layout["positions"]:
                        ink.text((lx, ly), text, font=layout["font"], fill="black")
                    tile.paste(layer, (bx, by), layer)
        ImageDraw.Draw(tile).rectangle((0, 0, width - 1, height - 1), outline="black", width=max(1, round(min(width, height) / 400)))
        canvas.paste(tile, (x, y))
    return canvas


# Asset references may be nested in history/versions/reference structures. Plain
# prose is never interpreted as a path; explicit asset fields are validated even
# when malicious, so imports cannot defer unsafe paths until rendering.
_ASSET_KEYS = {"current_image", "asset", "asset_path", "image_path", "path", "src", "reference_image", "reference_path", "image"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif"}


def referenced_assets(project: dict) -> list[str]:
    """Collect local assets, including history and reference images recursively."""
    found: set[str] = set()

    def walk(value: Any, key: str = "", context: bool = False) -> None:
        context = context or any(token in key.lower() for token in ("asset", "image", "histor", "version", "reference"))
        if isinstance(value, dict):
            for k, child in value.items():
                walk(child, str(k), context)
        elif isinstance(value, list):
            for child in value:
                walk(child, key, context)
        elif isinstance(value, str) and value:
            explicit = key in _ASSET_KEYS
            candidate = value.startswith("assets/") or context and Path(value).suffix.lower() in _IMAGE_SUFFIXES
            if explicit or candidate:
                found.add(_path(value))
    walk(project)
    return sorted(found)


def _bytes(resolver: Any, path: str) -> bytes:
    source = _resolve(resolver, path)
    if isinstance(source, (bytes, bytearray)):
        result = bytes(source)
    elif hasattr(source, "read"):
        result = source.read(MAX_FILE_BYTES + 1)
    else:
        source = Path(source)
        if source.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("Asset exceeds file size limit")
        result = source.read_bytes()
    if len(result) > MAX_FILE_BYTES:
        raise ValueError("Asset exceeds file size limit")
    return result


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")


def _metadata(files: dict[str, bytes], **extra: Any) -> bytes:
    return _json({"schema_version": SCHEMA_VERSION, "generator": "FicFrame/Pillow", **extra, "files": {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()}})


def _write_zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(_path(name), data)
    return path


def archive_project(project: dict, directory: str | Path, asset_resolver: Any) -> Path:
    """Archive original JSON plus every referenced asset and SHA-256 metadata."""
    _validate_project(project)
    files = {"project.json": _json(project)}
    for path in referenced_assets(project):
        if path.casefold() in {"project.json", "metadata.json"}:
            raise ValueError("Asset collides with archive metadata")
        files[path] = _bytes(asset_resolver, path)
    if len(files) + 1 > MAX_ARCHIVE_FILES or sum(map(len, files.values())) > MAX_TOTAL_BYTES:
        raise ValueError("Project exceeds archive limits")
    if len({unicodedata.normalize("NFC", name).casefold() for name in files}) != len(files):
        raise ValueError("Colliding asset paths")
    files["metadata.json"] = _metadata(files, format="project")
    if any(len(value) > MAX_FILE_BYTES for value in files.values()) or sum(map(len, files.values())) > MAX_TOTAL_BYTES:
        raise ValueError("Project file exceeds archive limit")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    result = _write_zip(root / "comic-project.zip", files)
    if result.stat().st_size > MAX_ARCHIVE_BYTES:
        result.unlink()
        raise ValueError("Compressed project exceeds archive limit")
    return result


def _object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def read_archive(data: bytes) -> tuple[dict, dict[str, bytes]]:
    """Validate an archive entirely in memory, returning project and asset bytes.

    Never extracts files. Rejects unsafe/colliding paths, symlinks, unsupported
    versions, extra/missing files, hash/size mismatches and decompression bombs.
    Limits are module constants, applied before and during decompression.
    """
    if not isinstance(data, bytes) or len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("Archive exceeds compressed size limit")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_FILES:
                raise ValueError("Too many archive entries")
            names: set[str] = set()
            total = 0
            for info in infos:
                name = _path(info.filename)
                canonical = unicodedata.normalize("NFC", name).casefold()
                if canonical in names:
                    raise ValueError("Duplicate/colliding archive path")
                names.add(canonical)
                if info.orig_filename != info.filename or info.is_dir() or info.flag_bits & 1:
                    raise ValueError("Unsupported archive entry")
                mode = info.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                    raise ValueError("Non-regular archive entry")
                if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError("Unsupported ZIP compression")
                total += info.file_size
                if info.file_size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                    raise ValueError("Archive exceeds decompressed size limit")
            files = {}
            for info in infos:
                with archive.open(info) as stream:
                    payload = stream.read(min(MAX_FILE_BYTES, info.file_size) + 1)
                    if len(payload) != info.file_size:
                        raise ValueError("Invalid decompressed size")
                    files[info.filename] = payload
        def parse(name: str) -> Any:
            return json.loads(files[name].decode("utf-8"), object_pairs_hook=_object, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
        project = parse("project.json")
        metadata = parse("metadata.json")
        _validate_project(project)
        if not isinstance(metadata, dict) or type(metadata.get("schema_version")) is not int or metadata["schema_version"] != SCHEMA_VERSION or metadata.get("format") != "project":
            raise ValueError("Unsupported archive metadata version/format")
        manifest = metadata.get("files")
        if not isinstance(manifest, dict) or set(manifest) != set(files) - {"metadata.json"}:
            raise ValueError("Archive manifest does not match files")
        for name, entry in manifest.items():
            if not isinstance(entry, dict) or type(entry.get("size")) is not int or entry["size"] != len(files[name]) or entry.get("sha256") != hashlib.sha256(files[name]).hexdigest():
                raise ValueError("Archive file checksum/size mismatch")
        assets = {name: payload for name, payload in files.items() if name not in {"project.json", "metadata.json"}}
        if set(referenced_assets(project)) != set(assets):
            raise ValueError("Archive assets do not match project references")
        return project, assets
    except (zipfile.BadZipFile, KeyError, UnicodeError, json.JSONDecodeError, RuntimeError, OSError, TypeError, RecursionError, OverflowError, zlib.error) as exc:
        raise ValueError(f"Invalid comic archive: {exc}") from exc


def _png(image: Image.Image, project: dict, page_id: str) -> bytes:
    output = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Title", str(project.get("title", "")))
    metadata.add_text("Page", page_id)
    metadata.add_text("Software", "FicFrame/Pillow")
    image.save(output, "PNG", pnginfo=metadata)
    return output.getvalue()


def export_project(project: dict, directory: str | Path, asset_resolver: Any, format: str, mode: str | None = None, page_ids: list[str] | None = None) -> Path:
    """Export PNG ZIP, raster multipage PDF, segmented strip ZIP, or project ZIP.

    Page filters retain project order. Strip segments use the widest selected
    page, preserve aspect ratio and have at most STRIP_MAX_HEIGHT pixels. All
    ZIP exports contain metadata.json with file sizes and hashes.
    """
    _validate_project(project)
    format = format.lower()
    if format in {"project", "archive"}:
        if page_ids is not None:
            raise ValueError("Project archives always include the whole project")
        return archive_project(project, directory, asset_resolver)
    if format not in {"png", "pdf", "strip"}:
        raise ValueError("Unsupported export format")
    if mode is not None and mode not in _MODES:
        raise ValueError("Unknown lettering mode")
    if page_ids is not None and (len(set(page_ids)) != len(page_ids) or set(page_ids) - {p["id"] for p in project["pages"]}):
        raise ValueError("Unknown or duplicate page ids")
    pages = [p for p in project["pages"] if page_ids is None or p["id"] in page_ids]
    if not pages:
        raise ValueError("No pages selected")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    if format == "pdf":
        images = [render_page(project, page, asset_resolver, mode) for page in pages]
        try:
            path = root / "comic.pdf"
            images[0].save(path, "PDF", save_all=True, append_images=images[1:], resolution=72, title=str(project.get("title", "")), producer="FicFrame/Pillow")
            return path
        finally:
            for image in images:
                image.close()
    files: dict[str, bytes] = {}
    page_files = []
    if format == "png":
        for index, page in enumerate(pages, 1):
            image = render_page(project, page, asset_resolver, mode)
            name = f"pages/{index:04d}.png"
            files[name] = _png(image, project, page["id"])
            image.close()
            page_files.append({"page_id": page["id"], "file": name})
    else:
        width = max(_size(page)[0] for page in pages)
        segment_height = min(STRIP_MAX_HEIGHT, MAX_PAGE_PIXELS // width)
        segment = Image.new("RGB", (width, segment_height), "white")
        offset = 0
        def flush() -> None:
            nonlocal offset
            name = f"strip/{len(files) + 1:04d}.png"
            files[name] = _png(segment.crop((0, 0, width, offset)), project, "strip")
            offset = 0
        for page in pages:
            image = render_page(project, page, asset_resolver, mode)
            scaled_h = max(1, round(image.height * width / image.width))
            # Resize in bounded slices to avoid constructing one giant strip.
            pos = 0
            while pos < scaled_h:
                take = min(segment_height - offset, scaled_h - pos)
                chunk = image.resize((width, take), Image.Resampling.LANCZOS, box=(0, pos * image.height / scaled_h, image.width, (pos + take) * image.height / scaled_h))
                segment.paste(chunk, (0, offset))
                offset += take
                pos += take
                if offset == segment_height:
                    flush()
            image.close()
        if offset:
            flush()
        segment.close()
    files["metadata.json"] = _metadata(files, format=format, title=project.get("title", ""), page_ids=[p["id"] for p in pages], pages=page_files, lettering_mode=mode or "inherit")
    return _write_zip(root / f"comic-{format}.zip", files)
