from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ficframe.image_workflow import ImageWorkflow, image_target_for_generation
from ficframe.models import Shot, to_dict
from ficframe.providers import ProviderError
from ficframe.run_repository import RunRepository
from ficframe.visual_presets import VisualPresetStore


def shot() -> Shot:
    return Shot(id="shot_1", scene_id="scene_1", title="test", source_excerpt="", characters=[],
                location="", time="", mood=[], camera="", composition="", visual_goal="",
                continuity_notes=[], positive_prompt="BASE", negative_prompt="NEG")


class ImageWorkflowTests(unittest.TestCase):
    def test_candidate_names_cannot_collide_in_the_same_millisecond(self):
        with patch("ficframe.image_workflow.time.time", return_value=123):
            first = image_target_for_generation(Path("run"), "shot_1", True)
            second = image_target_for_generation(Path("run"), "shot_1", True)
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, Path("run/images"))
        for invalid in ("../escape", "..\\escape", "F:\\escape", ""):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                image_target_for_generation(Path("run"), invalid, False)

    def test_retry_keeps_pinned_style_and_commits_only_the_successful_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, store = RunRepository(root / "runs"), VisualPresetStore(root / "presets")
            style = store.create(name="Ink", preset_type="style", positive="original ink")
            current = shot()
            repository.save("run", {"shots": [to_dict(current)], "visual_presets": {"style_id": style["id"]}})
            workflow = ImageWorkflow(repository, store, lambda *_: [])
            prompts = []

            def image(prompt, target, **kwargs):
                prompts.append(prompt)
                if len(prompts) == 1:
                    store.update(style["id"], {"positive": "changed while retrying"})
                    raise ProviderError("temporary failure")
                Path(target).parent.mkdir(parents=True, exist_ok=True)
                Path(target).write_bytes(b"image")

            provider = Mock(image=Mock(side_effect=image))
            target = image_target_for_generation(repository.run_dir("run"), current.id, False)
            with patch("ficframe.image_workflow.time.sleep"):
                result = workflow.generate_item(provider, "run", current, target, "1024x1024", retry_count=1)
            saved = repository.load("run")["shots"][0]
            self.assertTrue(result["ok"])
            self.assertEqual(result["attempts"], 2)
            self.assertEqual(prompts[0], prompts[1])
            self.assertIn("original ink", prompts[1])
            self.assertEqual(len(saved["image_versions"]), 1)
            self.assertEqual(saved["image_versions"][0]["visual_preset_snapshot"]["style"]["version"], 1)
            self.assertEqual(saved["positive_prompt"], "BASE")

