"""Shared event streaming helpers for CLI commands."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from typing import Callable

from digital_employee.application.dto.common import CommandFailure
from digital_employee.domain.events import RunEvent
from digital_employee.domain.session import SessionRecord


def stream_session_record_events(
    record_loader: Callable[[], SessionRecord | None],
    *,
    resource_id: str,
    follow: bool,
    since: str | None,
    level: str | None,
    as_jsonl: bool,
    not_found: tuple[int, str, str] | None = None,
    payload_factory: Callable[[SessionRecord, RunEvent, str], dict] | None = None,
) -> None:
    since_dt = parse_since(since)
    seen_count = 0

    while True:
        record = record_loader()
        if record is None:
            if not_found is None:
                return
            raise CommandFailure(*not_found)

        if len(record.events) < seen_count:
            seen_count = 0

        pending_events = record.events[seen_count:]
        seen_count = len(record.events)

        for event in pending_events:
            level_name = event_level(event.event_type)
            if since_dt is not None and datetime.fromisoformat(event.created_at) < since_dt:
                continue
            if level is not None and level_name != level:
                continue

            payload = {
                **event.payload,
                "level": level_name,
            }
            if payload_factory is not None:
                payload.update(payload_factory(record, event, level_name))

            item = {
                "ts": event.created_at,
                "event_type": event.event_type,
                "resource_id": resource_id,
                "status": event_status(event.event_type),
                "payload": payload,
            }
            if as_jsonl:
                sys.stdout.write(json.dumps(item, ensure_ascii=True) + "\n")
            else:
                sys.stdout.write(
                    f"{item['ts']} {item['event_type']} {item['status']} {item['payload']}\n"
                )

        sys.stdout.flush()
        if not follow:
            break
        if record.session.status in {"closed", "paused"}:
            if _background_runner_active(record):
                time.sleep(0.05)
                continue
            break
        time.sleep(0.05)


def parse_since(value: str | None):
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CommandFailure(2, "since_invalid", f"invalid RFC3339 timestamp: {value}") from error


def event_level(event_type: str) -> str:
    if event_type.endswith("failed") or event_type.endswith("reclaimed") or "error" in event_type:
        return "error"
    if "warning" in event_type:
        return "warn"
    if event_type.startswith("tool.") or event_type.startswith("completion."):
        return "debug"
    return "info"


def event_status(event_type: str) -> str:
    if event_type.endswith("failed") or event_type.endswith("reclaimed"):
        return "failed"
    if event_type.endswith("cancelled") or event_type.endswith("expired"):
        return "cancelled"
    if event_type.endswith("queued"):
        return "queued"
    if event_type.endswith("completed"):
        return "completed"
    return "running"


def _background_runner_active(record: SessionRecord) -> bool:
    metadata = record.session.metadata
    if metadata.get("dispatch_mode") != "background" and "background_state" not in metadata:
        return False

    runner_pid = metadata.get("runner_pid")
    try:
        pid = int(runner_pid)
    except (TypeError, ValueError):
        return False

    # When watch is executed in the same long-lived parent process (test mode),
    # proactively reap an exited child to avoid treating zombies as running.
    try:
        finished_pid, _status = os.waitpid(pid, os.WNOHANG)
        if finished_pid == pid:
            return False
    except ChildProcessError:
        pass

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    return True
