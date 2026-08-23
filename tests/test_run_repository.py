from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ficframe.run_repository import RunNotFoundError, RunRepository


class RunRepositoryTests(unittest.TestCase):
    def test_save_adds_defaults_and_increments_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = RunRepository(directory)
            payload = {"shots": []}
            repository.save("run-1", payload)
            saved = repository.load("run-1")

        self.assertEqual(saved["run_id"], "run-1")
        self.assertEqual(saved["schema_version"], 1)
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(saved["storyboard_messages"], [])
        self.assertEqual(saved["prompt_feedback_messages"], [])
        self.assertEqual(saved["storyboard_versions"], {})

    def test_transaction_commits_once_and_updates_projections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = RunRepository(directory)
            repository.save("run-1", {"shots": []})
            with repository.transaction("run-1") as payload:
                payload["storyboard_messages"].append({"role": "user", "content": "保留远景"})
            saved = repository.load("run-1")
            storyboard = (Path(directory) / "run-1" / "storyboard.md").read_text(encoding="utf-8")

        self.assertEqual(saved["revision"], 2)
        self.assertEqual(saved["storyboard_messages"][0]["content"], "保留远景")
        self.assertIsInstance(storyboard, str)

    def test_transaction_exception_does_not_write_partial_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = RunRepository(directory)
            repository.save("run-1", {"shots": [], "marker": "before"})
            with self.assertRaisesRegex(RuntimeError, "stop"):
                with repository.transaction("run-1") as payload:
                    payload["marker"] = "partial"
                    raise RuntimeError("stop")
            saved = repository.load("run-1")

        self.assertEqual(saved["marker"], "before")
        self.assertEqual(saved["revision"], 1)

    def test_list_runs_skips_invalid_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = RunRepository(directory)
            repository.save("valid", {"shots": [{"id": "shot-1"}], "characters": [{"name": "A"}]}, render=False)
            invalid = Path(directory) / "invalid"
            invalid.mkdir()
            (invalid / "pipeline.json").write_text("{broken", encoding="utf-8")

            runs = repository.list_runs()

        self.assertEqual([item["run_id"] for item in runs], ["valid"])
        self.assertEqual(runs[0]["shot_count"], 1)
        self.assertEqual(runs[0]["character_count"], 1)

    def test_missing_required_run_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = RunRepository(directory)
            with self.assertRaises(RunNotFoundError):
                repository.load("missing")


if __name__ == "__main__":
    unittest.main()
