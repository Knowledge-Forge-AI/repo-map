"""Local-safe compact-context projection.

This module imports no PostgreSQL staging, driver, parser or enrichment owner,
so SQLite Local context paths can project their returned packet. It projects
only the returned packet and the owner ledger that served the call; it never
queries storage, constructs a ledger or reads source bodies.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from common_lore_index.retrieval.context_contracts import PACKET_STATUSES
from common_lore_index.retrieval.context_work import (
    SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT,
    WALL_CLOCK_DEADLINE_MS,
)

from ._contracts import Basis, Backend, Instrumentation, ResourceMetric, ResourceReport, SCHEMA, Unit, UnavailableReason
from ._controls import context_limit


_CONTEXT_COUNTERS = (
    "config_revalidations_executed", "logical_read_units", "sql_statements_executed",
    "scan_units_executed", "seed_expansions_executed", "candidate_rows_scanned",
    "evidence_rows_scanned",
)
_CONTEXT_METRICS = (
    *_CONTEXT_COUNTERS, "elapsed_ms", "actual_bytes", "sqlite_progress_callbacks",
    "sqlite_vm_steps_estimate", "sqlite_progress_interval_ops",
)
_CONTEXT_UNITS = {
    **{name: Unit.COUNT for name in _CONTEXT_COUNTERS},
    "elapsed_ms": Unit.MILLISECONDS,
    "actual_bytes": Unit.BYTES,
    "sqlite_progress_callbacks": Unit.COUNT,
    "sqlite_vm_steps_estimate": Unit.COUNT,
    "sqlite_progress_interval_ops": Unit.COUNT,
}
_CONTEXT_BASES = {
    **{name: Basis.LEDGER_COUNTER for name in _CONTEXT_COUNTERS},
    "elapsed_ms": Basis.LEDGER_LOWER_BOUND,
    "actual_bytes": Basis.LEDGER_COUNTER,
    "sqlite_progress_callbacks": Basis.LEDGER_COUNTER,
    "sqlite_vm_steps_estimate": Basis.ESTIMATE,
    "sqlite_progress_interval_ops": Basis.OWNER_PARAMETER,
}
_SQLITE_METRICS = (
    "sqlite_progress_callbacks", "sqlite_vm_steps_estimate", "sqlite_progress_interval_ops",
)
def _read(source: object, name: str, default: object = None) -> object:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _nonnegative(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _metric(
    name: str, value: object, unit: str, basis: str, *, reason: str = UnavailableReason.INVALID_OWNER_VALUE
) -> ResourceMetric:
    checked = _nonnegative(value)
    if checked is None:
        return ResourceMetric.unavailable(name, unit, basis, reason)
    return ResourceMetric.measured(name, checked, unit, basis)


def _unavailable(name: str, reason: str) -> ResourceMetric:
    return ResourceMetric.unavailable(name, _CONTEXT_UNITS[name], _CONTEXT_BASES[name], reason)


def _context_limits(
    packet: Mapping[str, Any], backend: str | None, ledger: object | None
) -> tuple:
    deadline: object
    callback: object
    if packet.get("status") == "budget_error":
        return ()
    source = packet.get("work_ledger", {})
    rows = []
    for name, unit in (
        ("max_logical_read_units", Unit.COUNT),
        ("max_sql_statements", Unit.COUNT),
        ("max_scan_units", Unit.COUNT),
        ("max_seed_expansions", Unit.COUNT),
    ):
        value = _read(source, name)
        row = context_limit(name, value, unit)
        if row is not None:
            rows.append(row)
    request = packet.get("request")
    if isinstance(request, Mapping):
        row = context_limit("budget_bytes", request.get("budget_bytes"), Unit.BYTES)
        if row is not None:
            rows.append(row)
    # A packet mapping does not carry a selected deadline. In that case this
    # is the owner's default ceiling, not a claim about a custom lower value.
    if ledger is None:
        deadline = WALL_CLOCK_DEADLINE_MS
        callback = SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT
    else:
        deadline = _read(ledger, "deadline_ms")
        callback = _read(ledger, "sqlite_progress_callback_limit")
    applies = True if ledger is not None else None
    row = context_limit("wall_clock_deadline", deadline, Unit.MILLISECONDS, applies_this_call=applies)
    if row is not None:
        rows.append(row)
    if backend == Backend.SQLITE:
        row = context_limit("sqlite_progress_callback_limit", callback, Unit.COUNT, applies_this_call=applies)
        if row is not None:
            rows.append(row)
    return tuple(rows)


def project_compact_context(
    packet: Mapping[str, Any], *, work_ledger: object | None = None
) -> ResourceReport:
    """Project only existing packet/ledger values; never mutate or read storage."""
    scope = packet.get("scope")
    backend_raw = scope.get("backend") if isinstance(scope, Mapping) else None
    backend = backend_raw if isinstance(backend_raw, str) and backend_raw in {item.value for item in Backend} else None
    status = packet.get("status")
    if status == "budget_error":
        backend = None
    outcome = status if isinstance(status, str) and status in PACKET_STATUSES else "unclassified"
    metrics: list[ResourceMetric] = []
    if status == "budget_error":
        metrics.extend(_unavailable(name, UnavailableReason.NOT_REACHED) for name in _CONTEXT_METRICS)
    else:
        source = packet.get("work_ledger", {})
        for name in _CONTEXT_COUNTERS:
            metrics.append(_metric(name, _read(source, name), _CONTEXT_UNITS[name], _CONTEXT_BASES[name]))
        metrics.append(_metric(
            "elapsed_ms", _read(source, "elapsed_ms"), Unit.MILLISECONDS, Basis.LEDGER_LOWER_BOUND,
        ))
        metrics.append(_metric(
            "actual_bytes", _read(packet.get("work_ledger", {}), "actual_bytes"),
            Unit.BYTES, Basis.LEDGER_COUNTER,
        ))
        for name in _SQLITE_METRICS:
            if backend == Backend.POSTGRESQL:
                metrics.append(_unavailable(name, UnavailableReason.BACKEND_NOT_APPLICABLE))
            else:
                metrics.append(_metric(name, _read(source, name), _CONTEXT_UNITS[name], _CONTEXT_BASES[name]))
    return ResourceReport(
        SCHEMA, "compact_context", backend, outcome,
        Instrumentation.COMPLETE, tuple(metrics), _context_limits(packet, backend, work_ledger),
    )


def unfinished_compact_context() -> ResourceReport:
    """Report a context call whose owner raised before returning a packet.

    No backend is guessed and no counter is invented: every slot is
    unavailable and the outcome is not recorded.
    """
    return ResourceReport(
        SCHEMA, "compact_context", None, "not_recorded", Instrumentation.INCOMPLETE,
        tuple(_unavailable(name, UnavailableReason.NOT_REACHED) for name in _CONTEXT_METRICS),
    )


__all__ = ("project_compact_context", "unfinished_compact_context")
