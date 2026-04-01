from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from digital_employee.domain.approval import ApprovalRequest
from digital_employee.domain.employee_profile import EmployeeProfile
from digital_employee.domain.errors import BudgetExceededError, HookBlockedError
from digital_employee.memory.context_compactor import ContextCompactor
from digital_employee.policy.engine import PolicyEngine
from digital_employee.providers.mock_provider import MockProvider
from digital_employee.providers.models import CompletionRequest, CompletionResult
from digital_employee.providers.openai_provider import OpenAIProvider
from digital_employee.providers.router import ProviderRouter
from digital_employee.runtime.hooks import HookDispatcher, HookPoint
from digital_employee.runtime.turn_engine import TurnEngine
from digital_employee.tools.exposure import ToolExposurePlanner
from digital_employee.tools.registry import build_tool_registry


class _ToolCallingProvider:
    name = "mock"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        if request.metadata["tool_observations"]:
            return CompletionResult(
                text="Done after using knowledge-search",
                usage={"input_tokens": 2, "output_tokens": 5},
            )
        return CompletionResult(
            text="Need a tool before answering",
            tool_calls=[
                {
                    "tool_name": "knowledge-search",
                    "payload": {"query": "upsell playbook", "scope": "sales-playbook"},
                }
            ],
            usage={"input_tokens": 2, "output_tokens": 4},
        )


class _ExpensiveProvider:
    name = "mock"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        return CompletionResult(text="Too expensive", usage={"input_tokens": 100})


class _CapturingProvider:
    name = "mock"

    def __init__(self) -> None:
        self.requests: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        return CompletionResult(text="Captured", usage={"input_tokens": 2, "output_tokens": 1})


class _ApprovalToolProvider:
    name = "mock"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        if request.metadata["tool_observations"]:
            return CompletionResult(text="Done after approval", usage={"input_tokens": 2, "output_tokens": 3})
        return CompletionResult(
            text="Need approval before sending email",
            tool_calls=[
                {
                    "tool_name": "send-email",
                    "payload": {"recipient": "a@example.com", "subject": "Follow up"},
                }
            ],
            usage={"input_tokens": 2, "output_tokens": 5},
        )


class _InMemoryApprovalRepo:
    def __init__(self) -> None:
        self._items: dict[str, ApprovalRequest] = {}

    def create(self, approval: ApprovalRequest) -> ApprovalRequest:
        self._items[approval.approval_id] = approval
        return approval

    def save(self, approval: ApprovalRequest) -> ApprovalRequest:
        self._items[approval.approval_id] = approval
        return approval

    def get(self, approval_id: str) -> ApprovalRequest | None:
        return self._items.get(approval_id)

    def list_all(self) -> list[ApprovalRequest]:
        return list(self._items.values())


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class _SequencedURLRecorder:
    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = list(payloads)
        self.requests: list[dict] = []

    def __call__(self, request, timeout=0):
        del timeout
        self.requests.append(json.loads(request.data.decode("utf-8")))
        return _FakeHTTPResponse(self._payloads.pop(0))


