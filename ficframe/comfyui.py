from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import secrets
import time
from pathlib import Path
from typing import Any

import httpx


class ComfyUIError(RuntimeError):
    pass


def load_api_workflow(
    raw: str,
    reference_count: int = 0,
    reference_group_sizes: list[int] | None = None,
    reference_regions: list[list[float] | None] | None = None,
    regional_guidance: bool | None = None,
) -> dict[str, Any]:
    if not raw.strip():
        raise ComfyUIError("请先导入 ComfyUI API 格式工作流 JSON。")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ComfyUIError(f"ComfyUI 工作流 JSON 格式错误：{exc}") from exc
    if isinstance(data, dict) and isinstance(data.get("prompt"), dict):
        data = data["prompt"]
    if isinstance(data, dict) and isinstance(data.get("ficframe_dynamic_ipadapter"), dict):
        descriptor = data["ficframe_dynamic_ipadapter"]
        group_sizes = reference_group_sizes if reference_group_sizes is not None else [1] * reference_count
        return build_dynamic_ipadapter_workflow(
            descriptor,
            group_sizes,
            reference_regions=reference_regions,
            regional_guidance=regional_guidance,
        )
    if isinstance(data, dict) and isinstance(data.get("ficframe_workflows"), dict):
        workflows = data["ficframe_workflows"]
        variant = "multi" if reference_count >= 2 else "single" if reference_count == 1 else "text"
        data = workflows.get(variant) or workflows.get("single") or workflows.get("text")
        if not isinstance(data, dict):
            raise ComfyUIError(f"ComfyUI 工作流包缺少 {variant} 变体。")
    if not isinstance(data, dict) or not data:
        raise ComfyUIError("ComfyUI 工作流必须是非空 JSON 对象。")
    if not any(isinstance(node, dict) and node.get("class_type") for node in data.values()):
        raise ComfyUIError("工作流不是 API 格式；请在 ComfyUI 中使用“导出（API）”。")
    return data


