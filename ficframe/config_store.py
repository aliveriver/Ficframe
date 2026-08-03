from __future__ import annotations

import os
import json
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


CONFIG_KEYS = [
    "FICFRAME_TIMEOUT",
    "FICFRAME_IMAGE_TIMEOUT",
    "FICFRAME_LLM_API_KEY",
    "FICFRAME_LLM_BASE_URL",
    "FICFRAME_LLM_MODEL",
    "FICFRAME_IMAGE_API_KEY",
    "FICFRAME_IMAGE_BASE_URL",
    "FICFRAME_IMAGE_PROVIDER",
    "FICFRAME_IMAGE_MODEL",
    "FICFRAME_VLM_API_KEY",
    "FICFRAME_VLM_BASE_URL",
    "FICFRAME_VLM_PROVIDER",
    "FICFRAME_VLM_MODEL",
    "FICFRAME_IMAGE_STEPS",
    "FICFRAME_IMAGE_GUIDANCE_SCALE",
    "FICFRAME_IMAGE_BATCH_SIZE",
    "FICFRAME_IMAGE_SEQUENTIAL",
    "FICFRAME_IMAGE_RESPONSE_FORMAT",
    "FICFRAME_IMAGE_WATERMARK",
]


DEFAULT_CONFIG = {
    "FICFRAME_TIMEOUT": "300",
    "FICFRAME_IMAGE_TIMEOUT": "900",
    "FICFRAME_LLM_BASE_URL": "https://api.openai.com/v1",
    "FICFRAME_LLM_MODEL": "gpt-5-mini",
    "FICFRAME_IMAGE_BASE_URL": "https://api.siliconflow.cn/v1",
    "FICFRAME_IMAGE_PROVIDER": "siliconflow",
    "FICFRAME_IMAGE_MODEL": "Kwai-Kolors/Kolors",
    "FICFRAME_VLM_BASE_URL": "https://api.openai.com/v1",
    "FICFRAME_VLM_PROVIDER": "openai",
    "FICFRAME_VLM_MODEL": "gpt-5-mini",
    "FICFRAME_IMAGE_STEPS": "20",
    "FICFRAME_IMAGE_GUIDANCE_SCALE": "7.5",
    "FICFRAME_IMAGE_BATCH_SIZE": "1",
    "FICFRAME_IMAGE_SEQUENTIAL": "disabled",
    "FICFRAME_IMAGE_RESPONSE_FORMAT": "url",
    "FICFRAME_IMAGE_WATERMARK": "true",
}


def default_provider_config(env_path: str | Path) -> dict[str, Any]:
    values = read_env_file(env_path)
    now = int(time.time())
    return {
        "version": 1,
        "active": {"llm": "llm-default", "image": "image-default", "vlm": "vlm-default"},
        "sources": [
            {
                "id": "llm-default",
                "label": "默认 LLM",
                "kind": "llm",
                "provider": "openai",
                "base_url": values.get("FICFRAME_LLM_BASE_URL", ""),
                "api_key": values.get("FICFRAME_LLM_API_KEY", ""),
                "models": [{"nickname": "默认模型", "model": values.get("FICFRAME_LLM_MODEL", "")}],
                "active_model": values.get("FICFRAME_LLM_MODEL", ""),
                "created_at": now,
            },
            {
                "id": "image-default",
                "label": "默认图片",
                "kind": "image",
                "provider": values.get("FICFRAME_IMAGE_PROVIDER", "openai"),
                "base_url": values.get("FICFRAME_IMAGE_BASE_URL", ""),
                "api_key": values.get("FICFRAME_IMAGE_API_KEY", ""),
                "models": [{"nickname": "默认模型", "model": values.get("FICFRAME_IMAGE_MODEL", "")}],
                "active_model": values.get("FICFRAME_IMAGE_MODEL", ""),
                "options": {
                    "steps": values.get("FICFRAME_IMAGE_STEPS", "20"),
                    "guidance_scale": values.get("FICFRAME_IMAGE_GUIDANCE_SCALE", "7.5"),
                    "batch_size": values.get("FICFRAME_IMAGE_BATCH_SIZE", "1"),
                    "sequential": values.get("FICFRAME_IMAGE_SEQUENTIAL", "disabled"),
                    "response_format": values.get("FICFRAME_IMAGE_RESPONSE_FORMAT", "url"),
                    "watermark": values.get("FICFRAME_IMAGE_WATERMARK", "true"),
                },
                "created_at": now,
            },
            {
                "id": "vlm-default",
                "label": "默认 VLM",
                "kind": "vlm",
                "provider": values.get("FICFRAME_VLM_PROVIDER", "openai"),
                "base_url": values.get("FICFRAME_VLM_BASE_URL", ""),
                "api_key": values.get("FICFRAME_VLM_API_KEY", ""),
                "models": [{"nickname": "默认模型", "model": values.get("FICFRAME_VLM_MODEL", "")}],
                "active_model": values.get("FICFRAME_VLM_MODEL", ""),
                "created_at": now,
            },
        ],
    }


