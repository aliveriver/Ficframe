from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from ficframe.run_repository import RunRepository
from ficframe.task_manager import TaskManager


class TaskManagerTests(unittest.TestCase):
    def wait_terminal(self, manager: TaskManager, task_id: str) -> dict:
        deadline = time.time() + 3
        while time.time() < deadline:
            task = manager.get(task_id)
            if task["status"] in {"succeeded", "failed", "cancelled"}:
                return task
            time.sleep(0.01)
        self.fail("任务未在测试时限内结束")

    def test_task_progress_result_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = RunRepository(directory)
            manager = TaskManager(repository, max_workers=1)

            def work(reporter):
                reporter.update("调用 LLM", 40, "正在生成")
                reporter.log("LLM 已返回")
                return {"shot_id": "shot_01"}

            created = manager.submit("run-1", "storyboard_generate", work)
            task = self.wait_terminal(manager, created["task_id"])

            self.assertEqual(task["status"], "succeeded")
            self.assertEqual(task["progress"], 100)
            self.assertEqual(task["result"]["shot_id"], "shot_01")
            self.assertTrue((Path(directory) / "run-1" / "tasks.json").exists())
            reloaded = TaskManager(repository, max_workers=1).get(created["task_id"])
            self.assertEqual(reloaded["status"], "succeeded")

    def test_failure_records_error_and_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = TaskManager(RunRepository(directory), max_workers=1)

            def fail(_reporter):
                raise RuntimeError("生成失败")

            created = manager.submit("run-2", "image", fail)
            task = self.wait_terminal(manager, created["task_id"])

            self.assertEqual(task["status"], "failed")
            self.assertIn("生成失败", task["error"])
            self.assertTrue(any("Traceback" in item["message"] for item in task["logs"]))


if __name__ == "__main__":
    unittest.main()