class TurnEngineTest(unittest.TestCase):
    def _build_engine(self, provider_factory, tool_names: list[str]) -> TurnEngine:
        return TurnEngine(
            provider_router=ProviderRouter({"mock": provider_factory}),
            tool_registry=build_tool_registry(tool_names),
            hook_dispatcher=HookDispatcher(),
            approval_repo=_InMemoryApprovalRepo(),
            policy_engine=PolicyEngine(),
            default_budget_tokens=40,
        )

    def _build_profile(self) -> EmployeeProfile:
        return EmployeeProfile(
            employee_id="sales-assistant",
            display_name="Sales Assistant",
            default_provider="mock",
            approval_policy="manual",
            skill_packs=["customer-followup"],
            allowed_tools=["knowledge-search", "send-email"],
            knowledge_scopes=["sales-playbook"],
        )

    def test_turn_engine_uses_provider_router_and_tracks_budget(self) -> None:
        engine = self._build_engine(lambda: MockProvider(), ["knowledge-search", "send-email"])
        result = asyncio.run(
            engine.run(
                profile=self._build_profile(),
                prompt="Plan outreach",
                budget_tokens=40,
            )
        )
        self.assertIn("Plan outreach", result.output_text)
        self.assertEqual(result.provider_name, "mock")
        self.assertGreater(result.budget_used, 0)
        self.assertEqual(result.turns, 1)
        self.assertEqual(result.events[0].event_type, "turn.started")
        self.assertTrue(result.session_id.startswith("ses_"))
        self.assertEqual(result.compaction_strategy, "none")

    def test_turn_engine_executes_tool_calls(self) -> None:
        engine = self._build_engine(lambda: _ToolCallingProvider(), ["knowledge-search"])
        result = asyncio.run(
            engine.run(
                profile=self._build_profile(),
                prompt="Find an upsell angle",
                budget_tokens=40,
            )
        )
        self.assertEqual(result.turns, 2)
        self.assertEqual(len(result.tool_observations), 1)
        self.assertEqual(result.tool_observations[0].tool_name, "knowledge-search")
        self.assertIn("Done after using knowledge-search", result.output_text)
        self.assertIn("tool.executed", [event.event_type for event in result.events])
        self.assertIn("knowledge-search", result.exposed_tools)

    def test_hook_can_block_tool_use(self) -> None:
        dispatcher = HookDispatcher()

        def _block_tool(context) -> None:
            if context.hook_point == HookPoint.PRE_TOOL_USE:
                context.blocked = True

        dispatcher.on(HookPoint.PRE_TOOL_USE, _block_tool)
        engine = TurnEngine(
            provider_router=ProviderRouter({"mock": lambda: _ToolCallingProvider()}),
            tool_registry=build_tool_registry(["knowledge-search"]),
            hook_dispatcher=dispatcher,
            approval_repo=_InMemoryApprovalRepo(),
            policy_engine=PolicyEngine(),
            default_budget_tokens=40,
        )
        with self.assertRaises(HookBlockedError):
            asyncio.run(
                engine.run(
                    profile=self._build_profile(),
                    prompt="Find an upsell angle",
                    budget_tokens=40,
                )
            )

    def test_budget_exceeded_raises(self) -> None:
        engine = self._build_engine(lambda: _ExpensiveProvider(), [])
        with self.assertRaises(BudgetExceededError):
            asyncio.run(
                engine.run(
                    profile=self._build_profile(),
                    prompt="Short task",
                    budget_tokens=5,
                )
            )

    def test_turn_engine_applies_compaction_and_progressive_tool_disclosure(self) -> None:
        provider = _CapturingProvider()
        engine = TurnEngine(
            provider_router=ProviderRouter({"mock": lambda: provider}),
            tool_registry=build_tool_registry(["knowledge-search", "send-email"]),
            hook_dispatcher=HookDispatcher(),
            approval_repo=_InMemoryApprovalRepo(),
            policy_engine=PolicyEngine(),
            default_budget_tokens=40,
            context_compactor=ContextCompactor(max_context_tokens=3, recent_message_window=1, compaction_target_tokens=8),
            tool_exposure_planner=ToolExposurePlanner(max_tools_per_turn=4),
        )
        profile = self._build_profile()
        result = asyncio.run(
            engine.run(
                profile=profile,
                prompt="Summarize the sales playbook and customer notes for follow-up planning",
                budget_tokens=40,
            )
        )
        request = provider.requests[0]
        self.assertEqual(result.compaction_strategy, "autocompact")
        self.assertEqual(request.metadata["context_compaction"]["strategy"], "autocompact")
        self.assertEqual(request.metadata["allowed_tools"], ["knowledge-search"])
        self.assertIn("send-email", request.metadata["hidden_tools"])

    def test_turn_engine_pauses_when_tool_requires_approval(self) -> None:
        approval_repo = _InMemoryApprovalRepo()
        engine = TurnEngine(
            provider_router=ProviderRouter({"mock": lambda: _ApprovalToolProvider()}),
            tool_registry=build_tool_registry(["send-email"]),
            hook_dispatcher=HookDispatcher(),
            approval_repo=approval_repo,
            policy_engine=PolicyEngine(),
            default_budget_tokens=40,
        )
        result = asyncio.run(
            engine.run(
                profile=self._build_profile(),
                prompt="Send email to a@example.com about the renewal",
                work_order_id="wo_test",
                budget_tokens=40,
            )
        )
        self.assertEqual(result.status, "waiting_approval")
        self.assertEqual(result.session.current_stage, "waiting_approval")
        self.assertEqual(result.session.status, "paused")
        self.assertEqual(len(approval_repo.list_all()), 1)
        self.assertIn("approval.requested", [event.event_type for event in result.events])

    def test_openai_provider_uses_structured_history_for_second_turn(self) -> None:
        provider = OpenAIProvider(
            base_url="https://openai.example.test/v1",
            api_key_env="TEST_OPENAI_KEY",
            model="gpt-test",
        )
        recorder = _SequencedURLRecorder(
            [
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call_abc",
                                        "type": "function",
                                        "function": {
                                            "name": "knowledge-search",
                                            "arguments": "{\"query\":\"upsell playbook\",\"scope\":\"sales-playbook\"}",
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 4},
                },
                {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "Done after using knowledge-search."},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            ]
        )
        engine = TurnEngine(
            provider_router=ProviderRouter({"openai": lambda: provider}),
            tool_registry=build_tool_registry(["knowledge-search"]),
            hook_dispatcher=HookDispatcher(),
            approval_repo=_InMemoryApprovalRepo(),
            policy_engine=PolicyEngine(),
            default_budget_tokens=40,
        )
        profile = EmployeeProfile(
            employee_id="sales-assistant",
            display_name="Sales Assistant",
            default_provider="openai",
            approval_policy="manual",
            skill_packs=["customer-followup"],
            allowed_tools=["knowledge-search"],
            knowledge_scopes=["sales-playbook"],
        )

        with patch.dict(os.environ, {"TEST_OPENAI_KEY": "sk-test"}, clear=False):
            with patch("urllib.request.urlopen", side_effect=recorder):
                result = asyncio.run(
                    engine.run(
                        profile=profile,
                        prompt="Find an upsell angle",
                        budget_tokens=40,
                    )
                )

        self.assertEqual(result.output_text, "Done after using knowledge-search.")
        self.assertEqual(result.turns, 2)
        self.assertEqual(len(recorder.requests), 2)
        second_messages = recorder.requests[1]["messages"]
        assistant_messages = [item for item in second_messages if item["role"] == "assistant"]
        tool_messages = [item for item in second_messages if item["role"] == "tool"]
        self.assertTrue(assistant_messages)
        self.assertEqual(assistant_messages[-1]["tool_calls"][0]["id"], "call_abc")
        self.assertTrue(tool_messages)
        self.assertEqual(tool_messages[-1]["tool_call_id"], "call_abc")
        self.assertNotIn(
            True,
            ["Previous completion:" in str(item.get("content", "")) for item in second_messages],
        )


if __name__ == "__main__":
    unittest.main()
