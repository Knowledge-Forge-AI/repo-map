"""Explicitly versioned v2 records and tables; v1 domains, bounds and tables unchanged."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

import pytest

from common_lore_index.ops.resource_view._canonical import canonical_bytes
from common_lore_index.ops.resource_view._contracts import (
    MAX_LIMITS, MAX_METRICS, MAX_PAYLOAD_BYTES, SCHEMA, ResourceLimit, ResourceMetric, ResourceReport,
)
from common_lore_index.ops.resource_view._contracts_v2 import (
    MAX_LIMITS_V2, MAX_METRICS_V2, MAX_PAYLOAD_BYTES_V2, NEW_BASES, NEW_ENFORCEMENT, NEW_LIMIT_NAMES,
    NEW_METRIC_NAMES, NEW_REASONS, SCHEMA_V2, ResourceLimitV2, ResourceMetricV2, ResourceReportV2,
    upgrade_report,
)
from common_lore_index.ops.resource_view._slots import LIMIT_SLOTS, METRIC_SLOTS, OUTCOMES_BY_OPERATION
from common_lore_index.ops.resource_view._slots_v2 import (
    LIMIT_SLOTS_V2, METRIC_SLOTS_V2, OUTCOMES_BY_OPERATION_V2, check_report_domain_v2,
)

# The closed v1 tables at the source parent; any v1 widening changes these pins.
V1_TABLE_DIGEST = "e9de7eeb799dca28a5e975323e84951dba79cb62961ac890c52f39d5172c6767"
V1_TABLES = {
    "metrics": "local_refresh:12,server_refresh:11,lexical_build:6,compact_context:12,lexical_query:4,lexical_revoke:7",
    "limits": "local_refresh:6,server_refresh:6,lexical_build:7,compact_context:7,lexical_query:3,lexical_revoke:1",
}


def _shape(table: dict) -> str:
    return ",".join(f"{operation}:{len(rows)}" for operation, rows in table.items())


def test_v1_tables_bounds_and_schema_are_unchanged() -> None:
    assert (SCHEMA, MAX_PAYLOAD_BYTES, MAX_METRICS, MAX_LIMITS) == ("cloe-resource-view-v1", 8192, 24, 16)
    assert _shape(METRIC_SLOTS) == V1_TABLES["metrics"]
    assert _shape(LIMIT_SLOTS) == V1_TABLES["limits"]
    assert LIMIT_SLOTS["local_refresh"][-1] == ("sealing_io_limit", "bytes", "absent")
    assert "refused" not in OUTCOMES_BY_OPERATION["local_refresh"] | OUTCOMES_BY_OPERATION["server_refresh"]
    digest = hashlib.sha256(json.dumps([METRIC_SLOTS, LIMIT_SLOTS], sort_keys=True).encode()).hexdigest()
    assert digest == V1_TABLE_DIGEST, "the public v1 tables are closed"


@pytest.mark.parametrize("name", sorted(NEW_METRIC_NAMES))
def test_v1_metric_records_reject_every_v2_only_name(name: str) -> None:
    with pytest.raises(ValueError):
        ResourceMetric.unavailable(name, "count", None, "not_started")
    assert ResourceMetricV2.unavailable(name, "count", None, "not_started").name == name


@pytest.mark.parametrize("value", sorted(NEW_BASES))
def test_v1_metric_records_reject_every_v2_only_basis(value: str) -> None:
    with pytest.raises(ValueError):
        ResourceMetric.measured("operation_elapsed", 1, "nanoseconds", value)
    assert ResourceMetricV2.measured("operation_elapsed", 1, "nanoseconds", value).basis == value


@pytest.mark.parametrize("value", sorted(NEW_REASONS))
def test_v1_metric_records_reject_every_v2_only_reason(value: str) -> None:
    with pytest.raises(ValueError):
        ResourceMetric.unavailable("operation_elapsed", "nanoseconds", None, value)
    ResourceMetricV2.unavailable("worker_cpu", "nanoseconds", None, value)


@pytest.mark.parametrize("enforcement", sorted(NEW_ENFORCEMENT))
def test_v1_limit_records_reject_every_v2_only_enforcement_and_name(enforcement: str) -> None:
    with pytest.raises(ValueError):
        ResourceLimit("manifest_max_artifacts", 1, "count", enforcement, True)
    for name in NEW_LIMIT_NAMES:
        with pytest.raises(ValueError):
            ResourceLimit(name, 1, "count", "owner_enforced", True)
    assert ResourceLimitV2("sealing_max_opens", 1, "count", enforcement, True).enforcement == enforcement


def test_v2_record_invariants_match_v1() -> None:
    with pytest.raises(ValueError):
        ResourceMetricV2("sealing_opens", 1, "count", "measured", None)
    with pytest.raises(ValueError):
        ResourceMetricV2("sealing_opens", 1, "count", "unavailable", None, "not_started")
    with pytest.raises(ValueError):
        ResourceMetricV2("sealing_opens", -1, "count", "measured", "call_meter_exact")
    with pytest.raises(ValueError):
        ResourceLimitV2("sealing_max_opens", 3, "count", "absent", None)
    with pytest.raises(ValueError):
        ResourceLimitV2("sealing_max_opens", None, "count", "call_budget_pre_io", True)
    with pytest.raises(ValueError):
        ResourceLimitV2("sealing_max_opens", 1, "count", "call_budget_pre_io", cast(Any, "yes"))


def test_refresh_tables_have_the_documented_rows_in_order() -> None:
    local = [name for name, _, _ in METRIC_SLOTS_V2["local_refresh"]]
    server = [name for name, _, _ in METRIC_SLOTS_V2["server_refresh"]]
    assert len(local) == 31 and len(server) == 30
    assert local[:10] == [name for name, _, _ in METRIC_SLOTS["local_refresh"]][:10]
    assert "worker_cpu" not in local[:10] and server == [name for name in local if name != "lock_and_reconcile_elapsed"]
    assert local[10:22] == [
        "sealing_read_bytes", "sealing_discovery_read_bytes", "sealing_classification_read_bytes",
        "sealing_capture_read_bytes", "sealing_copy_read_bytes", "sealing_store_read_bytes",
        "sealing_write_bytes", "sealing_read_calls", "sealing_opens", "sealing_directory_entries",
        "sealing_fsyncs", "sealing_capture_retries",
    ]
    assert local[22:] == [
        "planned_inventory_files", "planned_inventory_bytes", "planned_min_read_bytes",
        "worker_launches", "worker_cpu", "worker_user_cpu", "worker_system_cpu", "worker_peak_rss",
        "worker_group_members_after_reap",
    ]
    limits = [name for name, _, _ in LIMIT_SLOTS_V2["local_refresh"]]
    assert len(limits) == 14 and "sealing_io_limit" not in limits
    assert limits[:5] == [name for name, _, _ in LIMIT_SLOTS["local_refresh"]][:5]
    for operation in ("lexical_build", "compact_context", "lexical_query", "lexical_revoke"):
        assert [(n, u, {b}) for n, u, b in METRIC_SLOTS[operation]] == [
            (n, u, set(b)) for n, u, b in METRIC_SLOTS_V2[operation]
        ]
        assert OUTCOMES_BY_OPERATION_V2[operation] == OUTCOMES_BY_OPERATION[operation]
    assert "refused" in OUTCOMES_BY_OPERATION_V2["local_refresh"] & OUTCOMES_BY_OPERATION_V2["server_refresh"]


def _worst_case(operation: str) -> ResourceReportV2:
    big = 2**63 - 1
    metrics = []
    for name, unit, bases in METRIC_SLOTS_V2[operation]:
        basis = max((item for item in bases if item is not None), key=len, default=None)
        metrics.append(ResourceMetricV2.measured(name, big, unit, basis) if basis else
                       ResourceMetricV2.unavailable(name, unit, None, "invalid_owner_value"))
    limits = tuple(
        ResourceLimitV2(name, big, unit, max(enforcements - {"absent"}, key=len), True)
        for name, unit, enforcements in LIMIT_SLOTS_V2[operation]
    )
    return ResourceReportV2(SCHEMA_V2, operation, "sqlite" if operation == "local_refresh" else "postgresql",
                            "commit_unknown" if operation == "server_refresh" else "reconciled_replay",
                            "incomplete", tuple(metrics), limits)


@pytest.mark.parametrize("operation", ["local_refresh", "server_refresh"])
def test_worst_case_v2_payload_stays_within_three_quarters_of_the_bound(operation: str) -> None:
    report = _worst_case(operation)
    check_report_domain_v2(report)
    size = len(canonical_bytes(report.to_payload(), MAX_PAYLOAD_BYTES_V2))
    assert size <= 0.75 * MAX_PAYLOAD_BYTES_V2, size
    assert len(report.metrics) <= MAX_METRICS_V2 and len(report.limits) <= MAX_LIMITS_V2


def test_v2_report_bounds_and_record_types_are_enforced() -> None:
    with pytest.raises(ValueError, match="schema"):
        ResourceReportV2(SCHEMA, None, None, "not_recorded", "incomplete")
    with pytest.raises(ValueError, match="schema"):
        ResourceReport(SCHEMA_V2, None, None, "not_recorded", "incomplete")
    with pytest.raises(ValueError, match="record is invalid"):
        ResourceReportV2(SCHEMA_V2, "local_refresh", "sqlite", "refused", "incomplete",
                         cast(Any, (ResourceMetric.measured("operation_elapsed", 1, "nanoseconds", "monotonic_span"),)))
    with pytest.raises(ValueError, match="outcome"):
        ResourceReportV2(SCHEMA_V2, "lexical_query", "postgresql", "committed", "complete")
    too_many = tuple(ResourceMetricV2.unavailable(f"{name}", "count", None, "not_started")
                     for name in sorted(NEW_METRIC_NAMES))[:19] * 3
    with pytest.raises(ValueError):
        ResourceReportV2(SCHEMA_V2, "local_refresh", "sqlite", "refused", "incomplete", too_many)


def test_domain_check_refuses_slot_order_unit_and_basis_drift() -> None:
    report = _worst_case("local_refresh")
    swapped = ResourceReportV2(report.schema, report.operation, report.backend, report.outcome,
                               report.instrumentation, report.metrics[1:] + report.metrics[:1], report.limits)
    with pytest.raises(ValueError):
        check_report_domain_v2(swapped)
    wrong_basis = list(report.metrics)
    wrong_basis[10] = ResourceMetricV2.measured("sealing_read_bytes", 1, "bytes", "metadata_inventory")
    with pytest.raises(ValueError):
        check_report_domain_v2(ResourceReportV2(report.schema, report.operation, report.backend, report.outcome,
                                                report.instrumentation, tuple(wrong_basis), report.limits))
    reversed_limits = ResourceReportV2(report.schema, report.operation, report.backend, report.outcome,
                                       report.instrumentation, report.metrics, report.limits[::-1])
    with pytest.raises(ValueError):
        check_report_domain_v2(reversed_limits)


def test_upgrade_reexpresses_v1_tables_without_loss() -> None:
    v1 = ResourceReport(SCHEMA, "lexical_revoke", "postgresql", "preview", "complete", (), ())
    upgraded = upgrade_report(v1)
    assert upgraded.schema == SCHEMA_V2 and upgraded.to_payload() | {"schema": SCHEMA} == v1.to_payload()
    with pytest.raises(ValueError):
        upgrade_report(cast(Any, upgraded))
