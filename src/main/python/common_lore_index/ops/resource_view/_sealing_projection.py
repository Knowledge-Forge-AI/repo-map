"""Project one sealing meter snapshot and budget into v2 metric and limit rows.

A closed meter yields ``call_meter_exact`` rows; an unclosed one (refusal or
failure inside the boundary) yields ``call_meter_partial``. Without a noted
meter the boundary was never entered and every sealing and plan row is
``not_started``. Plan rows are measured only by a governed metadata preflight;
observe-only calls report them as ``not_selected``.
"""

from __future__ import annotations

from common_lore_index.artifacts._manifest_records import DEFAULT_ARTIFACT_LIMITS
from common_lore_index.artifacts._sealing_meter import SealingMeterSnapshot
from common_lore_index.artifacts.sealing_governance import (
    CLASSIFICATION_MAX_RETAINED_CHARS,
    STABLE_CAPTURE_MAX_ATTEMPTS,
    SealingBudget,
    effective_max_directory_entries,
    planned_min_read_bytes,
)

from ._contracts_v2 import ResourceLimitV2, ResourceMetricV2
from ._slots_v2 import PLAN_METRICS, SEALING_METRICS


def _sealing_values(snapshot: SealingMeterSnapshot) -> dict[str, int]:
    return {
        "sealing_read_bytes": snapshot.read_bytes,
        "sealing_discovery_read_bytes": snapshot.reader("discovery"),
        "sealing_classification_read_bytes": snapshot.reader("classification"),
        "sealing_capture_read_bytes": snapshot.reader("capture"),
        "sealing_copy_read_bytes": snapshot.reader("copy"),
        "sealing_store_read_bytes": snapshot.reader("store"),
        "sealing_write_bytes": snapshot.write_bytes,
        "sealing_read_calls": snapshot.read_calls,
        "sealing_opens": snapshot.opens,
        "sealing_directory_entries": snapshot.directory_entries,
        "sealing_fsyncs": snapshot.fsyncs,
        "sealing_capture_retries": snapshot.capture_retries,
    }


def sealing_metrics(snapshot: SealingMeterSnapshot | None) -> tuple[ResourceMetricV2, ...]:
    if snapshot is None:
        return tuple(
            ResourceMetricV2.unavailable(name, unit, None, "not_started")
            for name, unit, _ in SEALING_METRICS
        )
    basis = "call_meter_exact" if snapshot.complete else "call_meter_partial"
    values = _sealing_values(snapshot)
    return tuple(
        ResourceMetricV2.measured(name, values[name], unit, basis)
        for name, unit, _ in SEALING_METRICS
    )


def plan_metrics(snapshot: SealingMeterSnapshot | None) -> tuple[ResourceMetricV2, ...]:
    plan = None if snapshot is None else snapshot.plan
    if plan is None:
        reason = "not_started" if snapshot is None else (
            "not_reached" if snapshot.governed else "not_selected"
        )
        return tuple(
            ResourceMetricV2.unavailable(name, unit, None, reason) for name, unit, _ in PLAN_METRICS
        )
    return (
        ResourceMetricV2.measured("planned_inventory_files", plan.inventory_files, "count", "metadata_inventory"),
        ResourceMetricV2.measured("planned_inventory_bytes", plan.inventory_bytes, "bytes", "metadata_inventory"),
        ResourceMetricV2.measured(
            "planned_min_read_bytes", planned_min_read_bytes(plan.inventory_bytes),
            "bytes", "derived_lower_bound",
        ),
    )


def _field(budget: SealingBudget | None, name: str) -> int | None:
    return None if budget is None else getattr(budget, name)


def governance_limits(
    budget: SealingBudget | None, *, entered: bool
) -> tuple[ResourceLimitV2, ...]:
    """The nine v2 governance rows; ``entered`` is true once sealing began."""

    governed = budget is not None
    applies = entered if governed else (True if entered else None)

    def budget_row(name: str, value: int | None, unit: str, enforcement: str) -> ResourceLimitV2:
        if value is None:
            return ResourceLimitV2(name, None, unit, "absent", None)
        return ResourceLimitV2(name, value, unit, enforcement, entered)

    entries = effective_max_directory_entries(budget) if governed else None
    return (
        ResourceLimitV2("inventory_max_artifacts", DEFAULT_ARTIFACT_LIMITS.max_artifacts,
                        "count", "pre_body_admission", entered and governed),
        ResourceLimitV2("inventory_max_total_bytes", DEFAULT_ARTIFACT_LIMITS.max_total_bytes,
                        "bytes", "pre_body_admission", entered and governed),
        budget_row("sealing_max_read_bytes", _field(budget, "max_read_bytes"), "bytes", "call_budget_pre_io"),
        budget_row("sealing_max_write_bytes", _field(budget, "max_write_bytes"), "bytes", "call_budget_pre_io"),
        budget_row("sealing_max_opens", _field(budget, "max_opens"), "count", "call_budget_pre_io"),
        budget_row("sealing_max_directory_entries", entries, "count", "call_budget_pre_io"),
        budget_row("sealing_max_elapsed", _field(budget, "max_elapsed_ms"), "milliseconds",
                   "call_budget_cooperative"),
        ResourceLimitV2("classification_max_retained_chars", CLASSIFICATION_MAX_RETAINED_CHARS,
                        "count", "governed_owner_bound", entered and governed),
        ResourceLimitV2("stable_capture_max_attempts", STABLE_CAPTURE_MAX_ATTEMPTS,
                        "count", "owner_enforced", applies),
    )


__all__ = ("governance_limits", "plan_metrics", "sealing_metrics")
