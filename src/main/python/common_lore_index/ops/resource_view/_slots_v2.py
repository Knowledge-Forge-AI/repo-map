"""Closed ``cloe-resource-view-v2`` slot, limit and outcome tables.

Each metric slot has a name, a unit and an allowed basis set; each limit slot
has a name, a unit and an allowed enforcement set. Lexical and context tables
equal their v1 tables. Refresh tables keep the v1 time and total rows in v1
order without the two v1 worker rows, then add sealing, plan and worker rows;
``sealing_io_limit`` is not a v2 row.
"""

from __future__ import annotations

from typing import Any

from ._slots import BACKENDS_BY_OPERATION, LIMIT_SLOTS, METRIC_SLOTS, OUTCOMES_BY_OPERATION

MetricSlotV2 = tuple[str, str, frozenset[str | None]]
LimitSlotV2 = tuple[str, str, frozenset[str]]

_NS, _MS, _BYTES, _COUNT = "nanoseconds", "milliseconds", "bytes", "count"
_METER = frozenset({"call_meter_exact", "call_meter_partial", None})
_CPU = frozenset({"wait4_self_and_waited_descendants", "wait4_platform_defined", None})
_RSS = frozenset({"wait4_max_single_process_rss", "wait4_platform_defined", None})
_BUDGET = frozenset({"call_budget_pre_io", "absent"})
_V1_WORKER_ROWS = frozenset({"worker_cpu", "worker_peak_rss"})

SEALING_METRICS: tuple[MetricSlotV2, ...] = tuple(
    (name, unit, _METER)
    for name, unit in (
        ("sealing_read_bytes", _BYTES), ("sealing_discovery_read_bytes", _BYTES),
        ("sealing_classification_read_bytes", _BYTES), ("sealing_capture_read_bytes", _BYTES),
        ("sealing_copy_read_bytes", _BYTES), ("sealing_store_read_bytes", _BYTES),
        ("sealing_write_bytes", _BYTES), ("sealing_read_calls", _COUNT),
        ("sealing_opens", _COUNT), ("sealing_directory_entries", _COUNT),
        ("sealing_fsyncs", _COUNT), ("sealing_capture_retries", _COUNT),
    )
)
PLAN_METRICS: tuple[MetricSlotV2, ...] = (
    ("planned_inventory_files", _COUNT, frozenset({"metadata_inventory", None})),
    ("planned_inventory_bytes", _BYTES, frozenset({"metadata_inventory", None})),
    ("planned_min_read_bytes", _BYTES, frozenset({"derived_lower_bound", None})),
)
WORKER_METRICS: tuple[MetricSlotV2, ...] = (
    ("worker_launches", _COUNT, frozenset({"supervisor_record", None})),
    ("worker_cpu", _NS, _CPU),
    ("worker_user_cpu", _NS, _CPU),
    ("worker_system_cpu", _NS, _CPU),
    ("worker_peak_rss", _BYTES, _RSS),
    ("worker_group_members_after_reap", _COUNT, frozenset({"process_group_probe", None})),
)
GOVERNANCE_LIMITS: tuple[LimitSlotV2, ...] = (
    ("inventory_max_artifacts", _COUNT, frozenset({"pre_body_admission"})),
    ("inventory_max_total_bytes", _BYTES, frozenset({"pre_body_admission"})),
    ("sealing_max_read_bytes", _BYTES, _BUDGET),
    ("sealing_max_write_bytes", _BYTES, _BUDGET),
    ("sealing_max_opens", _COUNT, _BUDGET),
    ("sealing_max_directory_entries", _COUNT, _BUDGET),
    ("sealing_max_elapsed", _MS, frozenset({"call_budget_cooperative", "absent"})),
    ("classification_max_retained_chars", _COUNT, frozenset({"governed_owner_bound"})),
    ("stable_capture_max_attempts", _COUNT, frozenset({"owner_enforced"})),
)
_REFRESH = frozenset({"local_refresh", "server_refresh"})


def _metrics_from_v1(operation: str) -> tuple[MetricSlotV2, ...]:
    return tuple(
        (name, unit, frozenset({basis}))
        for name, unit, basis in METRIC_SLOTS[operation]
        if operation not in _REFRESH or name not in _V1_WORKER_ROWS
    )


def _limits_from_v1(operation: str) -> tuple[LimitSlotV2, ...]:
    return tuple(
        (name, unit, frozenset({enforcement}))
        for name, unit, enforcement in LIMIT_SLOTS[operation]
        if name != "sealing_io_limit"
    )


METRIC_SLOTS_V2: dict[str, tuple[MetricSlotV2, ...]] = {
    operation: _metrics_from_v1(operation)
    + ((SEALING_METRICS + PLAN_METRICS + WORKER_METRICS) if operation in _REFRESH else ())
    for operation in METRIC_SLOTS
}
LIMIT_SLOTS_V2: dict[str, tuple[LimitSlotV2, ...]] = {
    operation: _limits_from_v1(operation) + (GOVERNANCE_LIMITS if operation in _REFRESH else ())
    for operation in LIMIT_SLOTS
}
OUTCOMES_BY_OPERATION_V2: dict[str | None, frozenset[str]] = {
    operation: outcomes | ({"refused"} if operation in _REFRESH else frozenset())
    for operation, outcomes in OUTCOMES_BY_OPERATION.items()
}


def check_operation_pairing_v2(operation: str | None, backend: str | None, outcome: str) -> None:
    if backend not in BACKENDS_BY_OPERATION.get(operation, frozenset()):
        raise ValueError("resource backend does not match operation")
    if outcome not in OUTCOMES_BY_OPERATION_V2.get(operation, frozenset()):
        raise ValueError("resource outcome does not match operation")


def check_report_domain_v2(report: Any) -> None:
    """Exact v2 metric slots in table order; limits an ordered subset of the table."""

    operation = report.operation
    check_operation_pairing_v2(operation, report.backend, report.outcome)
    if operation is None:
        if report.metrics or report.limits:
            raise ValueError("unbegun resource report cannot carry slots")
        return
    expected = METRIC_SLOTS_V2[operation]
    if len(report.metrics) != len(expected):
        raise ValueError("resource metric slots do not match operation")
    for metric, (name, unit, bases) in zip(report.metrics, expected):
        if (metric.name, metric.unit) != (name, unit) or metric.basis not in bases:
            raise ValueError("resource metric slot does not match operation")
    table = LIMIT_SLOTS_V2[operation]
    order = {name: index for index, (name, _, _) in enumerate(table)}
    previous = -1
    for limit in report.limits:
        index = order.get(limit.name)
        if index is None or index <= previous:
            raise ValueError("resource limit slot does not match operation")
        _, unit, enforcement = table[index]
        if limit.unit != unit or limit.enforcement not in enforcement:
            raise ValueError("resource limit slot does not match operation")
        previous = index


__all__ = (
    "GOVERNANCE_LIMITS", "LIMIT_SLOTS_V2", "METRIC_SLOTS_V2", "OUTCOMES_BY_OPERATION_V2",
    "PLAN_METRICS", "SEALING_METRICS", "WORKER_METRICS", "check_operation_pairing_v2",
    "check_report_domain_v2",
)
