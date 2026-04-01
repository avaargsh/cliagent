"""Application facades exposed to CLI and REST entrypoints."""

from __future__ import annotations

from dataclasses import dataclass

from digital_employee.application.commands import work_order_commands
from digital_employee.application.dto.common import CommandResult
from digital_employee.application.queries import work_order_queries
from digital_employee.application.services.deps import Deps
from digital_employee.application.services.session_observability import load_session_record
from digital_employee.application.use_cases import (
    approval_use_cases,
    config_use_cases,
    doctor_use_cases,
    employee_use_cases,
    replay_use_cases,
    session_use_cases,
    tool_use_cases,
)
from digital_employee.domain.session import SessionRecord


@dataclass(slots=True)
class CommandFacade:
    deps: Deps

    def validate_config(self) -> CommandResult:
        return config_use_cases.validate_config(self.deps)

    async def test_employee(self, employee_id: str, prompt: str) -> CommandResult:
        return await employee_use_cases.test_employee(self.deps, employee_id, prompt)

    def create_work_order(
        self,
        employee_id: str,
        input_text: str,
        budget_tokens: int | None,
        *,
        coordinated: bool = False,
        participant_ids: list[str] | None = None,
    ) -> CommandResult:
        return work_order_commands.create_work_order(
            self.deps,
            employee_id,
            input_text,
            budget_tokens,
            coordinated=coordinated,
            participant_ids=participant_ids,
        )

    async def run_work_order(self, work_order_id: str) -> CommandResult:
        return await work_order_commands.run_work_order(self.deps, work_order_id)

    def start_background_work_order(self, work_order_id: str) -> CommandResult:
        return work_order_commands.start_background_work_order(self.deps, work_order_id)

    def cancel_work_order(self, work_order_id: str) -> CommandResult:
        return work_order_commands.cancel_work_order(self.deps, work_order_id)

    def reclaim_work_order(self, work_order_id: str, *, reason: str | None = None) -> CommandResult:
        return work_order_commands.reclaim_work_order(self.deps, work_order_id, reason=reason)

    async def resume_work_order(self, work_order_id: str) -> CommandResult:
        return await work_order_commands.resume_work_order(self.deps, work_order_id)

    def start_background_resume_work_order(self, work_order_id: str) -> CommandResult:
        return work_order_commands.start_background_resume_work_order(self.deps, work_order_id)

    async def execute_work_order_task(
        self,
        work_order_id: str,
        *,
        session_id: str,
        task_id: str,
    ) -> CommandResult:
        return await work_order_commands.execute_work_order_task(
            self.deps,
            work_order_id,
            session_id=session_id,
            task_id=task_id,
        )

    def dry_run_tool(self, tool_name: str, employee_id: str, payload: dict) -> CommandResult:
        return tool_use_cases.dry_run_tool(
            self.deps,
            tool_name=tool_name,
            employee_id=employee_id,
            payload=payload,
        )

    def decide_approval(self, approval_id: str, *, decision: str, reason: str) -> CommandResult:
        return approval_use_cases.decide_approval(self.deps, approval_id, decision=decision, reason=reason)


@dataclass(slots=True)
class QueryFacade:
    deps: Deps

    def show_config(self) -> CommandResult:
        return config_use_cases.show_config(self.deps)

    def list_employees(self) -> CommandResult:
        return employee_use_cases.list_employees(self.deps)

    def show_employee(self, employee_id: str) -> CommandResult:
        return employee_use_cases.show_employee(self.deps, employee_id)

    def run_doctor(self) -> CommandResult:
        return doctor_use_cases.run_doctor(self.deps)

    def get_work_order(self, work_order_id: str) -> CommandResult:
        return work_order_queries.get_work_order(self.deps, work_order_id)

    def list_work_orders(self) -> CommandResult:
        return work_order_queries.list_work_orders(self.deps)

    def list_work_order_artifacts(self, work_order_id: str) -> CommandResult:
        return work_order_queries.list_work_order_artifacts(self.deps, work_order_id)

    def watch_work_order(self, work_order_id: str) -> CommandResult:
        return work_order_queries.watch_work_order(self.deps, work_order_id)

    def resolve_work_order_session_record(self, work_order_id: str) -> SessionRecord:
        return work_order_queries.resolve_work_order_session_record(self.deps, work_order_id)

    def list_sessions(
        self,
        *,
        work_order_id: str | None = None,
        employee_id: str | None = None,
        status: str | None = None,
    ) -> CommandResult:
        return session_use_cases.list_sessions(
            self.deps,
            work_order_id=work_order_id,
            employee_id=employee_id,
            status=status,
        )

    def get_session(self, session_id: str) -> CommandResult:
        return session_use_cases.get_session(self.deps, session_id)

    def tail_session(self, session_id: str) -> CommandResult:
        return session_use_cases.tail_session(self.deps, session_id)

    def export_session(self, session_id: str) -> CommandResult:
        return session_use_cases.export_session(self.deps, session_id)

    def resolve_session_record(self, session_id: str) -> SessionRecord | None:
        return load_session_record(self.deps, session_id)

    def list_tools(self) -> CommandResult:
        return tool_use_cases.list_tools(self.deps)

    def show_tool(self, tool_name: str) -> CommandResult:
        return tool_use_cases.show_tool(self.deps, tool_name)

    def list_approvals(self, *, status: str | None = None) -> CommandResult:
        return approval_use_cases.list_approvals(self.deps, status=status)

    def get_approval(self, approval_id: str) -> CommandResult:
        return approval_use_cases.get_approval(self.deps, approval_id)

    def run_replay(self, work_order_id: str) -> CommandResult:
        return replay_use_cases.replay_work_order(self.deps, work_order_id)
