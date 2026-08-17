from __future__ import annotations

import unittest
from unittest.mock import patch

from ficframe.providers import (
    EndpointConfig,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderConfig,
    extract_response_text,
    llm_runtime_path,
)


class DeepSeekResponsesTests(unittest.TestCase):
    def _provider(self) -> OpenAICompatibleProvider:
        config = ProviderConfig(
            llm=EndpointConfig(
                api_key="test-key",
                base_url="https://api.deepseek.com",
                model="deepseek-v4-flash",
                provider="deepseek",
            ),
            image=EndpointConfig(),
            vlm=EndpointConfig(),
        )
        return OpenAICompatibleProvider(config)

    def test_deepseek_prefers_responses_with_high_reasoning(self) -> None:
        provider = self._provider()
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": '{"ok": true}'}],
                }
            ]
        }

        with patch.object(provider, "_post", return_value=response) as post:
            text = provider.text("system", "user", purpose="test")

        endpoint, label, path, payload = post.call_args.args
        self.assertEqual(endpoint, provider.config.llm)
        self.assertEqual(label, "llm")
        self.assertEqual(path, "responses")
        self.assertEqual(payload["reasoning"], {"effort": "high"})
        self.assertEqual(text, '{"ok": true}')
        self.assertEqual(llm_runtime_path(provider.config.llm), "responses")

    def test_deepseek_falls_back_to_chat_when_responses_is_unsupported(self) -> None:
        provider = self._provider()
        chat_response = {
            "choices": [
                {
                    "message": {
                        "reasoning_content": "private chain of thought",
                        "content": '{"ok": true}',
                    }
                }
            ]
        }

        with patch.object(
            provider,
            "_post",
            side_effect=[ProviderError("404 https://api.deepseek.com/responses: not found"), chat_response],
        ) as post:
            text = provider.text("system", "user", purpose="test")

        self.assertEqual([call.args[2] for call in post.call_args_list], ["responses", "chat/completions"])
        fallback_payload = post.call_args_list[1].args[3]
        self.assertEqual(fallback_payload["reasoning_effort"], "high")
        self.assertEqual(fallback_payload["thinking"], {"type": "enabled"})
        self.assertEqual(text, '{"ok": true}')

    def test_deepseek_does_not_retry_chat_after_timeout(self) -> None:
        provider = self._provider()
        with patch.object(provider, "_post", side_effect=ProviderError("llm 请求超时（300s）。")) as post:
            with self.assertRaises(ProviderError):
                provider.text("system", "user", purpose="test")

        post.assert_called_once()

    def test_response_parser_ignores_reasoning_items(self) -> None:
        data = {
            "output": [
                {
                    "type": "reasoning",
                    "content": [{"type": "reasoning_text", "text": "private chain of thought"}],
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "final answer"}],
                },
            ]
        }

        self.assertEqual(extract_response_text(data), "final answer")


if __name__ == "__main__":
    unittest.main()
