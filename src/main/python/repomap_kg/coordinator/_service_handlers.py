"""Request dispatcher handlers for CoordinatorService."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict
import threading
import time

from repomap_kg.coordinator._coordinator_protocols import (
    RequestResolver,
    ServiceCoordinator as _Coordinator,
    ServiceStore as _Store,
    require_payload_int,
    require_payload_string,
)
from repomap_kg.coordinator.contracts import (
    JobRequest,
    TERMINAL_JOB_STATES,
    normalize_request,
)
from repomap_kg.coordinator.limits import CoordinatorLimits
from repomap_kg.coordinator.transport import TransportError


class ServiceHandlersMixin:
    """Provide local request dispatching and synchronous polling handlers."""

    _state_lock: threading.Lock
    _state: str
    _request_resolver: RequestResolver
    _coordinator: _Coordinator
    _store: _Store
    _limits: CoordinatorLimits
    _wait_seconds: float
    _stop: threading.Event
    _idle_poll: float

    def health(self) -> dict[str, object]:
        raise NotImplementedError

    def _handlers(self) -> dict[str, Callable[[Mapping[str, object]], object]]:
        return {
            "health": lambda _payload: self.health(),
            "submit": self._submit,
            "status": self._status,
            "wait": self._wait,
            "cancel": self._cancel,
            "list": self._list,
        }

    def _submit(self, payload: Mapping[str, object]) -> dict[str, object]:
        with self._state_lock:
            if self._state != "ready":
                raise TransportError("saturated")
        try:
            request = self._request_resolver(payload["request"])
            result = self._coordinator.submit(lambda: self._store.submit(request))
        except (KeyError, ValueError):
            raise TransportError("invalid_request") from None
        return {
            "job_id": result.job_id,
            "state": result.state,
            "replayed": result.replayed,
        }

    def _resolve_synthetic_request(self, payload: object) -> JobRequest:
        if not isinstance(payload, Mapping):
            raise ValueError("request fields do not match the version-1 schema")
        request_payload: dict[str, object] = {}
        for key, value in payload.items():
            if not isinstance(key, str):
                raise ValueError("request fields do not match the version-1 schema")
            request_payload[key] = value
        return normalize_request(
            request_payload,
            source_generation="sg1:synthetic",
            config_generation="cg1:synthetic",
            limits=self._limits,
        )

    def _status(self, payload: Mapping[str, object]) -> dict[str, object]:
        try:
            status = self._store.status(require_payload_string(payload, "job_id"))
        except (KeyError, ValueError):
            raise TransportError("invalid_request") from None
        result: dict[str, object] = {
            "job_id": status.job_id,
            "graph_id": status.graph_id,
            "state": status.state,
            "attempt_count": status.attempt,
            "phase": status.phase,
            "completed": status.completed,
        }
        if status.total is not None:
            result["total"] = status.total
        if status.error_category is not None:
            result["error_category"] = status.error_category
        return result

    def _wait(self, payload: Mapping[str, object]) -> dict[str, object]:
        deadline = time.monotonic() + self._wait_seconds
        while True:
            result = self._status(payload)
            if result["state"] in TERMINAL_JOB_STATES or time.monotonic() >= deadline:
                return result
            self._stop.wait(min(self._idle_poll, max(0, deadline - time.monotonic())))

    def _cancel(self, payload: Mapping[str, object]) -> dict[str, object]:
        try:
            job_id = require_payload_string(payload, "job_id")
            state = self._coordinator.request_cancel(job_id)
        except (KeyError, ValueError):
            raise TransportError("invalid_request") from None
        return {"job_id": job_id, "state": state}

    def _list(self, payload: Mapping[str, object]) -> dict[str, object]:
        try:
            page = self._store.list_recent_jobs(
                limit=require_payload_int(payload, "limit"),
                graph_id=str(gid) if (gid := payload.get("graph_id")) is not None else None,
                cursor=str(cur) if (cur := payload.get("cursor")) is not None else None,
            )
        except (KeyError, TypeError, ValueError):
            raise TransportError("invalid_request") from None
        return {
            "jobs": [asdict(job) for job in page.jobs],
            "next_cursor": page.next_cursor,
        }
