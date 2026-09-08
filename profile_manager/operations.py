"""Thread-safe lifecycle operation registry."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Operation:
    id: str
    profile_id: str
    kind: str
    status: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OperationRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._operations: dict[str, Operation] = {}
        self._active: dict[tuple[str, str], str] = {}

    def create(self, profile_id: str, kind: str) -> tuple[Operation, bool]:
        key = (profile_id, kind)
        with self._lock:
            active_id = self._active.get(key)
            if active_id:
                active = self._operations[active_id]
                if active.status in {"queued", "running"}:
                    return active, False
            operation = Operation(str(uuid.uuid4()), profile_id, kind, "queued", _now())
            self._operations[operation.id] = operation
            self._active[key] = operation.id
            return operation, True

    def get(self, operation_id: str) -> Operation:
        with self._lock:
            try:
                return self._operations[operation_id]
            except KeyError as exc:
                raise KeyError("Không tìm thấy operation") from exc

    def start(self, operation_id: str) -> None:
        with self._lock:
            operation = self.get(operation_id)
            operation.status = "running"
            operation.started_at = _now()

    def succeed(self, operation_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            operation = self.get(operation_id)
            operation.status = "succeeded"
            operation.result = result
            operation.completed_at = _now()
            self._active.pop((operation.profile_id, operation.kind), None)

    def fail(self, operation_id: str, code: str, message: str) -> None:
        with self._lock:
            operation = self.get(operation_id)
            operation.status = "failed"
            operation.error = {"code": code, "message": message}
            operation.completed_at = _now()
            self._active.pop((operation.profile_id, operation.kind), None)

    def observe(self, operation_id: str, future: Future[Any]) -> None:
        def complete(done: Future[Any]) -> None:
            try:
                result = done.result()
                operation = self.get(operation_id)
                payload = {"runtime_status": "running", "cdp_url": result} if operation.kind == "open" else {"runtime_status": "stopped"}
                self.succeed(operation_id, payload)
            except Exception as exc:
                self.fail(operation_id, "browser_operation_failed", str(exc))
        future.add_done_callback(complete)

    def active_count(self) -> int:
        with self._lock:
            return len(self._active)
