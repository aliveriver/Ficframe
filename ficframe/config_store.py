from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


CONFIG_KEYS = [
    "FICFRAME_LLM_API_KEY",
    "FICFRAME_LLM_BASE_URL",
    "FICFRAME_LLM_MODEL",
    "FICFRAME_IMAGE_API_KEY",
    "FICFRAME_IMAGE_BASE_URL",
    "FICFRAME_IMAGE_PROVIDER",
    "FICFRAME_IMAGE_MODEL",
    "FICFRAME_IMAGE_STEPS",
    "FICFRAME_IMAGE_GUIDANCE_SCALE",
    "FICFRAME_IMAGE_BATCH_SIZE",
    "FICFRAME_VLM_API_KEY",
    "FICFRAME_VLM_BASE_URL",
    "FICFRAME_VLM_MODEL",
]


DEFAULT_CONFIG = {
    "FICFRAME_LLM_BASE_URL": "https://api.openai.com/v1",
    "FICFRAME_LLM_MODEL": "gpt-5-mini",
    "FICFRAME_IMAGE_BASE_URL": "https://api.siliconflow.cn/v1",
    "FICFRAME_IMAGE_PROVIDER": "siliconflow",
    "FICFRAME_IMAGE_MODEL": "Kwai-Kolors/Kolors",
    "FICFRAME_IMAGE_STEPS": "20",
    "FICFRAME_IMAGE_GUIDANCE_SCALE": "7.5",
    "FICFRAME_IMAGE_BATCH_SIZE": "1",
    "FICFRAME_VLM_BASE_URL": "https://api.openai.com/v1",
    "FICFRAME_VLM_MODEL": "gpt-5-mini",
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


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def is_masked_or_empty(value: str) -> bool:
    stripped = value.strip()
    return not stripped or stripped == "****" or "..." in stripped
