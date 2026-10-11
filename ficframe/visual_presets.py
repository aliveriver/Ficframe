from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from .runtime_paths import visual_presets_root


PRESET_TYPES = {"style", "composition"}
REFERENCE_MODES = {"text", "image"}
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp"}
MAX_REFERENCE_BYTES = 20 * 1024 * 1024
MAX_REFERENCE_COUNT = 8
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")


def _now() -> int:
    return int(time.time())


def _safe_type(value: Any) -> str:
    value = str(value or "").strip().lower()
    if value not in PRESET_TYPES:
        raise ValueError("预设类型必须是 style 或 composition")
    return value


def validate_reference_mode(value: Any, *, inherit: bool = False) -> str:
    mode = str(value or ("inherit" if inherit else "text"))
    if mode not in (REFERENCE_MODES | {"inherit"} if inherit else REFERENCE_MODES):
        raise ValueError("参考模式必须为 text（仅文本）或 image（原图与文本）")
    return mode


def _safe_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 120:
        raise ValueError("预设名称不能为空且不能超过 120 个字符")
    return name


def _safe_id(value: Any) -> str:
    value = str(value or "")
    if not _ID_RE.fullmatch(value):
        raise ValueError("非法预设 ID")
    return value


def validate_reference_bytes(filename: str, content: bytes, content_type: str | None = None) -> str:
    suffix = Path(str(filename or "")).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("参考图仅支持 PNG、JPG、WEBP、GIF 或 BMP")
    if len(content) > MAX_REFERENCE_BYTES:
        raise ValueError("单张参考图不能超过 20 MB")
    guessed = (content_type or mimetypes.guess_type(filename)[0] or "").lower()
    if guessed and guessed not in ALLOWED_MIME_TYPES:
        raise ValueError("参考图 MIME 类型不受支持")
    if not content:
        raise ValueError("参考图不能为空")
    signatures = {
        ".png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": lambda data: data.startswith(b"\xff\xd8\xff"),
        ".jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
        ".webp": lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
        ".gif": lambda data: data.startswith((b"GIF87a", b"GIF89a")),
        ".bmp": lambda data: data.startswith(b"BM"),
    }
    if not signatures[suffix](content):
        raise ValueError("文件内容与图片扩展名不匹配")
    return suffix


def normalize_vlm_draft(preset_type: str, value: Any) -> dict[str, Any]:
    """Keep VLM output editable and scoped to one visual category."""
    kind = _safe_type(preset_type)
    data = value if isinstance(value, dict) else {}
    if kind == "style":
        positive_keys = ("positive", "positive_prompt", "style_prompt", "style_constraints")
        negative_keys = ("negative", "negative_prompt", "avoid", "negative_constraints")
        allowed = {"linework", "color", "lighting", "materials", "background", "rendering", "positive", "negative", "summary"}
    else:
        positive_keys = ("positive", "positive_prompt", "composition_prompt", "composition_constraints")
        negative_keys = ("negative", "negative_prompt", "avoid", "negative_constraints")
        allowed = {"shot", "viewpoint", "subject_placement", "whitespace", "visual_weight", "relationships", "background_ratio", "positive", "negative", "summary"}
    def first(keys: Iterable[str]) -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list):
                values = [str(item).strip() for item in value if str(item).strip()]
                if values:
                    return ", ".join(values)
        return ""
    nested = data.get("structured") if isinstance(data.get("structured"), dict) else {}
    structured = {key: nested.get(key, data.get(key)) for key in sorted(allowed - {"positive", "negative"}) if key in nested or key in data}
    return {
        "positive": first(positive_keys),
        "negative": first(negative_keys),
        "structured": structured,
        "raw": {"positive": first(positive_keys), "negative": first(negative_keys), "structured": structured},
    }


