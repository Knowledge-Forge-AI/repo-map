"""Private finish/report helpers kept separate from the hook surface."""

from __future__ import annotations

from typing import Any, TypeVar

from ._contracts import (
    Basis, Instrumentation, Operation, ResourceMetric, ResourceReport, SCHEMA,
    Unit, UnavailableReason,
)
from ._slots import LIMIT_SLOTS, METRIC_SLOTS


_STAGES = {
    "lock_and_reconcile": "lock_and_reconcile_elapsed",
    "capture": "capture_elapsed", "validation": "validation_elapsed",
    "publication": "publication_elapsed",
}
_Result = TypeVar("_Result")


def _int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _finish_times(observer: Any) -> int:
    if observer._start_ns is None or observer._start_cpu_ns is None:
        raise ValueError("resource observer did not begin")
    ended = _int(observer._monotonic(), "monotonic clock")
    cpu_ended = _int(observer._process_time(), "process clock")
    observer._add_metric(ResourceMetric.measured(
        "operation_elapsed", max(0, ended - observer._start_ns),
        Unit.NANOSECONDS, Basis.MONOTONIC_SPAN,
    ))
    observer._add_metric(ResourceMetric.measured(
        "operation_process_cpu", max(0, cpu_ended - observer._start_cpu_ns),
        Unit.NANOSECONDS, Basis.PROCESS_CLOCK_INCLUSIVE,
    ))
    return ended


def _close_publication(observer: Any, ended: int) -> None:
    existing = observer._stages.get("publication")
    if existing is None:
        return
    if existing[1] is not None:
        raise ValueError("publication stage already ended")
    started, _ = existing
    observer._stages["publication"] = (started, ended)
    observer._add_metric(ResourceMetric.measured(
        "publication_elapsed", max(0, ended - started),
        Unit.NANOSECONDS, Basis.MONOTONIC_SPAN,
    ))


def _ensure_worker_metrics(observer: Any) -> None:
    if observer._operation not in {Operation.LOCAL_REFRESH, Operation.SERVER_REFRESH}:
        return
    reason = UnavailableReason.NOT_OBSERVED if observer._worker_launched else UnavailableReason.NOT_STARTED
    if "worker_cpu" not in observer._metrics:
        observer._add_metric(ResourceMetric.unavailable(
            "worker_cpu", Unit.NANOSECONDS, None, reason,
        ))
    if "worker_peak_rss" not in observer._metrics:
        observer._add_metric(ResourceMetric.unavailable(
            "worker_peak_rss", Unit.BYTES, None, reason,
        ))


def finish_local(observer: Any, result: _Result) -> _Result:
    if not observer._active():
        return result
    if observer._operation != Operation.LOCAL_REFRESH or observer._outcome_recorded:
        raise ValueError("local finish is invalid")
    ended = _finish_times(observer)
    reconciled = getattr(result, "reconciled", None)
    observer._outcome = (
        "reconciled_replay" if reconciled is True else
        "published" if reconciled is False else "unclassified"
    )
    if observer._outcome == "published":
        _close_publication(observer, ended)
    _ensure_worker_metrics(observer)
    observer._outcome_recorded = True
    return result


def finish_server(observer: Any, result: _Result) -> _Result:
    if not observer._active():
        return result
    if observer._operation != Operation.SERVER_REFRESH or observer._outcome_recorded:
        raise ValueError("server finish is invalid")
    ended = _finish_times(observer)
    raw_result = getattr(result, "result", None)
    state = getattr(result, "publication_state", None)
    category = getattr(result, "error_category", None)
    if raw_result == "success" and state == "committed":
        observer._outcome = "committed"
    elif category == "cancelled":
        observer._outcome = "cancelled"
    elif state == "commit_unknown":
        observer._outcome = "commit_unknown"
    elif raw_result == "failure":
        observer._outcome = "failed"
    else:
        observer._outcome = "unclassified"
    if observer._outcome == "committed":
        _close_publication(observer, ended)
    _ensure_worker_metrics(observer)
    observer._outcome_recorded = True
    return result


