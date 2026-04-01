"""Tests for the OpenAI provider."""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from digital_employee.domain.errors import ProviderExecutionError
from digital_employee.providers.models import CompletionRequest
from digital_employee.providers.openai_provider import OpenAIProvider


def _make_chat_response(
    content: str | list[dict] = "Hello!",
    tool_calls: list | None = None,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"message": message, "finish_reason": "stop" if not tool_calls else "tool_calls"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class _URLRecorder:
    def __init__(self, *, response_body: dict | None = None, error: Exception | None = None) -> None:
        self._response_body = response_body or _make_chat_response()
        self._error = error
        self.last_request = None
        self.last_timeout = None

    def __call__(self, request, timeout=0):
        self.last_request = request
        self.last_timeout = timeout
        if self._error is not None:
            raise self._error
        return _FakeHTTPResponse(self._response_body)

    def body(self) -> dict:
        if self.last_request is None or self.last_request.data is None:
            return {}
        return json.loads(self.last_request.data.decode("utf-8"))


class OpenAIProviderTest(unittest.TestCase):
    def _provider(self, **kwargs) -> OpenAIProvider:
        return OpenAIProvider(
            base_url="https://openai.example.test/v1",
            api_key_env="TEST_OPENAI_KEY",
            **kwargs,
        )

    def test_missing_api_key_raises(self):
        provider = self._provider()
        request = CompletionRequest(system="test", prompt="hi")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ProviderExecutionError) as ctx:
                asyncio.run(provider.complete(request))
            self.assertIn("TEST_OPENAI_KEY", ctx.exception.message)

    def test_basic_completion_uses_latest_chat_payload_fields(self):
        recorder = _URLRecorder(
            response_body=_make_chat_response(
                content=[{"type": "text", "text": "Mock reply"}],
                prompt_tokens=8,
                completion_tokens=3,
            )
        )
        provider = self._provider(model="gpt-test", max_output_tokens=333)
        request = CompletionRequest(system="You are helpful.", prompt="Say hi")

        with patch.dict(os.environ, {"TEST_OPENAI_KEY": "sk-test"}, clear=False):
            with patch("urllib.request.urlopen", side_effect=recorder):
                result = asyncio.run(provider.complete(request))

        payload = recorder.body()
        self.assertEqual(result.text, "Mock reply")
        self.assertEqual(result.usage["input_tokens"], 8)
        self.assertEqual(result.usage["output_tokens"], 3)
        self.assertEqual(result.tool_calls, [])
        self.assertEqual(payload["model"], "gpt-test")
        self.assertEqual(payload["max_completion_tokens"], 333)
        self.assertEqual(payload["messages"][0]["role"], "developer")
        self.assertEqual(payload["messages"][1]["role"], "user")
        self.assertEqual(recorder.last_timeout, provider._timeout)
        self.assertEqual(recorder.last_request.get_header("Authorization"), "Bearer sk-test")

    def test_tool_call_response(self):
        recorder = _URLRecorder(
            response_body=_make_chat_response(
                content="I'll send the email.",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "send-email",
                            "arguments": '{"recipient":"a@b.com","subject":"Hi"}',
                        },
                    }
                ],
            )
        )
        provider = self._provider()
        request = CompletionRequest(
            system="test",
            prompt="Send email",
            metadata={
                "exposed_tools": [
                    {
                        "name": "send-email",
                        "description": "Send an email",
                        "input_schema": {
                            "type": "object",
                            "properties": {"recipient": {"type": "string"}},
                        },
                    }
                ],
            },
        )

        with patch.dict(os.environ, {"TEST_OPENAI_KEY": "sk-test"}, clear=False):
            with patch("urllib.request.urlopen", side_effect=recorder):
                result = asyncio.run(provider.complete(request))

        payload = recorder.body()
        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0]["tool_call_id"], "call_1")
        self.assertEqual(result.tool_calls[0]["tool_name"], "send-email")
        self.assertEqual(result.tool_calls[0]["payload"]["recipient"], "a@b.com")
        self.assertEqual(result.stop_reason, "tool_use")
        self.assertTrue(payload.get("tools"))
        self.assertEqual(payload["tools"][0]["function"]["parameters"]["type"], "object")

    def test_recent_context_and_compaction_summary_are_sent_as_structured_messages(self):
        recorder = _URLRecorder(response_body=_make_chat_response(content="Done."))
        provider = self._provider()
        request = CompletionRequest(
            system="test",
            prompt="ignored when recent context exists",
            metadata={
                "context_compaction": {
                    "strategy": "autocompact",
                    "summary": "User requested a follow-up plan and a knowledge lookup already ran.",
                },
                "recent_context": [
                    {"role": "user", "content": "Find an upsell angle", "metadata": {}},
                    {
                        "role": "assistant",
                        "content": "Need to search first.",
                        "metadata": {
                            "tool_calls": [
                                {
                                    "tool_name": "knowledge-search",
                                    "payload": {"query": "upsell playbook"},
                                    "tool_call_id": "call_42",
                                }
                            ]
                        },
                    },
                    {
                        "role": "tool",
                        "content": "{\"matches\": [\"renewal script\"]}",
                        "metadata": {
                            "tool_name": "knowledge-search",
                            "tool_call_id": "call_42",
                        },
                    },
                ],
            },
        )

        with patch.dict(os.environ, {"TEST_OPENAI_KEY": "sk-test"}, clear=False):
            with patch("urllib.request.urlopen", side_effect=recorder):
                asyncio.run(provider.complete(request))

        messages = recorder.body()["messages"]
        self.assertEqual(messages[0]["role"], "developer")
        self.assertIn("Conversation summary:", messages[1]["content"])
        self.assertEqual(messages[2]["role"], "user")
        self.assertEqual(messages[3]["role"], "assistant")
        self.assertEqual(messages[3]["tool_calls"][0]["id"], "call_42")
        self.assertEqual(messages[4]["role"], "tool")
        self.assertEqual(messages[4]["tool_call_id"], "call_42")
        self.assertNotIn("ignored when recent context exists", [item.get("content") for item in messages])

    def test_tool_observations_included_in_messages(self):
        recorder = _URLRecorder(response_body=_make_chat_response(content="Done."))
        provider = self._provider()
        request = CompletionRequest(
            system="test",
            prompt="Continue",
            metadata={
                "tool_observations": [
                    {"tool_name": "search", "payload": {"results": 3}},
                ],
            },
        )

        with patch.dict(os.environ, {"TEST_OPENAI_KEY": "sk-test"}, clear=False):
            with patch("urllib.request.urlopen", side_effect=recorder):
                asyncio.run(provider.complete(request))

        messages = recorder.body()["messages"]
        self.assertEqual(len(messages), 3)
        self.assertIn("search", messages[2]["content"])

    def test_http_error_maps_to_provider_error(self):
        error = urllib.error.HTTPError(
            url="https://openai.example.test/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"error":{"message":"bad key"}}'),
        )
        recorder = _URLRecorder(error=error)
        provider = self._provider()
        request = CompletionRequest(system="test", prompt="hi")

        with patch.dict(os.environ, {"TEST_OPENAI_KEY": "sk-test"}, clear=False):
            with patch("urllib.request.urlopen", side_effect=recorder):
                with self.assertRaises(ProviderExecutionError) as ctx:
                    asyncio.run(provider.complete(request))

        self.assertIn("HTTP 401", ctx.exception.message)
        self.assertIn("check API key", ctx.exception.hint or "")

    def test_connection_error_maps_to_provider_error(self):
        recorder = _URLRecorder(error=urllib.error.URLError("network down"))
        provider = self._provider()
        request = CompletionRequest(system="test", prompt="hi")

        with patch.dict(os.environ, {"TEST_OPENAI_KEY": "sk-test"}, clear=False):
            with patch("urllib.request.urlopen", side_effect=recorder):
                with self.assertRaises(ProviderExecutionError) as ctx:
                    asyncio.run(provider.complete(request))

        self.assertIn("connection failed", ctx.exception.message)
        self.assertIn("OPENAI_BASE_URL", ctx.exception.hint or "")

    def test_complete_offloads_blocking_http_work(self):
        provider = self._provider()
        request = CompletionRequest(system="test", prompt="hi")

        def _slow_post(*args, **kwargs):
            time.sleep(0.05)
            return _make_chat_response(content="Delayed.")

        async def _run() -> None:
            with patch.dict(os.environ, {"TEST_OPENAI_KEY": "sk-test"}, clear=False):
                with patch.object(provider, "_post", side_effect=_slow_post):
                    task = asyncio.create_task(provider.complete(request))
                    await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.02)
                    await task

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
