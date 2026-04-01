"""OpenAI provider implementation using stdlib urllib."""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any

from digital_employee.domain.errors import ProviderExecutionError
from digital_employee.providers.models import CompletionRequest, CompletionResult


_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider:
    def __init__(
        self,
        name: str = "openai",
        model: str = "gpt-4o",
        timeout_seconds: int = 30,
        max_output_tokens: int = 4096,
        api_key_env: str = "OPENAI_API_KEY",
        base_url: str | None = None,
    ) -> None:
        self.name = name
        self._model = model
        self._timeout = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._api_key_env = api_key_env
        self._base_url = (base_url or os.getenv("OPENAI_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        api_key = os.getenv(self._api_key_env)
        if not api_key:
            raise ProviderExecutionError(
                self.name,
                f"environment variable {self._api_key_env} is not set",
                hint=f"export {self._api_key_env}=sk-...",
            )

        messages = self._build_messages(request)
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_completion_tokens": self._max_output_tokens,
        }

        tools = self._build_tools(request)
        if tools:
            body["tools"] = tools

        try:
            raw = await asyncio.to_thread(self._post, f"{self._base_url}/chat/completions", body, api_key)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise ProviderExecutionError(
                self.name,
                f"HTTP {exc.code}: {detail[:200]}",
                hint="check API key and model availability",
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderExecutionError(
                self.name,
                f"connection failed: {exc.reason}",
                hint="check network connectivity and OPENAI_BASE_URL",
            ) from exc

        return self._parse_response(raw)

    def _build_messages(self, request: CompletionRequest) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if request.system:
            messages.append({"role": "developer", "content": request.system})

        compaction = request.metadata.get("context_compaction", {})
        if isinstance(compaction, dict):
            summary = str(compaction.get("summary") or "").strip()
            if summary:
                messages.append({"role": "developer", "content": f"Conversation summary: {summary}"})

        recent_context = request.metadata.get("recent_context", [])
        history_messages = self._build_history_messages(recent_context)
        if history_messages:
            messages.extend(history_messages)
        elif request.prompt:
            messages.append({"role": "user", "content": request.prompt})

        if not history_messages:
            tool_observations = request.metadata.get("tool_observations", [])
            for obs in tool_observations:
                tool_name = obs.get("tool_name", "unknown")
                payload_text = str(obs.get("payload", ""))
                messages.append({"role": "developer", "content": f"Tool result from {tool_name}: {payload_text}"})

        return messages

    def _build_tools(self, request: CompletionRequest) -> list[dict[str, Any]]:
        exposed = request.metadata.get("exposed_tools", [])
        tools: list[dict[str, Any]] = []
        for item in exposed:
            if isinstance(item, dict) and "name" in item:
                tool_def: dict[str, Any] = {
                    "type": "function",
                    "function": {
                        "name": item["name"],
                        "description": item.get("description", ""),
                    },
                }
                if "input_schema" in item and item["input_schema"]:
                    tool_def["function"]["parameters"] = item["input_schema"]
                tools.append(tool_def)
        return tools

    def _post(self, url: str, body: dict, api_key: str) -> dict:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _parse_response(self, raw: dict) -> CompletionResult:
        choice = raw.get("choices", [{}])[0]
        message = choice.get("message", {})
        text = self._extract_text_content(message.get("content"))
        stop_reason = choice.get("finish_reason", "stop")

        tool_calls: list[dict[str, Any]] = []
        for tc in message.get("tool_calls", []):
            fn = tc.get("function", {})
            try:
                payload = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                payload = {"raw": fn.get("arguments", "")}
            tool_calls.append({
                "tool_call_id": tc.get("id", ""),
                "tool_name": fn.get("name", "unknown"),
                "payload": payload,
            })

        usage_raw = raw.get("usage", {})
        usage = {
            "input_tokens": usage_raw.get("prompt_tokens", 0),
            "output_tokens": usage_raw.get("completion_tokens", 0),
        }

        return CompletionResult(
            text=text,
            tool_calls=tool_calls,
            usage=usage,
            stop_reason="tool_use" if tool_calls else stop_reason,
        )

    def _extract_text_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""

        text_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text_value = item.get("text")
                if isinstance(text_value, str):
                    text_parts.append(text_value)
                    continue
            text_value = item.get("content")
            if isinstance(text_value, str):
                text_parts.append(text_value)
        return "\n".join(part for part in text_parts if part)

    def _build_history_messages(self, recent_context: Any) -> list[dict[str, Any]]:
        if not isinstance(recent_context, list):
            return []

        messages: list[dict[str, Any]] = []
        pending_tool_calls: dict[str, list[str]] = {}
        generated_count = 0

        for item in recent_context:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "")
            metadata = item.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}

            if role in {"system", "developer"}:
                if content:
                    messages.append({"role": "developer", "content": content})
                continue

            if role == "user":
                if content:
                    messages.append({"role": "user", "content": content})
                continue

            if role == "assistant":
                assistant_message: dict[str, Any] = {"role": "assistant", "content": content}
                raw_tool_calls = metadata.get("tool_calls")
                assistant_tool_calls = self._build_assistant_tool_calls(
                    raw_tool_calls,
                    pending_tool_calls=pending_tool_calls,
                    generated_count_start=generated_count,
                )
                generated_count += len(assistant_tool_calls)
                if assistant_tool_calls:
                    assistant_message["tool_calls"] = assistant_tool_calls
                if content or assistant_tool_calls:
                    messages.append(assistant_message)
                continue

            if role == "tool":
                tool_name = str(metadata.get("tool_name") or "tool")
                tool_call_id = str(metadata.get("tool_call_id") or "")
                if not tool_call_id:
                    queue = pending_tool_calls.get(tool_name, [])
                    if queue:
                        tool_call_id = queue.pop(0)
                if tool_call_id:
                    messages.append(
                        {
                            "role": "tool",
                            "content": content,
                            "tool_call_id": tool_call_id,
                        }
                    )
                elif content:
                    messages.append({"role": "developer", "content": f"Tool {tool_name} result: {content}"})

        return messages

    def _build_assistant_tool_calls(
        self,
        raw_tool_calls: Any,
        *,
        pending_tool_calls: dict[str, list[str]],
        generated_count_start: int,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_tool_calls, list):
            return []

        tool_calls: list[dict[str, Any]] = []
        generated_count = generated_count_start
        for raw_call in raw_tool_calls:
            if not isinstance(raw_call, dict):
                continue
            tool_name = str(raw_call.get("tool_name") or raw_call.get("name") or "unknown")
            payload = dict(raw_call.get("payload") or raw_call.get("input") or {})
            tool_call_id = str(raw_call.get("tool_call_id") or raw_call.get("id") or "")
            if not tool_call_id:
                generated_count += 1
                tool_call_id = f"call_history_{generated_count}"
            pending_tool_calls.setdefault(tool_name, []).append(tool_call_id)
            tool_calls.append(
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(payload, separators=(",", ":"), ensure_ascii=True),
                    },
                }
            )
        return tool_calls