def read_env_file(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    values = dict(DEFAULT_CONFIG)
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() in CONFIG_KEYS:
                values[key.strip()] = value.strip().strip('"').strip("'")
    for key in CONFIG_KEYS:
        if os.getenv(key):
            values[key] = os.getenv(key, "")
    return values


def write_env_file(path: str | Path, values: dict[str, str]) -> None:
    env_path = Path(path)
    current = read_env_file(env_path)
    for key in CONFIG_KEYS:
        if key in values:
            if key.endswith("_API_KEY") and is_masked_or_empty(str(values[key])):
                continue
            current[key] = str(values[key])
            os.environ[key] = str(values[key])
    lines = ["# FicFrame API configuration"]
    for key in CONFIG_KEYS:
        if key in current:
            lines.append(f"{key}={current[key]}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    load_dotenv(env_path, override=True)


def public_config(path: str | Path, reveal_keys: bool = True) -> dict[str, str]:
    values = read_env_file(path)
    if reveal_keys:
        return values
    masked = values.copy()
    for key in [item for item in CONFIG_KEYS if item.endswith("_API_KEY")]:
        value = masked.get(key, "")
        masked[key] = mask_secret(value)
    return masked


def read_provider_config(path: str | Path, env_path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        return default_provider_config(env_path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_provider_config(env_path)
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        return default_provider_config(env_path)
    data.setdefault("version", 1)
    data.setdefault("active", {})
    data["sources"] = [source for source in data["sources"] if isinstance(source, dict) and source.get("kind") in {"llm", "image", "vlm"}]
    data["active"] = {key: value for key, value in data["active"].items() if key in {"llm", "image", "vlm"}}
    return data


def public_provider_config(path: str | Path, env_path: str | Path) -> dict[str, Any]:
    data = read_provider_config(path, env_path)
    public = {
        "version": data.get("version", 1),
        "active": dict(data.get("active", {})),
        "sources": [],
    }
    for source in data.get("sources", []):
        item = dict(source)
        item["api_key"] = mask_secret(str(item.get("api_key", "")))
        public["sources"].append(item)
    return public


def write_provider_config(path: str | Path, env_path: str | Path, incoming: dict[str, Any]) -> dict[str, Any]:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    current = read_provider_config(config_path, env_path)
    current_by_id = {str(item.get("id", "")): item for item in current.get("sources", [])}

    clean_sources: list[dict[str, Any]] = []
    for source in incoming.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("id") or "").strip()
        if not source_id:
            continue
        item = {
            "id": source_id,
            "label": str(source.get("label") or source_id).strip(),
            "kind": str(source.get("kind") or "image").strip().lower(),
            "provider": str(source.get("provider") or "openai").strip().lower(),
            "base_url": str(source.get("base_url") or "").strip().rstrip("/"),
            "api_key": str(source.get("api_key") or ""),
            "models": normalize_models(source.get("models")),
            "active_model": str(source.get("active_model") or "").strip(),
            "options": normalize_options(source.get("options")),
            "created_at": source.get("created_at") or int(time.time()),
        }
        if item["kind"] not in {"llm", "image", "vlm"}:
            continue
        if is_masked_or_empty(item["api_key"]):
            item["api_key"] = str(current_by_id.get(source_id, {}).get("api_key") or "")
        if not item["active_model"] and item["models"]:
            item["active_model"] = str(item["models"][0].get("model") or "")
        clean_sources.append(item)

    data = {
        "version": 1,
        "active": normalize_active(incoming.get("active"), clean_sources),
        "sources": clean_sources,
    }
    config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sync_active_sources_to_env(env_path, data)
    return data


def normalize_models(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    models = []
    for item in value:
        if not isinstance(item, dict):
            continue
        model = str(item.get("model") or "").strip()
        nickname = str(item.get("nickname") or model or "未命名模型").strip()
        if model:
            models.append({"nickname": nickname, "model": model})
    return models


def normalize_options(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if item is not None}


def normalize_active(value: Any, sources: list[dict[str, Any]]) -> dict[str, str]:
    active = value if isinstance(value, dict) else {}
    result: dict[str, str] = {}
    for kind in ("llm", "image", "vlm"):
        selected = str(active.get(kind) or "")
        if not any(item.get("id") == selected and item.get("kind") == kind for item in sources):
            selected = next((str(item.get("id")) for item in sources if item.get("kind") == kind), "")
        result[kind] = selected
    return result


def sync_active_sources_to_env(env_path: str | Path, data: dict[str, Any]) -> None:
    sources = {str(item.get("id")): item for item in data.get("sources", [])}
    active = data.get("active", {})
    values: dict[str, str] = {}
    mappings = {
        "llm": ("FICFRAME_LLM", False),
        "image": ("FICFRAME_IMAGE", True),
        "vlm": ("FICFRAME_VLM", True),
    }
    for kind, (prefix, has_provider) in mappings.items():
        source = sources.get(str(active.get(kind) or ""))
        if not source:
            continue
        values[f"{prefix}_API_KEY"] = str(source.get("api_key") or "")
        values[f"{prefix}_BASE_URL"] = str(source.get("base_url") or "")
        values[f"{prefix}_MODEL"] = str(source.get("active_model") or "")
        if has_provider:
            values[f"{prefix}_PROVIDER"] = str(source.get("provider") or "openai")
        if kind == "vlm":
            continue
        if has_provider:
            options = source.get("options") if isinstance(source.get("options"), dict) else {}
            option_map = {
                "steps": "FICFRAME_IMAGE_STEPS",
                "guidance_scale": "FICFRAME_IMAGE_GUIDANCE_SCALE",
                "batch_size": "FICFRAME_IMAGE_BATCH_SIZE",
                "sequential": "FICFRAME_IMAGE_SEQUENTIAL",
                "response_format": "FICFRAME_IMAGE_RESPONSE_FORMAT",
                "watermark": "FICFRAME_IMAGE_WATERMARK",
            }
            for option_key, env_key in option_map.items():
                if option_key in options:
                    values[env_key] = str(options[option_key])
    write_env_file(env_path, values)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def is_masked_or_empty(value: str) -> bool:
    stripped = value.strip()
    return not stripped or stripped == "****" or "..." in stripped
