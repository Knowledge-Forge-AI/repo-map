"""Project owned-worker usage into the six v2 worker rows.

``worker_launches`` comes from the supervisor record. CPU and peak RSS come
only from the parent's single-owner ``wait4`` of the launched child; anything
else is ``unavailable`` with a closed reason. ``operation_process_cpu`` stays
parent-self and no row adds parent and worker values.
"""

from __future__ import annotations

from typing import Any

from ._contracts_v2 import ResourceMetricV2
from ._slots_v2 import WORKER_METRICS


def worker_metrics(*, entered: bool, launched: bool, usage: Any | None) -> tuple[ResourceMetricV2, ...]:
    """``entered``: capture began; ``launched``: the worker launch was noted."""

    if not entered:
        return tuple(
            ResourceMetricV2.unavailable(name, unit, None, "not_started")
            for name, unit, _ in WORKER_METRICS
        )
    rows = [ResourceMetricV2.measured("worker_launches", int(launched), "count", "supervisor_record")]
    if not launched or usage is None:
        reason = "not_observed" if launched else "not_started"
        rows.extend(
            ResourceMetricV2.unavailable(name, unit, None, reason)
            for name, unit, _ in WORKER_METRICS[1:]
        )
        return tuple(rows)
    reason = getattr(usage, "reason", None) or "invalid_owner_value"
    for name, unit, value, basis in (
        ("worker_cpu", "nanoseconds", usage.total_cpu_ns, usage.cpu_basis),
        ("worker_user_cpu", "nanoseconds", usage.user_cpu_ns, usage.cpu_basis),
        ("worker_system_cpu", "nanoseconds", usage.system_cpu_ns, usage.cpu_basis),
        ("worker_peak_rss", "bytes", usage.peak_rss_bytes, usage.rss_basis),
    ):
        rows.append(
            ResourceMetricV2.measured(name, value, unit, basis)
            if value is not None and basis is not None
            else ResourceMetricV2.unavailable(name, unit, None, reason)
        )
    members = usage.group_members_after_reap
    rows.append(
        ResourceMetricV2.measured("worker_group_members_after_reap", members, "count", "process_group_probe")
        if members is not None
        else ResourceMetricV2.unavailable(
            "worker_group_members_after_reap", "count", None,
            usage.group_reason or reason,
        )
    )
    return tuple(rows)


__all__ = ("worker_metrics",)
