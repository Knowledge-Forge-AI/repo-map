"""Sanitized V1-derived rows used by the opt-in W5 V2 report."""

from __future__ import annotations

from collections.abc import Mapping
import math

from retrieval_semantic_pair_artifacts import refuse
from retrieval_semantic_pair_v2_cost_fields import RESULT_INTEGER, byte_map
from retrieval_evaluation_schema import TASK_FAMILIES


_STATES = frozenset({"completed", "failed", "unavailable", "refused", "not_run"})
_CAPABILITIES = frozenset({"available", "partial", "refused", "stale", "unavailable", "failed", "not_run"})
_STRATA = frozenset({"body", "metadata", "graph_topology", "direct_handoff"})
_EXPOSURES = frozenset({"accepted_canonical_and_observation_metadata", "authorized_bodies_and_approved_metadata", "projected_authorized_bodies"})
_QUERY_STYLES = frozenset({
    "ranked_terms", "normalized_phrase", "literal_captured_text", "unsupported", "unknown",
    "direct_handoff_recheck", "git_grep_fixed_strings", "git_grep_extended_regex",
    "node_locations_direct", "navigation_search", "neighborhood_traversal", "observation_substring_search",
})
_FILE_STATUSES = frozenset({"verified", "gap", "not_applicable", "not_recorded"})
_CORRESPONDENCE_STATUSES = frozenset({"verified", "gap", "unavailable", "refused", "stale", "not_applicable", "unverified", "not_recorded"})
_RULES = frozenset({"ranked_positive", "absent_answer", "safety_refusal", "direct_handoff"})
_GRADES = frozenset({"correct", "partial", "incorrect", "ungraded", "not_applicable"})
_SURFACES = frozenset({"captured_text", "stored_metadata", "graph_topology", "direct_handoff", "none"})
_MODES = frozenset(
    {
        "exact_identity",
        "current_literal_enumeration",
        "literal_captured_text",
        "ranked_discovery",
        "graph_investigation",
        "semantic_discovery",
    }
)
_REASONS = frozenset({
    "backend_unsupported", "capability_not_admitted", "artifact_store_expired",
    "projection_absent", "external_tool_unavailable", "unsupported_semantic_query_mode",
    "index_not_selected", "hnsw_index_not_selected", "query_not_admitted",
    "source_scope_refused", "admitted_exact_query_not_executed",
    "admitted_hybrid_query_not_executed", "admitted_hnsw_execution_failed",
    "fixture_not_run", "not_run", "timeout", "withheld",
})
_ALIGNMENT_REASONS = frozenset({
    "journal_query_started_missing", "journal_query_observed_missing", "result_cell_missing",
    "journal_task_grade_not_recorded",
})
_COMPARISON_GAPS = frozenset(
    {
        "arm_identity_missing",
        "classification_missing",
        "classification_missing_result_v2",
        "classification_failed",
        "classification_refused",
        "classification_unsupported",
        "classification_unavailable",
        "grade_not_recorded",
        "scope_incomplete",
        "scope_not_recorded",
        "scope_omissions_present",
        "omissions_not_recorded",
        "result_not_recorded",
        "correspondence_not_recorded",
        "correspondence_not_verified",
        "byte_work_not_recorded",
    }
)
_CLEANUP = frozenset({"verified", "failed", "not_applicable", "not_attempted"})
_OBSERVATION_BYTES = frozenset({
    "agent_completion_cost_usd", "artifact_store_bytes_read", "internal_source_io_bytes",
    "model_tokens_spent", "observed_output_payload_bytes",
})
_RESULT_BYTES = frozenset({
    "schema_version", "correspondence_verification_ns", "correspondence_verification_bytes_read",
    "decoded_candidate_count", "direct_selected_text_bytes", "native_process_stdout_cap_bytes",
    "observed_output_payload_bytes", "raw_process_stdout_bytes", "returned_hit_count",
    "serialized_envelope_bytes",
})
_POLICY_VERSIONS = frozenset({"cloe-w5-file-grading-v1", "cloe-w5-file-grading-v2"})
_POLICY_SOURCES = frozenset(
    {
        "query_observed",
        "query_observed.slot",
        "query_observed.slot.slot", "query_observed.slot+query_observed.slot.slot",
        "query_observed.envelope",
        "task_graded",
        "task_graded.slot",
        "task_graded.slot.slot", "task_graded.slot+task_graded.slot.slot",
        "task_graded.slot+query_observed.slot",
        "not_recorded",
    }
)
_TIMING_SOURCES = frozenset({"slot.timing", "event.elapsed_ns", "not_recorded"})
_BYTE_SOURCES = frozenset(
    {"slot.byte_accounting", "event.byte_accounting", "envelope.byte_accounting", "not_recorded"}
)
_PAIR_FIELDS = {
    "identity",
    "classification",
    "alignment",
    "journal_observation",
    "journal_grade",
    "result_v2",
    "file_grading_policy_version",
    "file_grading_policy_version_source",
    "rational_fusion",
    "context",
    "recorded_work",
}
_CLASSIFICATIONS = frozenset(
    {
        "missing",
        "missing_result_v2",
        "failed",
        "refused",
        "unsupported",
        "unavailable",
        "safety_correct",
        "safety_incorrect",
        "safety_not_recorded",
        "absence_correct",
        "absence_incorrect",
        "absence_not_recorded",
        "inapplicable",
        "graded",
        "available_empty",
        "not_recorded",
    }
)


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise refuse(code)
    return value


