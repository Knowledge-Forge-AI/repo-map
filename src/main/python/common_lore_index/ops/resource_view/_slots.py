"""Explicit per-operation slot, limit, backend and outcome tables.

Producers and the strict report reader share these tables. They are plain
string tables so the closed record module can import them without a cycle.
Once ``cloe-resource-view-v1`` is public, growing any table requires a schema
bump rather than an in-place vocabulary change.
"""

from __future__ import annotations

from typing import Any

MetricSlot = tuple[str, str, str | None]
LimitSlot = tuple[str, str, str]

_NS, _MS, _S, _BYTES, _COUNT = "nanoseconds", "milliseconds", "seconds", "bytes", "count"
_SPAN, _CPU, _AGGREGATE = "monotonic_span", "process_clock_inclusive", "owner_aggregate"

_TIMES: tuple[MetricSlot, ...] = (
    ("operation_elapsed", _NS, _SPAN),
    ("operation_process_cpu", _NS, _CPU),
)
_STAGES: tuple[MetricSlot, ...] = (
    ("lock_and_reconcile_elapsed", _NS, _SPAN),
    ("capture_elapsed", _NS, _SPAN),
    ("validation_elapsed", _NS, _SPAN),
    ("publication_elapsed", _NS, _SPAN),
)
_REFRESH_TOTALS: tuple[MetricSlot, ...] = (
    ("sealed_manifest_files", _COUNT, "accepted_manifest_total"),
    ("sealed_manifest_bytes", _BYTES, "accepted_manifest_total"),
    ("validated_bundle_records", _COUNT, "parent_validated_total"),
    ("validated_bundle_bytes", _BYTES, "parent_validated_total"),
    ("worker_cpu", _NS, None),
    ("worker_peak_rss", _BYTES, None),
)
_CONTEXT_COUNTERS = (
    "config_revalidations_executed", "logical_read_units", "sql_statements_executed",
    "scan_units_executed", "seed_expansions_executed", "candidate_rows_scanned",
    "evidence_rows_scanned",
)

METRIC_SLOTS: dict[str, tuple[MetricSlot, ...]] = {
    "local_refresh": _TIMES + _STAGES + _REFRESH_TOTALS,
    "server_refresh": _TIMES + _STAGES[1:] + _REFRESH_TOTALS,
    "lexical_build": _TIMES + (
        ("lexical_input_bytes", _BYTES, _AGGREGATE),
        ("lexical_projected_bytes", _BYTES, _AGGREGATE),
        ("lexical_documents", _COUNT, _AGGREGATE),
        ("lexical_omissions", _COUNT, _AGGREGATE),
    ),
    "compact_context": tuple((name, _COUNT, "ledger_counter") for name in _CONTEXT_COUNTERS) + (
        ("elapsed_ms", _MS, "ledger_lower_bound"),
        ("actual_bytes", _BYTES, "ledger_counter"),
        ("sqlite_progress_callbacks", _COUNT, "ledger_counter"),
        ("sqlite_vm_steps_estimate", _COUNT, "estimate"),
        ("sqlite_progress_interval_ops", _COUNT, "owner_parameter"),
    ),
    "lexical_query": _TIMES + (
        ("query_hits_returned", _COUNT, _AGGREGATE),
        ("query_omissions_returned", _COUNT, _AGGREGATE),
    ),
    "lexical_revoke": _TIMES + (
        ("revoked_generations", _COUNT, _AGGREGATE),
        ("revoked_authority_rows", _COUNT, _AGGREGATE),
        ("purged_documents", _COUNT, _AGGREGATE),
        ("purged_chunks", _COUNT, _AGGREGATE),
        ("purged_omissions", _COUNT, _AGGREGATE),
    ),
}

