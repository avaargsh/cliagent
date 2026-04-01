"""File-backed session repository."""

from __future__ import annotations

import json
import os
from pathlib import Path

from digital_employee.domain.session import SessionRecord
from digital_employee.infra.repositories.work_orders import _FileLock


class FileSessionRepository:
    def __init__(self, root_path: Path, tenant: str | None = None) -> None:
        state_root = Path(os.getenv("DE_STATE_DIR", root_path / ".de-state"))
        self._session_dir = state_root / (tenant or "_default") / "sessions"
        self._session_dir.mkdir(parents=True, exist_ok=True)

    def save(self, record: SessionRecord) -> SessionRecord:
        path = self._path_for(record.session.session_id)
        with _FileLock(path.with_suffix(".lock")):
            payload = json.dumps(record.to_dict(), indent=2, sort_keys=True)
            temp_path = path.with_suffix(".tmp")
            temp_path.write_text(payload, encoding="utf-8")
            temp_path.replace(path)
        return record

    def get(self, session_id: str) -> SessionRecord | None:
        path = self._path_for(session_id)
        with _FileLock(path.with_suffix(".lock")):
            if not path.exists():
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
        return SessionRecord.from_dict(payload)

    def list_all(self) -> list[SessionRecord]:
        records: list[SessionRecord] = []
        for path in sorted(self._session_dir.glob("*.json")):
            with _FileLock(path.with_suffix(".lock")):
                payload = json.loads(path.read_text(encoding="utf-8"))
            records.append(SessionRecord.from_dict(payload))
        return sorted(records, key=lambda item: item.session.started_at, reverse=True)

    def _path_for(self, session_id: str) -> Path:
        return self._session_dir / f"{session_id}.json"
