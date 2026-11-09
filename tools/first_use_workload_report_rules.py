"""Report identity, sealing witness arithmetic and the plan-member codec.

Resource reports are decoded only through the product's strict codec; the
codec proves format and domain validity, never measurement truth. Expected
values come from the frozen census (``S``, ``C``), the retained manifest length
(``m``) and the recipe; never from a report or plan. ``m_c`` and ``r`` are zero
only under the witnessed fresh-attempt and stable-fixture conditions.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from common_lore_index.ops.resource_reports._codec import ResourceReportError, decode_report
from first_use_workload_domains import MAX_PLAN_MEMBER_BYTES, WorkloadError
from first_use_workload_encoding import closed, decode_record, is_count
from first_use_workload_recipe_shapes import ReportSpec

REPORT_SCHEMAS = {1: "cloe-resource-view-v1", 2: "cloe-resource-view-v2"}
CANARY_TEXT = (b"mixed-v1",)
PLAN_SCHEMA = "cloe-sealing-plan-v1"
PLAN_KEYS = (
    "bindings", "directory_entries", "effective_max_directory_entries", "factors",
    "instrumentation", "inventory_bytes", "inventory_files", "inventory_symlinked_files",
    "opens", "planned_min_read_bytes", "planned_min_read_bytes_basis", "planned_min_write_bytes",
    "projected_directory_entries", "projection_basis", "refusal", "schema",
)
PLAN_FACTOR_KEYS = (
    "collision_extra_reads_per_file", "full_body_reads_per_file", "stable_capture_max_attempts",
)
SEALING_READS = (
    "sealing_read_bytes", "sealing_copy_read_bytes", "sealing_capture_read_bytes",
    "sealing_store_read_bytes", "sealing_discovery_read_bytes", "sealing_classification_read_bytes",
)


def decode_report_member(data: bytes) -> dict[str, Any]:
    try:
        return decode_report(data).to_payload()
    except ResourceReportError:
        raise WorkloadError("report_mismatch") from None


def _row(payload: Mapping[str, Any], group: str, name: str) -> Mapping[str, Any] | None:
    for item in payload.get(group, ()):
        if item.get("name") == name:
            return item
    return None


def metric_value(payload: Mapping[str, Any], name: str) -> object:
    row = _row(payload, "metrics", name)
    return None if row is None else row.get("value")


def metric_basis(payload: Mapping[str, Any], name: str) -> object:
    row = _row(payload, "metrics", name)
    return None if row is None else row.get("basis")


def limit_field(payload: Mapping[str, Any], name: str, key: str) -> object:
    row = _row(payload, "limits", name)
    return None if row is None else row.get(key)


def report_identity(spec: ReportSpec, payload: Mapping[str, Any], data: bytes) -> set[str]:
    """Recipe labels, schema version and canary-free bytes of one report member."""
    found = (
        payload.get("schema") == REPORT_SCHEMAS[spec.schema]
        and payload.get("operation") == spec.operation
        and payload.get("backend") == spec.backend
        and payload.get("outcome") in spec.outcomes
        and (spec.instrumentation is None or payload.get("instrumentation") == spec.instrumentation)
        and not any(text in data for text in CANARY_TEXT)
    )
    return set() if found else {"report_mismatch"}


def publish_formula(payload: Mapping[str, Any], *, S: int, C: int, m: int) -> set[str]:
    """Ordinary publish under a fresh attempt store and stable fixture: ``m_c = r = 0``."""
    expected = {
        "sealed_manifest_bytes": S,
        "sealing_read_bytes": 4 * S + C + m,
        "sealing_copy_read_bytes": S,
        "sealing_capture_read_bytes": 2 * S,
        "sealing_store_read_bytes": S + C + m,
        "sealing_write_bytes": S + m,
        "sealing_discovery_read_bytes": 0,
        "sealing_classification_read_bytes": 0,
    }
    exact = ("sealing_read_bytes", "sealing_discovery_read_bytes", "sealing_classification_read_bytes")
    ok = all(metric_value(payload, name) == value for name, value in expected.items())
    ok = ok and all(metric_basis(payload, name) == "call_meter_exact" for name in exact)
    ok = ok and limit_field(payload, "classification_max_retained_chars", "applies_this_call") is False
    return set() if ok else {"report_mismatch"}


def planned_refusal_formula(payload: Mapping[str, Any], *, S: int, multiplier: int) -> set[str]:
    """Explicit limit ``4S``, lower bound ``4S+1``, no launch and no sealing read."""
    ok = (
        metric_value(payload, "planned_inventory_bytes") == S
        and metric_value(payload, "planned_min_read_bytes") == 4 * S + 1
        and limit_field(payload, "sealing_max_read_bytes", "value") == multiplier * S
        and metric_value(payload, "worker_launches") == 0
        and all(metric_value(payload, name) == 0 for name in SEALING_READS)
        and limit_field(payload, "classification_max_retained_chars", "applies_this_call") is False
    )
    return set() if ok else {"report_mismatch"}


def decode_plan_member(data: bytes) -> dict[str, Any]:
    """Strict canonical ``cloe-sealing-plan-v1`` member; values are only typed here."""
    if any(text in data for text in CANARY_TEXT):
        raise WorkloadError("report_mismatch")
    try:
        plan = closed(decode_record(data, MAX_PLAN_MEMBER_BYTES), PLAN_KEYS)
        factors = closed(plan["factors"], PLAN_FACTOR_KEYS)
    except WorkloadError:
        raise WorkloadError("report_mismatch") from None
    counts = (
        "directory_entries", "effective_max_directory_entries", "opens",
        "projected_directory_entries", *PLAN_FACTOR_KEYS,
    )
    nullable = (
        "bindings", "inventory_bytes", "inventory_files", "inventory_symlinked_files",
        "planned_min_read_bytes", "planned_min_write_bytes",
    )
    merged = {**plan, **factors}
    ok = (
        plan["schema"] == PLAN_SCHEMA
        and all(is_count(merged[key]) for key in counts)
        and all(plan[key] is None or is_count(plan[key]) for key in nullable)
        and (plan["refusal"] is None or type(plan["refusal"]) is str)
        and type(plan["instrumentation"]) is str
        and type(plan["planned_min_read_bytes_basis"]) is str
        and type(plan["projection_basis"]) is str
    )
    if not ok:
        raise WorkloadError("report_mismatch")
    return plan


def plan_rules(plan: Mapping[str, Any], facts: Mapping[str, Any], *, S: int) -> set[str]:
    """Plan agrees with its facts; ``S`` and ``4S+1`` come from the census."""
    categories: set[str] = set()
    for key in ("inventory_bytes", "inventory_files", "planned_min_read_bytes"):
        if facts[key] is None:
            categories.add("witness_missing")
        elif facts[key] != plan[key]:
            categories.add("report_mismatch")
    if plan["refusal"] is not None or plan["instrumentation"] != "complete":
        categories.add("report_mismatch")
    if plan["planned_min_read_bytes_basis"] != "derived_lower_bound":
        categories.add("report_mismatch")
    if plan["inventory_bytes"] != S or plan["planned_min_read_bytes"] != 4 * S + 1:
        categories.add("witness_mismatch")
    return categories


__all__ = [
    "PLAN_KEYS", "decode_plan_member", "decode_report_member", "limit_field", "metric_basis",
    "metric_value", "plan_rules", "planned_refusal_formula", "publish_formula", "report_identity",
]
