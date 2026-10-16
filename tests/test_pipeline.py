from __future__ import annotations

import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ficframe import api
from ficframe.characters import build_character_cards
from ficframe.models import Shot
from ficframe.pipeline import build_story_payload, polish_shots_with_llm, run_pipeline
from ficframe.run_repository import RunRepository
from ficframe.task_manager import TaskManager
from ficframe.visual_presets import VisualPresetStore
from ficframe.visual_preset_workflow import resolve_generation


NOVEL = "# Chapter 1\n\nAlice waits at the station."
CHARACTERS = "## Alice\n- 身份：主角\n- 外貌：黑色短发"


class PipelineTests(unittest.TestCase):
    def test_initial_style_selection_is_pinned_and_used_without_overwriting_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = VisualPresetStore(root / "presets")
            paths = store.save_draft_references([("ref.png", b"\x89PNG\r\n\x1a\nreference")])
            style = store.create(name="Ink", preset_type="style", positive="ink lines", reference_mode="image", reference_paths=paths)
            with patch.object(api, "RUNS", root / "runs"), patch.object(api, "get_visual_preset_store", return_value=store), TestClient(api.app) as client:
                for mode in ("text", "image"):
                    with self.subTest(mode=mode):
                        response = client.post("/api/pipeline",
                            data={"use_llm": "false", "run_id": mode, "style_id": style["id"], "style_reference_mode": mode},
                            files={"novel": ("novel.md", NOVEL.encode()), "characters": ("characters.md", CHARACTERS.encode())})
                        self.assertEqual(response.status_code, 200, response.text)
                        payload = response.json()
                        self.assertEqual(payload["visual_presets"]["style_id"], style["id"])
                        self.assertEqual(payload["visual_presets"]["style_reference_mode"], mode)
                        for shot in payload["shots"]:
                            self.assertEqual(shot["style_preset_snapshot"]["id"], style["id"])
                            self.assertEqual(shot["style_preset_snapshot"]["reference_mode"], mode)
                            self.assertEqual(shot["style_preset_mode"], "inherit")
                store.update(style["id"], {"positive": "NEW STYLE"})
                positive, _, snapshot = resolve_generation(store, payload, Shot(**payload["shots"][0]))
                self.assertIn("Style guide: ink lines", positive)
                self.assertNotIn("NEW STYLE", positive)
                self.assertNotIn("Style guide:", payload["shots"][0]["positive_prompt"])
                self.assertEqual(snapshot["style"]["version"], 1)

    def test_pipeline_task_carries_style_selection_into_saved_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = VisualPresetStore(root / "presets")
            style = store.create(name="Ink", preset_type="style", positive="ink lines")
            manager = TaskManager(RunRepository(root / "runs"))
            try:
                with patch.object(api, "RUNS", root / "runs"), patch.object(api, "get_visual_preset_store", return_value=store), patch.object(api, "get_task_manager", return_value=manager), TestClient(api.app) as client:
                    created = client.post("/api/pipeline/task", data={"use_llm": "false", "style_id": style["id"], "style_reference_mode": "text"},
                        files={"novel": ("novel.md", NOVEL.encode()), "characters": ("characters.md", CHARACTERS.encode())})
                    self.assertEqual(created.status_code, 202, created.text)
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        task = manager.get(created.json()["task_id"])
                        if task["status"] in ("succeeded", "failed", "cancelled"):
                            break
                        time.sleep(0.01)
                    self.assertEqual(task["status"], "succeeded", task)
                    saved = manager.repository.load(created.json()["run_id"])
                    self.assertEqual(saved["visual_presets"]["style_id"], style["id"])
                    self.assertEqual(saved["shots"][0]["style_preset_snapshot"]["id"], style["id"])
            finally:
                manager.executor.shutdown(wait=True)

    def test_invalid_initial_style_is_rejected_before_calling_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(api, "RUNS", root / "runs"), patch.object(api, "get_visual_preset_store", return_value=VisualPresetStore(root / "presets")), patch.object(api, "OpenAICompatibleProvider") as provider, TestClient(api.app) as client:
                response = client.post("/api/pipeline", data={"use_llm": "true", "style_id": "missing-style"},
                    files={"novel": ("novel.md", NOVEL.encode()), "characters": ("characters.md", CHARACTERS.encode())})
                self.assertEqual(response.status_code, 400, response.text)
                provider.assert_not_called()

    def test_cli_and_web_share_the_same_local_story_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            novel, characters = root / "novel.md", root / "characters.md"
            novel.write_text(NOVEL, encoding="utf-8")
            characters.write_text(CHARACTERS, encoding="utf-8")
            cli = run_pipeline(novel, characters, root / "cli")
            with patch.object(api, "RUNS", root / "runs"), TestClient(api.app) as client:
                response = client.post("/api/pipeline", data={"use_llm": "false", "run_id": "test"},
                                       files={"novel": ("novel.md", NOVEL.encode()),
                                              "characters": ("characters.md", CHARACTERS.encode())})
            self.assertEqual(response.status_code, 200, response.text)
            for key in cli:
                self.assertEqual(cli[key], response.json()[key], key)

    def test_serial_and_parallel_polishing_keep_order_and_isolate_failure(self):
        base = build_story_payload(NOVEL, build_character_cards(CHARACTERS))["shots"][0]
        for concurrency in (1, 3):
            with self.subTest(concurrency=concurrency):
                shots = [Shot(**{**deepcopy(base), "id": f"shot_{index}"}) for index in range(3)]

                def polish(shot, *_args, **_kwargs):
                    if shot.id == "shot_1":
                        raise RuntimeError("bad response")
                    shot.positive_prompt = "polished " + shot.id
                    return shot

                with patch("ficframe.pipeline.polish_shot_prompt", side_effect=polish):
                    result = polish_shots_with_llm(shots, [], object(), concurrency, "test")
                self.assertEqual([item.id for item in result], ["shot_0", "shot_1", "shot_2"])
                self.assertEqual(result[1].positive_prompt, base["positive_prompt"])
                self.assertTrue(any("bad response" in note for note in result[1].qa_notes))
                self.assertEqual(result[2].positive_prompt, "polished shot_2")
