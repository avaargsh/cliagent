"""Turn pipeline orchestration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from digital_employee.contracts.repositories import ApprovalRepository
from digital_employee.domain.approval import ApprovalRequest
from digital_employee.domain.employee_profile import EmployeeProfile
from digital_employee.domain.errors import (
    DigitalEmployeeError,
    HookBlockedError,
    ToolExecutionError,
    ToolNotAllowedError,
)
from digital_employee.domain.enums import SessionStatus
from digital_employee.domain.session import ConversationSession, generate_session_id
from digital_employee.memory.context_compactor import ContextCompactor
from digital_employee.policy.engine import PolicyEngine
from digital_employee.runtime.hooks import HookContext, HookDispatcher, HookPoint
from digital_employee.runtime.turn.action_interpreter import ActionInterpreter
from digital_employee.runtime.turn.budget_controller import BudgetController
from digital_employee.runtime.turn.context_assembler import ContextAssembler
from digital_employee.runtime.turn.model_gateway import ModelGateway
from digital_employee.runtime.turn.result_mapper import ResultMapper, TurnRunResult
from digital_employee.runtime.turn.session_recorder import SessionRecorder
from digital_employee.tools.exposure import ToolExposurePlanner
from digital_employee.tools.executor import ToolExecutor
from digital_employee.tools.registry import ToolRegistry


class TurnEngine:
    def __init__(
        self,
        *,
        provider_router,
        tool_registry: ToolRegistry,
        hook_dispatcher: HookDispatcher,
        approval_repo: ApprovalRepository,
        policy_engine: PolicyEngine,
        tool_executor: ToolExecutor | None = None,
        default_budget_tokens: int,
        context_compactor: ContextCompactor | None = None,
        tool_exposure_planner: ToolExposurePlanner | None = None,
        max_turns: int = 4,
    ) -> None:
        self._tool_registry = tool_registry
        self._hook_dispatcher = hook_dispatcher
        self._approval_repo = approval_repo
        self._policy_engine = policy_engine
        self._max_turns = max_turns
        self._context_assembler = ContextAssembler(
            context_compactor=context_compactor or ContextCompactor(),
            tool_exposure_planner=tool_exposure_planner or ToolExposurePlanner(),
            tool_registry=tool_registry,
            policy_engine=policy_engine,
        )
        self._budget_controller = BudgetController(default_budget_tokens=default_budget_tokens)
        self._model_gateway = ModelGateway(provider_router=provider_router)
        self._action_interpreter = ActionInterpreter()
        self._session_recorder = SessionRecorder()
        self._result_mapper = ResultMapper()
        self._tool_executor = tool_executor or ToolExecutor()

    async def run(
        self,
        *,
        profile: EmployeeProfile,
        prompt: str,
        work_order_id: str | None = None,
        budget_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
        session: ConversationSession | None = None,
        progress_callback: Callable[[ConversationSession, list], None] | None = None,
    ) -> TurnRunResult:
        provider_name = profile.default_provider
        budget = self._budget_controller.start(budget_tokens)
        tool_observations = []
        events = []
        current_prompt = prompt
        current_exposed_tools = [tool.name for tool in self._tool_registry.filter_by_names(profile.allowed_tools)]
        compaction_strategy = "none"
        last_result = None
        session = session or ConversationSession(session_id=generate_session_id(), work_order_id=work_order_id)
        session.work_order_id = work_order_id
        session.employee_id = profile.employee_id
        session.status = SessionStatus.STREAMING.value
        session.current_stage = "planning"
        if not session.messages:
            session.add_message("user", prompt, {"employee_id": profile.employee_id})

        self._session_recorder.record_event(
            events,
            event_type="turn.started",
            work_order_id=work_order_id,
            payload={
                "employee_id": profile.employee_id,
                "provider": provider_name,
                "budget_tokens": budget.total_tokens,
                "session_id": session.session_id,
            },
        )
        self._session_recorder.publish_progress(session, events, progress_callback)
        self._dispatch(
            HookPoint.TURN_START,
            work_order_id=work_order_id,
            payload={
                "employee_id": profile.employee_id,
                "provider": provider_name,
                "budget_tokens": budget.total_tokens,
            },
        )

        turns = 0
        for turn_index in range(1, self._max_turns + 1):
            turns = turn_index
            packet = self._context_assembler.assemble(
                profile=profile,
                prompt=current_prompt,
                session=session,
                turn_index=turn_index,
                budget_remaining=budget.remaining_tokens,
                tool_observations=tool_observations,
                session_id=session.session_id,
                extra_metadata=metadata,
            )
            compaction_strategy = packet.prepared_context.strategy
            current_exposed_tools = [tool.name for tool in packet.exposure_plan.exposed_tools]
            session.current_stage = "planning" if not tool_observations else "executing"
            self._session_recorder.record_event(
                events,
                event_type="tools.exposed",
                work_order_id=work_order_id,
                turn_index=turn_index,
                payload={
                    "strategy": packet.exposure_plan.strategy,
                    "exposed_tools": current_exposed_tools,
                    "hidden_tools": packet.exposure_plan.hidden_tools,
                },
            )
            self._session_recorder.publish_progress(session, events, progress_callback)
            if packet.prepared_context.strategy != "none":
                self._session_recorder.record_event(
                    events,
                    event_type="context.compacted",
                    work_order_id=work_order_id,
                    turn_index=turn_index,
                    payload=asdict(packet.prepared_context),
                )
                self._session_recorder.publish_progress(session, events, progress_callback)

            completion_payload = self._dispatch(
                HookPoint.PRE_COMPLETION,
                work_order_id=work_order_id,
                payload={
                    "prompt": current_prompt,
                    "provider": provider_name,
                    "metadata": packet.request_metadata,
                    "turn_index": turn_index,
                },
            )
            provider_name, last_result = await self._model_gateway.complete(
                profile=profile,
                prompt=str(completion_payload.get("prompt", current_prompt)),
                metadata=dict(completion_payload.get("metadata", packet.request_metadata)),
                turn_index=turn_index,
            )
            structured_tool_calls = self._ensure_tool_call_ids(last_result.tool_calls, turn_index=turn_index)

            snapshot = self._budget_controller.consume(
                budget,
                self._action_interpreter.usage_tokens(last_result),
            )
            if self._budget_controller.should_warn(snapshot):
                self._session_recorder.record_event(
                    events,
                    event_type="budget.warning",
                    work_order_id=work_order_id,
                    turn_index=turn_index,
                    payload=asdict(snapshot),
                )
                self._session_recorder.publish_progress(session, events, progress_callback)
                self._dispatch(
                    HookPoint.BUDGET_WARNING,
                    work_order_id=work_order_id,
                    payload=asdict(snapshot),
                    raise_if_blocked=False,
                )

            self._session_recorder.record_event(
                events,
                event_type="completion.completed",
                work_order_id=work_order_id,
                turn_index=turn_index,
                payload={
                    "provider": provider_name,
                    "usage": dict(last_result.usage),
                    "tool_calls": list(structured_tool_calls),
                },
            )
            assistant_metadata = {
                "provider": provider_name,
                "turn_index": turn_index,
            }
            if structured_tool_calls:
                assistant_metadata["tool_calls"] = list(structured_tool_calls)
            session.add_message(
                "assistant",
                last_result.text,
                assistant_metadata,
            )
            self._session_recorder.publish_progress(session, events, progress_callback)
            self._dispatch(
                HookPoint.POST_COMPLETION,
                work_order_id=work_order_id,
                payload={
                    "provider": provider_name,
                    "text": last_result.text,
                    "usage": dict(last_result.usage),
                    "tool_calls": list(structured_tool_calls),
                    "turn_index": turn_index,
                },
                raise_if_blocked=False,
            )

            if not structured_tool_calls:
                break

            for raw_call in structured_tool_calls:
                tool_call = self._action_interpreter.normalize_tool_call(raw_call)
                if tool_call.tool_name not in profile.allowed_tools:
                    raise ToolNotAllowedError(profile.employee_id, tool_call.tool_name)
                tool_payload = self._dispatch(
                    HookPoint.PRE_TOOL_USE,
                    work_order_id=work_order_id,
                    payload={
                        "tool_name": tool_call.tool_name,
                        "payload": dict(tool_call.payload),
                        "turn_index": turn_index,
                    },
                )
                normalized_call = self._action_interpreter.normalize_tool_call(tool_payload)
                definition = self._tool_registry.require(normalized_call.tool_name)
                policy_decision = self._policy_engine.evaluate_tool_use(profile, definition)
                if policy_decision.requires_approval:
                    approved_request = self._find_approved_request(
                        work_order_id=work_order_id,
                        tool_name=normalized_call.tool_name,
                        tool_payload=normalized_call.payload,
                    )
                    if approved_request is None:
                        approval_request = self._find_pending_request(
                            session_id=session.session_id,
                            tool_name=normalized_call.tool_name,
                            tool_payload=normalized_call.payload,
                        ) or self._create_approval_request(
                            profile=profile,
                            session=session,
                            work_order_id=work_order_id,
                            tool_call=normalized_call,
                            reason=policy_decision.reason,
                        )
                        session.pause(
                            current_stage="waiting_approval",
                            turns=turn_index,
                            budget_used=budget.used_tokens,
                            budget_remaining=budget.remaining_tokens,
                            metadata={
                                "pending_approval_id": approval_request.approval_id,
                                "pending_tool_name": normalized_call.tool_name,
                                "pending_tool_payload": dict(normalized_call.payload),
                            },
                        )
                        self._session_recorder.record_event(
                            events,
                            event_type="approval.requested",
                            work_order_id=work_order_id,
                            turn_index=turn_index,
                            payload={
                                "approval_id": approval_request.approval_id,
                                "tool_name": normalized_call.tool_name,
                                "tool_payload": dict(normalized_call.payload),
                                "reason": policy_decision.reason,
                            },
                        )
                        self._session_recorder.publish_progress(session, events, progress_callback)
                        return self._result_mapper.waiting_approval(
                            output_text=last_result.text,
                            provider_name=provider_name,
                            turns=turn_index,
                            budget_used=budget.used_tokens,
                            budget_remaining=budget.remaining_tokens,
                            session=session,
                            compaction_strategy=compaction_strategy,
                            approval_id=approval_request.approval_id,
                            exposed_tools=current_exposed_tools,
                            tool_observations=tool_observations,
                            events=events,
                        )
                    session.metadata.pop("pending_approval_id", None)
                    session.metadata.pop("pending_tool_name", None)
                    session.metadata.pop("pending_tool_payload", None)
                    self._session_recorder.record_event(
                        events,
                        event_type="approval.applied",
                        work_order_id=work_order_id,
                        turn_index=turn_index,
                        payload={
                            "approval_id": approved_request.approval_id,
                            "tool_name": normalized_call.tool_name,
                        },
                    )
                    self._session_recorder.publish_progress(session, events, progress_callback)
                observation = await self._tool_executor.execute(definition, normalized_call.payload)
                tool_observations.append(observation)
                session.add_message(
                    "tool",
                    str(observation.payload),
                    {
                        "tool_name": observation.tool_name,
                        "tool_call_id": str(raw_call.get("tool_call_id") or ""),
                        "status": observation.status,
                        "turn_index": turn_index,
                    },
                )
                self._session_recorder.record_event(
                    events,
                    event_type="tool.executed",
                    work_order_id=work_order_id,
                    turn_index=turn_index,
                    payload=asdict(observation),
                )
                self._session_recorder.publish_progress(session, events, progress_callback)
                self._dispatch(
                    HookPoint.POST_TOOL_USE,
                    work_order_id=work_order_id,
                    payload={
                        "tool_name": normalized_call.tool_name,
                        "observation": asdict(observation),
                        "turn_index": turn_index,
                    },
                    raise_if_blocked=False,
                )

            current_prompt = self._action_interpreter.build_follow_up_prompt(
                prompt,
                last_result.text,
                tool_observations,
            )

        self._session_recorder.record_event(
            events,
            event_type="turn.completed",
            work_order_id=work_order_id,
            turn_index=turns or 1,
            payload={
                "provider": provider_name,
                "turns": turns,
                "budget_used": budget.used_tokens,
                "budget_remaining": budget.remaining_tokens,
                "tool_observations": len(tool_observations),
            },
        )
        self._session_recorder.publish_progress(session, events, progress_callback)
        self._dispatch(
            HookPoint.TURN_END,
            work_order_id=work_order_id,
            payload={
                "provider": provider_name,
                "turns": turns,
                "budget_used": budget.used_tokens,
                "budget_remaining": budget.remaining_tokens,
                "tool_observations": len(tool_observations),
            },
            raise_if_blocked=False,
        )
        session.close(
            current_stage="completed",
            turns=turns,
            budget_used=budget.used_tokens,
            budget_remaining=budget.remaining_tokens,
            metadata={
                "provider_name": provider_name,
                "compaction_strategy": compaction_strategy,
                "exposed_tools": list(current_exposed_tools),
            },
        )
        self._session_recorder.publish_progress(session, events, progress_callback)
        return self._result_mapper.completed(
            output_text=last_result.text if last_result is not None else "",
            provider_name=provider_name,
            turns=turns,
            budget_used=budget.used_tokens,
            budget_remaining=budget.remaining_tokens,
            session=session,
            compaction_strategy=compaction_strategy,
            exposed_tools=current_exposed_tools,
            tool_observations=tool_observations,
            events=events,
        )

    def _create_approval_request(
        self,
        *,
        profile: EmployeeProfile,
        session: ConversationSession,
        work_order_id: str | None,
        tool_call,
        reason: str,
    ) -> ApprovalRequest:
        approval_request = ApprovalRequest.create_new(
            work_order_id=work_order_id,
            session_id=session.session_id,
            employee_id=profile.employee_id,
            tool_name=tool_call.tool_name,
            tool_payload=tool_call.payload,
            approval_policy=profile.approval_policy,
            requested_reason=reason,
        )
        self._approval_repo.create(approval_request)
        return approval_request

    def _ensure_tool_call_ids(self, tool_calls: list[dict[str, Any]], *, turn_index: int) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(tool_calls, start=1):
            payload = dict(item)
            tool_call_id = str(payload.get("tool_call_id") or payload.get("id") or "")
            if not tool_call_id:
                tool_name = str(payload.get("tool_name") or payload.get("name") or "tool")
                tool_call_id = f"call_turn_{turn_index}_{index}_{tool_name.replace(' ', '_')}"
            payload["tool_call_id"] = tool_call_id
            normalized.append(payload)
        return normalized

    def _find_pending_request(
        self,
        *,
        session_id: str,
        tool_name: str,
        tool_payload: dict[str, Any],
    ) -> ApprovalRequest | None:
        for approval in self._approval_repo.list_all():
            if (
                approval.session_id == session_id
                and approval.tool_name == tool_name
                and approval.tool_payload == tool_payload
                and approval.status == "pending"
            ):
                return approval
        return None

    def _find_approved_request(
        self,
        *,
        work_order_id: str | None,
        tool_name: str,
        tool_payload: dict[str, Any],
    ) -> ApprovalRequest | None:
        for approval in self._approval_repo.list_all():
            if (
                approval.work_order_id == work_order_id
                and approval.tool_name == tool_name
                and approval.tool_payload == tool_payload
                and approval.status == "approved"
            ):
                return approval
        return None

    def _dispatch(
        self,
        hook_point: HookPoint,
        *,
        work_order_id: str | None,
        payload: dict[str, Any],
        raise_if_blocked: bool = True,
    ) -> dict[str, Any]:
        context = self._hook_dispatcher.fire(
            HookContext(
                hook_point=hook_point,
                work_order_id=work_order_id,
                payload=dict(payload),
            )
        )
        if context.blocked and raise_if_blocked:
            raise HookBlockedError(hook_point.value)
        return dict(context.modified_payload or context.payload)