def _label(value: object, allowed: frozenset[str]) -> str | None:
    if value is None:
        return None
    if type(value) is not str or value not in allowed:
        raise refuse("pair_v2_label_value")
    return value


def _choice(value: object, allowed: frozenset[str], default: str | None) -> str | None:
    if value is None:
        return default
    if type(value) is not str or value not in allowed:
        raise refuse("pair_v2_choice_value")
    return value


def _reason(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise refuse("pair_v2_reason_type")
    return value if value in _REASONS else "withheld"


def _boolean(value: object, code: str) -> bool | None:
    if value is None or type(value) is bool:
        return value
    raise refuse(code)


def _safe_text(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or any(ord(char) < 32 for char in value):
        return None
    if any(char in "/\\" for char in value):
        return None
    return value


def _number(value: object, code: str) -> int | float | None:
    if value is None:
        return None
    if type(value) is bool or not isinstance(value, (int, float)):
        raise refuse(code)
    if isinstance(value, float) and not math.isfinite(value):
        raise refuse(code)
    return value


def _nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise refuse("pair_v2_integer")
    if value < 0:
        raise refuse("pair_v2_integer")
    return value


def _unit(value: object, code: str) -> int | float | None:
    result = _number(value, code)
    if result is not None and not 0 <= result <= 1:
        raise refuse(code)
    return result


def _numeric_map(value: object, code: str, allowed: frozenset[str] | None = None) -> dict[str, object] | None:
    if value is None:
        return None
    source = _mapping(value, code)
    result: dict[str, object] = {}
    for key, item in source.items():
        if type(key) is not str:
            raise refuse(code)
        if allowed is not None and key not in allowed:
            continue
        result[key] = _number(item, code)
    return result


def _byte_map(value: object, code: str) -> dict[str, object] | None:
    return byte_map(value, _RESULT_BYTES, RESULT_INTEGER, code)


def _timing(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if type(value) is int:
        if value < 0:
            raise refuse("pair_v2_timing")
        return {"raw_samples_ns": [value], "sample_count": 1}
    timing = _mapping(value, "pair_v2_timing")
    samples = timing.get("raw_samples_ns")
    if samples is not None and (type(samples) is not list or any(type(sample) is not int or sample < 0 for sample in samples)):
        raise refuse("pair_v2_timing")
    count = timing.get("sample_count")
    if count is not None and (type(count) is not int or count < 0):
        raise refuse("pair_v2_timing")
    if samples is not None and count is not None and len(samples) != count:
        raise refuse("pair_v2_timing")
    return {"raw_samples_ns": samples, "sample_count": count}


def _fallback(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    raw = _mapping(value, "pair_v2_grade_fallback")
    return {
        "caller_selected": raw.get("caller_selected") if type(raw.get("caller_selected")) is bool else None,
        "from_mode": _label(raw.get("from_mode"), _MODES),
        "to_mode": _label(raw.get("to_mode"), _MODES),
        "reason_code": _reason(raw.get("reason_code")),
    }


def _grade(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    grade = _mapping(value, "pair_v2_grade")
    return {
        "family": _label(grade.get("family"), frozenset(TASK_FAMILIES)),
        "comparability_stratum": _label(grade.get("comparability_stratum"), _STRATA),
        "comparator_exposure": _label(grade.get("comparator_exposure"), _EXPOSURES),
        "requested_mode": _label(grade.get("requested_mode"), _MODES),
        "effective_mode": _label(grade.get("effective_mode"), _MODES),
        "fallback": _fallback(grade.get("fallback")),
        "match_surface": _label(grade.get("match_surface"), _SURFACES),
        "query_style": _label(grade.get("query_style"), _QUERY_STYLES),
        "grading_rule": _label(grade.get("grading_rule"), _RULES),
        "grading_state": _label(grade.get("grading_state"), _GRADES),
        "capability_state": _label(grade.get("capability_state"), _CAPABILITIES),
        "execution_state": _label(grade.get("execution_state"), _STATES),
        "safety_refusal_correct": _boolean(
            grade.get("safety_refusal_correct"), "pair_v2_grade_safety"
        ),
        "absent_answer_correct": _boolean(
            grade.get("absent_answer_correct"), "pair_v2_grade_absence"
        ),
        "metrics": _numeric_map(grade.get("metrics"), "pair_v2_grade_metrics"),
        "file_metrics": _numeric_map(grade.get("file_metrics"), "pair_v2_file_metrics"),
        "file_metrics_status": _choice(
            grade.get("file_metrics_status"), _FILE_STATUSES, None
        ),
        "span_metrics": _numeric_map(grade.get("span_metrics"), "pair_v2_span_metrics"),
        "timing": _timing(grade.get("timing")),
        "byte_accounting": _numeric_map(grade.get("byte_accounting"), "pair_v2_grade_bytes"),
        "file_grading_policy_version": _policy(grade.get("file_grading_policy_version")),
        "file_grading_policy_version_source": _choice(
            grade.get("file_grading_policy_version_source"), _POLICY_SOURCES, "not_recorded"
        ),
        "quality_credit": _choice(
            grade.get("quality_credit"), frozenset({"stored_only", "not_applicable"}), "stored_only"
        ),
        "grade_source": _choice(
            grade.get("grade_source"),
            frozenset({"task_graded.slot", "query_observed.slot", "task_graded.slot+query_observed.slot", "not_recorded"}),
            "not_recorded",
        ),
        "timing_source": _choice(grade.get("timing_source"), _TIMING_SOURCES, "not_recorded"),
        "byte_accounting_source": _choice(
            grade.get("byte_accounting_source"), _BYTE_SOURCES, "not_recorded"
        ),
    }


def _observation(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    observation = _mapping(value, "pair_v2_observation")
    return {
        "execution_state": _label(observation.get("execution_state"), _STATES),
        "reason": _reason(observation.get("reason")),
        "elapsed_ns": _nonnegative_int(observation.get("elapsed_ns")),
        "query_bytes": _nonnegative_int(observation.get("query_bytes")),
        "capability_state": _label(observation.get("capability_state"), _CAPABILITIES),
        "unavailable_reason": _reason(observation.get("unavailable_reason")),
        "refusal_code": _reason(observation.get("refusal_code")),
        "scope_complete": _boolean(observation.get("scope_complete"), "pair_v2_observation_scope"),
        "omission_count": _nonnegative_int(observation.get("omission_count")),
        "omissions_status": _choice(
            observation.get("omissions_status"), frozenset({"recorded", "not_recorded"}), "not_recorded"
        ),
        "returned_hit_count": _nonnegative_int(observation.get("returned_hit_count")),
        "available_empty": _boolean(observation.get("available_empty"), "pair_v2_observation_empty"),
        "ann_exact_reference_recall": _unit(
            observation.get("ann_exact_reference_recall"), "pair_v2_recall"
        ),
        "byte_accounting": _numeric_map(
            observation.get("byte_accounting"), "pair_v2_observation_accounting", _OBSERVATION_BYTES
        ),
        "byte_accounting_source": _choice(
            observation.get("byte_accounting_source"), _BYTE_SOURCES, "not_recorded"
        ),
        "timing_source": _choice(observation.get("timing_source"), _TIMING_SOURCES, "not_recorded"),
    }


def _result(value: object) -> dict[str, object]:
    result = _mapping(value, "pair_v2_result")
    cell_value = result.get("cell")
    cell = _mapping(cell_value, "pair_v2_cell") if cell_value is not None else None
    candidates = cell.get("candidates") if cell is not None else None
    return {
        "cell": None
        if cell is None
        else {
            "execution_state": _label(cell.get("execution_state"), _STATES),
            "reason": _reason(cell.get("reason")),
            "elapsed_ns": _nonnegative_int(cell.get("elapsed_ns")),
            "query_bytes": _nonnegative_int(cell.get("query_bytes")),
            "cleanup_status": _label(cell.get("cleanup_status"), _CLEANUP),
            "candidate_count": len(candidates) if type(candidates) is list else None,
        },
        "correspondence": _correspondence(result.get("correspondence")),
        "byte_work": _byte_map(result.get("byte_work"), "pair_v2_result_bytes"),
    }


def _correspondence(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    correspondence = _mapping(value, "pair_v2_correspondence")
    sidecar = correspondence.get("sidecar")
    sidecar_map = sidecar if isinstance(sidecar, Mapping) else {}
    verification = sidecar_map.get("verification")
    verification_map = verification if isinstance(verification, Mapping) else {}
    status = verification_map.get("status")
    return {
        "verification_status": _choice(
            status, _CORRESPONDENCE_STATUSES, "not_recorded"
        ),
        "cost": _numeric_map(correspondence.get("cost"), "pair_v2_correspondence_cost"),
    }


def _alignment(value: object) -> dict[str, object]:
    alignment = _mapping(value, "pair_v2_alignment")
    reasons = alignment.get("reasons")
    if type(reasons) is not list or any(
        type(reason) is not str or reason not in _ALIGNMENT_REASONS for reason in reasons
    ):
        raise refuse("pair_v2_alignment")
    return {
        "status": _choice(alignment.get("status"), frozenset({"matched", "gapped"}), "gapped"),
        "reasons": reasons,
    }


def _policy(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or value not in _POLICY_VERSIONS:
        raise refuse("pair_v2_policy_version")
    return value
