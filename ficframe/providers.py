from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from .logging_utils import get_logger
from .comfyui import ComfyUIClient, ComfyUIError, load_api_workflow, render_api_workflow
from .runtime_paths import env_file


load_dotenv(env_file())
logger = get_logger("providers")


DEEPSEEK_JSON_MAX_OUTPUT_TOKENS = 32768


class ProviderError(RuntimeError):
    pass


@dataclass
class EndpointConfig:
    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    provider: str = "openai"


@dataclass
class ProviderConfig:
    llm: EndpointConfig
    image: EndpointConfig
    vlm: EndpointConfig
    timeout: float = 300.0
    image_timeout: float = 900.0
    image_options: dict[str, str] | None = None

    @classmethod
    def from_env(cls) -> "ProviderConfig":
        legacy_key = os.getenv("OPENAI_API_KEY") or os.getenv("FICFRAME_API_KEY")
        legacy_base_url = os.getenv("FICFRAME_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        llm_model = os.getenv("FICFRAME_LLM_MODEL", "gpt-5-mini")
        return cls(
            llm=EndpointConfig(
                api_key=os.getenv("FICFRAME_LLM_API_KEY") or legacy_key,
                base_url=os.getenv("FICFRAME_LLM_BASE_URL", legacy_base_url).rstrip("/"),
                model=llm_model,
                provider=os.getenv("FICFRAME_LLM_PROVIDER", "openai").lower(),
            ),
            image=EndpointConfig(
                api_key=os.getenv("FICFRAME_IMAGE_API_KEY") or legacy_key,
                base_url=os.getenv("FICFRAME_IMAGE_BASE_URL", legacy_base_url).rstrip("/"),
                model=os.getenv("FICFRAME_IMAGE_MODEL", "gpt-image-1"),
                provider=os.getenv("FICFRAME_IMAGE_PROVIDER", "openai").lower(),
            ),
            vlm=EndpointConfig(
                api_key=os.getenv("FICFRAME_VLM_API_KEY"),
                base_url=os.getenv("FICFRAME_VLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
                model=os.getenv("FICFRAME_VLM_MODEL", llm_model),
                provider=os.getenv("FICFRAME_VLM_PROVIDER", "openai").lower(),
            ),
            timeout=env_float("FICFRAME_TIMEOUT", 300.0),
            image_timeout=env_float("FICFRAME_IMAGE_TIMEOUT", env_float("FICFRAME_TIMEOUT", 900.0)),
            image_options={
                "steps": os.getenv("FICFRAME_IMAGE_STEPS", "20"),
                "guidance_scale": os.getenv("FICFRAME_IMAGE_GUIDANCE_SCALE", "7.5"),
                "workflow_json": read_env_text_file("FICFRAME_COMFYUI_WORKFLOW_PATH"),
                "negative_prompt": os.getenv("FICFRAME_COMFYUI_NEGATIVE_PROMPT", ""),
                "output_node_id": os.getenv("FICFRAME_COMFYUI_OUTPUT_NODE_ID", ""),
                "poll_interval": os.getenv("FICFRAME_COMFYUI_POLL_INTERVAL", "1"),
            },
        )


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig | None = None):
        self.config = config or ProviderConfig.from_env()

    def _headers(self, endpoint: EndpointConfig, label: str) -> dict[str, str]:
        if not endpoint.api_key:
            raise ProviderError(f"缺少 {label} API key。请设置 FICFRAME_{label.upper()}_API_KEY。")
        return {"Authorization": f"Bearer {endpoint.api_key}", "Content-Type": "application/json"}

    def _post(
        self,
        endpoint: EndpointConfig,
        label: str,
        path: str,
        payload: dict[str, Any],
        purpose: str = "",
    ) -> dict[str, Any]:
        url = build_url(endpoint.base_url, path)
        timeout = self._timeout_for(label)
        request_summary = summarize_payload(payload)
        started = time.perf_counter()
        logger.info(
            "provider request label=%s purpose=%s provider=%s url=%s model=%s timeout_s=%s summary=%s",
            label,
            purpose,
            endpoint.provider,
            safe_url(url),
            payload.get("model", ""),
            int(timeout),
            request_summary,
        )
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=self._headers(endpoint, label), json=payload)
        except httpx.HTTPError as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.warning(
                "provider post exception label=%s purpose=%s url=%s path=%s duration_ms=%s summary=%s error=%s",
                label,
                purpose,
                safe_url(url),
                path,
                duration_ms,
                request_summary,
                exc,
            )
            raise ProviderError(provider_exception_message(label, exc, timeout)) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "provider response label=%s purpose=%s provider=%s url=%s path=%s status=%s duration_ms=%s model=%s summary=%s",
            label,
            purpose,
            endpoint.provider,
            safe_url(url),
            path,
            response.status_code,
            duration_ms,
            payload.get("model", ""),
            summarize_response(response),
        )
        if response.status_code >= 400:
            logger.warning(
                "provider post failed label=%s purpose=%s url=%s path=%s status=%s request_summary=%s body=%s",
                label,
                purpose,
                safe_url(url),
                path,
                response.status_code,
                request_summary,
                response.text[:500],
            )
            raise ProviderError(f"{response.status_code} {url}: {response.text[:1000]}")
        return response.json()

    def _post_multipart(
        self,
        endpoint: EndpointConfig,
        label: str,
        path: str,
        data: dict[str, str],
        files: list[tuple[str, tuple[str, bytes, str]]],
        purpose: str = "",
    ) -> dict[str, Any]:
        url = build_url(endpoint.base_url, path)
        headers = self._headers(endpoint, label)
        headers.pop("Content-Type", None)
        timeout = self._timeout_for(label)
        request_summary = {
            "model": data.get("model", ""),
            "data_keys": sorted(data.keys()),
            "file_count": len(files),
            "filenames": [item[1][0] for item in files[:8]],
        }
        started = time.perf_counter()
        logger.info(
            "provider multipart request label=%s purpose=%s provider=%s url=%s timeout_s=%s summary=%s",
            label,
            purpose,
            endpoint.provider,
            safe_url(url),
            int(timeout),
            request_summary,
        )
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=headers, data=data, files=files)
        except httpx.HTTPError as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.warning(
                "provider multipart exception label=%s purpose=%s url=%s path=%s duration_ms=%s summary=%s error=%s",
                label,
                purpose,
                safe_url(url),
                path,
                duration_ms,
                request_summary,
                exc,
            )
            raise ProviderError(provider_exception_message(label, exc, timeout)) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "provider multipart response label=%s purpose=%s provider=%s url=%s path=%s status=%s duration_ms=%s model=%s file_count=%s summary=%s",
            label,
            purpose,
            endpoint.provider,
            safe_url(url),
            path,
            response.status_code,
            duration_ms,
            data.get("model", ""),
            len(files),
            summarize_response(response),
        )
        if response.status_code >= 400:
            logger.warning("provider multipart failed label=%s purpose=%s url=%s path=%s status=%s body=%s", label, purpose, safe_url(url), path, response.status_code, response.text[:500])
            raise ProviderError(f"{response.status_code} {url}: {response.text[:1000]}")
        return response.json()

    def text(self, system: str, user: str, model: str | None = None, purpose: str = "") -> str:
        endpoint = self.config.llm
        runtime = effective_llm_provider(endpoint)
        if runtime == "chat_completions":
            payload = {
                "model": model or endpoint.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
            }
            data = self._post(endpoint, "llm", "chat/completions", payload, purpose=purpose)
        else:
            payload = {
                "model": model or endpoint.model,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": system}]},
                    {"role": "user", "content": [{"type": "input_text", "text": user}]},
                ],
            }
            if is_deepseek_endpoint(endpoint):
                payload["reasoning"] = {"effort": "high"}
                # DeepSeek Responses API 使用 text.format 开启 JSON 模式；
                # max_output_tokens 同时包含推理与最终回答，需要为长 JSON 留出空间。
                payload["text"] = {"format": {"type": "json_object"}}
                payload["max_output_tokens"] = DEEPSEEK_JSON_MAX_OUTPUT_TOKENS
            try:
                data = self._post(endpoint, "llm", "responses", payload, purpose=purpose)
            except ProviderError as exc:
                if not is_deepseek_endpoint(endpoint) or not can_fallback_deepseek_to_chat(exc):
                    raise
                logger.warning(
                    "DeepSeek Responses API unavailable purpose=%s model=%s; retrying with chat/completions: %s",
                    purpose,
                    model or endpoint.model,
                    exc,
                )
                chat_payload = {
                    "model": model or endpoint.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "response_format": {"type": "json_object"},
                    "reasoning_effort": "high",
                    "thinking": {"type": "enabled"},
                }
                data = self._post(endpoint, "llm", "chat/completions", chat_payload, purpose=f"{purpose}:chat_fallback")
        ensure_response_completed(data)
        return extract_response_text(data)

    def vision(self, system: str, prompt: str, image_paths: list[Path], model: str | None = None, purpose: str = "") -> str:
        endpoint = self.config.vlm
        runtime = effective_vlm_provider(endpoint)
        if runtime == "chat_completions":
            content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for path in image_paths:
                content.append({"type": "image_url", "image_url": {"url": to_data_url(path)}})
            payload = {
                "model": model or endpoint.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 800,
            }
            try:
                data = self._post(endpoint, "vlm", "chat/completions", payload, purpose=purpose)
            except ProviderError as exc:
                if "response_format" not in str(exc):
                    raise
                logger.warning("vlm json response_format unsupported purpose=%s provider=%s model=%s retrying_without_json_mode", purpose, endpoint.provider, model or endpoint.model)
                payload.pop("response_format", None)
                data = self._post(endpoint, "vlm", "chat/completions", payload, purpose=f"{purpose}:no_json_mode")
        else:
            content = [{"type": "input_text", "text": prompt}]
            for path in image_paths:
                content.append({"type": "input_image", "image_url": to_data_url(path)})
            payload = {
                "model": model or endpoint.model,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": system}]},
                    {"role": "user", "content": content},
                ],
            }
            data = self._post(endpoint, "vlm", "responses", payload, purpose=purpose)
        return extract_response_text(data)

    def _timeout_for(self, label: str) -> float:
        return self.config.image_timeout if label.startswith("image") else self.config.timeout

    def image(
        self,
        prompt: str,
        out_path: str | Path,
        model: str | None = None,
        size: str = "1024x1024",
        negative_prompt: str = "",
        reference_images: list[Path] | None = None,
        reference_image_groups: list[list[Path]] | None = None,
        reference_regions: list[list[float] | None] | None = None,
        regional_guidance: bool | None = None,
        purpose: str = "",
    ) -> Path:
        endpoint = self.config.image
        groups = [group for group in (reference_image_groups or []) if group]
        references = [path for group in groups for path in group] if groups else (reference_images or [])
        provider = effective_image_provider(endpoint)
        cloud_prompt = image_prompt_with_negative(prompt, negative_prompt)
        logger.info("image request purpose=%s provider=%s model=%s size=%s reference_count=%s", purpose, provider, model or endpoint.model, size, len(references))

        if provider == "comfyui":
            options = self.config.image_options or {}
            try:
                client = ComfyUIClient(
                    endpoint.base_url,
                    api_key=endpoint.api_key or "",
                    timeout=self.config.image_timeout,
                    poll_interval=float(options.get("poll_interval") or 1),
                )
                uploaded = client.upload_images(references) if references else []
                group_sizes = [len(group) for group in groups] if groups else [1] * len(references)
                workflow = render_api_workflow(
                    load_api_workflow(
                        options.get("workflow_json", ""),
                        reference_count=len(references),
                        reference_group_sizes=group_sizes,
                        reference_regions=reference_regions,
                        regional_guidance=regional_guidance,
                    ),
                    prompt=prompt,
                    negative_prompt=combine_negative_prompts(negative_prompt, options.get("negative_prompt", "")),
                    size=size,
                    model=model or endpoint.model,
                    steps=int(options.get("steps") or 20),
                    cfg=float(options.get("guidance_scale") or 7.5),
                    reference_images=uploaded,
                    reference_group_sizes=group_sizes,
                    reference_regions=reference_regions,
                )
                return client.generate(workflow, out_path, output_node_id=options.get("output_node_id", ""))
            except httpx.HTTPError as exc:
                raise ProviderError(provider_exception_message("ComfyUI", exc, self.config.image_timeout)) from exc
            except (ComfyUIError, ValueError) as exc:
                raise ProviderError(str(exc)) from exc
        if provider == "grsai":
            payload = {
                "model": model or endpoint.model,
                "prompt": reference_aware_prompt(cloud_prompt, bool(references)),
                "images": [to_data_url(path) for path in references],
                "aspectRatio": size,
                "replyType": "json",
            }
            data = self._post(endpoint, "image", "api/generate", payload, purpose=purpose)
        elif provider == "ark":
            payload = {
                "model": model or endpoint.model,
                "prompt": reference_aware_prompt(cloud_prompt, bool(references)),
                "sequential_image_generation": os.getenv("FICFRAME_IMAGE_SEQUENTIAL", "disabled"),
                "response_format": os.getenv("FICFRAME_IMAGE_RESPONSE_FORMAT", "url"),
                "size": size,
                "stream": False,
                "watermark": env_bool("FICFRAME_IMAGE_WATERMARK", True),
            }
            if references:
                payload["images"] = [to_data_url(path) for path in references]
            data = self._post(endpoint, "image", "images/generations", payload, purpose=purpose)
        elif provider == "siliconflow":
            payload = {
                "model": model or endpoint.model,
                "prompt": cloud_prompt,
                "image_size": size,
                "batch_size": int(os.getenv("FICFRAME_IMAGE_BATCH_SIZE", "1")),
                "num_inference_steps": int(os.getenv("FICFRAME_IMAGE_STEPS", "20")),
                "guidance_scale": float(os.getenv("FICFRAME_IMAGE_GUIDANCE_SCALE", "7.5")),
            }
            data = self._post(endpoint, "image", "images/generations", payload, purpose=purpose)
        elif references:
            multipart_files = [
                (
                    "image",
                    (
                        path.name,
                        path.read_bytes(),
                        mimetypes.guess_type(path.name)[0] or "image/png",
                    ),
                )
                for path in references
            ]
            data = self._post_multipart(
                endpoint,
                "image",
                "images/edits",
                {
                    "model": model or endpoint.model,
                    "prompt": reference_aware_prompt(cloud_prompt, True),
                    "size": size,
                    "n": "1",
                },
                multipart_files,
                purpose=purpose,
            )
        else:
            payload = {
                "model": model or endpoint.model,
                "prompt": cloud_prompt,
                "size": size,
                "n": 1,
            }
            data = self._post(endpoint, "image", "images/generations", payload, purpose=purpose)

        item = extract_image_item(data)
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if item.get("b64_json"):
            target.write_bytes(base64.b64decode(item["b64_json"]))
            logger.info("image saved path=%s source=b64", target)
            return target
        if item.get("url"):
            try:
                with httpx.Client(timeout=self.config.image_timeout) as client:
                    response = client.get(item["url"])
            except httpx.HTTPError as exc:
                logger.warning("image download exception error=%s", exc)
                raise ProviderError(provider_exception_message("image download", exc, self.config.image_timeout)) from exc
            if response.status_code >= 400:
                logger.warning("image download failed status=%s", response.status_code)
                raise ProviderError(f"图片下载失败：{response.status_code}")
            target.write_bytes(response.content)
            logger.info("image saved path=%s source=url status=%s", target, response.status_code)
            return target
        logger.warning("image response missing payload keys=%s", list(item.keys()))
        raise ProviderError("图片 API 没有返回 b64_json 或 url。")


