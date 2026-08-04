from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from .logging_utils import get_logger


load_dotenv()
logger = get_logger("providers")


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
        )


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfig | None = None):
        self.config = config or ProviderConfig.from_env()

    def _headers(self, endpoint: EndpointConfig, label: str) -> dict[str, str]:
        if not endpoint.api_key:
            raise ProviderError(f"缺少 {label} API key。请设置 FICFRAME_{label.upper()}_API_KEY。")
        return {"Authorization": f"Bearer {endpoint.api_key}", "Content-Type": "application/json"}

    def _post(self, endpoint: EndpointConfig, label: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = build_url(endpoint.base_url, path)
        timeout = self._timeout_for(label)
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=self._headers(endpoint, label), json=payload)
        except httpx.HTTPError as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.warning("provider post exception label=%s path=%s duration_ms=%s error=%s", label, path, duration_ms, exc)
            raise ProviderError(provider_exception_message(label, exc, timeout)) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "provider post label=%s provider=%s path=%s status=%s duration_ms=%s model=%s",
            label,
            endpoint.provider,
            path,
            response.status_code,
            duration_ms,
            payload.get("model", ""),
        )
        if response.status_code >= 400:
            logger.warning("provider post failed label=%s path=%s status=%s body=%s", label, path, response.status_code, response.text[:500])
            raise ProviderError(f"{response.status_code} {url}: {response.text[:1000]}")
        return response.json()

    def _post_multipart(
        self,
        endpoint: EndpointConfig,
        label: str,
        path: str,
        data: dict[str, str],
        files: list[tuple[str, tuple[str, bytes, str]]],
    ) -> dict[str, Any]:
        url = build_url(endpoint.base_url, path)
        headers = self._headers(endpoint, label)
        headers.pop("Content-Type", None)
        timeout = self._timeout_for(label)
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, headers=headers, data=data, files=files)
        except httpx.HTTPError as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.warning("provider multipart exception label=%s path=%s duration_ms=%s error=%s", label, path, duration_ms, exc)
            raise ProviderError(provider_exception_message(label, exc, timeout)) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "provider multipart label=%s provider=%s path=%s status=%s duration_ms=%s model=%s file_count=%s",
            label,
            endpoint.provider,
            path,
            response.status_code,
            duration_ms,
            data.get("model", ""),
            len(files),
        )
        if response.status_code >= 400:
            logger.warning("provider multipart failed label=%s path=%s status=%s body=%s", label, path, response.status_code, response.text[:500])
            raise ProviderError(f"{response.status_code} {url}: {response.text[:1000]}")
        return response.json()

    def text(self, system: str, user: str, model: str | None = None) -> str:
        endpoint = self.config.llm
        payload = {
            "model": model or endpoint.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": [{"type": "input_text", "text": user}]},
            ],
        }
        data = self._post(endpoint, "llm", "responses", payload)
        return extract_response_text(data)

    def vision(self, system: str, prompt: str, image_paths: list[Path], model: str | None = None) -> str:
        endpoint = self.config.vlm
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for path in image_paths:
            content.append({"type": "input_image", "image_url": to_data_url(path)})
        payload = {
            "model": model or endpoint.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": content},
            ],
        }
        data = self._post(endpoint, "vlm", "responses", payload)
        return extract_response_text(data)

    def _timeout_for(self, label: str) -> float:
        return self.config.image_timeout if label.startswith("image") else self.config.timeout

    def image(
        self,
        prompt: str,
        out_path: str | Path,
        model: str | None = None,
        size: str = "1024x1024",
        reference_images: list[Path] | None = None,
    ) -> Path:
        endpoint = self.config.image
        references = reference_images or []
        provider = effective_image_provider(endpoint)
        logger.info("image request provider=%s model=%s size=%s reference_count=%s", provider, model or endpoint.model, size, len(references))

        if provider == "grsai":
            payload = {
                "model": model or endpoint.model,
                "prompt": reference_aware_prompt(prompt, bool(references)),
                "images": [to_data_url(path) for path in references],
                "aspectRatio": size,
                "replyType": "json",
            }
            data = self._post(endpoint, "image", "api/generate", payload)
        elif provider == "ark":
            payload = {
                "model": model or endpoint.model,
                "prompt": reference_aware_prompt(prompt, bool(references)),
                "sequential_image_generation": os.getenv("FICFRAME_IMAGE_SEQUENTIAL", "disabled"),
                "response_format": os.getenv("FICFRAME_IMAGE_RESPONSE_FORMAT", "url"),
                "size": size,
                "stream": False,
                "watermark": env_bool("FICFRAME_IMAGE_WATERMARK", True),
            }
            if references:
                payload["images"] = [to_data_url(path) for path in references]
            data = self._post(endpoint, "image", "images/generations", payload)
        elif provider == "siliconflow":
            payload = {
                "model": model or endpoint.model,
                "prompt": prompt,
                "image_size": size,
                "batch_size": int(os.getenv("FICFRAME_IMAGE_BATCH_SIZE", "1")),
                "num_inference_steps": int(os.getenv("FICFRAME_IMAGE_STEPS", "20")),
                "guidance_scale": float(os.getenv("FICFRAME_IMAGE_GUIDANCE_SCALE", "7.5")),
            }
            data = self._post(endpoint, "image", "images/generations", payload)
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
                    "prompt": reference_aware_prompt(prompt, True),
                    "size": size,
                    "n": "1",
                },
                multipart_files,
            )
        else:
            payload = {
                "model": model or endpoint.model,
                "prompt": prompt,
                "size": size,
                "n": 1,
            }
            data = self._post(endpoint, "image", "images/generations", payload)

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
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        if isinstance(choices[0], dict) and isinstance(choices[0].get("text"), str):
            return choices[0]["text"]
    pieces: list[str] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, str):
                pieces.append(content)
                continue
            if not isinstance(content, dict):
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

    fallback_pieces = collect_response_text_fields(data.get("output"))
    if fallback_pieces:
        return "\n".join(fallback_pieces)
    return json.dumps(data, ensure_ascii=False)


def collect_response_text_fields(value: Any) -> list[str]:
    pieces: list[str] = []
    if isinstance(value, dict):
        value_type = str(value.get("type") or "")
        for key in ("output_text", "text", "content"):
            item = value.get(key)
            if isinstance(item, str) and ("text" in value_type or key in {"output_text", "text"}):
                pieces.append(item)
        for item in value.values():
            if isinstance(item, (dict, list)):
                pieces.extend(collect_response_text_fields(item))
    elif isinstance(value, list):
        for item in value:
            pieces.extend(collect_response_text_fields(item))
    return pieces
