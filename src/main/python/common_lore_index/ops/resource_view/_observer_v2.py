"""Build ``cloe-resource-view-v2`` reports for an explicitly v2 observer.

Lexical and context operations keep their v1 tables and are re-expressed as
v2. Refresh operations add the sealing meter, governed plan and owned-worker
rows of the same call. A meter refusal with no other recorded outcome is
``refused``: the refusal is raised before the worker and publisher. A refused
or failed boundary leaves the meter unclosed, so the report is ``incomplete``.
"""

from __future__ import annotations

from typing import Any

from ._contracts import Instrumentation, Operation, ResourceLimit, ResourceMetric, UnavailableReason
from ._contracts_v2 import (
    SCHEMA_V2, ResourceLimitV2, ResourceMetricV2, ResourceReportV2, upgrade_report,
)
from ._sealing_projection import governance_limits, plan_metrics, sealing_metrics
from ._slots_v2 import LIMIT_SLOTS_V2, METRIC_SLOTS_V2
from ._worker_projection import worker_metrics

_REFRESH = frozenset({Operation.LOCAL_REFRESH.value, Operation.SERVER_REFRESH.value})
_SHARED_WORKER_LIMITS = 5


def _metric(item: ResourceMetric) -> ResourceMetricV2:
    return ResourceMetricV2(item.name, item.value, item.unit, item.availability, item.basis, item.reason)


def _limit(item: ResourceLimit | ResourceLimitV2, *, clear: bool = False) -> ResourceLimitV2:
    applies = None if clear else item.applies_this_call
    return ResourceLimitV2(item.name, item.value, item.unit, item.enforcement, applies)


def _degraded_basis(bases: frozenset[str | None]) -> str | None:
    return None if None in bases else next(iter(bases))


def build_report_v2(observer: Any, build_v1: Any, default_metric: Any) -> ResourceReportV2:
    """Construct the detached v2 report; never raises for an unknown slot."""

    if not observer._begun:
        return ResourceReportV2(
            SCHEMA_V2, None, None, "not_recorded",
            Instrumentation.DEGRADED if observer._degraded else Instrumentation.INCOMPLETE,
        )
    operation = observer._operation
    if operation not in _REFRESH:
        return upgrade_report(build_v1(observer))
    slots = METRIC_SLOTS_V2[operation]
    meter = observer._sealing_meter
    snapshot = None if meter is None else meter.snapshot()
    entered = snapshot is not None
    v1_limits = tuple(
        _limit(observer._limits[name])
        for name, _, _ in LIMIT_SLOTS_V2[operation][:_SHARED_WORKER_LIMITS]
        if name in observer._limits
    )
    governance = governance_limits(observer._sealing_budget, entered=entered)
    if observer._degraded:
        metrics = tuple(
            ResourceMetricV2.unavailable(name, unit, _degraded_basis(bases), UnavailableReason.OBSERVER_FAILED)
            for name, unit, bases in slots
        )
        return ResourceReportV2(
            SCHEMA_V2, operation, observer._backend, observer._outcome, Instrumentation.DEGRADED,
            metrics, v1_limits + tuple(_limit(item, clear=True) for item in governance),
        )
    shared = []
    for name, unit, bases in slots[: len(slots) - 21]:
        existing = observer._metrics.get(name)
        if existing is None:
            existing = default_metric(observer, name, unit, next(iter(bases)))
        shared.append(_metric(existing))
    metrics = (
        tuple(shared) + sealing_metrics(snapshot) + plan_metrics(snapshot)
        + worker_metrics(
            entered=entered, launched=observer._worker_launched, usage=observer._worker_usage,
        )
    )
    if observer._outcome_recorded:
        outcome = observer._outcome
    else:
        outcome = "refused" if observer._sealing_refusal is not None else "not_recorded"
    complete = (
        observer._outcome_recorded
        and all(end is not None for _, end in observer._stages.values())
        and (snapshot is None or snapshot.complete)
    )
    return ResourceReportV2(
        SCHEMA_V2, operation, observer._backend, outcome,
        Instrumentation.COMPLETE if complete else Instrumentation.INCOMPLETE,
        metrics, v1_limits + governance,
    )


__all__ = ("build_report_v2",)