def finish_lexical(observer: Any, result: _Result) -> _Result:
    if not observer._active():
        return result
    if observer._operation != Operation.LEXICAL_BUILD or observer._outcome_recorded:
        raise ValueError("lexical finish is invalid")
    ended = _finish_times(observer)
    _close_publication(observer, ended)
    raw_result = getattr(result, "result", None)
    observer._outcome = raw_result if raw_result in {"published", "refused"} else "unclassified"
    plan = getattr(result, "plan", None)
    applies = True if plan is not None else None
    for name in tuple(observer._limits):
        if name.startswith("max_") or name == "lexical_build_statement_timeout":
            observer._replace_limit(name, applies_this_call=applies)
    if plan is None:
        for name, unit in (
            ("lexical_input_bytes", Unit.BYTES), ("lexical_projected_bytes", Unit.BYTES),
            ("lexical_documents", Unit.COUNT), ("lexical_omissions", Unit.COUNT),
        ):
            observer._add_metric(ResourceMetric.unavailable(
                name, unit, Basis.OWNER_AGGREGATE, UnavailableReason.NOT_REACHED,
            ))
    else:
        observer._add_metric(ResourceMetric.measured(
            "lexical_input_bytes", _int(getattr(plan, "aggregate_input_bytes"), "lexical input"),
            Unit.BYTES, Basis.OWNER_AGGREGATE,
        ))
        observer._add_metric(ResourceMetric.measured(
            "lexical_projected_bytes", _int(getattr(plan, "aggregate_projected_bytes"), "lexical projected"),
            Unit.BYTES, Basis.OWNER_AGGREGATE,
        ))
        observer._add_metric(ResourceMetric.measured(
            "lexical_documents", len(getattr(plan, "documents")), Unit.COUNT, Basis.OWNER_AGGREGATE,
        ))
        observer._add_metric(ResourceMetric.measured(
            "lexical_omissions", len(getattr(plan, "omissions")), Unit.COUNT, Basis.OWNER_AGGREGATE,
        ))
    observer._outcome_recorded = True
    return result


def _default_metric(observer: Any, name: str, unit: str, basis: str | None) -> ResourceMetric:
    reason = (
        UnavailableReason.NOT_STARTED
        if name in {"operation_elapsed", "operation_process_cpu"}
        else UnavailableReason.NOT_REACHED
    )
    if name in _STAGES.values():
        stage = next(key for key, value in _STAGES.items() if value == name)
        reason = UnavailableReason.NOT_REACHED if stage in observer._stages else UnavailableReason.NOT_STARTED
    return ResourceMetric.unavailable(name, unit, basis, reason)


def build_report(observer: Any) -> ResourceReport:
    """Build from the explicit operation tables; unknown slots never raise KeyError."""
    if not observer._begun:
        return ResourceReport(
            SCHEMA, None, None, "not_recorded",
            Instrumentation.DEGRADED if observer._degraded else Instrumentation.INCOMPLETE,
        )
    operation = observer._operation
    slots = METRIC_SLOTS[operation]
    limits = tuple(
        observer._limits[name] for name, _, _ in LIMIT_SLOTS[operation] if name in observer._limits
    )
    if observer._degraded:
        metrics = tuple(
            ResourceMetric.unavailable(name, unit, basis, UnavailableReason.OBSERVER_FAILED)
            for name, unit, basis in slots
        )
        return ResourceReport(
            SCHEMA, operation, observer._backend, observer._outcome,
            Instrumentation.DEGRADED, metrics, limits,
        )
    _ensure_worker_metrics(observer)
    for name, unit, basis in slots:
        if name not in observer._metrics:
            observer._metrics[name] = _default_metric(observer, name, unit, basis)
    instrumentation = (
        Instrumentation.COMPLETE
        if observer._outcome_recorded and all(end is not None for _, end in observer._stages.values())
        else Instrumentation.INCOMPLETE
    )
    return ResourceReport(
        SCHEMA, operation, observer._backend,
        observer._outcome if observer._outcome_recorded else "not_recorded",
        instrumentation, tuple(observer._metrics[name] for name, _, _ in slots), limits,
    )


__all__ = ("build_report", "finish_lexical", "finish_local", "finish_server")
