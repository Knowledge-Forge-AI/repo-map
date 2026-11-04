"""Closed validation for V2 fixed-comparison side projections."""

from __future__ import annotations

from collections.abc import Mapping
import math

from retrieval_semantic_pair_artifacts import refuse
from retrieval_semantic_pair_v2_projection import (
    _CLASSIFICATIONS, _FILE_STATUSES, _GRADES, _RULES, _alignment, _boolean, _byte_map,
    _label, _numeric_map, _reason, _timing, _unit,
)


_SIDE_FIELDS = {
    "classification", "alignment", "execution_state", "reason", "capability_state",
    "ann_exact_reference_recall", "grading", "safety_refusal_correct", "absent_answer_correct",
    "metrics", "file_metrics", "file_metrics_status", "timing", "byte_accounting",
    "result_byte_work", "correspondence_cost", "rational_fusion", "scope_complete", "omission_count",
    "omissions_status", "timing_source", "byte_accounting_source", "observed_operation",
}
_ACTUAL_FIELDS = {
    "operation", "backend", "publication_identity", "profile_identity", "rebuild_id",
    "input_descriptor_sha256", "snapshot_manifest_id", "effective_mode", "match_surface", "fallback",
    "selected_binding_count", "selected_binding_ids_sha256",
}
_WORK_FIELDS = {"per_binding", "hnsw", "fusion", "reference"}
_HNSW_FIELDS = {
    "source_binding_id", "plan", "plan_sha256", "provenance", "recall", "receipt_sha256",
    "creation_state", "creation_error", "explain_executed", "cleanup_state", "cell_state", "cell_reason",
    "result_state", "result_reason",
}
_REFERENCE_FIELDS = {"status", "reason", "recall"}
_PLAN_FIELDS = {
    "node_types", "index_names", "actual_rows", "planning_time_ms", "execution_time_ms",
    "shared_hit_blocks", "shared_read_blocks", "used_expected_index", "used_seq_scan",
    "distance_order_present", "planner_forced",
}
_PROVENANCE_FIELDS = {
    "repository_identity", "run_id", "receipt_identity", "profile_identity", "rebuild_id",
    "index_name", "query_digest", "attempt_identity", "source_scope", "dimensions", "ef_search",
    "iterative_scan", "ann_scan_limit", "baseline_sql_digest", "privacy_class", "search",
    "input_digest_validation",
}
_RECALL_FIELDS = {"exact_count", "ann_count", "overlap_at_k", "recall_at_k", "truncated"}
_POLICY_VERSIONS = {"cloe-w5-file-grading-v1", "cloe-w5-file-grading-v2"}
_STATES = {"completed", "failed", "unavailable", "refused", "not_run"}
_TIMING_SOURCES = {"slot.timing", "event.elapsed_ns", "not_recorded"}
_BYTE_SOURCES = {"slot.byte_accounting", "event.byte_accounting", "envelope.byte_accounting", "not_recorded"}
_FUSION_FIELDS = {
    "policy_version", "representation_version", "rrf_k", "per_arm_raw_hit_counts",
    "per_arm_collapsed_file_counts", "pre_cap_fused_file_count", "work_candidates_inspected",
    "truncated", "partial_coverage", "fallback_disclosed", "fallback_from_arms",
    "incomplete_arms", "truncated_arms", "fusion_state", "fusion_reason", "provenance_identity",
}


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise refuse(code)
    return value


def _digest(value: object, code: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(char not in "0123456789abcdef" for char in value[7:])
    ):
        raise refuse(code)


