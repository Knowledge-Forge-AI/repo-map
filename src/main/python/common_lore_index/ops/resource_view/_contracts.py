"""Closed, detached records for the internal CLOE resource view."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ._canonical import CanonicalBoundError, canonical_bytes
from ._slots import check_operation_pairing


SCHEMA = "cloe-resource-view-v1"
MAX_PAYLOAD_BYTES = 8192
MAX_METRICS = 24
MAX_LIMITS = 16


class Operation(StrEnum):
    LOCAL_REFRESH = "local_refresh"
    SERVER_REFRESH = "server_refresh"
    LEXICAL_BUILD = "lexical_build"
    COMPACT_CONTEXT = "compact_context"
    LEXICAL_QUERY = "lexical_query"
    LEXICAL_REVOKE = "lexical_revoke"


class Backend(StrEnum):
    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"


class Instrumentation(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    DEGRADED = "degraded"


class Availability(StrEnum):
    MEASURED = "measured"
    UNAVAILABLE = "unavailable"


class Basis(StrEnum):
    MONOTONIC_SPAN = "monotonic_span"
    PROCESS_CLOCK_INCLUSIVE = "process_clock_inclusive"
    ACCEPTED_MANIFEST_TOTAL = "accepted_manifest_total"
    PARENT_VALIDATED_TOTAL = "parent_validated_total"
    OWNER_AGGREGATE = "owner_aggregate"
    LEDGER_COUNTER = "ledger_counter"
    LEDGER_LOWER_BOUND = "ledger_lower_bound"
    OWNER_PARAMETER = "owner_parameter"
    OWNER_CONSTANT = "owner_constant"
    ESTIMATE = "estimate"
    SHARED_UPPER_BOUND = "shared_upper_bound"
    SAMPLED_MAX = "sampled_max"
    PROCESS_LIFETIME_PEAK = "process_lifetime_peak"


class UnavailableReason(StrEnum):
    NOT_STARTED = "not_started"
    NOT_REACHED = "not_reached"
    NOT_SELECTED = "not_selected"
    NOT_OBSERVED = "not_observed"
    BACKEND_NOT_APPLICABLE = "backend_not_applicable"
    NOT_EMITTED = "not_emitted"
    AMBIGUOUS_REPEAT = "ambiguous_repeat"
    INVALID_OWNER_VALUE = "invalid_owner_value"
    OBSERVER_FAILED = "observer_failed"


class Unit(StrEnum):
    NANOSECONDS = "nanoseconds"
    MILLISECONDS = "milliseconds"
    SECONDS = "seconds"
    BYTES = "bytes"
    COUNT = "count"


class Enforcement(StrEnum):
    PARENT_SUPERVISED = "parent_supervised"
    DECLARED_TO_WORKER = "declared_to_worker"
    POST_CAPTURE_VALIDATION = "post_capture_validation"
    DATABASE_STATEMENT_TIMEOUT = "database_statement_timeout"
    OWNER_ENFORCED = "owner_enforced"
    ABSENT = "absent"


OUTCOMES = frozenset(
    {
        "published", "reconciled_replay", "committed", "failed", "commit_unknown",
        "cancelled", "refused", "unclassified", "not_recorded", "complete",
        "partial", "stale", "unavailable", "budget_error", "available", "not_run",
        "revoked", "preview",
    }
)
METRIC_NAMES = frozenset(
    {
        "operation_elapsed", "operation_process_cpu", "lock_and_reconcile_elapsed",
        "capture_elapsed", "validation_elapsed", "publication_elapsed",
        "sealed_manifest_files", "sealed_manifest_bytes", "validated_bundle_records",
        "validated_bundle_bytes", "worker_cpu", "worker_peak_rss",
        "lexical_input_bytes", "lexical_projected_bytes", "lexical_documents",
        "lexical_omissions", "config_revalidations_executed", "logical_read_units",
        "sql_statements_executed", "scan_units_executed", "seed_expansions_executed",
        "candidate_rows_scanned", "evidence_rows_scanned", "elapsed_ms", "actual_bytes",
        "sqlite_progress_callbacks", "sqlite_vm_steps_estimate", "sqlite_progress_interval_ops",
        "wal_upper_bound", "temporary_byte_upper_bound", "postgresql_memory", "client_memory",
        "query_hits_returned", "query_omissions_returned", "revoked_generations",
        "revoked_authority_rows", "purged_documents", "purged_chunks", "purged_omissions",
    }
)
LIMIT_NAMES = frozenset(
    {
        "worker_process_deadline", "worker_max_artifact_bytes", "worker_max_bundle_bytes",
        "manifest_max_artifacts", "manifest_max_total_bytes", "sealing_io_limit",
        "max_projected_files", "max_aggregate_input_bytes", "max_input_artifact_bytes",
        "max_projected_file_bytes", "max_chunk_lines", "max_chunk_bytes",
        "lexical_build_statement_timeout", "max_logical_read_units", "max_sql_statements",
        "max_scan_units", "max_seed_expansions", "budget_bytes", "wall_clock_deadline",
        "sqlite_progress_callback_limit", "query_result_limit", "query_max_occurrences_per_file",
        "lexical_query_statement_timeout", "lexical_revoke_statement_timeout",
    }
)
_OPERATIONS = frozenset(item.value for item in Operation)
_BACKENDS = frozenset(item.value for item in Backend)
_INSTRUMENTATION = frozenset(item.value for item in Instrumentation)
_AVAILABILITY = frozenset(item.value for item in Availability)
_BASES = frozenset(item.value for item in Basis)
_REASONS = frozenset(item.value for item in UnavailableReason)
_UNITS = frozenset(item.value for item in Unit)
_ENFORCEMENT = frozenset(item.value for item in Enforcement)


def _closed(value: object, values: frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in values:
        raise ValueError(f"{label} is not a closed value")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


@dataclass(frozen=True, slots=True)
class ResourceMetric:
    """One bounded, identifier-free resource measurement."""

    name: str
    value: int | None
    unit: str
    availability: str
    basis: str | None
    reason: str | None = None

    def __post_init__(self) -> None:
        _closed(self.name, METRIC_NAMES, "metric name")
        _closed(self.unit, _UNITS, "metric unit")
        _closed(self.availability, _AVAILABILITY, "metric availability")
        if self.basis is not None:
            _closed(self.basis, _BASES, "metric basis")
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
            _closed(self.reason, _REASONS, "metric reason")

    @classmethod
    def measured(cls, name: str, value: int, unit: str, basis: str) -> "ResourceMetric":
        return cls(name, value, unit, Availability.MEASURED, basis)

    @classmethod
    def unavailable(
        cls, name: str, unit: str, basis: str | None, reason: str
    ) -> "ResourceMetric":
        return cls(name, None, unit, Availability.UNAVAILABLE, basis, reason)

    def to_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "availability": self.availability,
            "basis": self.basis,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ResourceLimit:
    """One existing owner control, reported without adding enforcement."""

    name: str
    value: int | None
    unit: str
    enforcement: str
    applies_this_call: bool | None

    def __post_init__(self) -> None:
        _closed(self.name, LIMIT_NAMES, "limit name")
        _closed(self.unit, _UNITS, "limit unit")
        _closed(self.enforcement, _ENFORCEMENT, "limit enforcement")
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
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "enforcement": self.enforcement,
            "applies_this_call": self.applies_this_call,
        }


@dataclass(frozen=True, slots=True)
class ResourceReport:
    """A detached, frozen report constructed once at the call boundary."""

    schema: str
    operation: str | None
    backend: str | None
    outcome: str
    instrumentation: str
    metrics: tuple[ResourceMetric, ...] = ()
    limits: tuple[ResourceLimit, ...] = ()

    def __post_init__(self) -> None:
        if self.schema != SCHEMA:
            raise ValueError("resource report schema is invalid")
        if self.operation is not None:
            _closed(self.operation, _OPERATIONS, "resource operation")
        if self.backend is not None:
            _closed(self.backend, _BACKENDS, "resource backend")
        _closed(self.outcome, OUTCOMES, "resource outcome")
        _closed(self.instrumentation, _INSTRUMENTATION, "resource instrumentation")
        check_operation_pairing(self.operation, self.backend, self.outcome)
        if not isinstance(self.metrics, tuple) or len(self.metrics) > MAX_METRICS:
            raise ValueError("resource metrics exceed the fixed bound")
        if not isinstance(self.limits, tuple) or len(self.limits) > MAX_LIMITS:
            raise ValueError("resource limits exceed the fixed bound")
        if any(not isinstance(item, ResourceMetric) for item in self.metrics):
            raise ValueError("resource metric record is invalid")
        if any(not isinstance(item, ResourceLimit) for item in self.limits):
            raise ValueError("resource limit record is invalid")
        if len({item.name for item in self.metrics}) != len(self.metrics):
            raise ValueError("resource metric slot repeated")
        if len({item.name for item in self.limits}) != len(self.limits):
            raise ValueError("resource limit slot repeated")
        self._assert_payload_bound()

    def _assert_payload_bound(self) -> None:
        try:
            canonical_bytes(self.to_payload(), MAX_PAYLOAD_BYTES)
        except CanonicalBoundError:
            raise ValueError("resource report payload exceeds 8192 bytes") from None

    def to_payload(self) -> dict[str, object]:
        """Return a fresh primitive-only mapping detached from the report."""
        return {
            "schema": self.schema,
            "operation": self.operation,
            "backend": self.backend,
            "outcome": self.outcome,
            "instrumentation": self.instrumentation,
            "metrics": [item.to_payload() for item in self.metrics],
            "limits": [item.to_payload() for item in self.limits],
        }


def report_payload(report: ResourceReport) -> dict[str, Any]:
    """Typed convenience used by tests without exposing mutable internals."""
    return report.to_payload()


__all__ = (
    "Availability", "Backend", "Basis", "Enforcement", "Instrumentation", "Operation",
    "ResourceLimit", "ResourceMetric", "ResourceReport", "SCHEMA", "Unit",
    "UnavailableReason", "MAX_LIMITS", "MAX_METRICS", "MAX_PAYLOAD_BYTES", "report_payload",
)
