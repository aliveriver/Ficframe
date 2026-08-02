from __future__ import annotations

import json
import logging
import platform
import re
import sys
import time
import zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


LOGGER_NAME = "ficframe"
SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(ark-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(?i)(api[_-]?key['\"\s:=]+)([A-Za-z0-9_\-\.]{8,})"),
    re.compile(r"(?i)(authorization['\"\s:=]+bearer\s+)([A-Za-z0-9_\-\.]{8,})"),
]


def setup_logging(root: str | Path) -> Path:
    logs_dir = Path(root) / "outputs" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logs_dir

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    app_handler = RotatingFileHandler(
        logs_dir / "ficframe.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(formatter)
    logger.addHandler(app_handler)

    error_handler = RotatingFileHandler(
        logs_dir / "errors.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)

    logger.info("logging initialized logs_dir=%s", logs_dir)
    return logs_dir


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact_secret_value(key, item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_secret_value(key: Any, value: Any) -> Any:
    if str(key).lower() in {"api_key", "authorization", "token", "secret", "password"}:
        return mask_secret(str(value)) if value else ""
    return redact(value)


def redact_text(value: str) -> str:
    redacted = value
    for pattern in SECRET_PATTERNS:
        if pattern.groups >= 2:
            redacted = pattern.sub(lambda match: match.group(1) + mask_secret(match.group(2)), redacted)
        else:
            redacted = pattern.sub(lambda match: mask_secret(match.group(1)), redacted)
    return redacted


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def build_log_bundle(
    root: str | Path,
    config: dict[str, Any] | None = None,
    active_run_id: str | None = None,
) -> Path:
    root_path = Path(root)
    logs_dir = root_path / "outputs" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = logs_dir / f"ficframe-logs-{int(time.time())}.zip"
    diagnostics = collect_diagnostics(root_path, config or {}, active_run_id)

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", json.dumps(redact(diagnostics), ensure_ascii=False, indent=2))
        for path in sorted(logs_dir.glob("*.log*")):
            if path == bundle_path:
                continue
            archive.write(path, f"logs/{path.name}")
        readme = root_path / "README.md"
        if readme.exists():
            archive.write(readme, "project/README.md")
        if active_run_id:
            run_dir = root_path / "outputs" / "web-runs" / active_run_id
            for name in ["pipeline.json", "storyboard.md", "prompts.md", "continuity.json"]:
                path = run_dir / name
                if path.exists():
                    archive.writestr(f"run/{name}", redact_text(path.read_text(encoding="utf-8", errors="replace")))
    return bundle_path


def collect_diagnostics(root: Path, config: dict[str, Any], active_run_id: str | None) -> dict[str, Any]:
    runs_dir = root / "outputs" / "web-runs"
    recent_runs = []
    if runs_dir.exists():
        for path in sorted(runs_dir.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)[:10]:
            if path.is_dir():
                recent_runs.append(
                    {
                        "run_id": path.name,
                        "modified_at": int(path.stat().st_mtime),
                        "has_pipeline": (path / "pipeline.json").exists(),
                        "image_count": len(list((path / "images").glob("*"))) if (path / "images").exists() else 0,
                    }
                )
    return {
        "created_at": int(time.time()),
        "python": sys.version,
        "platform": platform.platform(),
        "active_run_id": active_run_id,
        "config": config,
        "recent_runs": recent_runs,
    }
