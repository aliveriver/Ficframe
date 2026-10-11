from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from ficframe.image_reference_workflow import synthetic_png
from ficframe.providers import EndpointConfig, OpenAICompatibleProvider, ProviderConfig, ProviderError


class ImageReferenceProviderTests(unittest.TestCase):
    def provider(self, kind):
        return OpenAICompatibleProvider(ProviderConfig(llm=EndpointConfig(), vlm=EndpointConfig(),
            image=EndpointConfig(provider=kind, model="test-model", api_key="test-key", base_url="https://fake.invalid/v1")))

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
