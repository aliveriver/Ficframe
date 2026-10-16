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

from ficframe import api, features
from ficframe.models import Scene, Shot, to_dict
from ficframe.llm_pipeline import polish_shot_prompt
from ficframe.pipeline import polish_shots_with_llm
from ficframe.storyboard_visual_guidance import style_neutral_errors
from ficframe.providers import EndpointConfig, ProviderError
from ficframe.prompts import SINGLE_FRAME_RULE, build_negative_prompt, build_positive_prompt, single_frame_constraints
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
        self.text_calls = []
        self.text_responses = []
        self.reject_images = False
        self.fail_once = False

    def vision(self, system, prompt, paths, **kwargs):
        self.calls.append((system, prompt, paths))
        return self.response

    def text(self, system, user, **kwargs):
        self.text_calls.append((system, json.loads(user), deepcopy(kwargs)))
        if self.reject_images and kwargs.get("image_paths"):
            raise ProviderError("400 This model does not support image inputs")
        if self.text_responses:
            return self.text_responses.pop(0)
        return json.dumps({"positive_prompt": "Scene: quiet bedroom, early morning. Composition: two adults hold hands. "
                          "Characters: two distinct adult identities. Relationships: tender companionship." +
                          ("" if json.loads(user).get("visual_guides", {}).get("style", {}).get("reference_mode") == "image" else " Style: simple flat manga lines."),
                           "negative_prompt": "extra people, duplicate character, wrong character identity"})

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
        # Retained implementation remains covered independently of release defaults.
        self.stack.enter_context(patch.object(features, "COMPOSITION_REFERENCES_ENABLED", True))
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
        self.assertEqual(update.json()["reference_images"], item["reference_images"])
        self.assertEqual(self.client.get("/api/visual-presets", params={"preset_type": "composition"}).json()["presets"][0]["id"], composition["id"])
        self.assertEqual(self.client.delete(f"/api/visual-presets/{item['id']}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/visual-presets/{item['id']}").status_code, 404)
        self.assertEqual(self.repository.load("other")["visual_presets"]["style_snapshot"], original)
        for path in [*paths, *item["reference_images"], *update.json()["reference_images"]]:
            self.assertEqual(self.client.get("/api/visual-presets/reference/" + path).content, PNG)

    def test_editor_round_trip_does_not_increment_bound_preset_version(self):
        paths = self.store.save_draft_references([("style.png", PNG)])
        item = self.create(positive="", reference_mode="image", reference_paths=paths)
        self.defaults(item["id"])
        original = self.repository.load("run")
        response = self.client.patch(f"/api/visual-presets/{item['id']}", json={
            "name": item["name"], "positive": "", "negative": "", "reference_mode": "image",
            "reference_paths": item["reference_images"], "vlm_analysis": {"positive": "", "negative": "", "structured": {}},
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), item)
        refreshed = self.defaults(item["id"], refresh=True)
        self.assertEqual(refreshed["visual_presets"], original["visual_presets"])
        self.assertEqual(refreshed["shots"][0]["style_preset_snapshot"]["version"], 1)

    def test_image_only_style_overrides_default_rendering_in_preview_single_and_batch(self):
        style = self.create(positive="", reference_mode="image",
                            reference_paths=self.store.save_draft_references([("style.png", PNG), ("style2.png", PNG)]))
        scene = Scene(id="scene", chapter="Chapter 1", index=1, text="Two adults hold hands.", summary="Two adults hold hands.",
                      characters=["Alice", "Bob"], location="bedroom", time="morning", mood=["tender"], visual_type="双人情绪特写", visual_priority=1)
        shot = shot_data()
        shot.update(positive_prompt=build_positive_prompt(scene, [], []), negative_prompt=build_negative_prompt())
        self.repository.save("run", {"shots": [shot]})
        self.defaults(style["id"])
        shot = self.repository.load("run")["shots"][0]
        identity = self.repository.run_dir("run") / "identity.png"
        identity.write_bytes(PNG)
        with patch.object(api, "reference_image_entries_for_shot", return_value=[("Alice", [identity]), ("Bob", [identity])]):
            preview = self.client.post("/api/runs/run/visual-preview", json={"shot": shot})
            single = self.client.post("/api/images", json={"run_id": "run", "shot": shot, "overwrite": True})
            batch = self.client.post("/api/images/batch", json={"run_id": "run", "shots": [shot], "skip_existing": False})
        for response in (preview, single, batch):
            self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(batch.json()["results"][0]["ok"], batch.text)
        for prompt, kwargs in self.provider.calls:
            self.assertTrue(prompt.startswith("Reference image roles"))
            self.assertIn("Images 1-2: character identity", prompt)
            self.assertIn("Images 3-4: drawing style only", prompt)
            self.assertIn("primary visual target", prompt)
            self.assertIn("head-to-body and facial proportions", prompt)
            self.assertIn("Two adults hold hands.", prompt)
            self.assertNotIn("subtle painterly texture", prompt)
            self.assertNotIn("soft volumetric light", prompt)
            self.assertNotIn("high quality anime light novel illustration", prompt)
            self.assertNotIn("chibi", kwargs["negative_prompt"])
            self.assertEqual(len(kwargs["style_reference_images"]), 2)
            self.assertEqual(kwargs["reference_images"], [identity, identity])
            self.assertEqual(prompt, preview.json()["positive_prompt"])
            self.assertEqual(kwargs["negative_prompt"], preview.json()["negative_prompt"])
        self.assertEqual(self.repository.load("run")["shots"][0]["positive_prompt"], shot["positive_prompt"])
        self.assertEqual(self.store.get(style["id"])["version"], 1)

    def test_existing_sequence_gets_one_frame_constraints_in_preview_single_and_batch(self):
        shot = self.repository.load("run")["shots"][0]
        original = "Scene: Bedroom, lights out. First she smooths the sheet. Then he warms her foot. Later they laugh and touch foreheads.\nLighting: No lamps or screen light."
        shot.update(positive_prompt=original, negative_prompt="extra fingers")
        preview = self.client.post("/api/runs/run/visual-preview", json={"shot": shot})
        self.assertEqual(preview.status_code, 200, preview.text)
        single = self.client.post("/api/images", json={"run_id": "run", "shot": shot})
        batch = self.client.post("/api/images/batch", json={"run_id": "run", "shots": [shot], "skip_existing": False})
        self.assertEqual(single.status_code, 200, single.text)
        self.assertEqual(batch.status_code, 200, batch.text)
        self.assertTrue(batch.json()["results"][0]["ok"], batch.text)
        self.assertEqual(len(self.provider.calls), 2)
        for prompt, kwargs in self.provider.calls:
            self.assertTrue(prompt.startswith(SINGLE_FRAME_RULE))
            self.assertIn(original, prompt)
            self.assertEqual(prompt, preview.json()["positive_prompt"])
            self.assertEqual(kwargs["negative_prompt"], preview.json()["negative_prompt"])
            self.assertIn("panel grid", kwargs["negative_prompt"])
        saved = self.repository.load("run")["shots"][0]
        self.assertEqual(saved["positive_prompt"], "USER BASE")
        self.assertEqual(saved["image_versions"][-1]["visual_preset_snapshot"]["assembly_version"], 4)
        self.assertEqual(saved["image_versions"][-1]["visual_preset_snapshot"]["positive_prompt"], preview.json()["positive_prompt"])

    def test_initial_pipeline_llm_receives_text_policy_before_writing_prompts(self):
        style = self.create(positive="flat manga", reference_mode="image",
                            reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        with patch("ficframe.pipeline.refine_scenes_with_llm", side_effect=lambda scenes, *_args, **_kwargs: scenes), \
             patch("ficframe.pipeline.build_character_prompt_bank", return_value=SimpleNamespace(mode="local")), \
             patch("ficframe.pipeline.analyze_character_differences", return_value={}):
            result = self.client.post("/api/pipeline", data={"run_id": "styled", "use_llm": "true", "llm_profile": "full",
                                      "style_id": style["id"], "style_reference_mode": "image", "prepared_characters": '[{"name":"Alice"}]'},
                                      files={"novel": ("novel.md", b"# Chapter 1\n\nAlice waits at the station."),
                                             "characters": ("characters.md", b"## Alice\nAn adult with dark blue hair.")})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(self.provider.text_calls), len(result.json()["shots"]))
        self.assertGreater(len(self.provider.text_calls), 0)
        for system, user, kwargs in self.provider.text_calls:
            self.assertEqual(user["visual_guides"]["style"]["id"], style["id"])
            self.assertEqual(user["visual_guides"]["style"]["compatibility_context"]["positive"], "flat manga")
            self.assertEqual(user["visual_guides"]["style"]["image_indices"], [])
            self.assertNotIn("image_paths", kwargs)
            self.assertNotIn("subtle painterly texture", user["shot"]["positive_prompt"])
            self.assertNotIn("chibi", user["shot"]["negative_prompt"])
            self.assertIn("No images are attached", system)

    def test_new_revised_and_prompt_rebuilt_shots_receive_pinned_text_only_guidance(self):
        style = self.create(positive="old flat manga", reference_mode="image",
                            reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        self.store.update(style["id"], {"positive": "new painterly style"})
        self.repository.novel_path("run").write_text("Two adults hold hands.", encoding="utf-8")
        responses = [
            self.client.post("/api/storyboard/generate", json={"run_id": "run", "description": "Two adults hold hands."}),
            self.client.post("/api/storyboard/regenerate", json={"run_id": "run", "shot_ids": ["shot_1"]}),
            self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"}),
        ]
        for response in responses:
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.provider.text_calls), 3)
        for system, user, kwargs in self.provider.text_calls:
            self.assertEqual(user["visual_guides"]["style"]["version"], 1)
            self.assertEqual(user["visual_guides"]["style"]["compatibility_context"]["positive"], "old flat manga")
            self.assertNotIn("image_paths", kwargs)
            self.assertIn("do not copy characters, outfits", system)

    def test_storyboard_text_mode_and_disabled_style_do_not_send_images(self):
        style = self.create(positive="flat manga", reference_mode="text",
                            reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        result = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"})
        self.assertEqual(result.status_code, 200, result.text)
        _, user, kwargs = self.provider.text_calls[-1]
        self.assertEqual(user["visual_guides"]["style"]["reference_mode"], "text")
        self.assertEqual(user["visual_guides"]["style"]["image_indices"], [])
        self.assertNotIn("image_paths", kwargs)
        self.selection("shot_1", style_preset_mode="none")
        result = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"})
        self.assertEqual(result.status_code, 200, result.text)
        _, user, kwargs = self.provider.text_calls[-1]
        self.assertEqual(user.get("visual_guides", {}), {})
        self.assertNotIn("image_paths", kwargs)

    def test_prompt_repair_keeps_text_only_bound_guidance(self):
        style = self.create(positive="flat manga", reference_mode="image",
                            reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        self.provider.text_responses = [json.dumps({"positive_prompt": "需要修正格式", "negative_prompt": "extra people"})]
        shot = Shot(**self.repository.load("run")["shots"][0])
        result = polish_shot_prompt(shot, [], self.provider, visual_store=self.store)
        self.assertEqual(len(self.provider.text_calls), 2)
        first, repaired = self.provider.text_calls
        self.assertEqual(first[1]["visual_guides"], repaired[1]["visual_guides"])
        self.assertNotIn("image_paths", first[2])
        self.assertNotIn("image_paths", repaired[2])
        self.assertFalse(style_neutral_errors(to_dict(result)))

    def test_text_only_llm_uses_existing_summary_only_to_avoid_conflicts(self):
        style = self.create(positive="simple manga", reference_mode="image", negative="painterly texture",
                            vlm_analysis={"structured": {"proportions": "two heads tall"}},
                            reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        self.provider.reject_images = True
        for _ in range(2):
            response = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.provider.text_calls), 2)  # both are text-only, no capability probe
        self.assertEqual(self.provider.calls, [])
        system, user, kwargs = self.provider.text_calls[-1]
        self.assertNotIn("image_paths", kwargs)
        guide = user["visual_guides"]["style"]
        self.assertEqual(guide["guidance_mode"], "compatibility_only")
        self.assertEqual(guide["compatibility_context"], {"positive": "simple manga", "negative": "painterly texture",
                                                       "structured": {"proportions": "two heads tall"}})
        for field in ("positive", "negative", "structured"):
            self.assertNotIn(field, guide)
        self.assertEqual(guide["image_indices"], [])
        self.assertEqual(guide["reference_mode"], "image")
        self.assertIn("never as a target style to imitate", system)
        shot = response.json()["shot"]
        self.assertEqual(shot["style_preset_snapshot"]["reference_mode"], "image")
        self.assertNotIn("simple flat manga lines", shot["positive_prompt"])
        self.assertFalse(style_neutral_errors(shot))
        self.assertNotIn("LLM 不支持图片", str(shot["qa_notes"]))
        self.assertEqual(self.store.get(style["id"]), style)

    def test_text_only_llm_never_analyzes_images_or_reuses_inferred_style_cache(self):
        style = self.create(positive="", reference_mode="image",
                            reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        self.provider.reject_images = True
        cache = self.store.root / "storyboard-analysis-cache"
        cache.mkdir()
        legacy = cache / "legacy.json"
        legacy.write_text(json.dumps({"positive": "INFERRED_VLM_STYLE"}), encoding="utf-8")
        before = {path: path.read_bytes() for path in self.store.root.rglob("*") if path.is_file()}
        shots = [Shot(**item) for item in self.repository.load("run")["shots"]]
        with patch.object(self.provider, "vision", side_effect=AssertionError("Automatic VLM analysis must not run")) as vision:
            result = polish_shots_with_llm(shots, [], self.provider, concurrency=2, visual_store=self.store)
        vision.assert_not_called()
        self.assertEqual(self.provider.calls, [])
        fallback = [(user, kwargs) for _, user, kwargs in self.provider.text_calls if not kwargs.get("image_paths")]
        self.assertEqual(len(fallback), 2)
        for user, _ in fallback:
            self.assertEqual(user["visual_guides"]["style"]["compatibility_context"], {})
            self.assertNotIn("INFERRED_VLM_STYLE", json.dumps(user))
        self.assertTrue(all(not style_neutral_errors(to_dict(shot)) for shot in result))
        self.assertTrue(all("simple flat manga lines" not in shot.positive_prompt for shot in result))
        self.assertEqual({path: path.read_bytes() for path in self.store.root.rglob("*") if path.is_file()}, before)
        self.assertEqual(self.store.get(style["id"]), style)

    def test_storyboard_never_reads_images_but_generation_keeps_original_images(self):
        style = self.create(positive="", reference_mode="image",
                            reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        self.provider.reject_images = True
        self.provider.config.vlm.api_key = None
        response = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"})
        self.assertEqual(response.status_code, 200, response.text)
        system, user, kwargs = self.provider.text_calls[-1]
        self.assertEqual(user["visual_guides"]["style"]["guidance_mode"], "compatibility_only")
        self.assertNotIn("image_paths", kwargs)
        self.assertIn("Do not invent visual observations", system)
        shot = response.json()["shot"]
        self.assertNotIn("LLM 不支持图片", str(shot["qa_notes"]))
        self.assertEqual(shot["style_preset_snapshot"]["reference_mode"], "image")
        self.assertFalse(style_neutral_errors(shot))
        generated = self.client.post("/api/images", json={"run_id": "run", "shot": shot})
        self.assertEqual(generated.status_code, 200, generated.text)
        self.assertEqual(len(self.provider.calls[0][1]["style_reference_images"]), 1)
        self.assertIn("style reference", self.provider.calls[0][0])
        self.assertIn("if a summary conflicts with the style images, follow the images", self.provider.calls[0][0])
        self.assertEqual(self.store.get(style["id"]), style)

    def test_configured_vlm_is_never_called_by_storyboard(self):
        style = self.create(positive="", reference_mode="image",
                            reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        self.provider.reject_images = True
        with patch.object(self.provider, "vision", side_effect=ProviderError("private-key private-reference")) as vision:
            for shot_id in ("shot_1", "shot_2"):
                response = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": shot_id})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertNotIn("private-key", response.text)
                self.assertNotIn("private-reference", response.text)
                self.assertNotIn("image_paths", self.provider.text_calls[-1][2])
        vision.assert_not_called()

    def test_text_only_new_and_revised_storyboards_keep_styles_neutral(self):
        style = self.create(positive="", reference_mode="image",
                            reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        self.repository.novel_path("run").write_text("Two adults hold hands.", encoding="utf-8")
        self.provider.reject_images = True
        for path, request in (("generate", {"description": "Two adults hold hands."}),
                              ("regenerate", {"shot_ids": ["shot_1"]})):
            with self.subTest(path=path):
                response = self.client.post(f"/api/storyboard/{path}", json={"run_id": "run", **request})
                self.assertEqual(response.status_code, 200, response.text)
                shot = response.json().get("shot") or response.json()["shots"][0]
                self.assertFalse(style_neutral_errors(shot))
                self.assertNotIn("simple flat manga lines", shot["positive_prompt"])
                self.assertEqual(shot["style_preset_snapshot"]["reference_mode"], "image")
        self.assertEqual(self.provider.calls, [])

    def test_provider_errors_are_not_hidden_by_image_fallback(self):
        style = self.create(positive="", reference_mode="image",
                            reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        self.repository.novel_path("run").write_text("fixture novel", encoding="utf-8")
        with patch.object(self.provider, "text", side_effect=ProviderError("429 image service rate limited")) as text:
            response = self.client.post("/api/storyboard/generate", json={"run_id": "run", "description": "Two adults hold hands."})
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(text.call_count, 1)
        self.assertEqual(self.provider.calls, [])

    def test_style_switch_retains_user_edits_until_llm_updates_and_archives_them(self):
        old = self.create(positive="soft watercolor")
        self.defaults(old["id"])
        original = {"positive_prompt": "Scene: bedroom.\nComposition: close view of two adults.\nCharacters: two distinct adults.\nLighting and style: Morning sunlight enters the east window; soft watercolor.\nAction: She offers a blue glass of water.\nUser details: Keep the cat-shaped clock at 9:40.",
                    "negative_prompt": "extra fingers, red glass, cel shading"}
        with self.repository.transaction("run") as payload:
            payload["shots"][0].update(original, prompt_style_snapshot=preset_snapshot(old), prompt_generation_baseline={**original, "positive_prompt": "Scene: bedroom. Style: soft watercolor."})
        new = self.create(positive="coarse ink", reference_mode="image", reference_paths=self.store.save_draft_references([("new.png", PNG)]))
        selected = self.selection("shot_1", style_preset_mode="preset", style_preset_id=new["id"], style_reference_mode="image")
        self.assertEqual(selected["positive_prompt"], original["positive_prompt"])
        preview = self.client.post("/api/runs/run/visual-preview", json={"shot": selected}).json()
        self.assertTrue(preview["prompt_style_pending"])
        self.assertIn("LLM 重建", preview["prompt_style_message"])
        updated = {"positive_prompt": "Scene: bedroom.\nComposition: close view of two adults.\nCharacters: two distinct adults.\nLighting: Morning sunlight enters the east window.\nAction: She offers a blue glass of water.\nUser details: Keep the cat-shaped clock at 9:40.", "negative_prompt": "extra fingers, red glass"}
        self.provider.text_responses = [json.dumps(updated)]
        response = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"})
        self.assertEqual(response.status_code, 200, response.text)
        system, user, kwargs = self.provider.text_calls[-1]
        self.assertEqual(user["shot"]["positive_prompt"], original["positive_prompt"])
        self.assertEqual(user["previous_prompt_style"]["id"], old["id"])
        self.assertIn("preserve user modifications", system)
        self.assertNotIn("image_paths", kwargs)
        shot = response.json()["shot"]
        self.assertEqual(shot["positive_prompt"], updated["positive_prompt"])
        preview = self.client.post("/api/runs/run/visual-preview", json={"shot": shot}).json()
        self.assertFalse(preview["prompt_style_pending"])
        self.assertNotIn("watercolor", preview["positive_prompt"])
        self.assertNotIn("coarse ink", preview["positive_prompt"])
        self.assertNotIn("cel shading", preview["negative_prompt"])
        self.assertTrue(any(v["shot"]["positive_prompt"] == original["positive_prompt"] for v in response.json()["storyboard_versions"]["shot_1"]))

    def test_mixed_sections_and_negative_conflicts_are_repaired_by_llm_without_slicing(self):
        style = self.create(positive="", reference_mode="image", reference_paths=self.store.save_draft_references([("new.png", PNG)]))
        self.defaults(style["id"])
        bad = {"positive_prompt": "Scene: bedroom.\nComposition: two adults.\nCharacters: distinct identities.\nLighting and style: Morning sunlight enters the east window.\nStyle: watercolor.\nAction: She offers water.\nUnexpected heading: Keep the clock.", "negative_prompt": "chibi, flat colors, cel shading, extra fingers"}
        good = {"positive_prompt": "Scene: bedroom.\nComposition: two adults.\nCharacters: distinct identities.\nLighting: Morning sunlight enters the east window.\nAction: She offers water.\nUnexpected heading: Keep the clock.", "negative_prompt": "extra fingers"}
        self.provider.text_responses = [json.dumps(bad), json.dumps(good)]
        result = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(self.provider.text_calls), 2)
        self.assertEqual(self.provider.text_calls[-1][1]["candidate"], bad)
        self.assertEqual(result.json()["shot"]["positive_prompt"], good["positive_prompt"])
        self.assertEqual(result.json()["shot"]["negative_prompt"], "extra fingers")

    def test_failed_neutral_repair_preserves_prompts_and_pending_warning(self):
        style = self.create(positive="", reference_mode="image", reference_paths=self.store.save_draft_references([("new.png", PNG)]))
        self.defaults(style["id"])
        before = self.repository.load("run")["shots"][0]
        bad = json.dumps({"positive_prompt": "Scene: bedroom. Composition: close up. Characters: two adults. Style: watercolor.", "negative_prompt": "chibi, flat colors, cel shading"})
        self.provider.text_responses = [bad, bad]
        response = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"})
        self.assertEqual(response.status_code, 502, response.text)
        after = self.repository.load("run")["shots"][0]
        self.assertEqual(before, after)
        self.assertTrue(self.client.post("/api/runs/run/visual-preview", json={"shot": after}).json()["prompt_style_pending"])

    def test_missing_images_do_not_block_storyboard_but_fail_image_preflight(self):
        style = self.create(positive="", reference_mode="image", reference_paths=self.store.save_draft_references([("new.png", PNG)]))
        self.defaults(style["id"])
        self.store.reference_path(style["reference_images"][0]).unlink()
        with patch.object(self.store, "reference_path", side_effect=AssertionError("Storyboard must not read images")):
            result = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"})
        self.assertEqual(result.status_code, 200, result.text)
        generated = self.client.post("/api/images", json={"run_id": "run", "shot": result.json()["shot"]})
        self.assertNotEqual(generated.status_code, 200)
        self.assertFalse(self.provider.calls)

    def test_empty_negative_is_saved_instead_of_restoring_old_style_exclusions(self):
        style = self.create(positive="", reference_mode="image", reference_paths=self.store.save_draft_references([("new.png", PNG)]))
        self.defaults(style["id"])
        with self.repository.transaction("run") as payload:
            payload["shots"][0]["negative_prompt"] = "chibi, flat colors, cel shading"
        neutral = {"positive_prompt": "Scene: quiet bedroom in the early morning. Composition: close view of two adults holding hands. Characters: two distinct adult identities. Relationships: tender companionship.", "negative_prompt": ""}
        self.provider.text_responses = [json.dumps(neutral)]
        response = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["shot"]["negative_prompt"], "")
        preview = self.client.post("/api/runs/run/visual-preview", json={"shot": response.json()["shot"]}).json()
        self.assertNotIn("chibi", preview["negative_prompt"])

    def test_reselecting_same_style_is_not_pending_and_server_baseline_survives_save(self):
        style = self.create(positive="ink")
        self.defaults(style["id"])
        response = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"})
        self.assertEqual(response.status_code, 200, response.text)
        original = response.json()["shot"]
        self.selection("shot_1", style_preset_mode="none")
        selected = self.selection("shot_1", style_preset_mode="inherit")
        self.assertFalse(self.client.post("/api/runs/run/visual-preview", json={"shot": selected}).json()["prompt_style_pending"])
        stale = {**selected, "prompt_style_snapshot": {}, "prompt_generation_baseline": {}, "positive_prompt": selected["positive_prompt"] + "\nAction: Keep my blue glass."}
        saved = self.client.post("/api/storyboard/save", json={"run_id": "run", "shots": [stale]})
        self.assertEqual(saved.status_code, 200, saved.text)
        shot = saved.json()["shots"][0]
        self.assertEqual(shot["prompt_style_snapshot"], original["prompt_style_snapshot"])
        self.assertEqual(shot["prompt_generation_baseline"], original["prompt_generation_baseline"])
        self.assertIn("Keep my blue glass", shot["positive_prompt"])

    def test_missing_returned_negative_is_repaired_not_inherited(self):
        style = self.create(positive="", reference_mode="image", reference_paths=self.store.save_draft_references([("new.png", PNG)]))
        self.defaults(style["id"])
        self.provider.text_responses = [json.dumps({"positive_prompt": "Scene: bedroom. Composition: close view. Characters: two adults."})]
        response = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.provider.text_calls), 2)
        self.assertIn("corrections_required", self.provider.text_calls[-1][1])

    def test_no_style_keeps_existing_prompt_behavior_and_text_style_writes_style(self):
        result = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("Style: simple flat manga lines", result.json()["shot"]["positive_prompt"])
        self.assertNotIn("visual_guides", self.provider.text_calls[-1][1])
        style = self.create(positive="bold flat ink", reference_mode="text")
        self.defaults(style["id"])
        self.provider.text_responses = [json.dumps({"positive_prompt": "Scene: quiet bedroom in the early morning. Composition: close view of two adults holding hands. Characters: two distinct adult identities. Relationships: tender companionship. Style: bold flat ink.", "negative_prompt": "extra fingers"})]
        result = self.client.post("/api/storyboard/prompt", json={"run_id": "run", "shot_id": "shot_1"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("Style: bold flat ink", result.json()["shot"]["positive_prompt"])
        self.assertEqual(self.provider.text_calls[-1][1]["visual_guides"]["style"]["positive"], "bold flat ink")

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
        self.assertEqual((positive, negative), single_frame_constraints("USER BASE", "USER NEG"))
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

    def test_generation_does_not_require_probe_but_optional_probe_requires_confirmation(self):
        style = self.create(reference_mode="image", reference_paths=self.store.save_draft_references([("ref.png", PNG)]))
        self.defaults(style["id"])
        shot = self.repository.load("run")["shots"][0]
        response = self.client.post("/api/image-reference-test-task", json={"confirmed": False})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.provider.calls, [])
        response = self.client.post("/api/images", json={"run_id": "run", "shot": shot, "overwrite": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(len(self.provider.calls[0][1]["style_reference_images"]), 1)
        self.assertFalse((self.store.root / "reference-capabilities.json").exists())
        response = self.client.post("/api/image-reference-test-task", json={"confirmed": True, "reference_count": 2})
        self.assertEqual(response.status_code, 202)
        result = self.wait_task(response.json()["task_id"])
        self.assertEqual(result["status"], "supported")
        self.assertEqual(result["tested_count"], 2)
        self.assertEqual(len(self.provider.calls), 2)
        self.assertEqual(self.client.get("/api/image-reference-capability").json()["status"], "supported")
        self.provider.config.image.model = "changed-model"
        self.assertEqual(self.client.get("/api/image-reference-capability").json()["status"], "unknown")
        response = self.client.post("/api/images", json={"run_id": "run", "shot": shot, "overwrite": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.provider.calls), 3)

    def test_unverified_visual_channels_single_batch_and_retry_do_not_mix_identity_groups(self):
        style = self.create(reference_mode="image", reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        composition = self.create("composition", reference_mode="image", reference_paths=self.store.save_draft_references([("layout.png", PNG)]))
        self.defaults(style["id"], composition["id"])
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
        style = self.create(reference_mode="image", reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        shot = self.repository.load("run")["shots"][0]
        for kind in ("siliconflow", "comfyui"):
            with self.subTest(provider=kind):
                self.provider.config.image.provider = kind
                response = self.client.get("/api/image-reference-capability")
                self.assertEqual(response.json()["status"], "unsupported")
                response = self.client.post("/api/image-reference-test-task", json={"confirmed": True})
                result = self.wait_task(response.json()["task_id"])
                self.assertEqual(result["status"], "unsupported")
                response = self.client.post("/api/images", json={"run_id": "run", "shot": shot})
                self.assertEqual(response.status_code, 400, response.text)
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

    def test_changed_reference_count_size_and_credentials_do_not_require_new_probe(self):
        from ficframe.image_reference_workflow import probe_references, reference_preflight
        style = self.create(reference_mode="image", reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        payload = self.repository.load("run")
        snapshot = resolve_generation(self.store, payload, Shot(**payload["shots"][0]))[2]
        probe_references(self.store, self.provider, 2, "1024x1024")
        check = reference_preflight(self.store, self.provider, snapshot, 2, "1024x1024")
        self.assertTrue(check["ok"])
        self.assertEqual(check["total_count"], 3)
        self.assertEqual(check["tested_count"], 2)
        self.assertTrue(reference_preflight(self.store, self.provider, snapshot, 0, "2K")["ok"])
        self.provider.config.image.api_key = "changed-key"
        self.assertTrue(reference_preflight(self.store, self.provider, snapshot, 0, "1024x1024")["ok"])
        self.assertEqual(len(self.provider.calls), 1)

    def test_background_generation_can_ignore_previously_failed_probe(self):
        from ficframe.image_reference_workflow import probe_references
        style = self.create(reference_mode="image", reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        with patch.object(self.provider, "image", side_effect=ProviderError("400 reference images not supported")):
            self.assertEqual(probe_references(self.store, self.provider, 2, "1024x1024")["status"], "unsupported")
        shot = self.repository.load("run")["shots"][0]
        with patch.object(api, "get_task_manager", return_value=self.manager):
            response = self.client.post("/api/images/task", json={"run_id": "run", "shot": shot})
            self.assertEqual(response.status_code, 202, response.text)
            result = self.wait_task(response.json()["task_id"])
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(len(self.provider.calls[0][1]["style_reference_images"]), 1)
        self.assertTrue(result["visual_preset_snapshot"]["reference_delivery"]["capability"]["ok"])

    def test_old_cached_messages_no_longer_require_testing(self):
        from ficframe.image_reference_workflow import save_capability
        for status in ("unknown", "supported", "unsupported"):
            with self.subTest(status=status):
                save_capability(self.store, self.provider, "1024x1024", {"status": status, "tested_count": 2,
                                "message": "请先运行测试，更多图片需重新测试。"})
                result = self.client.get("/api/image-reference-capability").json()
                self.assertEqual(result["status"], status)
                self.assertEqual(result["tested_count"], 2)
                self.assertNotIn("请先运行测试", result["message"])
                self.assertNotIn("需重新测试", result["message"])

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
        style = self.create(reference_mode="image", reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
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
        retried = self.client.post("/api/images/batch", json={"run_id": "run", "shots": shots, "skip_existing": False})
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertTrue(all(item["ok"] for item in retried.json()["results"]))
        self.assertEqual(len(self.provider.calls), 2)

    def test_generation_preserves_supplier_load_error_and_allows_retry_without_probe(self):
        style = self.create(reference_mode="image", reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        shot = self.repository.load("run")["shots"][0]
        with patch.object(self.provider, "image", side_effect=ProviderError("图片 API 返回错误：excessive system load; request_id=task-14")):
            response = self.client.post("/api/images", json={"run_id": "run", "shot": shot})
        self.assertEqual(response.status_code, 400)
        self.assertIn("excessive system load", response.json()["detail"])
        self.assertIn("task-14", response.json()["detail"])
        self.assertIn("负载过高", response.json()["detail"])
        self.assertEqual(self.client.get("/api/image-reference-capability").json()["status"], "unknown")
        response = self.client.post("/api/images", json={"run_id": "run", "shot": shot})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.provider.calls), 1)

    def test_batch_retries_supplier_load_error_without_probe(self):
        style = self.create(reference_mode="image", reference_paths=self.store.save_draft_references([("style.png", PNG)]))
        self.defaults(style["id"])
        shots = self.repository.load("run")["shots"]
        original = self.provider.image
        calls = []

        def generate(prompt, target, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise ProviderError("图片 API 返回错误：excessive system load")
            return original(prompt, target, **kwargs)

        with patch.object(self.provider, "image", side_effect=generate), patch("ficframe.image_workflow.time.sleep") as pause:
            response = self.client.post("/api/images/batch", json={"run_id": "run", "shots": shots, "retry_count": 1})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(all(item["ok"] for item in response.json()["results"]))
        self.assertEqual([item["attempts"] for item in response.json()["results"]], [2, 1])
        self.assertEqual(len(calls), 3)
        pause.assert_called_once_with(2)
        self.assertTrue(all(len(kwargs["style_reference_images"]) == 1 for kwargs in calls))
        self.assertFalse((self.store.root / "reference-capabilities.json").exists())
