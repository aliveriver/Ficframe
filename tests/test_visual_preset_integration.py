from __future__ import annotations

import json
import tempfile
import time
import unittest
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from ficframe import api
from ficframe.models import Shot, to_dict
from ficframe.providers import EndpointConfig, ProviderError
from ficframe.run_repository import RunRepository
from ficframe.task_manager import TaskManager
from ficframe.visual_presets import MAX_REFERENCE_BYTES, VisualPresetStore, preset_snapshot
from ficframe.visual_preset_analysis import analyze_references
from ficframe.visual_preset_workflow import resolve_generation


PNG = b"\x89PNG\r\n\x1a\nreference"


def shot_data(shot_id="shot_1"):
    return to_dict(Shot(id=shot_id, scene_id="scene", title="test", source_excerpt="", characters=[],
                        location="", time="", mood=[], camera="", composition="", visual_goal="",
                        continuity_notes=[], positive_prompt="USER BASE", negative_prompt="USER NEG"))


class FakeProvider:
    def __init__(self, key="configured", response=None):
        self.config = SimpleNamespace(vlm=SimpleNamespace(api_key=key), llm=SimpleNamespace(api_key=key),
                                      image=EndpointConfig(api_key=key, base_url="https://fake.invalid/v1", model="image-test"))
        self.response = response or json.dumps({"positive": "ink lines", "negative": "glossy",
                                               "structured": {"linework": "ink", "shot": "ignored", "person_name": "ignored"}})
        self.calls = []
        self.fail_once = False

    def vision(self, system, prompt, paths, **kwargs):
        self.calls.append((system, prompt, paths))
        return self.response

    def image(self, prompt, out_path, **kwargs):
        self.calls.append((prompt, deepcopy(kwargs)))
        if self.fail_once:
            self.fail_once = False
            raise ProviderError("temporary failure")
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(PNG)


class VisualPresetIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.store = VisualPresetStore(root / "presets")
        self.repository = RunRepository(root / "runs")
        self.manager = TaskManager(RunRepository(self.store.root / "analysis-tasks"))
        self.provider = FakeProvider()
        for name, value in (("get_visual_preset_store", self.store), ("get_run_repository", self.repository),
                            ("get_visual_task_manager", self.manager), ("OpenAICompatibleProvider", self.provider)):
            self.stack.enter_context(patch.object(api, name, return_value=value))
        self.stack.enter_context(patch.object(api, "run_directory", side_effect=self.repository.run_dir))
        # The mounted storyboard router retains the original repository callback.
        self.stack.enter_context(patch.object(api, "RUNS", self.repository.root))
        self.stack.enter_context(patch.object(api.time, "sleep", return_value=None))
        self.client = self.stack.enter_context(TestClient(api.app))
        self.stack.callback(self.manager.executor.shutdown, wait=True)
        self.repository.save("run", {"shots": [shot_data(), shot_data("shot_2")]})

    def create(self, kind="style", **values):
        response = self.client.post("/api/visual-presets", json={"name": kind, "type": kind, "positive": "ink" if kind == "style" else "subject left", **values})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def defaults(self, style=None, composition=None, refresh=False):
        response = self.client.post("/api/runs/run/visual-presets", json={"run_id": "run", "style_id": style, "composition_id": composition, "refresh": refresh})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def selection(self, shot_id, **values):
        response = self.client.post(f"/api/runs/run/shots/{shot_id}/visual-presets", json={"shot": values})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["shot"]

    def test_crud_cross_run_versioning_and_reference_lifecycle(self):
        paths = self.store.save_draft_references([("ref.png", PNG)])
        item = self.create(reference_paths=paths)
        composition = self.create("composition")
        self.repository.save("other", {"shots": [shot_data()]})
        response = self.client.post("/api/runs/other/visual-presets", json={"run_id": "other", "style_id": item["id"]})
        self.assertEqual(response.status_code, 200)
        original = self.repository.load("other")["visual_presets"]["style_snapshot"]
        update = self.client.patch(f"/api/visual-presets/{item['id']}", json={"positive": "painted", "reference_paths": paths})
        self.assertEqual(update.json()["version"], 2)
        self.assertNotEqual(update.json()["reference_images"], item["reference_images"])
        self.assertEqual(self.client.get("/api/visual-presets", params={"preset_type": "composition"}).json()["presets"][0]["id"], composition["id"])
        self.assertEqual(self.client.delete(f"/api/visual-presets/{item['id']}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/visual-presets/{item['id']}").status_code, 404)
        self.assertEqual(self.repository.load("other")["visual_presets"]["style_snapshot"], original)
        for path in [*paths, *item["reference_images"], *update.json()["reference_images"]]:
            self.assertEqual(self.client.get("/api/visual-presets/reference/" + path).content, PNG)

    def test_analysis_draft_is_not_saved_and_nested_fields_are_scoped(self):
        result = self.client.post("/api/visual-presets/analyze", data={"preset_type": "STYLE"}, files=[("reference_images", ("../../ref.png", PNG, "image/png"))])
        self.assertEqual(result.status_code, 200, result.text)
        draft = result.json()
        self.assertEqual(draft["status"], "analyzed")
        self.assertEqual(draft["structured"], {"linework": "ink"})
        self.assertEqual(self.store.list(), [])
        self.assertEqual(len(self.provider.calls[0][2]), 1)
        item = self.create(positive=draft["positive"], vlm_analysis=draft, reference_paths=draft["reference_paths"])
        self.assertEqual(item["vlm_analysis"]["structured"], {"linework": "ink"})

    def test_global_background_task_and_no_vlm_manual_confirmation(self):
        self.provider.config.vlm.api_key = None
        response = self.client.post("/api/visual-presets/analyze-task", data={"preset_type": "composition"}, files=[("reference_images", ("ref.png", PNG, "image/png"))])
        self.assertEqual(response.status_code, 202, response.text)
        task_id = response.json()["task_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = self.client.get(f"/api/tasks/{task_id}").json()
            if task["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
        self.assertEqual(task["status"], "succeeded", task)
        self.assertEqual(task["result"]["status"], "vlm_not_configured")
        self.assertEqual(self.store.list(), [])
        self.assertTrue((self.store.root / "analysis-tasks/analysis/tasks.json").exists())
        self.assertFalse((self.repository.root / "analysis").exists())
        restored = TaskManager(self.manager.repository)
        try:
            self.assertEqual(restored.get(task_id)["result"], task["result"])
        finally:
            restored.executor.shutdown(wait=True)
        self.create("composition", positive="manual left", reference_paths=task["result"]["reference_paths"])

    def test_vlm_failure_and_malformed_output_preserve_editable_draft(self):
        for response in ("not JSON", "{}", "[]"):
            self.provider.response = response
            result = analyze_references(self.store, self.provider, "style", [("ref.png", PNG, "image/png")], "test")
            self.assertEqual(result["status"], "vlm_failed")
            self.assertTrue(self.store.reference_path(result["reference_paths"][0]).exists())
        with patch.object(self.provider, "vision", side_effect=ProviderError("api-key-secret request-content")):
            result = analyze_references(self.store, self.provider, "style", [("ref.png", PNG, None)], "test")
        self.assertNotIn("api-key-secret", json.dumps(result))
        self.assertEqual(self.store.list(), [])

    def test_upload_and_reference_path_validation(self):
        for name, content, mime in (("ref.txt", PNG, "image/png"), ("ref.png", b"invalid", "image/png"),
                                    ("ref.png", PNG, "text/plain"), ("ref.png", b"x" * (MAX_REFERENCE_BYTES + 1), "image/png")):
            response = self.client.post("/api/visual-presets/analyze-task", data={"preset_type": "style"}, files=[("reference_images", (name, content, mime))])
            self.assertEqual(response.status_code, 400, response.text)
        response = self.client.post("/api/visual-presets/analyze", data={"preset_type": "style"}, files=[("reference_images", ("ref.png", PNG, "image/png"))] * 9)
        self.assertEqual(response.status_code, 400)
        for relative in ("../secret.png", "C:/secret.png", "references/../presets.json", "drafts/id/../../secret.png", "presets.json"):
            response = self.client.post("/api/visual-presets", json={"name": "invalid", "type": "style", "reference_paths": [relative]})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.client.get("/visual-presets/presets.json").status_code, 404)

    def test_defaults_overrides_disable_and_explicit_refresh(self):
        style = self.create()
        other = self.create(positive="watercolor")
        composition = self.create("composition")
        saved = self.defaults(style["id"], composition["id"])
        self.selection("shot_2", style_preset_mode="preset", style_preset_id=other["id"], composition_preset_mode="none")
        self.store.update(style["id"], {"positive": "latest"})
        self.store.update(other["id"], {"positive": "latest other"})
        payload = self.repository.load("run")
        positive, _, snapshot = resolve_generation(self.store, payload, Shot(**payload["shots"][0]))
        self.assertIn("Style guide: ink", positive)
        self.assertEqual(snapshot["style"]["version"], 1)
        latest = self.defaults(style["id"], composition["id"], True)
        self.assertEqual(latest["shots"][0]["style_preset_snapshot"]["version"], 2)
        self.assertEqual(latest["shots"][1]["style_preset_snapshot"]["version"], 1)
        self.assertEqual(latest["shots"][1]["composition_preset_snapshot"], {})
        self.assertEqual(saved["shots"][0]["positive_prompt"], "USER BASE")
        response = self.client.post("/api/runs/run/shots/shot_2/visual-presets", json={"shot": {}, "refresh": True})
        self.assertEqual(response.json()["shot"]["style_preset_snapshot"]["version"], 2)
        self.selection("shot_1", style_preset_mode="none")
        self.assertEqual(self.repository.load("run")["shots"][0]["style_preset_snapshot"], {})

    def test_single_batch_retry_snapshots_and_identity_references_are_consistent(self):
        style = self.create(reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        composition = self.create("composition")
        self.defaults(style["id"], composition["id"])
        shot = self.repository.load("run")["shots"][0]
        identity = self.repository.run_dir("run") / "identity.png"
        identity.write_bytes(PNG)
        with patch.object(api, "reference_image_entries_for_shot", return_value=[("character", [identity])]):
            single = self.client.post("/api/images", json={"run_id": "run", "shot": shot, "overwrite": True})
            self.assertEqual(single.status_code, 200, single.text)
            self.store.update(style["id"], {"positive": "changed"})
            self.store.delete(composition["id"])
            self.provider.fail_once = True
            batch = self.client.post("/api/images/batch", json={"run_id": "run", "shots": [shot], "skip_existing": False, "retry_count": 1})
            self.assertEqual(batch.status_code, 200, batch.text)
            result = batch.json()["results"][0]
        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(single.json()["visual_preset_snapshot"], result["visual_preset_snapshot"])
        self.assertEqual(len(self.provider.calls), 3)
        for prompt, arguments in self.provider.calls:
            self.assertEqual(prompt, single.json()["visual_prompt"])
            self.assertEqual(arguments["reference_images"], [identity])
            self.assertEqual(arguments["reference_image_groups"], [[identity]])
        saved = self.repository.load("run")["shots"][0]
        self.assertEqual(saved["positive_prompt"], "USER BASE")
        self.assertEqual(len(saved["image_versions"]), 2)
        for version in saved["image_versions"]:
            self.assertEqual(version["visual_preset_snapshot"], result["visual_preset_snapshot"])
        preview = self.client.post("/api/runs/run/visual-preview", json={"shot": saved}).json()
        self.assertEqual(preview["positive_prompt"], result["visual_prompt"])

    def test_failed_batch_selection_does_not_discard_other_results(self):
        shots = self.repository.load("run")["shots"]
        shots[0].update(style_preset_mode="preset", style_preset_id="style_missing")
        response = self.client.post("/api/images/batch", json={"run_id": "run", "shots": shots, "skip_existing": False})
        self.assertEqual(response.status_code, 200, response.text)
        results = response.json()["results"]
        self.assertFalse(results[0]["ok"])
        self.assertTrue(results[1]["ok"])

    def test_save_restore_preserves_pinned_binding_and_server_generation_metadata(self):
        style = self.create()
        self.defaults(style["id"])
        self.selection("shot_1", style_preset_mode="preset", style_preset_id=style["id"])
        old = self.repository.load("run")["shots"]
        generated = self.client.post("/api/images", json={"run_id": "run", "shot": old[0], "overwrite": True}).json()
        old[0]["positive_prompt"] = "EDITED"
        old[0]["style_preset_snapshot"] = {"id": style["id"], "positive": "forged"}
        self.store.update(style["id"], {"positive": "changed"})
        self.store.delete(style["id"])
        response = self.client.post("/api/storyboard/save", json={"run_id": "run", "shots": old})
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertEqual(saved["shots"][0]["style_preset_snapshot"]["positive"], "ink")
        self.assertEqual(saved["shots"][0]["last_generation_visual_snapshot"], generated["visual_preset_snapshot"])
        version = saved["storyboard_versions"]["shot_1"][0]
        restored = self.client.post("/api/storyboard/version", json={"run_id": "run", "shot_id": "shot_1", "version_id": version["version_id"]})
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["shot"]["style_preset_snapshot"]["positive"], "ink")
        self.assertEqual(restored.json()["shot"]["last_generation_visual_snapshot"], generated["visual_preset_snapshot"])

    def test_legacy_run_and_id_only_bindings_remain_readable(self):
        self.repository.save("legacy", {"shots": [shot_data()]})
        payload = self.repository.load("legacy")
        positive, negative, snapshot = resolve_generation(self.store, payload, Shot(**payload["shots"][0]))
        self.assertEqual((positive, negative), ("USER BASE", "USER NEG"))
        self.assertEqual(snapshot["style"], {})
        style = self.create()
        old = shot_data()
        old["style_preset_snapshot"] = preset_snapshot(style)
        self.repository.save("early", {"shots": [old], "visual_presets": {"style_id": style["id"]}})
        self.store.delete(style["id"])
        early = self.repository.load("early")
        self.assertEqual(resolve_generation(self.store, early, Shot(**early["shots"][0]))[2]["style"]["version"], 1)

    def test_corrupt_index_is_not_overwritten(self):
        self.store.path.write_text("broken", encoding="utf-8")
        self.assertEqual(self.client.get("/api/visual-presets").status_code, 400)
        self.assertEqual(self.client.post("/api/visual-presets", json={"name": "new", "type": "style"}).status_code, 400)
        self.assertEqual(self.store.path.read_text(encoding="utf-8"), "broken")

    def test_missing_id_only_defaults_can_be_removed(self):
        self.repository.save("run", {"shots": [shot_data()], "visual_presets": {"style_id": "style_missing"}})
        result = self.defaults()
        self.assertIsNone(result["visual_presets"]["style_id"])
        self.assertEqual(result["shots"][0]["style_preset_snapshot"], {})

    def test_failed_single_generation_pins_binding_before_retry(self):
        style = self.create()
        self.defaults(style["id"])
        shot = self.selection("shot_1", style_preset_mode="preset", style_preset_id=style["id"])
        self.provider.fail_once = True
        response = self.client.post("/api/images", json={"run_id": "run", "shot": shot, "overwrite": True})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.repository.load("run")["shots"][0]["style_preset_snapshot"]["version"], 1)
        self.store.update(style["id"], {"positive": "new version"})
        response = self.client.post("/api/images", json={"run_id": "run", "shot": shot, "overwrite": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["visual_preset_snapshot"]["style"]["version"], 1)
        self.assertEqual(self.provider.calls[0][0], self.provider.calls[1][0])

    def test_new_llm_shot_binds_existing_run_defaults(self):
        style = self.create()
        self.defaults(style["id"])
        self.store.update(style["id"], {"positive": "latest"})
        self.repository.novel_path("run").write_text("fixture novel", encoding="utf-8")
        with patch.object(api, "generate_or_revise_shot_with_llm", side_effect=lambda shot, *args, **kwargs: shot):
            response = self.client.post("/api/storyboard/generate", json={"run_id": "run", "description": "test standalone illustration"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["shot"]["style_preset_snapshot"]["version"], 1)

    def test_composition_analysis_excludes_style_and_identity_fields(self):
        self.provider.response = json.dumps({"structured": {"subject_placement": "left", "linework": "ignored", "identity": "ignored"}})
        response = self.client.post("/api/visual-presets/analyze", data={"preset_type": "composition"}, files=[("reference_images", ("ref.png", PNG, "image/png"))])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["structured"], {"subject_placement": "left"})
        self.assertEqual(response.json()["positive"], "left")
        self.assertIn("Do not include drawing style", self.provider.calls[0][0])

    def wait_task(self, task_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = self.manager.get(task_id)
            if task["status"] in {"succeeded", "failed"}:
                self.assertEqual(task["status"], "succeeded", task)
                return task["result"]
            time.sleep(0.01)
        self.fail("task did not complete")

    def test_upload_without_vlm_and_two_modes_are_independent(self):
        self.provider.config.vlm.api_key = None
        uploaded = self.client.post("/api/visual-presets/upload", data={"preset_type": "style"}, files=[("reference_images", ("style.png", PNG, "image/png"))])
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.store.list(), [])
        style = self.create(reference_mode="image", reference_paths=uploaded.json()["reference_paths"])
        composition = self.create("composition", reference_mode="text")
        saved = self.defaults(style["id"], composition["id"])
        self.assertEqual(saved["visual_presets"]["style_reference_mode"], "image")
        self.assertEqual(saved["visual_presets"]["composition_reference_mode"], "text")
        shot = self.selection("shot_1", style_reference_mode="text", composition_reference_mode="image")
        preview = self.client.post("/api/runs/run/visual-preview", json={"shot": shot}).json()
        self.assertFalse(preview["reference_preflight"]["ok"])
        self.assertIn("没有参考图", preview["reference_preflight"]["message"])
        self.selection("shot_1", composition_reference_mode="text")
        payload = self.repository.load("run")
        self.assertEqual(payload["shots"][0]["style_reference_mode"], "text")
        self.assertEqual(payload["shots"][1]["style_preset_snapshot"]["reference_mode"], "image")

    def test_image_mode_requires_images_and_legacy_is_text(self):
        response = self.client.post("/api/visual-presets", json={"name": "empty", "type": "style", "reference_mode": "image"})
        self.assertEqual(response.status_code, 400)
        item = self.create()
        self.assertEqual(item["reference_mode"], "text")
        self.assertEqual(self.client.patch(f"/api/visual-presets/{item['id']}", json={"reference_mode": "invalid"}).status_code, 400)
        self.assertEqual(self.store.get(item["id"])["version"], 1)

    def test_live_probe_requires_confirmation_and_blocks_unverified_generation(self):
        style = self.create(reference_mode="image", reference_paths=self.store.save_draft_references([("ref.png", PNG)]))
        self.defaults(style["id"])
        shot = self.repository.load("run")["shots"][0]
        response = self.client.post("/api/image-reference-test-task", json={"confirmed": False})
        self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/images", json={"run_id": "run", "shot": shot, "overwrite": True})
        self.assertEqual(response.status_code, 400)
        self.assertIn("尚未验证", response.json()["detail"])
        self.assertEqual(self.provider.calls, [])
        response = self.client.post("/api/image-reference-test-task", json={"confirmed": True, "reference_count": 2})
        self.assertEqual(response.status_code, 202)
        result = self.wait_task(response.json()["task_id"])
        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["tested_count"], 2)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.client.get("/api/image-reference-capability").json()["status"], "supported")
        self.provider.config.image.model = "changed-model"
        self.assertEqual(self.client.get("/api/image-reference-capability").json()["status"], "unknown")

    def test_verified_visual_channels_single_batch_and_retry_do_not_mix_identity_groups(self):
        from ficframe.image_reference_workflow import probe_references
        style = self.create(reference_mode="image", reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        composition = self.create("composition", reference_mode="image", reference_paths=self.store.save_draft_references([("layout.png", PNG)]))
        self.defaults(style["id"], composition["id"])
        self.assertEqual(probe_references(self.store, self.provider, 3, "1024x1024")["status"], "supported")
        self.provider.calls.clear()
        shot = self.repository.load("run")["shots"][0]
        identity = self.repository.run_dir("run") / "identity.png"
        identity.write_bytes(PNG)
        with patch.object(api, "reference_image_entries_for_shot", return_value=[("actor", [identity])]):
            single = self.client.post("/api/images", json={"run_id": "run", "shot": shot, "overwrite": True})
            self.assertEqual(single.status_code, 200, single.text)
            self.store.update(style["id"], {"reference_mode": "text"})
            self.provider.fail_once = True
            batch = self.client.post("/api/images/batch", json={"run_id": "run", "shots": [shot], "skip_existing": False, "retry_count": 1})
            self.assertEqual(batch.status_code, 200, batch.text)
        result = batch.json()["results"][0]
        self.assertTrue(result["ok"], result)
        self.assertEqual(single.json()["visual_preset_snapshot"], result["visual_preset_snapshot"])
        for prompt, kwargs in self.provider.calls:
            self.assertEqual(kwargs["reference_images"], [identity])
            self.assertEqual(kwargs["reference_image_groups"], [[identity]])
            self.assertEqual(len(kwargs["style_reference_images"]), 1)
            self.assertEqual(len(kwargs["composition_reference_images"]), 1)
            self.assertIn("Images 1-1: character identity", prompt)
            self.assertIn("Images 2-2: drawing style only", prompt)
            self.assertIn("Images 3-3: composition only", prompt)
        snapshot = result["visual_preset_snapshot"]
        self.assertEqual(snapshot["reference_delivery"]["order"], ["identity", "style", "composition"])
        self.assertEqual(snapshot["style"]["reference_mode"], "image")
        self.assertEqual(self.repository.load("run")["shots"][0]["positive_prompt"], "USER BASE")

    def test_known_unsupported_adapter_does_not_call_provider(self):
        self.provider.config.image.provider = "siliconflow"
        response = self.client.get("/api/image-reference-capability")
        self.assertEqual(response.json()["status"], "unsupported")
        response = self.client.post("/api/image-reference-test-task", json={"confirmed": True})
        result = self.wait_task(response.json()["task_id"])
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(self.provider.calls, [])

    def test_probe_failure_distinguishes_rejection_from_temporary_errors(self):
        from ficframe.image_reference_workflow import capability, probe_references
        with patch.object(self.provider, "image", side_effect=ProviderError("400 reference images not supported private-secret")):
            result = probe_references(self.store, self.provider, 2, "1024x1024")
        self.assertEqual(result["status"], "unsupported")
        self.assertNotIn("private-secret", json.dumps(result))
        self.assertEqual(probe_references(self.store, self.provider, 2, "1024x1024")["status"], "supported")
        with patch.object(self.provider, "image", side_effect=ProviderError("429 quota exceeded")):
            result = probe_references(self.store, self.provider, 2, "2K")
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(capability(self.store, self.provider, "1024x1024")["status"], "supported")

    def test_total_reference_count_and_size_need_matching_probe(self):
        from ficframe.image_reference_workflow import probe_references, reference_preflight
        style = self.create(reference_mode="image", reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        payload = self.repository.load("run")
        snapshot = resolve_generation(self.store, payload, Shot(**payload["shots"][0]))[2]
        probe_references(self.store, self.provider, 2, "1024x1024")
        check = reference_preflight(self.store, self.provider, snapshot, 2, "1024x1024")
        self.assertFalse(check["ok"])
        self.assertEqual(check["total_count"], 3)
        self.assertFalse(reference_preflight(self.store, self.provider, snapshot, 0, "2K")["ok"])
        self.provider.config.image.api_key = "changed-key"
        self.assertFalse(reference_preflight(self.store, self.provider, snapshot, 0, "1024x1024")["ok"])

    def test_text_mode_with_images_never_sends_visual_images(self):
        item = self.create(reference_mode="text", reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(item["id"])
        shot = self.repository.load("run")["shots"][0]
        response = self.client.post("/api/images", json={"run_id": "run", "shot": shot, "overwrite": True})
        self.assertEqual(response.status_code, 200, response.text)
        kwargs = self.provider.calls[0][1]
        self.assertNotIn("style_reference_images", kwargs)
        self.assertNotIn("composition_reference_images", kwargs)

    def test_generation_rejection_updates_capability_and_blocks_remaining_batch_calls(self):
        from ficframe.image_reference_workflow import probe_references
        style = self.create(reference_mode="image", reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        probe_references(self.store, self.provider, 2, "1024x1024")
        shots = self.repository.load("run")["shots"]
        with patch.object(self.provider, "image", side_effect=ProviderError("400 too many reference images private-novel private-key")) as image:
            result = self.client.post("/api/images/batch", json={"run_id": "run", "shots": shots, "skip_existing": False, "retry_count": 2})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(image.call_count, 1)
        self.assertEqual([item["attempts"] for item in result.json()["results"]], [1, 0])
        self.assertTrue(all(not item["ok"] for item in result.json()["results"]))
        self.assertNotIn("private-novel", result.text)
        self.assertNotIn("private-key", result.text)
        self.assertEqual(self.client.get("/api/image-reference-capability").json()["status"], "unsupported")
        self.assertEqual(self.repository.load("run")["shots"][0]["positive_prompt"], "USER BASE")
