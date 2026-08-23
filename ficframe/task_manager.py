from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from .run_repository import RunRepository


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


class TaskReporter:
    """供后台工作函数更新任务阶段、进度和日志。"""

    def __init__(self, manager: "TaskManager", task_id: str):
        self.manager = manager
        self.task_id = task_id

    def update(self, stage: str, progress: int, message: str = "") -> None:
        self.manager.update(self.task_id, stage=stage, progress=progress, message=message)

    def log(self, message: str) -> None:
        self.manager.append_log(self.task_id, message)


class TaskManager:
    """使用进程内 worker 执行任务，并把任务快照持久化到对应 run。"""

    def __init__(self, repository: RunRepository, max_workers: int = 4):
        self.repository = repository
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ficframe-task")
        self._lock = threading.RLock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._futures: dict[str, Future[Any]] = {}

    def submit(
        self,
        run_id: str,
        kind: str,
        work: Callable[[TaskReporter], Any],
        *,
        message: str = "等待执行",
    ) -> dict[str, Any]:
        now = int(time.time())
        task_id = f"task_{uuid.uuid4().hex}"
        task = {
            "task_id": task_id,
            "run_id": run_id,
            "kind": kind,
            "status": "queued",
            "stage": "排队中",
            "progress": 0,
            "message": message,
            "created_at": now,
            "started_at": None,
            "updated_at": now,
            "finished_at": None,
            "result": None,
            "error": None,
            "logs": [],
        }
        with self._lock:
            self._tasks[task_id] = task
            self._persist_run(run_id)
            self._futures[task_id] = self.executor.submit(self._execute, task_id, work)
        return self.get(task_id)

    def get(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id) or self._load_task(task_id)
            if task is None:
                raise KeyError(task_id)
            return json.loads(json.dumps(task, ensure_ascii=False))

    def list_for_run(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            disk_tasks = self._read_run_tasks(run_id)
            for task in disk_tasks:
                self._tasks.setdefault(str(task.get("task_id")), task)
            tasks = [task for task in self._tasks.values() if task.get("run_id") == run_id]
            return json.loads(json.dumps(sorted(tasks, key=lambda item: item.get("created_at", 0), reverse=True), ensure_ascii=False))

    def update(self, task_id: str, **values: Any) -> None:
        with self._lock:
            task = self._tasks[task_id]
            task.update(values)
            task["progress"] = max(0, min(100, int(task.get("progress") or 0)))
            task["updated_at"] = int(time.time())
            self._persist_run(str(task["run_id"]))

    def append_log(self, task_id: str, message: str) -> None:
        with self._lock:
            task = self._tasks[task_id]
            task.setdefault("logs", []).append({"created_at": int(time.time()), "message": str(message)})
            del task["logs"][:-100]
            task["updated_at"] = int(time.time())
            self._persist_run(str(task["run_id"]))

    def cancel(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id) or self._load_task(task_id)
            if task is None:
                raise KeyError(task_id)
            if task.get("status") != "queued":
                raise RuntimeError("只能取消尚未开始的任务")
            future = self._futures.get(task_id)
            if future is None or not future.cancel():
                raise RuntimeError("任务已经开始，无法取消")
            now = int(time.time())
            task.update(status="cancelled", stage="已取消", message="任务已取消", finished_at=now, updated_at=now)
            self._persist_run(str(task["run_id"]))
            return self.get(task_id)

    def _execute(self, task_id: str, work: Callable[[TaskReporter], Any]) -> None:
        now = int(time.time())
        self.update(task_id, status="running", stage="准备输入", progress=1, message="任务已开始", started_at=now)
        reporter = TaskReporter(self, task_id)
        try:
            result = work(reporter)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.append_log(task_id, traceback.format_exc())
            self.update(
                task_id, status="failed", stage="失败", message=error,
                error=error, finished_at=int(time.time()),
            )
            return
        self.update(
            task_id, status="succeeded", stage="完成", progress=100, message="任务已完成",
            result=result, finished_at=int(time.time()), error=None,
        )

    def _tasks_path(self, run_id: str) -> Path:
        return self.repository.run_dir(run_id) / "tasks.json"

    def _read_run_tasks(self, run_id: str) -> list[dict[str, Any]]:
        path = self._tasks_path(run_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data.get("tasks", []) if isinstance(data, dict) else []

    def _persist_run(self, run_id: str) -> None:
        tasks = [task for task in self._tasks.values() if task.get("run_id") == run_id]
        tasks.sort(key=lambda item: item.get("created_at", 0), reverse=True)
        RunRepository._atomic_write_json(self._tasks_path(run_id), {"tasks": tasks[:100]})

    def _load_task(self, task_id: str) -> dict[str, Any] | None:
        if not self.repository.root.exists():
            return None
        for run_dir in self.repository.root.iterdir():
            if not run_dir.is_dir():
                continue
            for task in self._read_run_tasks(run_dir.name):
                if task.get("task_id") == task_id:
                    self._tasks[task_id] = task
                    return task
        return None
