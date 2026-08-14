from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from ficframe.comfyui import (
    ComfyUIClient,
    ComfyUIError,
    comfyui_upload_filename,
    find_output_image,
    load_api_workflow,
    parse_size,
    render_api_workflow,
)
from ficframe.config_store import write_provider_config
from ficframe.llm_pipeline import polish_shot_prompt
from ficframe.models import CharacterCard, Shot
from ficframe.providers import (
    EndpointConfig,
    OpenAICompatibleProvider,
    ProviderConfig,
    combine_negative_prompts,
    image_prompt_with_negative,
)


WORKFLOW = {
    "3": {
        "class_type": "KSampler",
        "inputs": {"seed": "{{seed}}", "steps": "{{steps}}", "cfg": "{{cfg}}"},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "prefix, {{prompt}}"},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "{{negative_prompt}}"},
    },
    "8": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": "{{width}}", "height": "{{height}}"},
    },
    "9": {
        "class_type": "LoadImage",
        "inputs": {"image": "{{reference_image}}"},
    },
}


class WorkflowTests(unittest.TestCase):
    def test_comfyui_reference_selection_keeps_all_images_grouped_by_shot_character_order(self) -> None:
        from ficframe import api as api_module

        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory)
            run_dir = runs / "test-run"
            references = run_dir / "references"
            references.mkdir(parents=True)
            for filename in ("a-first.png", "a-second.png", "b-first.png"):
                (references / filename).write_bytes(b"image")
            (run_dir / "pipeline.json").write_text(json.dumps({
                "characters": [
                    {"name": "A", "reference_images": [
                        "/runs/test-run/references/a-first.png",
                        "/runs/test-run/references/a-second.png",
                    ]},
                    {"name": "B", "reference_images": ["/runs/test-run/references/b-first.png"]},
                ]
            }), encoding="utf-8")
            shot = Shot(
                id="shot-1", scene_id="scene-1", title="", source_excerpt="", characters=["B", "A"],
                location="", time="", mood=[], camera="", composition="", visual_goal="",
                continuity_notes=[], positive_prompt="", negative_prompt="",
                character_layout=[
                    {"character": "A", "region": [0.4, 0.1, 1.0, 1.0]},
                    {"character": "B", "region": [0.0, 0.0, 0.6, 0.9]},
                ],
            )
            with patch.object(api_module, "RUNS", runs):
                entries = api_module.reference_image_entries_for_shot("test-run", shot)
                groups = api_module.reference_image_groups_for_shot("test-run", shot)
                selected = api_module.reference_paths_for_shot("test-run", shot)

        self.assertEqual([[path.name for path in group] for group in groups], [
            ["b-first.png"],
            ["a-first.png", "a-second.png"],
        ])
        self.assertEqual([path.name for path in selected], ["b-first.png", "a-first.png", "a-second.png"])
        self.assertEqual(
            api_module.reference_regions_for_characters(shot, [name for name, _ in entries]),
            [[0.0, 0.0, 0.6, 0.9], [0.4, 0.1, 1.0, 1.0]],
        )

    def test_repository_ipadapter_workflow_supports_multiple_images_and_characters(self) -> None:
        example = Path(__file__).resolve().parents[2] / "examples" / "comfyui" / "ficframe_sdxl_ipadapter_api.json"
        raw = example.read_text(encoding="utf-8")

        text_workflow = load_api_workflow(raw, reference_group_sizes=[])
        workflow = load_api_workflow(raw, reference_group_sizes=[2, 1, 1])
        classes = [node["class_type"] for node in workflow.values()]

        self.assertNotIn("IPAdapterUnifiedLoader", {node["class_type"] for node in text_workflow.values()})
        self.assertEqual(classes.count("LoadImage"), 4)
        self.assertEqual(classes.count("IPAdapterEncoder"), 4)
        self.assertEqual(classes.count("IPAdapterCombineEmbeds"), 2)
        self.assertEqual(classes.count("IPAdapterEmbeds"), 3)
        self.assertEqual(classes.count("FeatherMask"), 3)

        rendered = render_api_workflow(
            workflow,
            prompt="four references for three characters",
            negative_prompt="blur",
            size="768x1024",
            model="Illustrious-XL-v0.1.safetensors",
            steps=20,
            cfg=6.0,
            reference_images=[
                "ficframe/a-front.png",
                "ficframe/a-side.png",
                "ficframe/b.png",
                "ficframe/c.png",
            ],
            reference_group_sizes=[2, 1, 1],
            seed=3070,
        )
        by_title = {
            node.get("_meta", {}).get("title"): node
            for node in rendered.values()
            if node.get("_meta", {}).get("title")
        }
        self.assertEqual(by_title["Character 1 Reference 1"]["inputs"]["image"], "ficframe/a-front.png")
        self.assertEqual(by_title["Character 1 Reference 2"]["inputs"]["image"], "ficframe/a-side.png")
        self.assertEqual(by_title["Character 3 Reference 1"]["inputs"]["image"], "ficframe/c.png")
        self.assertEqual(by_title["Character 1 Region"]["inputs"]["width"], 256)
        self.assertEqual(by_title["Character 2 Positioned Region"]["inputs"]["x"], 256)
        self.assertEqual(by_title["Character 3 Positioned Region"]["inputs"]["x"], 512)
        self.assertEqual(by_title["Character 1 IP-Adapter"]["inputs"]["weight"], 0.15)
        self.assertEqual(by_title["Character 2 IP-Adapter"]["inputs"]["weight"], 0.3)
        self.assertEqual(rendered["3"]["inputs"]["model"][0], next(
            node_id for node_id, node in rendered.items()
            if node.get("_meta", {}).get("title") == "Character 3 IP-Adapter"
        ))
        self.assertIn("referenced characters", rendered["6"]["inputs"]["text"])
        self.assertNotIn("3 characters", rendered["6"]["inputs"]["text"])
        self.assertNotIn("{{", json.dumps(rendered))

    def test_duplicate_reference_names_keep_separate_files_and_bindings(self) -> None:
        from ficframe import api as api_module

        with tempfile.TemporaryDirectory() as directory:
            references = Path(directory)
            first = api_module.available_reference_filename(references, "image.png")
            (references / first).write_bytes(b"first")
            second = api_module.available_reference_filename(references, "image.png")
            bindings = api_module.parse_reference_bindings(json.dumps([
                {"filename": "image.png", "character": "A"},
                {"filename": "image.png", "character": "B"},
            ]))

            first_binding = api_module.take_reference_binding(bindings, "image.png")
            second_binding = api_module.take_reference_binding(bindings, "image.png")

        self.assertEqual(first, "image.png")
        self.assertEqual(second, "image_2.png")
        self.assertEqual(first_binding["character"], "A")
        self.assertEqual(second_binding["character"], "B")

    def test_pipeline_keeps_duplicate_reference_uploads_bound_to_separate_characters(self) -> None:
        from ficframe import api as api_module

        class Provider:
            config = SimpleNamespace(vlm=SimpleNamespace(api_key=""))

        bindings = json.dumps([
            {"filename": "image.png", "character": "角色甲", "enabled": True},
            {"filename": "image.png", "character": "角色乙", "enabled": True},
        ], ensure_ascii=False)
        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory)
            with (
                patch.object(api_module, "RUNS", runs),
                patch.object(api_module, "OpenAICompatibleProvider", return_value=Provider()),
                TestClient(api_module.app) as client,
            ):
                response = client.post(
                    "/api/pipeline",
                    data={
                        "reference_bindings": bindings,
                        "manual_characters": "[]",
                        "prepared_characters": "[]",
                        "max_shots": "1",
                        "use_llm": "false",
                    },
                    files=[
                        ("novel", ("novel.md", "角色甲和角色乙在车站见面。".encode(), "text/markdown")),
                        ("characters", ("characters.md", "## 角色甲\n- 外貌：黑发\n\n## 角色乙\n- 外貌：银发".encode(), "text/markdown")),
                        ("reference_images", ("image.png", b"first", "image/png")),
                        ("reference_images", ("image.png", b"second", "image/png")),
                    ],
                )

            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            by_name = {card["name"]: card for card in payload["characters"]}
            first_url = by_name["角色甲"]["reference_images"][0]
            second_url = by_name["角色乙"]["reference_images"][0]
            reference_files = sorted((runs / payload["run_id"] / "references").iterdir())

        self.assertNotEqual(first_url, second_url)
        self.assertEqual([path.name for path in reference_files], ["image.png", "image_2.png"])

    def test_comfyui_upload_names_are_unique_for_same_basename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "a" / "image.png"
            second = root / "b" / "image.png"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")

            first_name = comfyui_upload_filename(first)
            second_name = comfyui_upload_filename(second)

        self.assertNotEqual(first_name, second_name)
        self.assertTrue(first_name.startswith("image-"))
        self.assertTrue(first_name.endswith(".png"))

    def test_cloud_prompt_keeps_previous_negative_constraint_format(self) -> None:
        self.assertEqual(
            image_prompt_with_negative("positive", "blur, duplicate"),
            "positive\n\nNegative constraints:\nblur, duplicate",
        )
        self.assertEqual(combine_negative_prompts("blur,", "duplicate"), "blur, duplicate")

    def test_batch_image_api_passes_positive_and_negative_prompts_separately(self) -> None:
        from ficframe import api as api_module

        captured: dict[str, object] = {}

        class Provider:
            def image(self, prompt: str, out_path: Path, **kwargs: object) -> Path:
                captured["prompt"] = prompt
                captured.update(kwargs)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(b"image")
                return out_path

        shot = Shot(
            id="shot-prompts", scene_id="scene-prompts", title="", source_excerpt="", characters=[],
            location="", time="", mood=[], camera="", composition="", visual_goal="",
            continuity_notes=[], positive_prompt="positive only", negative_prompt="negative only",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(api_module, "RUNS", root):
                result = api_module.generate_batch_image_item(
                    Provider(),  # type: ignore[arg-type]
                    "test-run",
                    shot,
                    root / "test-run" / "images" / "shot-prompts.png",
                    "768x768",
                    0,
                    True,
                )

        self.assertTrue(result["ok"])
        self.assertEqual(captured["prompt"], "positive only")
        self.assertEqual(captured["negative_prompt"], "negative only")

    def test_llm_layout_drives_overlapping_two_dimensional_masks(self) -> None:
        example = Path(__file__).resolve().parents[2] / "examples" / "comfyui" / "ficframe_sdxl_ipadapter_api.json"
        raw = example.read_text(encoding="utf-8")
        regions = [[0.05, 0.1, 0.6, 0.95], [0.45, 0.2, 0.95, 0.8]]
        workflow = load_api_workflow(
            raw,
            reference_group_sizes=[1, 1],
            reference_regions=regions,
            regional_guidance=True,
        )
        rendered = render_api_workflow(
            workflow,
            prompt="a foreground conversation",
            negative_prompt="blur",
            size="1000x800",
            model="model.safetensors",
            steps=20,
            cfg=6.0,
            reference_images=["ficframe/a.png", "ficframe/b.png"],
            reference_group_sizes=[1, 1],
            reference_regions=regions,
            seed=42,
        )
        by_title = {
            node.get("_meta", {}).get("title"): node
            for node in rendered.values()
            if node.get("_meta", {}).get("title")
        }
        self.assertEqual(by_title["Character 1 Positioned Region"]["inputs"]["x"], 50)
        self.assertEqual(by_title["Character 1 Positioned Region"]["inputs"]["y"], 80)
        self.assertEqual(by_title["Character 1 Region"]["inputs"]["width"], 550)
        self.assertEqual(by_title["Character 1 Region"]["inputs"]["height"], 680)
        self.assertEqual(by_title["Character 2 Positioned Region"]["inputs"]["x"], 450)
        self.assertIn("assigned composition region", rendered["6"]["inputs"]["text"])
        self.assertNotIn("left to right", rendered["6"]["inputs"]["text"])
        self.assertNotIn("{{", json.dumps(rendered))

    def test_llm_can_choose_free_composition_without_attention_masks(self) -> None:
        example = Path(__file__).resolve().parents[2] / "examples" / "comfyui" / "ficframe_sdxl_ipadapter_api.json"
        workflow = load_api_workflow(
            example.read_text(encoding="utf-8"),
            reference_group_sizes=[1, 1, 1],
            regional_guidance=False,
        )
        classes = [node["class_type"] for node in workflow.values()]

        self.assertEqual(classes.count("IPAdapterEmbeds"), 3)
        self.assertNotIn("SolidMask", classes)
        self.assertNotIn("FeatherMask", classes)
        self.assertEqual(workflow["6"]["inputs"]["text"], "{{prompt}}")

    def test_llm_shot_polish_records_structured_character_layout(self) -> None:
        positive = (
            "Scene: Two researchers meet in a quiet laboratory at night. "
            "Composition: One stands in the foreground left while the other remains behind on the right. "
            "Characters: A looks determined and B watches carefully. "
            "Relationships: They cooperate while maintaining visual separation. "
            "Style: Detailed cinematic light novel illustration."
        )
        response = json.dumps({
            "positive_prompt": positive,
            "negative_prompt": "blur, duplicate people, merged bodies",
            "regional_guidance": True,
            "character_layout": [
                {"character": "A", "position": "foreground left", "depth": "foreground", "region": [0.0, 0.0, 0.6, 1.0]},
                {"character": "B", "position": "background right", "depth": "background", "region": [0.45, 0.1, 1.0, 0.9]},
            ],
            "qa_notes": [],
        })

        class Provider:
            def text(self, system: str, user: str, purpose: str = "") -> str:
                return response

        shot = Shot(
            id="shot-layout", scene_id="scene-layout", title="", source_excerpt="", characters=["A", "B"],
            location="laboratory", time="night", mood=[], camera="medium shot", composition="layered",
            visual_goal="", continuity_notes=[], positive_prompt=positive, negative_prompt="blur",
        )
        cards = [CharacterCard(name="A"), CharacterCard(name="B")]
        polished = polish_shot_prompt(shot, cards, Provider())  # type: ignore[arg-type]

        self.assertTrue(polished.regional_guidance)
        self.assertEqual([item["character"] for item in polished.character_layout], ["A", "B"])
        self.assertEqual(polished.character_layout[1]["region"], [0.45, 0.1, 1.0, 0.9])

    def test_repository_sdxl_example(self) -> None:
        example = Path(__file__).resolve().parents[2] / "examples" / "comfyui" / "ficframe_sdxl_api.json"
        workflow = load_api_workflow(example.read_text(encoding="utf-8"))
        rendered = render_api_workflow(
            workflow,
            prompt="novel scene",
            negative_prompt="blur",
            size="1024x1024",
            model="illustriousXL_v10.safetensors",
            steps=24,
            cfg=6.0,
            seed=3070,
        )

        self.assertEqual(rendered["4"]["inputs"]["ckpt_name"], "illustriousXL_v10.safetensors")
        self.assertEqual(rendered["5"]["inputs"]["width"], 1024)
        self.assertEqual(rendered["9"]["class_type"], "SaveImage")
        self.assertNotIn("{{", json.dumps(rendered))

    def test_load_and_render_api_workflow(self) -> None:
        workflow = load_api_workflow(json.dumps({"prompt": WORKFLOW}))
        rendered = render_api_workflow(
            workflow,
            prompt="a character",
            negative_prompt="blur",
            size="768x1024",
            model="model.safetensors",
            steps=24,
            cfg=6.5,
            reference_images=["ficframe/ref.png"],
            seed=42,
        )

        self.assertEqual(rendered["3"]["inputs"], {"seed": 42, "steps": 24, "cfg": 6.5})
        self.assertEqual(rendered["6"]["inputs"]["text"], "prefix, a character")
        self.assertEqual(rendered["7"]["inputs"]["text"], "blur")
        self.assertEqual(rendered["8"]["inputs"], {"width": 768, "height": 1024})
        self.assertEqual(rendered["9"]["inputs"]["image"], "ficframe/ref.png")
        self.assertEqual(WORKFLOW["3"]["inputs"]["seed"], "{{seed}}")

    def test_rejects_non_api_workflow(self) -> None:
        with self.assertRaises(ComfyUIError):
            load_api_workflow('{"nodes": []}')

    def test_symbolic_image_size(self) -> None:
        self.assertEqual(parse_size("2K"), (2048, 2048))

    def test_finds_configured_output_node(self) -> None:
        outputs = {
            "10": {"images": [{"filename": "preview.png"}]},
            "20": {"images": [{"filename": "final.png"}]},
        }
        self.assertEqual(find_output_image(outputs, "20")["filename"], "final.png")

    def test_active_workflow_survives_env_sync(self) -> None:
        workflow_json = json.dumps(WORKFLOW, ensure_ascii=False, indent=2)
        config = {
            "active": {"image": "local-comfy"},
            "sources": [{
                "id": "local-comfy",
                "label": "Local ComfyUI",
                "kind": "image",
                "provider": "comfyui",
                "base_url": "http://127.0.0.1:8188",
                "api_key": "",
                "models": [],
                "active_model": "",
                "options": {"workflow_json": workflow_json},
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {}, clear=False):
                write_provider_config(root / "providers.json", root / ".env", config)
                loaded = ProviderConfig.from_env()

        self.assertEqual(json.loads(loaded.image_options["workflow_json"]), WORKFLOW)


class _ComfyHandler(BaseHTTPRequestHandler):
    last_prompt: dict[str, object] | None = None

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        if self.path == "/upload/image":
            self._json({"name": "reference.png", "subfolder": "ficframe", "type": "input"})
            return
        if self.path == "/prompt":
            type(self).last_prompt = json.loads(body).get("prompt")
            self._json({"prompt_id": "test-prompt"})
            return
        self.send_error(404)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/history/test-prompt":
            self._json({
                "test-prompt": {
                    "status": {"status_str": "success", "completed": True},
                    "outputs": {"20": {"images": [{"filename": "result.png", "subfolder": "", "type": "output"}]}},
                }
            })
            return
        if self.path.startswith("/view?"):
            body = b"generated-image"
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, data: dict[str, object]) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ClientTests(unittest.TestCase):
    def test_upload_queue_poll_and_download(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ComfyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                reference = root / "reference.png"
                reference.write_bytes(b"reference")
                target = root / "result.png"
                client = ComfyUIClient(f"http://127.0.0.1:{server.server_port}", timeout=5, poll_interval=0.01)

                uploaded = client.upload_images([reference])
                result = client.generate(WORKFLOW, target, output_node_id="20")

                self.assertEqual(uploaded, ["ficframe/reference.png"])
                self.assertEqual(result.read_bytes(), b"generated-image")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_provider_routes_shot_negative_prompt_to_comfyui_negative_node(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ComfyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        _ComfyHandler.last_prompt = None
        try:
            config = ProviderConfig(
                llm=EndpointConfig(),
                image=EndpointConfig(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    model="model.safetensors",
                    provider="comfyui",
                ),
                vlm=EndpointConfig(),
                image_timeout=5,
                image_options={
                    "workflow_json": json.dumps(WORKFLOW),
                    "negative_prompt": "default negative",
                    "output_node_id": "20",
                    "poll_interval": "0.01",
                    "steps": "20",
                    "guidance_scale": "6",
                },
            )
            provider = OpenAICompatibleProvider(config)
            with tempfile.TemporaryDirectory() as directory:
                result = provider.image(
                    "positive scene",
                    Path(directory) / "result.png",
                    negative_prompt="shot negative",
                )
                generated = result.read_bytes()

            workflow = _ComfyHandler.last_prompt
            self.assertIsNotNone(workflow)
            self.assertEqual(workflow["6"]["inputs"]["text"], "prefix, positive scene")
            self.assertEqual(workflow["7"]["inputs"]["text"], "shot negative, default negative")
            self.assertNotIn("shot negative", workflow["6"]["inputs"]["text"])
            self.assertEqual(generated, b"generated-image")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