def build_dynamic_ipadapter_workflow(
    descriptor: dict[str, Any],
    reference_group_sizes: list[int],
    *,
    reference_regions: list[list[float] | None] | None = None,
    regional_guidance: bool | None = None,
) -> dict[str, Any]:
    base_workflow = descriptor.get("workflow")
    if not isinstance(base_workflow, dict) or not base_workflow:
        raise ComfyUIError("动态 IP-Adapter 工作流缺少 workflow 基础节点。")
    if not any(isinstance(node, dict) and node.get("class_type") for node in base_workflow.values()):
        raise ComfyUIError("动态 IP-Adapter 的 workflow 不是 ComfyUI API 格式。")

    try:
        group_sizes = [int(size) for size in reference_group_sizes if int(size) > 0]
    except (TypeError, ValueError) as exc:
        raise ComfyUIError("角色参考图分组大小必须是正整数。") from exc
    workflow = copy.deepcopy(base_workflow)
    if not group_sizes:
        return workflow

    sampler_node_id = str(descriptor.get("sampler_node_id") or "3")
    checkpoint_node_id = str(descriptor.get("checkpoint_node_id") or "4")
    prompt_node_id = str(descriptor.get("prompt_node_id") or "6")
    for node_id in (sampler_node_id, checkpoint_node_id, prompt_node_id):
        if not isinstance(workflow.get(node_id), dict):
            raise ComfyUIError(f"动态 IP-Adapter 工作流缺少节点 {node_id}。")

    numeric_ids = [int(node_id) for node_id in workflow if str(node_id).isdigit()]
    next_node_id = max(numeric_ids, default=0) + 1

    def add_node(class_type: str, inputs: dict[str, Any], title: str) -> str:
        nonlocal next_node_id
        while str(next_node_id) in workflow:
            next_node_id += 1
        node_id = str(next_node_id)
        next_node_id += 1
        workflow[node_id] = {
            "class_type": class_type,
            "inputs": inputs,
            "_meta": {"title": title},
        }
        return node_id

    settings = descriptor.get("settings") if isinstance(descriptor.get("settings"), dict) else {}
    loader_id = add_node(
        "IPAdapterUnifiedLoader",
        {
            "model": [checkpoint_node_id, 0],
            "preset": str(settings.get("preset") or "PLUS (high strength)"),
        },
        "FicFrame IP-Adapter Loader",
    )
    current_model: list[Any] = [loader_id, 0]
    empty_mask_id = ""
    use_attention_masks = len(group_sizes) > 1 and regional_guidance is not False
    custom_layout = any(is_normalized_region(region) for region in (reference_regions or []))
    if use_attention_masks:
        empty_mask_id = add_node(
            "SolidMask",
            {"value": 0, "width": "{{width}}", "height": "{{height}}"},
            "FicFrame Empty Attention Mask",
        )
        prompt_input = workflow[prompt_node_id].setdefault("inputs", {})
        prompt_text = prompt_input.get("text", "{{prompt}}")
        if custom_layout:
            prompt_input["text"] = f"keep each referenced character in their assigned composition region, {prompt_text}"
        else:
            prompt_input["text"] = (
                "place the referenced characters in separate left-to-right regions following reference group order, "
                f"keep each referenced character in their assigned region, {prompt_text}"
            )

    reference_index = 1
    base_weight = float(settings.get("weight", 0.3))
    weight_type = str(settings.get("weight_type") or "linear")
    start_at = float(settings.get("start_at", 0.0))
    end_at = float(settings.get("end_at", 0.65))
    embeds_scaling = str(settings.get("embeds_scaling") or "V only")

    for group_index, group_size in enumerate(group_sizes, start=1):
        positive_embed: list[Any] | None = None
        negative_embed: list[Any] | None = None
        for image_index in range(1, group_size + 1):
            image_id = add_node(
                "LoadImage",
                {"image": f"{{{{reference_image_{reference_index}}}}}"},
                f"Character {group_index} Reference {image_index}",
            )
            encoder_id = add_node(
                "IPAdapterEncoder",
                {"ipadapter": [loader_id, 1], "image": [image_id, 0], "weight": 1.0},
                f"Character {group_index} Reference Encoder {image_index}",
            )
            next_positive = [encoder_id, 0]
            next_negative = [encoder_id, 1]
            if positive_embed is None:
                positive_embed = next_positive
                negative_embed = next_negative
            else:
                positive_id = add_node(
                    "IPAdapterCombineEmbeds",
                    {"embed1": positive_embed, "embed2": next_positive, "method": "add"},
                    f"Character {group_index} Positive Embeds {image_index}",
                )
                negative_id = add_node(
                    "IPAdapterCombineEmbeds",
                    {"embed1": negative_embed, "embed2": next_negative, "method": "add"},
                    f"Character {group_index} Negative Embeds {image_index}",
                )
                positive_embed = [positive_id, 0]
                negative_embed = [negative_id, 0]
            reference_index += 1

        apply_inputs: dict[str, Any] = {
            "model": current_model,
            "ipadapter": [loader_id, 1],
            "pos_embed": positive_embed,
            "neg_embed": negative_embed,
            "weight": base_weight / group_size,
            "weight_type": weight_type,
            "start_at": start_at,
            "end_at": end_at,
            "embeds_scaling": embeds_scaling,
        }
        if use_attention_masks:
            region_id = add_node(
                "SolidMask",
                {
                    "value": 1,
                    "width": f"{{{{region_{group_index}_width}}}}",
                    "height": f"{{{{region_{group_index}_height}}}}",
                },
                f"Character {group_index} Region",
            )
            composite_id = add_node(
                "MaskComposite",
                {
                    "destination": [empty_mask_id, 0],
                    "source": [region_id, 0],
                    "x": f"{{{{region_{group_index}_x}}}}",
                    "y": f"{{{{region_{group_index}_y}}}}",
                    "operation": "add",
                },
                f"Character {group_index} Positioned Region",
            )
            feather_id = add_node(
                "FeatherMask",
                {
                    "mask": [composite_id, 0],
                    "left": f"{{{{region_{group_index}_feather_left}}}}",
                    "top": f"{{{{region_{group_index}_feather_top}}}}",
                    "right": f"{{{{region_{group_index}_feather_right}}}}",
                    "bottom": f"{{{{region_{group_index}_feather_bottom}}}}",
                },
                f"Character {group_index} Soft Region",
            )
            apply_inputs["attn_mask"] = [feather_id, 0]
        apply_id = add_node(
            "IPAdapterEmbeds",
            apply_inputs,
            f"Character {group_index} IP-Adapter",
        )
        current_model = [apply_id, 0]

    sampler_inputs = workflow[sampler_node_id].setdefault("inputs", {})
    sampler_inputs["model"] = current_model
    return workflow


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
    reference_group_sizes: list[int] | None = None,
    reference_regions: list[list[float] | None] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    width, height = parse_size(size)
    references = reference_images or []
    values: dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "half_width": width // 2,
        "half_height": height // 2,
        "seed": seed if seed is not None else secrets.randbelow(2**63),
        "steps": steps,
        "cfg": cfg,
        "model": model,
        "reference_image": references[0] if references else "",
    }
    for index, filename in enumerate(references, start=1):
        values[f"reference_image_{index}"] = filename
    group_sizes = [size for size in (reference_group_sizes or []) if size > 0]
    regions = resolve_reference_regions(len(group_sizes), reference_regions)
    for index, region in enumerate(regions, start=1):
        normalized_left, normalized_top, normalized_right, normalized_bottom = region
        left = min(width - 1, max(0, round(normalized_left * width)))
        top = min(height - 1, max(0, round(normalized_top * height)))
        right = min(width, max(left + 1, round(normalized_right * width)))
        bottom = min(height, max(top + 1, round(normalized_bottom * height)))
        region_width = right - left
        region_height = bottom - top
        horizontal_feather = min(96, max(1, region_width // 4))
        vertical_feather = min(96, max(1, region_height // 4))
        values[f"region_{index}_x"] = left
        values[f"region_{index}_y"] = top
        values[f"region_{index}_width"] = region_width
        values[f"region_{index}_height"] = region_height
        values[f"region_{index}_feather_left"] = 0 if normalized_left == 0 else horizontal_feather
        values[f"region_{index}_feather_top"] = 0 if normalized_top == 0 else vertical_feather
        values[f"region_{index}_feather_right"] = 0 if normalized_right == 1 else horizontal_feather
        values[f"region_{index}_feather_bottom"] = 0 if normalized_bottom == 1 else vertical_feather
    return _replace_placeholders(copy.deepcopy(workflow), values)


def resolve_reference_regions(
    count: int,
    reference_regions: list[list[float] | None] | None,
) -> list[list[float]]:
    if count <= 0:
        return []
    provided = reference_regions or []
    regions: list[list[float]] = []
    for index in range(count):
        region = provided[index] if index < len(provided) else None
        if is_normalized_region(region):
            regions.append([float(part) for part in region])
            continue
        regions.append([index / count, 0.0, (index + 1) / count, 1.0])
    return regions


def is_normalized_region(value: object) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    try:
        left, top, right, bottom = [float(part) for part in value]
    except (TypeError, ValueError):
        return False
    return 0 <= left < right <= 1 and 0 <= top < bottom <= 1


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
                upload_name = comfyui_upload_filename(path)
                with path.open("rb") as stream:
                    response = client.post(
                        f"{self.base_url}/upload/image",
                        files={"image": (upload_name, stream, mime)},
                        data={"type": "input", "subfolder": "ficframe", "overwrite": "true"},
                    )
                self._raise_for_status(response, f"上传参考图 {path.name}")
                data = response.json()
                name = str(data.get("name") or upload_name)
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


def comfyui_upload_filename(path: Path) -> str:
    resolved = str(path.resolve()).casefold().encode("utf-8")
    digest = hashlib.sha256(resolved).hexdigest()[:12]
    stem = path.stem or "reference"
    return f"{stem}-{digest}{path.suffix}"


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