def _safe_text(value: object, code: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if type(value) is not str or not value or len(value) > 256 or any(ord(char) < 32 for char in value):
        raise refuse(code)


def _nonnegative(value: object, code: str, *, integer: bool = False) -> None:
    if integer and (type(value) is not int or value < 0):
        raise refuse(code)
    if integer:
        return
    if type(value) is bool:
        raise refuse(code)
    if not isinstance(value, (int, float)):
        raise refuse(code)
    if isinstance(value, float) and not math.isfinite(value):
        raise refuse(code)
    if value < 0:
        raise refuse(code)


def _validate_operation_work_item(value: object) -> None:
    item = _mapping(value, "pair_v2_operation_summary")
    if frozenset(item) != _HNSW_FIELDS:
        raise refuse("pair_v2_operation_summary")
    _safe_text(item.get("source_binding_id"), "pair_v2_operation_summary")
    for field in ("creation_state", "cleanup_state", "cell_state"):
        _safe_text(item.get(field), "pair_v2_operation_summary")
    _safe_text(item.get("result_state"), "pair_v2_operation_summary", nullable=True)
    for field in ("creation_error", "cell_reason", "result_reason"):
        _safe_text(item.get(field), "pair_v2_operation_summary", nullable=True)
    if item.get("explain_executed") is not None and type(item.get("explain_executed")) is not bool:
        raise refuse("pair_v2_operation_summary")
    for field in ("plan_sha256", "receipt_sha256"):
        _digest(item.get(field), "pair_v2_operation_summary", nullable=True)
    plan = item.get("plan")
    if plan is not None:
        plan_map = _mapping(plan, "pair_v2_operation_summary")
        if frozenset(plan_map) != _PLAN_FIELDS:
            raise refuse("pair_v2_operation_summary")
        for field in ("node_types", "index_names"):
            values = plan_map.get(field)
            if type(values) is not list or any(type(value) is not str for value in values):
                raise refuse("pair_v2_operation_summary")
        for field in ("actual_rows", "shared_hit_blocks", "shared_read_blocks"):
            _nonnegative(plan_map.get(field), "pair_v2_operation_summary", integer=True)
        for field in ("planning_time_ms", "execution_time_ms"):
            _nonnegative(plan_map.get(field), "pair_v2_operation_summary")
        for field in ("used_expected_index", "used_seq_scan", "distance_order_present", "planner_forced"):
            if type(plan_map.get(field)) is not bool:
                raise refuse("pair_v2_operation_summary")
    provenance = item.get("provenance")
    if provenance is not None:
        provenance_map = _mapping(provenance, "pair_v2_operation_summary")
        if frozenset(provenance_map) != _PROVENANCE_FIELDS:
            raise refuse("pair_v2_operation_summary")
        for field in (
            "repository_identity", "rebuild_id", "index_name", "attempt_identity",
            "iterative_scan", "privacy_class", "search", "input_digest_validation",
        ):
            _safe_text(provenance_map.get(field), "pair_v2_operation_summary")
        for field in ("receipt_identity", "profile_identity", "query_digest", "baseline_sql_digest"):
            _digest(provenance_map.get(field), "pair_v2_operation_summary")
        for field in ("run_id", "dimensions", "ef_search", "ann_scan_limit"):
            _nonnegative(provenance_map.get(field), "pair_v2_operation_summary", integer=True)
        scope = provenance_map.get("source_scope")
        if type(scope) is not list or len(scope) > 24:
            raise refuse("pair_v2_operation_summary")
        for pair in scope:
            if type(pair) is not list or len(pair) != 2:
                raise refuse("pair_v2_operation_summary")
            _safe_text(pair[0], "pair_v2_operation_summary")
            _safe_text(pair[1], "pair_v2_operation_summary")
    recall = item.get("recall")
    if recall is not None:
        recall_map = _mapping(recall, "pair_v2_operation_summary")
        if frozenset(recall_map) != _RECALL_FIELDS:
            raise refuse("pair_v2_operation_summary")
        for field in ("exact_count", "ann_count", "overlap_at_k"):
            _nonnegative(recall_map.get(field), "pair_v2_operation_summary", integer=True)
        exact_count = recall_map.get("exact_count")
        ann_count = recall_map.get("ann_count")
        overlap_at_k = recall_map.get("overlap_at_k")
        if (
            type(exact_count) is not int
            or type(ann_count) is not int
            or type(overlap_at_k) is not int
        ):
            raise refuse("pair_v2_operation_summary")
        recall_at_k = recall_map.get("recall_at_k")
        if recall_at_k is not None:
            _nonnegative(recall_at_k, "pair_v2_operation_summary")
            if isinstance(recall_at_k, (int, float)) and recall_at_k > 1:
                raise refuse("pair_v2_operation_summary")
        if overlap_at_k > min(exact_count, ann_count):
            raise refuse("pair_v2_operation_summary")
        if type(recall_map.get("truncated")) is not bool:
            raise refuse("pair_v2_operation_summary")


def _validate_fusion(value: object) -> None:
    if value is None:
        return
    fusion = _mapping(value, "pair_v2_operation_summary")
    if frozenset(fusion) != _FUSION_FIELDS:
        raise refuse("pair_v2_operation_summary")
    for field in ("policy_version", "representation_version", "fusion_state"):
        _safe_text(fusion.get(field), "pair_v2_operation_summary")
    for field in ("rrf_k", "pre_cap_fused_file_count", "work_candidates_inspected"):
        _nonnegative(fusion.get(field), "pair_v2_operation_summary", integer=True)
    rrf_k = fusion.get("rrf_k")
    if type(rrf_k) is not int or rrf_k < 1:
        raise refuse("pair_v2_operation_summary")
    for field in ("per_arm_raw_hit_counts", "per_arm_collapsed_file_counts"):
        counts = _mapping(fusion.get(field), "pair_v2_operation_summary")
        if len(counts) > 3:
            raise refuse("pair_v2_operation_summary")
        for arm, count in counts.items():
            _safe_text(arm, "pair_v2_operation_summary")
            _nonnegative(count, "pair_v2_operation_summary", integer=True)
    for field in ("truncated", "partial_coverage", "fallback_disclosed"):
        if type(fusion.get(field)) is not bool:
            raise refuse("pair_v2_operation_summary")
    for field in ("fallback_from_arms", "incomplete_arms", "truncated_arms"):
        values = fusion.get(field)
        if type(values) is not list or len(values) > 3:
            raise refuse("pair_v2_operation_summary")
        for item in values:
            _safe_text(item, "pair_v2_operation_summary")
    fusion_state = fusion.get("fusion_state")
    if type(fusion_state) is not str or fusion_state not in _STATES:
        raise refuse("pair_v2_operation_summary")
    _safe_text(fusion.get("fusion_reason"), "pair_v2_operation_summary", nullable=True)
    _digest(fusion.get("provenance_identity"), "pair_v2_operation_summary", nullable=True)


def _validate_reference(value: object) -> None:
    if value is None:
        return
    reference = _mapping(value, "pair_v2_operation_summary")
    if frozenset(reference) != _REFERENCE_FIELDS:
        raise refuse("pair_v2_operation_summary")
    status = reference.get("status")
    if type(status) is not str or status not in {
        "measured", "unavailable", "vacuous_empty", "not_attempted",
    }:
        raise refuse("pair_v2_operation_summary")
    _safe_text(reference.get("reason"), "pair_v2_operation_summary", nullable=True)
    recall = reference.get("recall")
    if recall is not None:
        _nonnegative(recall, "pair_v2_operation_summary")
        if isinstance(recall, (int, float)) and recall > 1:
            raise refuse("pair_v2_operation_summary")
    if (status == "measured") != (recall is not None):
        raise refuse("pair_v2_operation_summary")


def _operation(value: object) -> None:
    if value is None:
        return
    operation = _mapping(value, "pair_v2_operation_summary")
    if frozenset(operation) != {"source", "schema", "kind", "state", "reason", "record_sha256", "actual", "work"}:
        raise refuse("pair_v2_operation_summary")
    if operation.get("source") != "query_observed.observed_operation" or operation.get("schema") != "cloe-w5-observed-operation-v1":
        raise refuse("pair_v2_operation_summary")
    for field in ("kind", "state"):
        if type(operation.get(field)) is not str:
            raise refuse("pair_v2_operation_summary")
    if operation.get("reason") is not None and type(operation.get("reason")) is not str:
        raise refuse("pair_v2_operation_summary")
    _digest(operation.get("record_sha256"), "pair_v2_operation_summary")
    actual = _mapping(operation.get("actual"), "pair_v2_operation_summary")
    if frozenset(actual) != _ACTUAL_FIELDS:
        raise refuse("pair_v2_operation_summary")
    for field in ("operation", "backend", "rebuild_id", "effective_mode", "match_surface"):
        if actual.get(field) is not None and type(actual.get(field)) is not str:
            raise refuse("pair_v2_operation_summary")
    for field in ("publication_identity", "profile_identity", "input_descriptor_sha256"):
        _digest(actual.get(field), "pair_v2_operation_summary", nullable=True)
    _digest(actual.get("selected_binding_ids_sha256"), "pair_v2_operation_summary", nullable=True)
    count = actual.get("selected_binding_count")
    if type(count) is not int or count < 0:
        raise refuse("pair_v2_operation_summary")
    fallback = actual.get("fallback")
    if fallback is not None and frozenset(_mapping(fallback, "pair_v2_operation_summary")) != {
        "caller_selected", "from_mode", "to_mode", "reason_code",
    }:
        raise refuse("pair_v2_operation_summary")
    work = _mapping(operation.get("work"), "pair_v2_operation_summary")
    if frozenset(work) != _WORK_FIELDS:
        raise refuse("pair_v2_operation_summary")
    per_binding = work.get("per_binding")
    if per_binding is not None:
        summary = _mapping(per_binding, "pair_v2_operation_summary")
        if frozenset(summary) != {"count", "states"}:
            raise refuse("pair_v2_operation_summary")
        summary_count = summary.get("count")
        if type(summary_count) is not int or summary_count < 0:
            raise refuse("pair_v2_operation_summary")
        states = _mapping(summary.get("states"), "pair_v2_operation_summary")
        if any(type(key) is not str or type(item) is not int or item < 0 for key, item in states.items()):
            raise refuse("pair_v2_operation_summary")
    hnsw = work.get("hnsw")
    if hnsw is not None and (type(hnsw) is not list or len(hnsw) > 24):
        raise refuse("pair_v2_operation_summary")
    if type(hnsw) is list:
        for item in hnsw:
            _validate_operation_work_item(item)
    fusion = work.get("fusion")
    _validate_fusion(fusion)
    reference = work.get("reference")
    _validate_reference(reference)


def validate_comparison_side(value: object) -> None:
    if value is None:
        return
    side = _mapping(value, "pair_v2_comparison_side")
    if frozenset(side) != _SIDE_FIELDS:
        raise refuse("pair_v2_comparison_side_fields")
    classification = side.get("classification")
    if classification is not None and (type(classification) is not str or classification not in _CLASSIFICATIONS):
        raise refuse("pair_v2_comparison_side")
    execution_state = side.get("execution_state")
    if execution_state is not None and (type(execution_state) is not str or execution_state not in _STATES):
        raise refuse("pair_v2_comparison_side")
    grading = _mapping(side.get("grading"), "pair_v2_comparison_side")
    if frozenset(grading) != {"rule", "state", "quality_credit", "file_grading_policy_version"}:
        raise refuse("pair_v2_comparison_side")
    _label(grading.get("rule"), _RULES)
    _label(grading.get("state"), _GRADES)
    if _reason(side.get("reason")) != side.get("reason"):
        raise refuse("pair_v2_comparison_side")
    quality_credit = grading.get("quality_credit")
    if type(quality_credit) is not str or quality_credit not in {"stored_only", "not_applicable"}:
        raise refuse("pair_v2_comparison_side")
    policy_version = grading.get("file_grading_policy_version")
    if policy_version is not None and (type(policy_version) is not str or policy_version not in _POLICY_VERSIONS):
        raise refuse("pair_v2_comparison_side")
    _alignment(side.get("alignment"))
    if side.get("ann_exact_reference_recall") is not None:
        _unit(side.get("ann_exact_reference_recall"), "pair_v2_comparison_side")
    for field in ("safety_refusal_correct", "absent_answer_correct", "scope_complete"):
        _boolean(side.get(field), "pair_v2_comparison_side")
    for field in ("metrics", "file_metrics", "correspondence_cost", "byte_accounting"):
        _numeric_map(side.get(field), "pair_v2_comparison_side")
    _byte_map(side.get("result_byte_work"), "pair_v2_comparison_side")
    _timing(side.get("timing"))
    file_status = side.get("file_metrics_status")
    if file_status is not None and (type(file_status) is not str or file_status not in _FILE_STATUSES):
        raise refuse("pair_v2_comparison_side")
    count = side.get("omission_count")
    if count is not None and (type(count) is not int or count < 0):
        raise refuse("pair_v2_comparison_side")
    omissions_status = side.get("omissions_status")
    if type(omissions_status) is not str or omissions_status not in {"recorded", "not_recorded"}:
        raise refuse("pair_v2_comparison_side")
    timing_source, byte_source = side.get("timing_source"), side.get("byte_accounting_source")
    if (
        type(timing_source) is not str or timing_source not in _TIMING_SOURCES
        or type(byte_source) is not str or byte_source not in _BYTE_SOURCES
    ):
        raise refuse("pair_v2_comparison_side")
    rational = _mapping(side.get("rational_fusion"), "pair_v2_comparison_side")
    rational_status = rational.get("status")
    if (
        frozenset(rational) != {"status", "record_count"}
        or type(rational_status) is not str
        or rational_status not in {"present", "not_recorded"}
    ):
        raise refuse("pair_v2_comparison_side")
    record_count = rational.get("record_count")
    if record_count is not None and (type(record_count) is not int or record_count < 0):
        raise refuse("pair_v2_comparison_side")
    _operation(side.get("observed_operation"))


__all__ = ["validate_comparison_side"]
