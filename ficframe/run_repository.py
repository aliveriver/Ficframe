from __future__ import annotations

import json
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .io import read_text
from .render import render_prompts, render_storyboard
from .models import Shot


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class RunNotFoundError(FileNotFoundError):
    """当 run 不包含规范的 pipeline 状态时抛出。"""


class RunRepository:
    """Web run 的统一持久化边界。

    Web 应用为每个 run 保存一份规范 JSON 文档。所有写入都经过此类，
    以便原子替换文件，并串行提交同一 run 的并发请求。
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def run_dir(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(str(run_id)):
            raise ValueError("非法 run_id")
        path = (self.root / str(run_id)).resolve()
        if self.root not in path.parents and path != self.root:
            raise ValueError("非法 run_id")
        return path

    def pipeline_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "pipeline.json"

    def novel_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "novel.md"

    def exists(self, run_id: str) -> bool:
        return self.pipeline_path(run_id).exists()

    def list_runs(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """按规范状态文件的修改时间倒序返回可读取的 run。"""
        entries: list[dict[str, Any]] = []
        if not self.root.exists():
            return entries
        paths = sorted(self.root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True)
        for path in paths:
            if not path.is_dir():
                continue
            pipeline_path = path / "pipeline.json"
            if not pipeline_path.exists():
                continue
            try:
                payload = self.load(path.name)
            except (json.JSONDecodeError, OSError, ValueError):
                continue
            entries.append({
                "run_id": path.name,
                "modified_at": int(pipeline_path.stat().st_mtime),
                "shot_count": len(payload.get("shots", [])),
                "character_count": len(payload.get("characters", [])),
                "revision": payload.get("revision", 0),
            })
            if limit is not None and len(entries) >= limit:
                break
        return entries

    def _lock_for(self, run_id: str) -> threading.RLock:
        key = str(self.run_dir(run_id))
        with self._locks_guard:
            return self._locks.setdefault(key, threading.RLock())

    def load(self, run_id: str, *, required: bool = True) -> dict[str, Any]:
        path = self.pipeline_path(run_id)
        if not path.exists():
            if required:
                raise RunNotFoundError(run_id)
            return {}
        with self._lock_for(run_id):
            payload = json.loads(read_text(path))
        return self._with_defaults(payload, run_id)

    def save(self, run_id: str, payload: dict[str, Any], *, render: bool = True) -> Path:
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        normalized = self._with_defaults(payload, run_id)
        with self._lock_for(run_id):
            normalized["revision"] = int(normalized.get("revision") or 0) + 1
            self._atomic_write_json(run_dir / "pipeline.json", normalized)
            if render:
                self._write_projections(run_dir, normalized)
        return run_dir / "pipeline.json"

    @contextmanager
    def transaction(self, run_id: str, *, render: bool = True) -> Iterator[dict[str, Any]]:
        """持有 run 锁期间加载、修改并原子保存状态。"""
        lock = self._lock_for(run_id)
        with lock:
            payload = self.load(run_id)
            yield payload
            normalized = self._with_defaults(payload, run_id)
            normalized["revision"] = int(normalized.get("revision") or 0) + 1
            self._atomic_write_json(self.pipeline_path(run_id), normalized)
            if render:
                self._write_projections(self.run_dir(run_id), normalized)

    def _with_defaults(self, payload: dict[str, Any], run_id: str) -> dict[str, Any]:
        payload.setdefault("run_id", run_id)
        payload.setdefault("schema_version", 1)
        payload.setdefault("revision", 0)
        payload.setdefault("storyboard_messages", [])
        payload.setdefault("prompt_feedback_messages", [])
        payload.setdefault("storyboard_versions", {})
        return payload

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
        )
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    @staticmethod
    def _write_projections(run_dir: Path, payload: dict[str, Any]) -> None:
        shots = [Shot(**item) for item in payload.get("shots", [])]
        RunRepository._atomic_write_text(run_dir / "storyboard.md", render_storyboard(shots))
        RunRepository._atomic_write_text(run_dir / "prompts.md", render_prompts(shots))
        if "continuity" in payload:
            RunRepository._atomic_write_json(run_dir / "continuity.json", payload["continuity"])

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp")
        temp.write_text(content, encoding="utf-8")
        os.replace(temp, path)
