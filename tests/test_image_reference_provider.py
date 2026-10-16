from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from ficframe.comfyui import render_api_workflow
from ficframe.image_reference_workflow import capability, probe_references, provider_fingerprint, synthetic_png
from ficframe.providers import EndpointConfig, OpenAICompatibleProvider, ProviderConfig, ProviderError
from ficframe.visual_presets import VisualPresetStore


class ImageReferenceProviderTests(unittest.TestCase):
    def provider(self, kind):
        return OpenAICompatibleProvider(ProviderConfig(llm=EndpointConfig(), vlm=EndpointConfig(),
            image=EndpointConfig(provider=kind, model="test-model", api_key="test-key", base_url="https://fake.invalid/v1")))

    def test_cloud_adapters_normalize_sizes_for_generation_and_reference_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.png"
            reference.write_bytes(synthetic_png(0))
            response = {"data": [{"b64_json": base64.b64encode(synthetic_png(0)).decode()}]}
            for kind, field in (("openai", "size"), ("ark", "size"), ("siliconflow", "image_size"), ("grsai", "aspectRatio")):
                provider = self.provider(kind)
                for references in ([], [reference]):
                    for size, expected in (("1K", "1024x1024"), ("2K", "2048x2048"), ("4K", "2880x2880"),
                                           (" 2k ", "2048x2048"), ("1536x1024", "1536x1024"),
                                           ("4096x4096", "4096x4096"), ("16:9", "16:9"), ("auto", "auto")):
                        with self.subTest(provider=kind, references=len(references), size=size), \
                                patch.object(provider, "_post", return_value=response) as post, \
                                patch.object(provider, "_post_multipart", return_value=response) as multipart:
                            provider.image("ABSTRACT", Path(directory) / "output.png", size=size, reference_images=references)
                            call = multipart.call_args if kind == "openai" and references else post.call_args
                            self.assertEqual(call.args[3][field], expected)
                            self.assertEqual(post.call_count + multipart.call_count, 1)

    def test_model_override_uses_the_same_resolution_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = self.provider("grsai")
            response = {"data": [{"b64_json": base64.b64encode(synthetic_png(0)).decode()}]}
            with patch.object(provider, "_post", return_value=response) as post:
                provider.image("ABSTRACT", Path(directory) / "output.png", size="2K", model="gpt-image-2.5-flare")
                self.assertEqual(post.call_args.args[3]["aspectRatio"], "2048x2048")
                self.assertEqual(post.call_args.args[3]["model"], "gpt-image-2.5-flare")
            with patch.object(provider, "_post", return_value=response) as post:
                provider.image("ABSTRACT", Path(directory) / "output.png", size="2K", model="nano-banana-2")
                self.assertEqual(post.call_args.args[3]["aspectRatio"], "2048x2048")
                self.assertEqual(post.call_args.args[3]["model"], "nano-banana-2")

    def test_grsai_four_reference_probe_uses_correct_size_and_matching_capability_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            store = VisualPresetStore(Path(directory) / "presets")
            provider = self.provider("grsai")
            provider.config.image.model = "gpt-image-2-vip"
            response = {"data": [{"b64_json": base64.b64encode(synthetic_png(0)).decode()}]}
            with patch.object(provider, "_post", return_value=response) as post:
                result = probe_references(store, provider, 4, "2K")
            self.assertEqual(result["status"], "supported")
            self.assertEqual(post.call_count, 1)
            payload = post.call_args.args[3]
            self.assertEqual(payload["aspectRatio"], "2048x2048")
            self.assertEqual(len(payload["images"]), 4)
            self.assertTrue(all(image.startswith("data:image/png;base64,") for image in payload["images"]))
            self.assertEqual(capability(store, provider, "2048x2048")["tested_count"], 4)
            self.assertEqual(capability(store, provider, "2048x2048")["status"], "supported")
            self.assertEqual(capability(store, provider, "1024x1024")["status"], "unknown")

    def test_generic_grsai_generation_failure_does_not_mean_multireference_is_unsupported(self):
        with tempfile.TemporaryDirectory() as directory:
            store = VisualPresetStore(Path(directory) / "presets")
            provider = self.provider("grsai")
            provider.config.image.model = "gpt-image-2-vip"
            response = {"id": "test-task", "status": "failed", "error": "generate failed"}
            with patch.object(provider, "_post", return_value=response) as post:
                result = probe_references(store, provider, 4, "2K")
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(capability(store, provider, "2K")["status"], "unknown")
            self.assertEqual(post.call_count, 1)

    def test_all_adapters_share_capability_fingerprints_for_aliases_and_pixels(self):
        for kind in ("openai", "ark", "siliconflow", "grsai", "comfyui"):
            provider = self.provider(kind)
            for size, pixels in (("1K", "1024x1024"), ("2K", "2048x2048"), ("4K", "2880x2880")):
                with self.subTest(provider=kind, size=size):
                    self.assertEqual(provider_fingerprint(provider, size), provider_fingerprint(provider, pixels))
                    self.assertNotEqual(provider_fingerprint(provider, size), provider_fingerprint(provider, "1536x1024"))

    def test_comfyui_normalizes_sizes_before_rendering_workflow_dimensions(self):
        provider = self.provider("comfyui")
        workflow = {"1": {"class_type": "EmptyLatentImage", "inputs": {"width": "{{width}}", "height": "{{height}}"}}}
        for size, pixels, dimensions in (("1K", "1024x1024", (1024, 1024)), ("2K", "2048x2048", (2048, 2048)),
                                          ("4K", "2880x2880", (2880, 2880)), ("4096x4096", "4096x4096", (4096, 4096)),
                                          ("1536x1024", "1536x1024", (1536, 1024))):
            with self.subTest(size=size), patch("ficframe.providers.ComfyUIClient") as client, \
                    patch("ficframe.providers.load_api_workflow", return_value=workflow), \
                    patch("ficframe.providers.render_api_workflow", wraps=render_api_workflow) as render:
                provider.image("ABSTRACT", "unused.png", size=size)
                self.assertEqual(render.call_args.kwargs["size"], pixels)
                inputs = client.return_value.generate.call_args.args[0]["1"]["inputs"]
                self.assertEqual((inputs["width"], inputs["height"]), dimensions)
                client.return_value.generate.assert_called_once()

    def test_failed_image_response_preserves_load_error_and_request_id(self):
        for kind in ("openai", "grsai", "ark"):
            with self.subTest(provider=kind), tempfile.TemporaryDirectory() as directory:
                provider = self.provider(kind)
                reference = Path(directory) / "style.png"
                reference.write_bytes(synthetic_png(0))
                target = Path(directory) / "output.png"
                response = {"id": "14-task", "status": "failed", "error": "excessive system load"}
                with patch.object(provider, "_post", return_value=response), patch.object(provider, "_post_multipart", return_value=response):
                    with self.assertRaises(ProviderError) as raised:
                        provider.image("ABSTRACT", target, style_reference_images=[reference])
                self.assertIn("excessive system load", str(raised.exception))
                self.assertIn("14-task", str(raised.exception))
                self.assertFalse(target.exists())

    def test_reference_http_error_keeps_diagnostics_without_echoing_inputs_or_credentials(self):
        provider = self.provider("openai")
        response = httpx.Response(400, json={"error": {"message": "invalid size; private-novel test-key", "code": "invalid_size"},
                                            "request_id": "request-123", "images": ["private-image"], "prompt": "private-novel"})
        with patch("ficframe.providers.httpx.Client") as client:
            client.return_value.__enter__.return_value.post.return_value = response
            for multipart in (False, True):
                with self.subTest(multipart=multipart), self.assertRaises(ProviderError) as raised:
                    if multipart:
                        provider._post_multipart(provider.config.image, "image", "images/edits", {"prompt": "private-novel"},
                                                 [("image", ("ref.png", b"private-image", "image/png"))], purpose="visual_reference:image:single")
                    else:
                        provider._post(provider.config.image, "image", "images/generations", {"prompt": "private-novel"},
                                       purpose="visual_reference:image:single")
                message = str(raised.exception)
                for expected in ("400", "invalid size", "invalid_size", "request-123"):
                    self.assertIn(expected, message)
                for private in ("private-novel", "private-image", "test-key"):
                    self.assertNotIn(private, message)

    def test_cloud_adapters_send_ordered_references_and_do_not_mark_all_as_identity(self):
        for kind in ("openai", "grsai", "ark"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                paths = [Path(directory) / f"{role}.png" for role in ("identity", "style", "composition")]
                for index, path in enumerate(paths):
                    path.write_bytes(synthetic_png(index))
                provider = self.provider(kind)
                response = {"data": [{"b64_json": base64.b64encode(synthetic_png(0)).decode()}]}
                with patch.object(provider, "_post", return_value=response) as post, patch.object(provider, "_post_multipart", return_value=response) as multipart:
                    provider.image("USER BASE", Path(directory) / "output.png", reference_image_groups=[[paths[0]]],
                                   style_reference_images=[paths[1]], composition_reference_images=[paths[2]])
                if kind == "openai":
                    call = multipart.call_args
                    self.assertEqual(call.args[2], "images/edits")
                    prompt = call.args[3]["prompt"]
                    self.assertEqual([file[1][0] for file in call.args[4]], [path.name for path in paths])
                    self.assertEqual([file[1][1] for file in call.args[4]], [path.read_bytes() for path in paths])
                else:
                    payload = post.call_args.args[3]
                    prompt = payload["prompt"]
                    self.assertEqual(payload["images"], ["data:image/png;base64," + base64.b64encode(path.read_bytes()).decode() for path in paths])
                self.assertIn("Images 1-1: character identity", prompt)
                self.assertIn("Images 2-2: drawing style only", prompt)
                self.assertIn("Images 3-3: composition only", prompt)
                self.assertEqual(prompt.count("Reference image roles"), 1)
                self.assertNotIn("Use every supplied reference image as the canonical character design", prompt)

    def test_unsupported_adapters_do_not_upload_visual_images(self):
        for kind in ("siliconflow", "comfyui"):
            provider = self.provider(kind)
            with patch.object(provider, "_post") as post:
                with self.assertRaisesRegex(ProviderError, "不支持"):
                    provider.image("prompt", "unused.png", style_reference_images=[Path("style.png")])
                post.assert_not_called()

    def test_preassembled_roles_are_not_duplicated(self):
        from ficframe.image_reference_workflow import purpose_prompt
        provider = self.provider("openai")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "style.png"
            path.write_bytes(synthetic_png(0))
            response = {"data": [{"b64_json": base64.b64encode(synthetic_png(0)).decode()}]}
            with patch.object(provider, "_post_multipart", return_value=response) as post:
                provider.image(purpose_prompt("BASE", 0, 1, 0), Path(directory) / "output.png",
                               style_reference_images=[path], reference_roles_embedded=True)
            self.assertEqual(post.call_args.args[3]["prompt"].count("Reference image roles"), 1)

    def test_multipart_visual_logs_do_not_echo_vendor_contents(self):
        provider = self.provider("openai")
        response = httpx.Response(400, json={"error": "private-novel private-image private-key"})
        with patch("ficframe.providers.httpx.Client") as client, patch("ficframe.providers.logger") as logger:
            client.return_value.__enter__.return_value.post.return_value = response
            with self.assertRaises(ProviderError):
                provider._post_multipart(provider.config.image, "image", "images/edits", {"prompt": "private-novel"},
                                         [("image", ("ref.png", b"private-image", "image/png"))], purpose="visual_reference:image:single")
        logs = str(logger.mock_calls)
        for private in ("private-novel", "private-image", "private-key"):
            self.assertNotIn(private, logs)
