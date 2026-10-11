"""Separate visual image channels, explicit live capability tests and safe preflight."""
from __future__ import annotations

import hashlib
import json
import struct
import tempfile
import threading
import time
import zlib
from pathlib import Path
from typing import Any

from .providers import ProviderError, effective_image_provider
from .run_repository import RunRepository
from .visual_presets import VisualPresetStore, validate_reference_bytes


ADAPTER_REVISION = 1
_CAPABILITY_LOCK = threading.RLock()


def purpose_prompt(prompt: str, identity_count: int, style_count: int, composition_count: int) -> str:
    """Cloud APIs share an image array, but roles remain explicit and ordered."""
    if not (style_count or composition_count):
        return prompt
    parts = ["Reference image roles (1-based order; do not treat every image as character identity):"]
    offset = 0
    for count, instruction in (
        (identity_count, "character identity and appearance only"),
        (style_count, "drawing style only: linework, rendering, palette, light and materials; ignore depicted identities, clothing, props, plot and layout"),
        (composition_count, "composition only: shot scale, viewpoint, placement, whitespace and spatial relationships; ignore depicted identities, clothing, props, plot and drawing style"),
    ):
        if count:
            parts.append(f"Images {offset + 1}-{offset + count}: {instruction}.")
        offset += count
    parts.append("Create one standalone novel illustration of the requested scene. Reference roles are soft guidance, not exact copying.")
    return prompt + "\n\n" + "\n".join(parts)


def provider_fingerprint(provider: Any, size: str) -> str:
    endpoint = provider.config.image
    data = {"provider": effective_image_provider(endpoint), "base_url": endpoint.base_url.rstrip("/"),
            "model": endpoint.model, "size": size, "adapter_revision": ADAPTER_REVISION,
            "credential_hash": hashlib.sha256((endpoint.api_key or "").encode()).hexdigest()}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def capability(store: VisualPresetStore, provider: Any, size: str = "1024x1024") -> dict[str, Any]:
    endpoint = provider.config.image
    runtime = effective_image_provider(endpoint)
    common = {"provider": runtime, "model": endpoint.model, "size": size, "tested_count": 0, "adapter_supported": runtime not in {"siliconflow", "comfyui"}}
    if runtime in {"siliconflow", "comfyui"}:
        reason = "当前 SiliconFlow 适配器不发送原图" if runtime == "siliconflow" else "当前 ComfyUI 工作流只有角色身份参考通道，未实现独立画风/构图原图控制"
        return {**common, "status": "unsupported", "message": reason + "；请改用仅文本模式或切换供应商。"}
    if not endpoint.api_key or not endpoint.model:
        return {**common, "status": "unknown", "message": "请先保存图片供应商的模型与 API key，再测试多图参考。"}
    fingerprint = provider_fingerprint(provider, size)
    path = store.root / "reference-capabilities.json"
    with _CAPABILITY_LOCK:
        try:
            result = json.loads(path.read_text(encoding="utf-8")).get(fingerprint)
        except (OSError, ValueError, AttributeError):
            result = None
    if isinstance(result, dict):
        return {**common, **result}
    return {**common, "status": "unknown", "message": "当前模型与尺寸尚未验证多图参考；请先运行测试（可能计费），或使用仅文本模式。"}


def save_capability(store: VisualPresetStore, provider: Any, size: str, result: dict[str, Any]) -> None:
    path = store.root / "reference-capabilities.json"
    with _CAPABILITY_LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data[provider_fingerprint(provider, size)] = result
        RunRepository._atomic_write_json(path, data)


def reference_rejected(exc: Exception) -> bool:
    message = str(exc).lower()
    status = message.split(maxsplit=1)[0] if message else ""
    if status in {"401", "403", "408", "429", "500", "502", "503", "504"}:
        return False
    return any(word in message for word in ("image", "reference", "图片", "参考")) and any(word in message for word in ("unsupported", "not support", "too many", "maximum", "only one", "at most", "不支持"))


