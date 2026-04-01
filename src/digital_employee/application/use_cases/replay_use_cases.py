"""Replay use cases."""

from __future__ import annotations

from dataclasses import asdict

from digital_employee.application.dto.common import CommandResult
from digital_employee.application.services.deps import Deps
from digital_employee.domain.errors import DigitalEmployeeError, NotFoundError


def replay_work_order(deps: Deps, work_order_id: str) -> CommandResult:
    work_order = deps.work_order_repo.get(work_order_id)
    if work_order is None:
        raise NotFoundError("work order", work_order_id)

    events = deps.event_ledger.list_for_work_order(work_order_id)
    if not events:
        raise DigitalEmployeeError(
            message=f"work order {work_order_id} has no ledger events to replay",
            error_type="replay_events_missing",
            exit_code=7,
            hint=f"run 'dectl work-order run {work_order_id}' first",
        )

    first = events[0]
    last = events[-1]
    session_id = work_order.last_session_id or first.session_id
    data = {
        "replay": {
            "work_order_id": work_order_id,
            "session_id": session_id,
            "event_count": len(events),
            "started_at": first.created_at,
            "ended_at": last.created_at,
            "last_event_type": last.event_type,
            "events": [asdict(event) for event in events],
        }
    }
    human_lines = [
        f"Replayed work order {work_order_id}",
        f"Session: {session_id or 'unknown'}",
        f"Events: {len(events)}",
        f"Last event: {last.event_type}",
    ]
    return CommandResult(command="replay run", data=data, human_lines=human_lines)
