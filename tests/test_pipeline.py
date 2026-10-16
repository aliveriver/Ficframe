from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from ficframe import api
from ficframe.characters import build_character_cards
from ficframe.models import Shot
from ficframe.pipeline import build_story_payload, polish_shots_with_llm, run_pipeline


NOVEL = "# Chapter 1\n\nAlice waits at the station."
CHARACTERS = "## Alice\n- 身份：主角\n- 外貌：黑色短发"


class PipelineTests(unittest.TestCase):
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