_REFRESH_LIMITS: tuple[LimitSlot, ...] = (
    ("worker_process_deadline", _S, "parent_supervised"),
    ("worker_max_artifact_bytes", _BYTES, "declared_to_worker"),
    ("worker_max_bundle_bytes", _BYTES, "declared_to_worker"),
    ("manifest_max_artifacts", _COUNT, "post_capture_validation"),
    ("manifest_max_total_bytes", _BYTES, "post_capture_validation"),
    ("sealing_io_limit", _BYTES, "absent"),
)
LIMIT_SLOTS: dict[str, tuple[LimitSlot, ...]] = {
    "local_refresh": _REFRESH_LIMITS,
    "server_refresh": _REFRESH_LIMITS,
    "lexical_build": (
        ("max_projected_files", _COUNT, "owner_enforced"),
        ("max_aggregate_input_bytes", _BYTES, "owner_enforced"),
        ("max_input_artifact_bytes", _BYTES, "owner_enforced"),
        ("max_projected_file_bytes", _BYTES, "owner_enforced"),
        ("max_chunk_lines", _COUNT, "owner_enforced"),
        ("max_chunk_bytes", _BYTES, "owner_enforced"),
        ("lexical_build_statement_timeout", _MS, "database_statement_timeout"),
    ),
    "compact_context": (
        ("max_logical_read_units", _COUNT, "owner_enforced"),
        ("max_sql_statements", _COUNT, "owner_enforced"),
        ("max_scan_units", _COUNT, "owner_enforced"),
        ("max_seed_expansions", _COUNT, "owner_enforced"),
        ("budget_bytes", _BYTES, "owner_enforced"),
        ("wall_clock_deadline", _MS, "owner_enforced"),
        ("sqlite_progress_callback_limit", _COUNT, "owner_enforced"),
    ),
    "lexical_query": (
        ("query_result_limit", _COUNT, "owner_enforced"),
        ("query_max_occurrences_per_file", _COUNT, "owner_enforced"),
        ("lexical_query_statement_timeout", _MS, "database_statement_timeout"),
    ),
    "lexical_revoke": (
        ("lexical_revoke_statement_timeout", _MS, "database_statement_timeout"),
    ),
}

_UNRECORDED = frozenset({"not_recorded", "unclassified"})
OUTCOMES_BY_OPERATION: dict[str | None, frozenset[str]] = {
    None: _UNRECORDED,
    "local_refresh": _UNRECORDED | {"published", "reconciled_replay"},
    "server_refresh": _UNRECORDED | {"committed", "failed", "commit_unknown", "cancelled"},
    "lexical_build": _UNRECORDED | {"published", "refused"},
    "compact_context": _UNRECORDED | {
        "complete", "partial", "refused", "stale", "unavailable", "failed", "budget_error",
    },
    "lexical_query": _UNRECORDED | {
        "available", "partial", "refused", "stale", "unavailable", "failed", "not_run",
    },
    "lexical_revoke": _UNRECORDED | {"revoked", "preview"},
}
BACKENDS_BY_OPERATION: dict[str | None, frozenset[str | None]] = {
    None: frozenset({None}),
    "local_refresh": frozenset({"sqlite"}),
    "server_refresh": frozenset({"postgresql"}),
    "lexical_build": frozenset({"postgresql"}),
    "compact_context": frozenset({None, "sqlite", "postgresql"}),
    "lexical_query": frozenset({"postgresql"}),
    "lexical_revoke": frozenset({"postgresql"}),
}
ALL_OUTCOMES = frozenset().union(*OUTCOMES_BY_OPERATION.values())
ALL_METRIC_NAMES = frozenset(name for rows in METRIC_SLOTS.values() for name, _, _ in rows)
ALL_LIMIT_NAMES = frozenset(name for rows in LIMIT_SLOTS.values() for name, _, _ in rows)


def check_operation_pairing(operation: str | None, backend: str | None, outcome: str) -> None:
    """Refuse an operation/backend/outcome triple that no producer can emit."""
    if backend not in BACKENDS_BY_OPERATION.get(operation, frozenset()):
        raise ValueError("resource backend does not match operation")
    if outcome not in OUTCOMES_BY_OPERATION.get(operation, frozenset()):
        raise ValueError("resource outcome does not match operation")


def check_report_domain(report: Any) -> None:
    """Validate per-operation metric and limit slots on an already closed report.

    Begun reports carry every metric slot of their operation in table order
    with the table unit and basis. Limits are an ordered subset of the
    operation's limit table with the table unit and enforcement.
    """
    operation = report.operation
    check_operation_pairing(operation, report.backend, report.outcome)
    if operation is None:
        if report.metrics or report.limits:
            raise ValueError("unbegun resource report cannot carry slots")
        return
    expected = METRIC_SLOTS[operation]
    if len(report.metrics) != len(expected):
        raise ValueError("resource metric slots do not match operation")
    for metric, (name, unit, basis) in zip(report.metrics, expected):
        if (metric.name, metric.unit, metric.basis) != (name, unit, basis):
            raise ValueError("resource metric slot does not match operation")
    table = LIMIT_SLOTS[operation]
    order = {name: index for index, (name, _, _) in enumerate(table)}
    previous = -1
    for limit in report.limits:
        index = order.get(limit.name)
        if index is None or index <= previous:
            raise ValueError("resource limit slot does not match operation")
        _, unit, enforcement = table[index]
        if (limit.unit, limit.enforcement) != (unit, enforcement):
            raise ValueError("resource limit slot does not match operation")
        previous = index


__all__ = (
    "ALL_LIMIT_NAMES", "ALL_METRIC_NAMES", "ALL_OUTCOMES", "BACKENDS_BY_OPERATION",
    "LIMIT_SLOTS", "METRIC_SLOTS", "OUTCOMES_BY_OPERATION", "check_operation_pairing",
    "check_report_domain",
)
