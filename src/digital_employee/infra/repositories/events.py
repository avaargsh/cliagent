"""Append-only event ledger repository."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path

from digital_employee.domain.events import LedgerEvent
from digital_employee.infra.repositories.work_orders import _FileLock


class FileEventLedgerRepository:
    def __init__(self, root_path: Path, tenant: str | None = None) -> None:
        state_root = Path(os.getenv("DE_STATE_DIR", root_path / ".de-state"))
        tenant_dir = state_root / (tenant or "_default")
        tenant_dir.mkdir(parents=True, exist_ok=True)
        self._file_path = tenant_dir / "events.jsonl"

    def append_all(self, events: list[LedgerEvent]) -> list[LedgerEvent]:
        if not events:
            return []
        with _FileLock(self._file_path.with_suffix(".lock")):
            with self._file_path.open("a", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(asdict(event), ensure_ascii=True, sort_keys=True) + "\n")
        return events

    def list_all(self) -> list[LedgerEvent]:
        lock_path = self._file_path.with_suffix(".lock")
        events: list[LedgerEvent] = []
        with _FileLock(lock_path):
            if not self._file_path.exists():
                return []
            for line in self._file_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                events.append(LedgerEvent(**json.loads(line)))
        return events

    def list_for_session(self, session_id: str) -> list[LedgerEvent]:
        return [event for event in self.list_all() if event.session_id == session_id]

    def list_for_work_order(self, work_order_id: str) -> list[LedgerEvent]:
        return [event for event in self.list_all() if event.work_order_id == work_order_id]
