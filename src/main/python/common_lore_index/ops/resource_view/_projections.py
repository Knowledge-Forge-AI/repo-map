"""Pure report projections and Server/Lexical finish hooks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeVar

from common_lore_index.retrieval.context_contracts import PACKET_STATUSES
from common_lore_index.retrieval.context_work import (
    SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT,
    WALL_CLOCK_DEADLINE_MS,
)
from common_lore_index.storage._staging_measurement_records import (
    StagingMeasurementAvailability, StagingMeasurementCategory,
)

from ._contracts import Basis, Backend, Instrumentation, ResourceMetric, ResourceReport, SCHEMA, Unit, UnavailableReason
from ._controls import context_limit
from ._observer import ResourceObserver


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
_STAGING = (
    ("wal_upper_bound", StagingMeasurementCategory.WAL_UPPER_BOUND, Basis.SHARED_UPPER_BOUND),
    ("temporary_byte_upper_bound", StagingMeasurementCategory.TEMPORARY_BYTE_UPPER_BOUND, Basis.SHARED_UPPER_BOUND),
    ("postgresql_memory", StagingMeasurementCategory.POSTGRESQL_MEMORY, Basis.SAMPLED_MAX),
    ("client_memory", StagingMeasurementCategory.CLIENT_MEMORY, Basis.PROCESS_LIFETIME_PEAK),
)
_Result = TypeVar("_Result")


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


def project_staging_resources(
    events: Sequence[object], *, measurements_failed: bool
) -> tuple[ResourceMetric, ...]:
    """Project four caller-selected staging events without invoking a sink or SQL."""
    if measurements_failed:
        return tuple(
            ResourceMetric.unavailable(name, Unit.BYTES, basis, UnavailableReason.OBSERVER_FAILED)
            for name, _, basis in _STAGING
        )
    by_category: dict[object, list[object]] = {category: [] for _, category, _ in _STAGING}
    for event in events:
        category = getattr(event, "category", None)
        for _, expected, _ in _STAGING:
            if category == expected or category == expected.value:
                by_category[expected].append(event)
                break
    projected: list[ResourceMetric] = []
    for name, category, basis in _STAGING:
        matching = by_category[category]
        if not matching:
            projected.append(ResourceMetric.unavailable(
                name, Unit.BYTES, basis, UnavailableReason.NOT_EMITTED,
            ))
            continue
        if len(matching) > 1:
            projected.append(ResourceMetric.unavailable(
                name, Unit.BYTES, basis, UnavailableReason.AMBIGUOUS_REPEAT,
            ))
            continue
        event = matching[0]
        availability = getattr(event, "availability", None)
        if (
            availability != StagingMeasurementAvailability.MEASURED
            and availability != StagingMeasurementAvailability.MEASURED.value
        ):
            projected.append(ResourceMetric.unavailable(
                name, Unit.BYTES, basis, UnavailableReason.NOT_OBSERVED,
            ))
            continue
        value = _nonnegative(getattr(event, "value", None))
        projected.append(
            ResourceMetric.measured(name, value, Unit.BYTES, basis)
            if value is not None else ResourceMetric.unavailable(
                name, Unit.BYTES, basis, UnavailableReason.INVALID_OWNER_VALUE,
            )
        )
    return tuple(projected)


def _finish(observer: ResourceObserver | None, method: str, result: _Result) -> _Result:
    if observer is None or type(observer) is not ResourceObserver:
        return result
    try:
        getattr(observer, method)(result)
    except Exception:
        observer._degrade()
    return result


def finish_server(observer: ResourceObserver | None, result: _Result) -> _Result:
    return _finish(observer, "_finish_server", result)


def finish_lexical(observer: ResourceObserver | None, result: _Result) -> _Result:
    return _finish(observer, "_finish_lexical", result)


__all__ = (
    "finish_lexical", "finish_server", "project_compact_context",
    "project_staging_resources",
)
