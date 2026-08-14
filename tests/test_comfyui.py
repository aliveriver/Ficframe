from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from ficframe.comfyui import (
    ComfyUIClient,
    ComfyUIError,
    find_output_image,
    load_api_workflow,
    parse_size,
    render_api_workflow,
)
from ficframe.config_store import write_provider_config
from ficframe.providers import ProviderConfig


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
    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(content_length)
        if self.path == "/upload/image":
            self._json({"name": "reference.png", "subfolder": "ficframe", "type": "input"})
            return
        if self.path == "/prompt":
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


if __name__ == "__main__":
    unittest.main()