def build_visual_prompt(base_positive: str, base_negative: str, style: dict[str, Any] | None = None, composition: dict[str, Any] | None = None) -> tuple[str, str]:
    """Assemble visual constraints without mutating the user's original prompt."""
    positive_parts = [str(base_positive or "").strip()]
    negative_parts = [str(base_negative or "").strip()]
    for label, item in (("Style guide", style), ("Composition guide", composition)):
        if not isinstance(item, dict):
            continue
        positive = str(item.get("positive") or "").strip()
        negative = str(item.get("negative") or "").strip()
        if positive:
            positive_parts.append(f"{label}: {positive}")
        if negative:
            negative_parts.append(f"{label} avoid: {negative}")
    return "\n\n".join(part for part in positive_parts if part), ", ".join(part for part in negative_parts if part)


class VisualPresetStore:
    """Small atomic JSON store for global, reusable visual presets."""
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else visual_presets_root()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "references").mkdir(exist_ok=True)
        (self.root / "drafts").mkdir(exist_ok=True)
        self.path = self.root / "presets.json"
        self._lock = threading.RLock()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "presets": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("预设存储无法读取，请检查或恢复 presets.json") from exc
        if not isinstance(data, dict) or not isinstance(data.get("presets"), list):
            raise ValueError("预设存储格式无效")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)

    def list(self, preset_type: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = self._read()["presets"]
            if preset_type:
                kind = _safe_type(preset_type)
                items = [item for item in items if item.get("type") == kind]
            return json.loads(json.dumps(items, ensure_ascii=False))

    def get(self, preset_id: str) -> dict[str, Any] | None:
        _safe_id(preset_id)
        return next((item for item in self.list() if item.get("id") == preset_id), None)

    def create(self, *, name: str, preset_type: str, positive: str = "", negative: str = "", vlm_analysis: dict[str, Any] | None = None, reference_files: list[tuple[str, bytes]] | None = None, reference_paths: list[str] | None = None, reference_mode: str = "text") -> dict[str, Any]:
        kind = _safe_type(preset_type)
        clean_name = _safe_name(name)
        mode = validate_reference_mode(reference_mode)
        if mode == "image" and not (reference_files or reference_paths):
            raise ValueError("原图参考模式至少需要一张参考图")
        preset_id = f"{kind}_{uuid.uuid4().hex[:12]}"
        now = _now()
        refs = self._copy_references(preset_id, reference_files or [], reference_paths or [])
        item = {"id": preset_id, "name": clean_name, "type": kind, "positive": str(positive or "").strip(), "negative": str(negative or "").strip(), "reference_images": refs, "vlm_analysis": normalize_vlm_draft(kind, vlm_analysis) if vlm_analysis else {}, "created_at": now, "updated_at": now, "version": 1}
        item["reference_mode"] = mode
        with self._lock:
            data = self._read(); data["presets"].append(item); self._write(data)
        return json.loads(json.dumps(item, ensure_ascii=False))

    def update(self, preset_id: str, values: dict[str, Any]) -> dict[str, Any]:
        _safe_id(preset_id)
        with self._lock:
            data = self._read()
            item = next((entry for entry in data["presets"] if entry.get("id") == preset_id), None)
            if item is None:
                raise KeyError(preset_id)
            mode = validate_reference_mode(values.get("reference_mode", item.get("reference_mode", "text")))
            refs = values.get("reference_paths", item.get("reference_images", []))
            if mode == "image" and not refs:
                raise ValueError("原图参考模式至少需要一张参考图")
            item["reference_mode"] = mode
            if "name" in values: item["name"] = _safe_name(values["name"])
            if "positive" in values: item["positive"] = str(values["positive"] or "").strip()
            if "negative" in values: item["negative"] = str(values["negative"] or "").strip()
            if isinstance(values.get("vlm_analysis"), dict): item["vlm_analysis"] = normalize_vlm_draft(item["type"], values["vlm_analysis"])
            if "reference_paths" in values:
                item["reference_images"] = self._copy_references(preset_id, [], values["reference_paths"])
            item["version"] = int(item.get("version") or 1) + 1; item["updated_at"] = _now()
            self._write(data)
            return json.loads(json.dumps(item, ensure_ascii=False))

    def delete(self, preset_id: str) -> None:
        _safe_id(preset_id)
        with self._lock:
            data = self._read(); before = len(data["presets"])
            data["presets"] = [item for item in data["presets"] if item.get("id") != preset_id]
            if len(data["presets"]) == before: raise KeyError(preset_id)
            self._write(data)
        # References are intentionally retained: run snapshots and old exports
        # may still point at them. They can be garbage-collected explicitly later.

    def save_draft_references(self, files: list[tuple[str, bytes]]) -> list[str]:
        if not files or len(files) > MAX_REFERENCE_COUNT:
            raise ValueError("请上传 1 至 8 张参考图")
        for filename, content in files:
            validate_reference_bytes(filename, content)
        draft_id = uuid.uuid4().hex
        target = self.root / "drafts" / draft_id; target.mkdir(parents=True)
        names = []
        for filename, content in files:
            validate_reference_bytes(filename, content)
            safe = Path(filename).name or "reference.png"
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", safe)
            path = target / f"{len(names)+1}_{safe}"; path.write_bytes(content); names.append(str(path.relative_to(self.root)).replace("\\", "/"))
        return names

    def remove_draft_references(self, paths: list[str]) -> None:
        draft_root = (self.root / "drafts").resolve()
        for relative in paths:
            target = (self.root / str(relative)).resolve()
            if draft_root not in target.parents or not target.is_file():
                continue
            target.unlink()
            folder = target.parent
            if folder.parent == draft_root:
                try:
                    folder.rmdir()
                except OSError:
                    pass

    def _copy_references(self, preset_id: str, files: list[tuple[str, bytes]], paths: list[str]) -> list[str]:
        if len(files) + len(paths) > MAX_REFERENCE_COUNT:
            raise ValueError("最多支持 8 张参考图")
        for filename, content in files:
            validate_reference_bytes(filename, content)
        sources = [self.reference_path(relative) for relative in paths]
        target = self.root / "references" / preset_id; target.mkdir(parents=True, exist_ok=True)
        result = []
        for filename, content in files:
            validate_reference_bytes(filename, content)
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(filename).name or "reference.png")
            path = target / f"{len(result)+1}_{safe}"; path.write_bytes(content); result.append(str(path.relative_to(self.root)).replace("\\", "/"))
        for source in sources:
            validate_reference_bytes(source.name, source.read_bytes())
            path = target / f"{uuid.uuid4().hex[:12]}_{source.name}"; shutil.copyfile(source, path); result.append(str(path.relative_to(self.root)).replace("\\", "/"))
        return result

    def reference_path(self, relative: str) -> Path:
        parts = str(relative).replace("\\", "/").split("/")
        if len(parts) != 3 or parts[0] not in {"drafts", "references"} or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("非法参考图路径")
        _safe_id(parts[1])
        path = (self.root / "/".join(parts)).resolve()
        if self.root.resolve() not in path.parents or not path.is_file():
            raise ValueError("参考图不存在")
        if path.stat().st_size > MAX_REFERENCE_BYTES:
            raise ValueError("参考图超过大小限制")
        validate_reference_bytes(path.name, path.read_bytes())
        return path


def preset_snapshot(item: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(item, dict): return {}
    return {"id": item.get("id"), "type": item.get("type"), "version": item.get("version", 1), "name": item.get("name", ""), "positive": item.get("positive", ""), "negative": item.get("negative", ""), "reference_mode": validate_reference_mode(item.get("reference_mode")), "reference_images": list(item.get("reference_images") or []), "structured": item.get("vlm_analysis", {}).get("structured", {}) if isinstance(item.get("vlm_analysis"), dict) else {}}
