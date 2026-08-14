from __future__ import annotations

import copy
import json
import mimetypes
import secrets
import time
from pathlib import Path
from typing import Any

import httpx


class ComfyUIError(RuntimeError):
    pass


def load_api_workflow(raw: str) -> dict[str, Any]:
    if not raw.strip():
        raise ComfyUIError("请先导入 ComfyUI API 格式工作流 JSON。")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ComfyUIError(f"ComfyUI 工作流 JSON 格式错误：{exc}") from exc
    if isinstance(data, dict) and isinstance(data.get("prompt"), dict):
        data = data["prompt"]
    if not isinstance(data, dict) or not data:
        raise ComfyUIError("ComfyUI 工作流必须是非空 JSON 对象。")
    if not any(isinstance(node, dict) and node.get("class_type") for node in data.values()):
        raise ComfyUIError("工作流不是 API 格式；请在 ComfyUI 中使用“导出（API）”。")
    return data


def render_api_workflow(
    workflow: dict[str, Any],
    *,
    prompt: str,
    negative_prompt: str,
    size: str,
    model: str,
    steps: int,
    cfg: float,
    reference_images: list[str] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    width, height = parse_size(size)
    references = reference_images or []
    values: dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "seed": seed if seed is not None else secrets.randbelow(2**63),
        "steps": steps,
        "cfg": cfg,
        "model": model,
        "reference_image": references[0] if references else "",
    }
    for index, filename in enumerate(references, start=1):
        values[f"reference_image_{index}"] = filename
    return _replace_placeholders(copy.deepcopy(workflow), values)


def parse_size(size: str) -> tuple[int, int]:
    normalized = size.lower().strip().replace(" ", "")
    aliases = {"1k": (1024, 1024), "2k": (2048, 2048), "4k": (4096, 4096)}
    if normalized in aliases:
        return aliases[normalized]
    parts = normalized.split("x", 1)
    if len(parts) != 2:
        raise ComfyUIError("ComfyUI 图片尺寸必须使用 宽x高 格式，例如 1024x1024。")
    try:
        width, height = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ComfyUIError("ComfyUI 图片尺寸必须使用 宽x高 格式，例如 1024x1024。") from exc
    if width <= 0 or height <= 0:
        raise ComfyUIError("ComfyUI 图片宽高必须大于 0。")
    return width, height


def _replace_placeholders(value: Any, replacements: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _replace_placeholders(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_placeholders(item, replacements) for item in value]
    if not isinstance(value, str):
        return value
    for key, replacement in replacements.items():
        token = "{{" + key + "}}"
        if value == token:
            return replacement
        if token in value:
            value = value.replace(token, str(replacement))
    return value


class ComfyUIClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        timeout: float = 900.0,
        poll_interval: float = 1.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.poll_interval = max(0.1, poll_interval)
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def generate(
        self,
        workflow: dict[str, Any],
        out_path: str | Path,
        *,
        output_node_id: str = "",
    ) -> Path:
        started = time.monotonic()
        with httpx.Client(timeout=min(self.timeout, 60.0), headers=self.headers) as client:
            response = client.post(f"{self.base_url}/prompt", json={"prompt": workflow})
            self._raise_for_status(response, "提交工作流")
            prompt_id = str(response.json().get("prompt_id") or "")
            if not prompt_id:
                raise ComfyUIError("ComfyUI 没有返回 prompt_id。")
            image = self._wait_for_image(client, prompt_id, output_node_id, started)
            response = client.get(
                f"{self.base_url}/view",
                params={
                    "filename": image["filename"],
                    "subfolder": image.get("subfolder", ""),
                    "type": image.get("type", "output"),
                },
            )
            self._raise_for_status(response, "下载生成图片")
            target = Path(out_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(response.content)
            return target

    def upload_images(self, paths: list[Path]) -> list[str]:
        uploaded: list[str] = []
        with httpx.Client(timeout=min(self.timeout, 60.0), headers=self.headers) as client:
            for path in paths:
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                with path.open("rb") as stream:
                    response = client.post(
                        f"{self.base_url}/upload/image",
                        files={"image": (path.name, stream, mime)},
                        data={"type": "input", "subfolder": "ficframe", "overwrite": "true"},
                    )
                self._raise_for_status(response, f"上传参考图 {path.name}")
                data = response.json()
                name = str(data.get("name") or path.name)
                subfolder = str(data.get("subfolder") or "")
                uploaded.append(f"{subfolder}/{name}".strip("/"))
        return uploaded

    def _wait_for_image(
        self,
        client: httpx.Client,
        prompt_id: str,
        output_node_id: str,
        started: float,
    ) -> dict[str, Any]:
        while time.monotonic() - started < self.timeout:
            response = client.get(f"{self.base_url}/history/{prompt_id}")
            self._raise_for_status(response, "查询工作流状态")
            history = response.json()
            entry = history.get(prompt_id) if isinstance(history, dict) else None
            if isinstance(entry, dict):
                status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
                if status.get("status_str") == "error":
                    messages = status.get("messages") or []
                    raise ComfyUIError(f"ComfyUI 工作流执行失败：{messages[-1] if messages else '未知错误'}")
                image = find_output_image(entry.get("outputs"), output_node_id)
                if image:
                    return image
            time.sleep(self.poll_interval)
        raise ComfyUIError(f"ComfyUI 生成超时（{self.timeout:.0f}s）。")

    @staticmethod
    def _raise_for_status(response: httpx.Response, action: str) -> None:
        if response.status_code >= 400:
            raise ComfyUIError(f"ComfyUI {action}失败：HTTP {response.status_code} {response.text[:500]}")


def find_output_image(outputs: Any, output_node_id: str = "") -> dict[str, Any] | None:
    if not isinstance(outputs, dict):
        return None
    nodes: list[Any]
    if output_node_id:
        nodes = [outputs.get(output_node_id)]
    else:
        nodes = list(outputs.values())
    for node in nodes:
        if not isinstance(node, dict):
            continue
        images = node.get("images")
        if isinstance(images, list):
            for image in images:
                if isinstance(image, dict) and image.get("filename"):
                    return image
    return None
