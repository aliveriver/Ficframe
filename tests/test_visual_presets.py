from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ficframe import api, features
from ficframe.models import Shot, to_dict
from ficframe.run_repository import RunRepository
from ficframe.visual_presets import (
    VisualPresetStore,
    build_visual_prompt,
    normalize_vlm_draft,
    validate_reference_bytes,
)


class VisualPresetTests(unittest.TestCase):
    def setUp(self) -> None:
        switch = patch.object(features, "COMPOSITION_REFERENCES_ENABLED", True)
        switch.start()
        self.addCleanup(switch.stop)

    def test_style_and_composition_drafts_keep_separate_fields(self) -> None:
        style = normalize_vlm_draft("style", {"linework": "ink", "shot": "wide", "person_name": "private identity", "positive": "clean lines"})
        composition = normalize_vlm_draft("composition", {"linework": "ignored", "shot": "wide", "positive": "subject left"})
        self.assertEqual(style["positive"], "clean lines")
        self.assertEqual(composition["positive"], "subject left")
        self.assertNotIn("shot", style["structured"])
        self.assertNotIn("person_name", style["raw"])
        self.assertEqual(composition["structured"]["shot"], "wide")

    def test_prompt_assembly_does_not_replace_original_prompt(self) -> None:
        positive, negative = build_visual_prompt(
            "original scene", "existing negative",
            {"id": "style_1", "positive": "dry brush", "negative": "glossy"},
            {"id": "composition_1", "positive": "subject on the left", "negative": "centered"},
        )
        self.assertIn("original scene", positive)
        self.assertIn("Style guide: dry brush", positive)
        self.assertIn("Composition guide: subject on the left", positive)
        self.assertIn("existing negative", negative)
        self.assertIn("Composition guide avoid: centered", negative)

    def test_store_versions_and_reference_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VisualPresetStore(directory)
            item = store.create(name="Ink", preset_type="style", positive="linework", reference_files=[("ref.png", b"\x89PNG\r\n\x1a\ncontent")])
            updated = store.update(item["id"], {"positive": "linework, hatching"})
            self.assertEqual(updated["version"], 2)
            reference = Path(directory) / item["reference_images"][0]
            store.delete(item["id"])
            self.assertTrue(reference.exists())

    def test_upload_validation_rejects_path_traversal_and_oversize(self) -> None:
        with self.assertRaises(ValueError):
            validate_reference_bytes("../ref.txt", b"x")
        with self.assertRaises(ValueError):
            validate_reference_bytes("ref.png", b"\x89PNG\r\n\x1a\n" + b"x" * (20 * 1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            validate_reference_bytes("ref.png", b"not a png")

    def test_single_and_batch_generation_use_same_prompt_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = RunRepository(root / "runs")
            store = VisualPresetStore(root / "presets")
            style = store.create(name="Ink", preset_type="style", positive="dry ink", negative="glossy")
            composition = store.create(name="Left", preset_type="composition", positive="subject on left")
            shot = Shot(
                id="shot_1", scene_id="scene_1", title="Shot", source_excerpt="", characters=[],
                location="", time="", mood=[], camera="", composition="", visual_goal="",
                continuity_notes=[], positive_prompt="BASE", negative_prompt="NEG",
            )
            repository.save("run", {"shots": [to_dict(shot)], "visual_presets": {"style_id": style["id"], "composition_id": composition["id"]}}, render=False)
            run_dir = root / "runs" / "run"
            prompts: list[str] = []

            class FakeProvider:
                def image(self, prompt, out_path, **_kwargs):
                    prompts.append(prompt)
                    target = Path(out_path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"image")

            with patch.object(api, "get_run_repository", return_value=repository), \
                 patch.object(api, "get_visual_preset_store", return_value=store), \
                 patch.object(api, "run_directory", return_value=run_dir), \
                 patch.object(api, "current_shot_image", return_value=None), \
                 patch.object(api, "reference_image_entries_for_shot", return_value=[]), \
                 patch.object(api, "OpenAICompatibleProvider", return_value=FakeProvider()):
                single = api.generate_image(api.ImageRequest(run_id="run", shot=to_dict(shot)))
                batch = api.generate_batch_image_item(
                    FakeProvider(), "run", shot, run_dir / "images" / "shot_1_batch.png", "1024x1024", 0, True
                )

            self.assertEqual(prompts[0], prompts[1])
            self.assertIn("Style guide: dry ink", prompts[0])
            self.assertIn("Composition guide: subject on left", prompts[0])
            self.assertEqual(single["visual_preset_snapshot"], batch["visual_preset_snapshot"])
            saved = repository.load("run")
            self.assertEqual(saved["shots"][0]["positive_prompt"], "BASE")
            self.assertEqual(saved["shots"][0]["last_generation_visual_snapshot"]["style"]["version"], 1)
            store.update(style["id"], {"positive": "changed"})
            self.assertEqual(saved["shots"][0]["last_generation_visual_snapshot"]["style"]["positive"], "dry ink")


if __name__ == "__main__":
    unittest.main()
