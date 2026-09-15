"""Typed construction boundary for observer trace events."""

from __future__ import annotations

from dataclasses import fields
from typing import TypedDict, cast

from repomap_test_support.observer_trace_evidence import (
    ObserverCaller,
    ObserverTraceEvent,
    ObserverTraceKind,
)


class _EventValues(TypedDict, total=False):
    session_token: str | None
    port_token: str | None
    operation_id: int | None
    generation: int | None
    boundary: str | None
    operation_class: str | None
    caller: ObserverCaller
    caller_thread_token: str | None
    owner_thread_token: str | None
    caller_timeout_ns: int | None
    remaining_authority_ns: int | None
    sql_admission_floor_ns: int | None
    duration_ns: int | None
    nominal_ns: int | None
    active_owner_operation_id: int | None
    active_owner_boundary: str | None
    active_owner_operation_class: str | None
    active_owner_generation: int | None
    active_owner_thread_token: str | None
    active_owner_caller: ObserverCaller | None
    session_state: str | None
    detail: str | None


_EVENT_VALUE_NAMES = frozenset(
    field.name for field in fields(ObserverTraceEvent) if field.name not in {"sequence", "monotonic_ns", "kind"}
)


def make_observer_trace_event(
    sequence: int,
    monotonic_ns: int,
    kind: ObserverTraceKind,
    values: dict[str, object],
) -> ObserverTraceEvent:
    """Construct an event while preserving unknown-key failure semantics."""
    unexpected = set(values).difference(_EVENT_VALUE_NAMES)
    if unexpected:
        raise TypeError(f"unexpected observer trace fields: {sorted(unexpected)!r}")
    return ObserverTraceEvent(
        sequence,
        monotonic_ns,
        kind,
        **cast(_EventValues, values),
    )


__all__ = ["make_observer_trace_event"]