def reference_failure(store: VisualPresetStore, provider: Any, size: str, exc: Exception) -> str:
    if reference_rejected(exc):
        result = {"status": "unsupported", "tested_count": 0, "tested_at": int(time.time()),
                  "message": "供应商拒绝本次原图参考，已更新能力状态；请重新测试、减少参考图、改用仅文本或切换模型。"}
        save_capability(store, provider, size, result)
        return result["message"]
    return "原图参考生成失败，请检查模型、权限、额度和网络；未自动丢弃原图，可重试或改用仅文本。"


def synthetic_png(index: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    pixel = bytes(((index * 67) % 256, (index * 109) % 256, (index * 43) % 256))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress((b"\0" + pixel * 64) * 64)) + chunk(b"IEND", b"")


def probe_references(store: VisualPresetStore, provider: Any, count: int, size: str) -> dict[str, Any]:
    current = capability(store, provider, size)
    if not current["adapter_supported"]:
        return current
    if not provider.config.image.api_key or not provider.config.image.model:
        return current
    result = {"tested_count": count, "tested_at": int(time.time()), "adapter_revision": ADAPTER_REVISION}
    with tempfile.TemporaryDirectory(prefix="reference-test-", dir=store.root) as directory:
        paths = []
        for index in range(count):
            path = Path(directory) / f"sample_{index}.png"
            path.write_bytes(synthetic_png(index + 1))
            paths.append(path)
        target = Path(directory) / "result.png"
        try:
            provider.image("Create a simple abstract illustration using the supplied color samples. No people or text.", target,
                           size=size, style_reference_images=paths[:-1], composition_reference_images=paths[-1:],
                           purpose="reference_probe:multi_image")
            if not target.is_file() or not target.stat().st_size:
                raise ProviderError("no generated output")
            content = target.read_bytes()
            valid_image = False
            for extension in (".png", ".jpg", ".webp", ".gif", ".bmp"):
                try:
                    validate_reference_bytes("result" + extension, content)
                    valid_image = True
                    break
                except ValueError:
                    pass
            if not valid_image:
                raise ProviderError("no valid image output")
            result.update(status="supported", message=f"{count} 张参考图请求已成功并返回图片；无法确认模型使用了每张图或理解用途，不保证严格复刻，更多图片需重新测试。")
        except Exception as exc:
            # Authentication/rate limits/timeouts are NOT evidence of lack of support.
            reference_rejection = reference_rejected(exc)
            status = "unsupported" if reference_rejection else "unknown"
            result.update(status=status, message="供应商拒绝多图参考，请减少图片、改用仅文本或切换模型。" if reference_rejection else "多图测试未成功，不能确认支持；请检查模型、权限、额度和网络后重试，或改用仅文本。")
    save_capability(store, provider, size, result)
    return {**current, **result}


def visual_paths(store: VisualPresetStore, snapshot: dict[str, Any]) -> dict[str, list[Path]]:
    result = {"style": [], "composition": []}
    for kind in result:
        guide = snapshot.get(kind) or {}
        if guide.get("id") and guide.get("reference_mode", "text") == "image":
            paths = guide.get("reference_images") or []
            if not paths:
                raise ValueError(f"{'画风' if kind == 'style' else '构图'}原图模式没有参考图，请上传图片或改用仅文本。")
            result[kind] = [store.reference_path(path) for path in paths]
    return result


def reference_preflight(store: VisualPresetStore, provider: Any, snapshot: dict[str, Any], identity_count: int,
                        size: str) -> dict[str, Any]:
    try:
        paths = visual_paths(store, snapshot)
    except ValueError as exc:
        return {"ok": False, "status": "invalid", "message": str(exc), "total_count": identity_count}
    style_count, composition_count = len(paths["style"]), len(paths["composition"])
    total = identity_count + style_count + composition_count
    if not (style_count or composition_count):
        return {"ok": True, "status": "text", "message": "画风与构图仅发送文本规范，不发送原图。", "total_count": identity_count}
    result = capability(store, provider, size)
    ok = result["status"] == "supported" and total <= result.get("tested_count", 0)
    message = result["message"]
    if result["status"] == "supported" and not ok:
        message = f"本次共 {total} 张参考图（含人设），超过已验证的 {result['tested_count']} 张；请按本次数量重新测试或改用仅文本。"
    return {**result, "ok": ok, "message": message, "total_count": total, "identity_count": identity_count,
            "style_count": style_count, "composition_count": composition_count}
