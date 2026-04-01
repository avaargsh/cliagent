"""Repositories for query projections."""

from __future__ import annotations

import json
import os
from pathlib import Path

from digital_employee.domain.session import SessionProjection
from digital_employee.infra.repositories.work_orders import _FileLock


class FileSessionProjectionRepository:
    def __init__(self, root_path: Path, tenant: str | None = None) -> None:
        state_root = Path(os.getenv("DE_STATE_DIR", root_path / ".de-state"))
        self._projection_dir = state_root / (tenant or "_default") / "projections" / "sessions"
        self._projection_dir.mkdir(parents=True, exist_ok=True)

    def save(self, projection: SessionProjection) -> SessionProjection:
        path = self._path_for(projection.session_id)
        with _FileLock(path.with_suffix(".lock")):
            payload = json.dumps(projection.to_dict(), indent=2, sort_keys=True)
            temp_path = path.with_suffix(".tmp")
            temp_path.write_text(payload, encoding="utf-8")
            temp_path.replace(path)
        return projection

    def get(self, session_id: str) -> SessionProjection | None:
        path = self._path_for(session_id)
        with _FileLock(path.with_suffix(".lock")):
            if not path.exists():
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
        return SessionProjection.from_dict(payload)

    def list_all(self) -> list[SessionProjection]:
        projections: list[SessionProjection] = []
        for path in sorted(self._projection_dir.glob("*.json")):
            with _FileLock(path.with_suffix(".lock")):
                payload = json.loads(path.read_text(encoding="utf-8"))
            projections.append(SessionProjection.from_dict(payload))
        return sorted(projections, key=lambda item: item.started_at, reverse=True)

    def _path_for(self, session_id: str) -> Path:
        return self._projection_dir / f"{session_id}.json"
