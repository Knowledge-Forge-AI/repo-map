"""Validate the projected ResultV2 shape without treating it as a raw result."""

from __future__ import annotations

from collections.abc import Mapping

from retrieval_semantic_pair_artifacts import refuse
from retrieval_semantic_pair_v2_cost_fields import (
    CORRESPONDENCE_COST, CORRESPONDENCE_INTEGER, RESULT_BYTES, RESULT_INTEGER,
    validate_byte_map, validate_numeric_map,
)
from retrieval_semantic_pair_v2_projection import (
    _CLEANUP, _CORRESPONDENCE_STATUSES, _STATES, _label, _mapping, _reason, _safe_text,
)


def validate_projected_result(value: object) -> None:
    """Refuse unknown fields and malformed counts in an already projected row."""
    result = _mapping(value, "pair_v2_result")
    if frozenset(result) != {"cell", "correspondence", "byte_work"}:
        raise refuse("pair_v2_result_fields")
    cell_value = result.get("cell")
    if cell_value is not None:
        cell = _mapping(cell_value, "pair_v2_cell")
        if frozenset(cell) != {
            "execution_state", "reason", "elapsed_ns", "query_bytes", "cleanup_status", "candidate_count",
        }:
            raise refuse("pair_v2_cell_fields")
        _label(cell.get("execution_state"), _STATES)
        _label(cell.get("cleanup_status"), _CLEANUP)
        if _reason(cell.get("reason")) != cell.get("reason"):
            raise refuse("pair_v2_cell_reason")
        for field in ("elapsed_ns", "query_bytes", "candidate_count"):
            item = cell.get(field)
            if field == "candidate_count" and item is None:
                raise refuse("pair_v2_cell_count")
            if item is not None and (type(item) is not int or item < 0):
                raise refuse("pair_v2_cell_count")
    correspondence_value = result.get("correspondence")
    if correspondence_value is not None:
        correspondence = _mapping(correspondence_value, "pair_v2_correspondence")
        if frozenset(correspondence) != {"verification_status", "cost"}:
            raise refuse("pair_v2_correspondence_fields")
        status = correspondence.get("verification_status")
        if type(status) is not str or status not in _CORRESPONDENCE_STATUSES:
            raise refuse("pair_v2_correspondence_status")
        validate_numeric_map(
            correspondence.get("cost"), CORRESPONDENCE_COST,
            "pair_v2_correspondence_cost", CORRESPONDENCE_INTEGER,
        )
    validate_byte_map(result.get("byte_work"), RESULT_BYTES, RESULT_INTEGER, "pair_v2_result_bytes")


def require_projection(value: object, projected: Mapping[str, object] | None, code: str) -> None:
    """A strict reader accepts only the closed projection, including nulls."""
    if value != projected:
        raise refuse(code)


def validate_generation_projection(summary: Mapping[str, object]) -> None:
    if frozenset(summary) != {
        "generation", "attempt_id", "terminal_status", "legacy_report", "result_v2_status",
        "result_v2_failure_code", "plan", "event_counts", "denominators", "recorded_work", "pair_count",
    }:
        raise refuse("pair_v2_generation_fields")
    attempt = summary.get("attempt_id")
    if type(attempt) is not str or not attempt or _safe_text(attempt) != attempt:
        raise refuse("pair_v2_generation_attempt")
    _label(summary.get("terminal_status"), _STATES)
    _label(summary.get("result_v2_status"), _STATES)
    if _reason(summary.get("result_v2_failure_code")) != summary.get("result_v2_failure_code"):
        raise refuse("pair_v2_generation_reason")
    legacy = _mapping(summary.get("legacy_report"), "pair_v2_generation_legacy")
    if frozenset(legacy) != {"status", "failure_code"}:
        raise refuse("pair_v2_generation_fields")
    _label(legacy.get("status"), _STATES)
    if _reason(legacy.get("failure_code")) != legacy.get("failure_code"):
        raise refuse("pair_v2_generation_reason")
    events = _mapping(summary.get("event_counts"), "pair_v2_generation_events")
    allowed = {
        "query_started", "query_observed", "task_graded", "binding_query_observed",
        "hnsw_binding_observed", "component_admission_accepted", "attempt_failed",
    }
    if any(key not in allowed or type(item) is not int or item < 0 for key, item in events.items()):
        raise refuse("pair_v2_generation_events")
    count = summary.get("pair_count")
    if type(count) is not int or count < 0:
        raise refuse("pair_v2_generation_count")


__all__ = ["require_projection", "validate_generation_projection", "validate_projected_result"]
