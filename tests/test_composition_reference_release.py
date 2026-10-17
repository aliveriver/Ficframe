from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from ficframe import api, features
from ficframe.image_reference_workflow import probe_references, visual_paths
from ficframe.models import Shot, to_dict
from ficframe.providers import EndpointConfig
from ficframe.run_repository import RunRepository
from ficframe.visual_presets import VisualPresetStore
from ficframe.visual_preset_workflow import bind_defaults, bind_shot


PNG = b"\x89PNG\r\n\x1a\nreference"


class CompositionReferenceReleaseTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.store = VisualPresetStore(root / "presets")
        self.repository = RunRepository(root / "runs")
        def generate(prompt, target, **kwargs):
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            Path(target).write_bytes(PNG)

        self.provider = SimpleNamespace(
            config=SimpleNamespace(image=EndpointConfig(api_key="configured", base_url="https://fake.invalid/v1", model="image-test")),
            image=Mock(side_effect=generate), vision=Mock(),
        )
        for name, value in (("get_visual_preset_store", self.store), ("get_run_repository", self.repository),
                            ("OpenAICompatibleProvider", self.provider)):
            self.stack.enter_context(patch.object(api, name, return_value=value))
        self.task_manager = self.stack.enter_context(patch.object(api, "get_visual_task_manager"))
        self.stack.enter_context(patch.object(api, "run_directory", side_effect=self.repository.run_dir))
        self.stack.enter_context(patch.object(api, "RUNS", self.repository.root))
        self.client = self.stack.enter_context(TestClient(api.app))
        self.shot = Shot(id="shot_1", scene_id="scene", title="test", source_excerpt="", characters=[],
                         location="", time="", mood=[], camera="", composition="normal scene composition", visual_goal="",
                         continuity_notes=[], positive_prompt="BASE", negative_prompt="NEG")

    def test_catalog_and_mutation_endpoints_do_not_publish_composition(self):
        self.assertFalse(features.COMPOSITION_REFERENCES_ENABLED)
        style = self.store.create(name="Ink", preset_type="style", positive="ink lines")
        composition = self.store.create(name="Left", preset_type="composition", positive="left")
        catalog = self.client.get("/api/visual-presets").json()
        self.assertEqual(catalog["enabled_types"], ["style"])
        self.assertEqual([item["id"] for item in catalog["presets"]], [style["id"]])
        self.assertEqual(self.client.get("/api/visual-presets", params={"preset_type": "composition"}).status_code, 404)
        path = f"/api/visual-presets/{composition['id']}"
        for response in (self.client.get(path), self.client.patch(path, json={"positive": "changed"}),
                         self.client.delete(path), self.client.post("/api/visual-presets", json={"name": "hidden", "type": "composition"})):
            self.assertEqual(response.status_code, 404)
        for action in ("analyze", "analyze-task", "upload"):
            response = self.client.post(f"/api/visual-presets/{action}", data={"preset_type": "COMPOSITION"},
                                        files=[("reference_images", ("ref.png", PNG, "image/png"))])
            self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.store.get(composition["id"])["positive"], "left")
        self.provider.vision.assert_not_called()
        self.task_manager.assert_not_called()

    def test_old_bindings_are_preserved_but_ignored_by_preview_single_and_batch(self):
        style = self.store.create(name="Ink", preset_type="style", positive="ink lines")
        composition = self.store.create(name="Old layout", preset_type="composition", positive="LAYOUT ONLY", negative="LAYOUT AVOID")
        # Bind while enabled to model an existing workspace; then remove its source preset.
        with patch.object(features, "COMPOSITION_REFERENCES_ENABLED", True):
            defaults = bind_defaults(self.store, {"style_id": style["id"], "composition_id": composition["id"]})
            bind_shot(self.store, self.shot, defaults)
        defaults["composition_snapshot"].update(reference_mode="image", reference_images=["references/missing/layout.png"])
        defaults["composition_reference_mode"] = "image"
        self.store.delete(composition["id"])
        self.shot.composition_preset_snapshot = deepcopy(defaults["composition_snapshot"])
        self.shot.composition_reference_mode = "image"
        original = deepcopy(self.shot.composition_preset_snapshot)
        self.repository.save("run", {"shots": [to_dict(self.shot)], "visual_presets": defaults})
        updated = self.client.post("/api/runs/run/visual-presets", json={"run_id": "run", "style_id": style["id"], "refresh": True})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["visual_presets"]["composition_snapshot"], defaults["composition_snapshot"])
        minimal = {key: value for key, value in to_dict(self.shot).items() if not key.startswith("composition_")}
        saved_edit = self.client.post("/api/storyboard/save", json={"run_id": "run", "shots": [minimal]})
        self.assertEqual(saved_edit.status_code, 200, saved_edit.text)
        self.assertEqual(saved_edit.json()["shots"][0]["composition_preset_snapshot"], original)
        preview = self.client.post("/api/runs/run/visual-preview", json={"shot": to_dict(self.shot)}).json()
        self.assertTrue(preview["reference_preflight"]["ok"])
        self.assertEqual(preview["visual_preset_snapshot"]["composition"], {})
        # Identity references continue to reach both generation paths.
        identity = self.store.root / "identity.png"
        identity.write_bytes(PNG)
        with patch.object(api, "reference_image_entries_for_shot", return_value=[("actor", [identity])]):
            single = self.client.post("/api/images", json={"run_id": "run", "shot": to_dict(self.shot)})
            self.assertEqual(single.status_code, 200, single.text)
            batch = self.client.post("/api/images/batch", json={"run_id": "run", "shots": [to_dict(self.shot)], "skip_existing": False})
            self.assertEqual(batch.status_code, 200, batch.text)
            self.assertTrue(batch.json()["results"][0]["ok"], batch.text)
        self.assertEqual(self.provider.image.call_count, 2)
        for call in self.provider.image.call_args_list:
            self.assertIn("Style guide: ink lines", call.args[0])
            self.assertNotIn("LAYOUT", call.args[0])
            self.assertNotIn("LAYOUT", call.kwargs["negative_prompt"])
            self.assertNotIn("composition_reference_images", call.kwargs)
            self.assertEqual(call.kwargs["reference_images"], [identity])
        saved = self.repository.load("run")
        self.assertEqual(saved["shots"][0]["composition_preset_snapshot"], original)
        self.assertEqual(saved["shots"][0]["composition"], "normal scene composition")
        self.assertEqual(saved["shots"][0]["positive_prompt"], "BASE")
        self.assertEqual(visual_paths(self.store, {"composition": original})["composition"], [])

    def test_multireference_probe_uses_only_active_style_channel(self):
        probe_references(self.store, self.provider, 3, "1024x1024")
        kwargs = self.provider.image.call_args.kwargs
        self.assertEqual(len(kwargs["style_reference_images"]), 3)
        self.assertNotIn("composition_reference_images", kwargs)


if __name__ == "__main__":
    unittest.main()