def build_url(base_url: str, path: str) -> str:
    normalized = base_url.rstrip("/")
    suffix = path.strip("/")
    if normalized.endswith(suffix):
        return normalized
    return f"{normalized}/{suffix}"


def effective_image_provider(endpoint: EndpointConfig) -> str:
    if endpoint.provider == "openai" and "grsai." in endpoint.base_url:
        return "grsai"
    if endpoint.provider == "openai" and "ark.cn-" in endpoint.base_url:
        return "ark"
    return endpoint.provider


def effective_llm_provider(endpoint: EndpointConfig) -> str:
    # OpenAI 和 DeepSeek 都提供 Responses API，因此文本生成统一使用一种
    # 请求与响应结构，不再将 DeepSeek 转发到旧版 Chat API。
    return "responses"


def llm_runtime_path(endpoint: EndpointConfig) -> str:
    return "chat/completions" if effective_llm_provider(endpoint) == "chat_completions" else "responses"


def is_deepseek_endpoint(endpoint: EndpointConfig) -> bool:
    provider = endpoint.provider.lower()
    host = urlparse(endpoint.base_url).netloc.lower()
    model = endpoint.model.lower()
    return provider == "deepseek" or "deepseek" in model or host == "api.deepseek.com"


def can_fallback_deepseek_to_chat(exc: ProviderError) -> bool:
    message = str(exc).lstrip()
    status_text = message.split(maxsplit=1)[0] if message else ""
    if not status_text.isdigit():
        # 超时或连接失败可能发生在服务器接受请求之后；
        # 此时重试其他 endpoint 可能造成重复任务。
        return False
    return int(status_text) not in {401, 403, 408, 409, 429}


