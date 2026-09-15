"""Shared runtime context and value sanitizers for observer tracing."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import math
from typing import Protocol, cast

from repomap_test_support.observer_trace_evidence import (
    ObserverCaller,
    ObserverTraceEvidenceError,
    ObserverTraceKind,
    _SAFE_DETAILS,
)


class _TraceRecorder(Protocol):
    def record(
        self,
        kind: ObserverTraceKind,
        **values: object,
    ) -> object | None: ...

    def owns_connection(self, session_token: str, candidate: object) -> bool: ...

    def settle_and_release_owner(self, session_token: str, operation_id: int) -> None: ...

    def record_for_active_operation(
        self,
        kind: ObserverTraceKind,
        *,
        session_token: str,
        caller: ObserverCaller | None = None,
        detail: str | None = None,
    ) -> object | None: ...


@dataclass(slots=True)
class _TraceContext:
    recorder: _TraceRecorder
    session_token: str
    operation_id: int | None
    boundary: str | None
    operation_class: str | None
    caller: ObserverCaller
    generation: int | None = None
    suppress_request_settlement: bool = False


_CALLER: ContextVar[ObserverCaller] = ContextVar(
    "observer_trace_caller",
    default=ObserverCaller.UNKNOWN,
)
_TRACE: ContextVar[_TraceContext | None] = ContextVar(
    "observer_trace_context",
    default=None,
)


def _value(value: object | None) -> str | None:
    return cast(str | None, getattr(value, "value", value)) if value is not None else None


def _exception_detail(error: BaseException) -> str:
    mechanism = _value(getattr(error, "observer_timeout_mechanism", None))
    if mechanism in _SAFE_DETAILS:
        return mechanism
    if isinstance(error, ObserverTraceEvidenceError):
        return "failed"
    return (
        "backend_monitor_error"
        if hasattr(error, "observer_boundary")
        else "other_error"
    )


def _seconds_ns(value: object) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        return None
    return int(value * 1_000_000_000)


def _context_values(context: _TraceContext) -> dict[str, object]:
    return {
        "session_token": context.session_token,
        "operation_id": context.operation_id,
        "generation": context.generation,
        "boundary": context.boundary,
        "operation_class": context.operation_class,
        "caller": context.caller,
    }


def _record_context(
    kind: ObserverTraceKind,
    *,
    detail: str | None = None,
) -> None:
    context = _TRACE.get()
    if context is not None:
        context.recorder.record(
            kind,
            detail=detail,
            **_context_values(context),
        )


def _context_owns_connection(
    context: _TraceContext,
    candidate: object,
) -> bool:
    return context.recorder.owns_connection(context.session_token, candidate)


__all__ = [
    "_CALLER",
    "_TRACE",
    "_TraceContext",
    "_context_owns_connection",
    "_context_values",
    "_exception_detail",
    "_record_context",
    "_seconds_ns",
    "_value",
]
