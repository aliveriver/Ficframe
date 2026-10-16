from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ficframe import api, features
from ficframe.models import Shot, to_dict
from ficframe.prompts import DEFAULT_STYLE_FINISH, REFERENCE_CONTINUITY, SINGLE_FRAME_RULE, build_negative_prompt, single_frame_constraints
from ficframe.run_repository import RunRepository
from ficframe.style import DEFAULT_STYLE
from ficframe.storyboard_visual_guidance import style_neutral_errors
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

    def test_one_frame_layout_is_enforced_independently_of_drawing_style(self):
        scene = "Scene: First she smooths the sheet, then they hold hands, later they touch foreheads.\nLighting: Lights out, no lamps."
        for style in (None, {"positive": "ink", "reference_mode": "text"},
                      {"reference_mode": "image", "reference_images": ["style.png"]}):
            with self.subTest(style=style):
                positive, negative = build_visual_prompt(scene, "extra fingers", style)
                self.assertTrue(positive.startswith(SINGLE_FRAME_RULE))
                self.assertIn(scene, positive)
                self.assertIn("one frozen moment", positive)
                for exclusion in ("panel grid", "nine-panel grid", "split screen", "collage", "storyboard sheet", "speech bubbles"):
                    self.assertIn(exclusion, negative)
                self.assertIn("extra fingers", negative)
                self.assertEqual(single_frame_constraints(positive, negative), (positive, negative))
                self.assertNotIn("manga", negative)

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

    def test_image_only_style_replaces_conflicting_generated_style_and_proportions(self) -> None:
        rendering = f"{DEFAULT_STYLE['lighting']}, {DEFAULT_STYLE['palette']}, {DEFAULT_STYLE['line']}."
        original = (f"{DEFAULT_STYLE['medium']}\n\nScene:\nBedroom, morning. Exactly two adults hold hands.\n\n"
                    f"Continuity:\n{REFERENCE_CONTINUITY}\n\nLighting and style:\n{rendering}\n{DEFAULT_STYLE_FINISH}")
        original_negative = build_negative_prompt() + ", wrong hair color"
        style = {"id": "style_1", "reference_mode": "image", "reference_images": ["references/style/ref.png"],
                 "positive": "", "negative": ""}
        positive, negative = build_visual_prompt(original, original_negative, style)
        self.assertTrue(positive.startswith(SINGLE_FRAME_RULE))
        self.assertIn("Style priority:", positive)
        self.assertIn("head-to-body and facial proportions", positive)
        self.assertIn("Bedroom, morning. Exactly two adults hold hands.", positive)
        self.assertIn("identity and age", positive)
        for conflicting in (DEFAULT_STYLE["medium"], rendering, "Lighting and style:", REFERENCE_CONTINUITY):
            self.assertNotIn(conflicting, positive)
        self.assertNotIn("chibi", negative)
        self.assertNotIn("childlike appearance", negative)
        self.assertIn("bad anatomy", negative)
        self.assertIn("wrong hair color", negative)
        # Without an active style, even the generated defaults remain intact.
        self.assertEqual(build_visual_prompt(original, original_negative), single_frame_constraints(original, original_negative))
        self.assertEqual(build_visual_prompt(original, original_negative, {"id": "empty", "positive": ""}),
                         single_frame_constraints(original, original_negative))

    def test_structured_style_is_used_and_custom_scene_lighting_is_preserved(self) -> None:
        original = "Scene: bedroom\n\nLighting and style:\nMorning sunlight through the window."
        positive, negative = build_visual_prompt(original, "hand errors", {
            "positive": "simple manga", "negative": "photorealism",
            "structured": {"stylization": "chibi", "proportions": "two heads tall", "linework": "bold flat lines",
                           "shot": "ignored composition"},
        })
        self.assertIn("Style guide: simple manga", positive)
        self.assertIn("stylization: chibi", positive)
        self.assertIn("proportions: two heads tall", positive)
        self.assertIn("linework: bold flat lines", positive)
        self.assertIn(original, positive)
        self.assertNotIn("ignored composition", positive)
        self.assertIn("Style guide avoid: photorealism", negative)
        # A deliberate standalone exclusion is separate from our default scaffold.
        self.assertIn("chibi", build_visual_prompt(original, "chibi", {"positive": "watercolor"})[1])
        custom_global_style = {**DEFAULT_STYLE, "negative_prompt": "blur, wrong identity"}
        _, negative = build_visual_prompt(original, build_negative_prompt(custom_global_style), {"positive": "chibi"})
        self.assertNotIn("chibi", negative)
        self.assertIn("wrong identity", negative)

    def test_style_validation_never_deletes_mixed_lighting_or_unknown_sections(self):
        original = {"positive_prompt": "Scene: bedroom.\nLighting and style: Morning sunlight enters the east window.\nStyle: watercolor.\nAction: She offers a glass of water.",
                    "negative_prompt": "chibi, flat colors, cel shading, extra fingers"}
        before = dict(original)
        self.assertEqual(len(style_neutral_errors(original)), 2)
        self.assertEqual(original, before)
        self.assertFalse(style_neutral_errors({"positive_prompt": "Lighting: Morning sunlight enters the east window.\nAction: She offers a glass of water.", "negative_prompt": "extra fingers"}))

    def test_store_versions_and_reference_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VisualPresetStore(directory)
            item = store.create(name="Ink", preset_type="style", positive="linework", reference_files=[("ref.png", b"\x89PNG\r\n\x1a\ncontent")])
            updated = store.update(item["id"], {"positive": "linework, hatching"})
            self.assertEqual(updated["version"], 2)
            reference = Path(directory) / item["reference_images"][0]
            store.delete(item["id"])
            self.assertTrue(reference.exists())

    def test_unchanged_save_preserves_version_timestamp_storage_and_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VisualPresetStore(directory)
            for content in ("", "ink lines"):
                with self.subTest(content=content):
                    item = store.create(name="Ink", preset_type="style", positive=content, reference_mode="image",
                                        reference_files=[("ref.png", b"\x89PNG\r\n\x1a\ncontent")])
                    saved_json = store.path.read_bytes()
                    saved_files = sorted(store.root.rglob("*"))
                    values = {"name": " Ink ", "positive": f" {content} ", "negative": " ",
                              "reference_mode": "image", "reference_paths": item["reference_images"],
                              "vlm_analysis": {"positive": content, "negative": "", "structured": {}}}
                    with patch("ficframe.visual_presets._now", return_value=item["updated_at"] + 100):
                        for update in ({}, values, values):
                            self.assertEqual(store.update(item["id"], update), item)
                    self.assertEqual(store.path.read_bytes(), saved_json)
                    self.assertEqual(sorted(store.root.rglob("*")), saved_files)

    def test_reuploaded_identical_images_do_not_create_a_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VisualPresetStore(directory)
            first = b"\x89PNG\r\n\x1a\nfirst"
            second = b"\x89PNG\r\n\x1a\nsecond"
            item = store.create(name="Ink", preset_type="style", reference_mode="image",
                                reference_files=[("first.png", first), ("second.png", second)])
            reuploaded = store.save_draft_references([("renamed.png", first), ("renamed-again.png", second)])
            with patch.object(store, "_copy_references", wraps=store._copy_references) as copy:
                self.assertEqual(store.update(item["id"], {"reference_paths": reuploaded}), item)
                changed_text = store.update(item["id"], {"positive": "new ink", "reference_paths": reuploaded})
                self.assertEqual(changed_text["version"], 2)
                self.assertEqual(changed_text["reference_images"], item["reference_images"])
                copy.assert_not_called()
            reordered = store.update(item["id"], {"reference_paths": list(reversed(reuploaded))})
            self.assertEqual(reordered["version"], 3)
            self.assertEqual([store.reference_path(path).read_bytes() for path in reordered["reference_images"]], [second, first])
            for path in item["reference_images"]:
                self.assertTrue(store.reference_path(path).exists())

    def test_each_editable_field_creates_one_revision_only_when_changed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VisualPresetStore(directory)
            item = store.create(name="Ink", preset_type="style", reference_files=[("ref.png", b"\x89PNG\r\n\x1a\nfirst")])
            different = store.save_draft_references([("ref.png", b"\x89PNG\r\n\x1a\nsecond")])
            changes = ({"name": "Manga"}, {"positive": "flat colors"}, {"negative": "glossy"},
                       {"reference_mode": "image"}, {"vlm_analysis": {"structured": {"proportions": "two heads tall"}}},
                       {"reference_paths": different})
            for version, values in enumerate(changes, start=2):
                with self.subTest(values=values):
                    updated = store.update(item["id"], values)
                    self.assertEqual(updated["version"], version)
                    self.assertEqual(store.update(item["id"], values), updated)

    def test_unchanged_reference_save_still_validates_paths_and_image_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = VisualPresetStore(directory)
            item = store.create(name="Ink", preset_type="style")
            for values in ({"reference_paths": ["../private.png"]}, {"reference_paths": ["drafts/missing/ref.png"]},
                           {"reference_paths": ["drafts/missing/ref.png"] * 9}, {"reference_mode": "image"}):
                with self.subTest(values=values), self.assertRaises(ValueError):
                    store.update(item["id"], values)
            self.assertEqual(store.get(item["id"]), item)

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
