"""Explicitly versioned ``cloe-resource-view-v2`` records (ADR 0173 E3).

Version 1 records, domains and bounds stay closed and unchanged: no v1 enum or
validator is widened. A v2 record is a separate class whose closed sets are the
v1 sets plus the additions below, selected before construction. Bounds are
16,384 payload bytes, 48 metrics and 24 limits.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._canonical import CanonicalBoundError, canonical_bytes
from ._contracts import (
    LIMIT_NAMES, METRIC_NAMES, OUTCOMES, Availability, Backend, Basis, Enforcement,
    Instrumentation, Operation, ResourceReport, Unit,
    UnavailableReason, _closed, _integer,
)

SCHEMA_V2 = "cloe-resource-view-v2"
MAX_PAYLOAD_BYTES_V2 = 16384
MAX_METRICS_V2 = 48
MAX_LIMITS_V2 = 24

NEW_BASES = frozenset({
    "call_meter_exact", "call_meter_partial", "metadata_inventory", "derived_lower_bound",
    "wait4_self_and_waited_descendants", "wait4_max_single_process_rss",
    "wait4_platform_defined", "supervisor_record", "process_group_probe",
})
NEW_REASONS = frozenset({"platform_unsupported", "reaped_elsewhere"})
NEW_ENFORCEMENT = frozenset({
    "call_budget_pre_io", "call_budget_cooperative", "pre_body_admission", "governed_owner_bound",
})
NEW_METRIC_NAMES = frozenset({
    "sealing_read_bytes", "sealing_discovery_read_bytes", "sealing_classification_read_bytes",
    "sealing_capture_read_bytes", "sealing_copy_read_bytes", "sealing_store_read_bytes",
    "sealing_write_bytes", "sealing_read_calls", "sealing_opens", "sealing_directory_entries",
    "sealing_fsyncs", "sealing_capture_retries", "planned_inventory_files",
    "planned_inventory_bytes", "planned_min_read_bytes", "worker_launches", "worker_user_cpu",
    "worker_system_cpu", "worker_group_members_after_reap",
})
NEW_LIMIT_NAMES = frozenset({
    "inventory_max_artifacts", "inventory_max_total_bytes", "sealing_max_read_bytes",
    "sealing_max_write_bytes", "sealing_max_opens", "sealing_max_directory_entries",
    "sealing_max_elapsed", "classification_max_retained_chars", "stable_capture_max_attempts",
})

BASES_V2 = frozenset(item.value for item in Basis) | NEW_BASES
REASONS_V2 = frozenset(item.value for item in UnavailableReason) | NEW_REASONS
ENFORCEMENT_V2 = frozenset(item.value for item in Enforcement) | NEW_ENFORCEMENT
METRIC_NAMES_V2 = METRIC_NAMES | NEW_METRIC_NAMES
LIMIT_NAMES_V2 = LIMIT_NAMES | NEW_LIMIT_NAMES
OUTCOMES_V2 = OUTCOMES
_UNITS = frozenset(item.value for item in Unit)
_AVAILABILITY = frozenset(item.value for item in Availability)
_OPERATIONS = frozenset(item.value for item in Operation)
_BACKENDS = frozenset(item.value for item in Backend)
_INSTRUMENTATION = frozenset(item.value for item in Instrumentation)


@dataclass(frozen=True, slots=True)
class ResourceMetricV2:
    """One v2 metric row; the v1 measured/unavailable invariants still hold."""

    name: str
    value: int | None
    unit: str
    availability: str
    basis: str | None
    reason: str | None = None

    def __post_init__(self) -> None:
        _closed(self.name, METRIC_NAMES_V2, "metric name")
        _closed(self.unit, _UNITS, "metric unit")
        _closed(self.availability, _AVAILABILITY, "metric availability")
        if self.basis is not None:
            _closed(self.basis, BASES_V2, "metric basis")
        if self.availability == Availability.MEASURED:
            if self.basis is None:
                raise ValueError("measured metric requires a basis")
            _integer(self.value, "metric value")
            if self.reason is not None:
                raise ValueError("measured metric cannot have an unavailable reason")
        else:
            if self.value is not None:
                raise ValueError("unavailable metric cannot have a value")
            if self.reason is None:
                raise ValueError("unavailable metric requires a reason")
            _closed(self.reason, REASONS_V2, "metric reason")

    @classmethod
    def measured(cls, name: str, value: int, unit: str, basis: str) -> "ResourceMetricV2":
        return cls(name, value, unit, Availability.MEASURED, basis)

    @classmethod
    def unavailable(cls, name: str, unit: str, basis: str | None, reason: str) -> "ResourceMetricV2":
        return cls(name, None, unit, Availability.UNAVAILABLE, basis, reason)

    def to_payload(self) -> dict[str, object]:
        return {
            "name": self.name, "value": self.value, "unit": self.unit,
            "availability": self.availability, "basis": self.basis, "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ResourceLimitV2:
    """One v2 control row; absent controls carry neither value nor applicability."""

    name: str
    value: int | None
    unit: str
    enforcement: str
    applies_this_call: bool | None

    def __post_init__(self) -> None:
        _closed(self.name, LIMIT_NAMES_V2, "limit name")
        _closed(self.unit, _UNITS, "limit unit")
        _closed(self.enforcement, ENFORCEMENT_V2, "limit enforcement")
        if self.value is not None:
            _integer(self.value, "limit value")
        if not isinstance(self.applies_this_call, (bool, type(None))):
            raise ValueError("limit applicability is invalid")
        if self.enforcement == Enforcement.ABSENT:
            if self.value is not None or self.applies_this_call is not None:
                raise ValueError("absent limit must be null")
        elif self.value is None:
            raise ValueError("non-absent limit requires a value")

    def to_payload(self) -> dict[str, object]:
        return {
            "name": self.name, "value": self.value, "unit": self.unit,
            "enforcement": self.enforcement, "applies_this_call": self.applies_this_call,
        }


@dataclass(frozen=True, slots=True)
class ResourceReportV2:
    """A detached ``cloe-resource-view-v2`` report constructed at the call boundary."""

    schema: str
    operation: str | None
    backend: str | None
    outcome: str
    instrumentation: str
    metrics: tuple[ResourceMetricV2, ...] = ()
    limits: tuple[ResourceLimitV2, ...] = ()

    def __post_init__(self) -> None:
        from ._slots_v2 import check_operation_pairing_v2

        if self.schema != SCHEMA_V2:
            raise ValueError("resource report schema is invalid")
        if self.operation is not None:
            _closed(self.operation, _OPERATIONS, "resource operation")
        if self.backend is not None:
            _closed(self.backend, _BACKENDS, "resource backend")
        _closed(self.outcome, OUTCOMES_V2, "resource outcome")
        _closed(self.instrumentation, _INSTRUMENTATION, "resource instrumentation")
        check_operation_pairing_v2(self.operation, self.backend, self.outcome)
        if not isinstance(self.metrics, tuple) or len(self.metrics) > MAX_METRICS_V2:
            raise ValueError("resource metrics exceed the fixed bound")
        if not isinstance(self.limits, tuple) or len(self.limits) > MAX_LIMITS_V2:
            raise ValueError("resource limits exceed the fixed bound")
        if any(type(item) is not ResourceMetricV2 for item in self.metrics):
            raise ValueError("resource metric record is invalid")
        if any(type(item) is not ResourceLimitV2 for item in self.limits):
            raise ValueError("resource limit record is invalid")
        if len({item.name for item in self.metrics}) != len(self.metrics):
            raise ValueError("resource metric slot repeated")
        if len({item.name for item in self.limits}) != len(self.limits):
            raise ValueError("resource limit slot repeated")
        try:
            canonical_bytes(self.to_payload(), MAX_PAYLOAD_BYTES_V2)
        except CanonicalBoundError:
            raise ValueError("resource report payload exceeds 16384 bytes") from None

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema, "operation": self.operation, "backend": self.backend,
            "outcome": self.outcome, "instrumentation": self.instrumentation,
            "metrics": [item.to_payload() for item in self.metrics],
            "limits": [item.to_payload() for item in self.limits],
        }


def upgrade_report(report: ResourceReport) -> ResourceReportV2:
    """Re-express a v1 report whose operation tables are equal in v2."""

    if type(report) is not ResourceReport:
        raise ValueError("resource report is not a v1 record")
    return ResourceReportV2(
        SCHEMA_V2, report.operation, report.backend, report.outcome, report.instrumentation,
        tuple(
            ResourceMetricV2(item.name, item.value, item.unit, item.availability, item.basis, item.reason)
            for item in report.metrics
        ),
        tuple(
            ResourceLimitV2(item.name, item.value, item.unit, item.enforcement, item.applies_this_call)
            for item in report.limits
        ),
    )


__all__ = (
    "BASES_V2", "ENFORCEMENT_V2", "LIMIT_NAMES_V2", "MAX_LIMITS_V2", "MAX_METRICS_V2",
    "MAX_PAYLOAD_BYTES_V2", "METRIC_NAMES_V2", "NEW_BASES", "NEW_ENFORCEMENT",
    "NEW_LIMIT_NAMES", "NEW_METRIC_NAMES", "NEW_REASONS", "REASONS_V2", "ResourceLimitV2",
    "ResourceMetricV2", "ResourceReportV2", "SCHEMA_V2", "upgrade_report",
)