def effective_vlm_provider(endpoint: EndpointConfig) -> str:
    provider = endpoint.provider.lower()
    host = urlparse(endpoint.base_url).netloc.lower()
    if provider in {"siliconflow"} or "siliconflow.cn" in host:
        return "chat_completions"
    if provider in {"ark"} or "ark.cn-" in host:
        return "chat_completions"
    return "responses"


def vlm_runtime_path(endpoint: EndpointConfig) -> str:
    return "chat/completions" if effective_vlm_provider(endpoint) == "chat_completions" else "responses"


def safe_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    texts = collect_texts(payload)
    images = collect_image_markers(payload)
    joined = "\n".join(texts)
    return {
        "keys": sorted(payload.keys()),
        "text_count": len(texts),
        "text_chars": len(joined),
        "text_sha12": hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12] if joined else "",
        "text_preview": compact_log_text(joined, 180),
        "image_count": len(images),
        "image_kinds": sorted(set(images))[:8],
    }


def summarize_response(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    text = response.text[:300] if response.text else ""
    summary: dict[str, Any] = {"content_type": content_type, "body_chars": len(response.text or "")}
    if "application/json" in content_type:
        try:
            data = response.json()
            summary["json_keys"] = sorted(data.keys())[:12] if isinstance(data, dict) else type(data).__name__
            preview = extract_response_text(data) if isinstance(data, dict) else ""
            if preview:
                summary["text_preview"] = compact_log_text(preview, 160)
        except (ValueError, TypeError):
            summary["body_preview"] = compact_log_text(text, 160)
    elif text:
        summary["body_preview"] = compact_log_text(text, 160)
    return summary


def collect_texts(value: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"text", "prompt", "content"} and isinstance(item, str):
                texts.append(item)
            elif isinstance(item, (dict, list)):
                texts.extend(collect_texts(item))
    elif isinstance(value, list):
        for item in value:
            texts.extend(collect_texts(item))
    return texts


def collect_image_markers(value: Any) -> list[str]:
    markers: list[str] = []
    if isinstance(value, dict):
        value_type = str(value.get("type") or "")
        if "image" in value_type:
            markers.append(value_type)
        for key, item in value.items():
            if key in {"image_url", "images"}:
                markers.append(key)
            if isinstance(item, (dict, list)):
                markers.extend(collect_image_markers(item))
    elif isinstance(value, list):
        for item in value:
            markers.extend(collect_image_markers(item))
    return markers


def compact_log_text(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def env_float(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("invalid float env key=%s value=%s", key, value)
        return default


def read_env_text_file(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        return ""
    try:
        return Path(value).read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("cannot read env file key=%s path=%s error=%s", key, value, exc)
        return ""


def provider_exception_message(label: str, exc: httpx.HTTPError, timeout: float) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return f"{label} 请求超时（{timeout:.0f}s）。服务商可能排队较久，可以增大 FICFRAME_TIMEOUT，或稍后重试。"
    if isinstance(exc, httpx.ConnectError):
        return f"{label} 连接失败：{exc}"
    return f"{label} 网络请求失败：{exc}"


def reference_aware_prompt(prompt: str, has_references: bool) -> str:
    if not has_references:
        return prompt
    return (
        "Use every supplied reference image as the canonical character design. "
        "Preserve the character's species traits, hair color, hairstyle, face, ears, outfit silhouette, "
        "accessories, and body proportions. Do not redesign the character. "
        + prompt
    )


def combine_negative_prompts(*prompts: str) -> str:
    return ", ".join(prompt.strip().strip(",") for prompt in prompts if prompt and prompt.strip())


def image_prompt_with_negative(prompt: str, negative_prompt: str) -> str:
    if not negative_prompt.strip():
        return prompt
    return f"{prompt}\n\nNegative constraints:\n{negative_prompt.strip()}"


def to_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def extract_image_item(data: dict[str, Any]) -> dict[str, Any]:
    candidates = data.get("data", data)
    if isinstance(candidates, dict):
        candidates = candidates.get("results") or candidates.get("outputs") or candidates.get("data") or candidates
    if isinstance(candidates, list) and candidates:
        return candidates[0]
    if isinstance(candidates, dict):
        return candidates
    return {}


def extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str) and message.get("content", "").strip():
            return message["content"]
        if isinstance(message, dict):
            message_pieces = collect_response_text_fields(message)
            if message_pieces:
                return "\n".join(message_pieces)
        if isinstance(choices[0], dict) and isinstance(choices[0].get("text"), str):
            return choices[0]["text"]
    pieces: list[str] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "reasoning":
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, str):
                pieces.append(content)
                continue
            if not isinstance(content, dict):
                continue
            if content.get("type") == "reasoning_text":
                continue
            text = content.get("text") or content.get("output_text")
            if isinstance(text, str):
                pieces.append(text)
            elif isinstance(text, dict):
                nested_text = text.get("value") or text.get("content")
                if isinstance(nested_text, str):
                    pieces.append(nested_text)
    if pieces:
        return "\n".join(pieces)

    fallback_pieces = collect_response_text_fields(data.get("output")) or collect_response_text_fields(data.get("choices"))
    if fallback_pieces:
        return "\n".join(fallback_pieces)
    return json.dumps(data, ensure_ascii=False)


def ensure_response_completed(data: dict[str, Any]) -> None:
    """在解析 JSON 前识别 Responses API 的失败或截断状态。"""
    status = str(data.get("status") or "").lower()
    error = data.get("error")
    if status == "failed" or error:
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("code") or "未知错误")
        else:
            message = str(error or "未知错误")
        raise ProviderError(f"LLM Responses 请求失败：{message}")
    if status != "incomplete" and not data.get("incomplete_details"):
        return
    details = data.get("incomplete_details")
    reason = str(details.get("reason") or "unknown") if isinstance(details, dict) else str(details or "unknown")
    if reason == "max_output_tokens":
        raise ProviderError(
            f"LLM Responses 输出因达到 max_output_tokens 而被截断（当前 {DEEPSEEK_JSON_MAX_OUTPUT_TOKENS}），未使用不完整 JSON"
        )
    if reason == "content_filter":
        raise ProviderError("LLM Responses 输出被内容过滤器中止，未使用不完整 JSON")
    raise ProviderError(f"LLM Responses 输出不完整：{reason}")


def collect_response_text_fields(value: Any) -> list[str]:
    pieces: list[str] = []
    if isinstance(value, dict):
        value_type = str(value.get("type") or "")
        if value_type in {"reasoning", "reasoning_text"}:
            return pieces
        direct_keys = {"output_text", "text", "content"}
        for key in direct_keys:
            item = value.get(key)
            if isinstance(item, str) and item.strip() and ("text" in value_type or key in direct_keys):
                pieces.append(item)
            elif isinstance(item, (dict, list)):
                pieces.extend(collect_response_text_fields(item))
        for key, item in value.items():
            if key in direct_keys:
                continue
            if isinstance(item, (dict, list)):
                pieces.extend(collect_response_text_fields(item))
    elif isinstance(value, list):
        for item in value:
            pieces.extend(collect_response_text_fields(item))
    return pieces
