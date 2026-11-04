"""Strict public-safe records for actual W5 operation observations."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import NoReturn, cast

from retrieval_semantic_experiment_contracts import ExperimentRefusal, digest_json
from retrieval_semantic_observed_operation_digest import observed_operation_digest
from retrieval_semantic_observed_operation_numbers import validate_nonnegative_number
from retrieval_semantic_observed_operation_plan import validate_plan_node_list
from retrieval_semantic_observed_operation_relationships import validate_operation_relationships


OBSERVED_OPERATION_SCHEMA = "cloe-w5-observed-operation-v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_SAFE_REASON = re.compile(r"[a-z][a-z0-9_.-]{0,127}\Z")
_STATES = frozenset({"completed", "not_run", "unavailable", "refused", "failed"})
_KINDS = frozenset({"baseline_query", "exact_vector", "hnsw_vector", "hybrid_rrf"})
_OPERATIONS = frozenset({
    "query_envelope", "exact_vector_sql", "hnsw_vector_sql", "rrf_file_fusion",
    "vector_query_not_attempted",
})
_FORBIDDEN_KEYS = frozenset({
    "body", "candidates", "contributions", "denied_binding_ids", "denied_bindings",
    "display_name", "hits", "index_owner", "locator", "owner_identity", "principal",
    "raw_vector", "rrf_denominator", "rrf_numerator", "score", "score_denominator",
    "score_numerator", "sql", "table_oid", "vector",
})
_TOP_FIELDS = frozenset({
    "schema", "identity", "kind", "state", "reason", "declared_mode", "actual", "work",
    "record_sha256",
})
_IDENTITY_FIELDS = frozenset({"generation", "task_id", "arm_id", "repetition"})
_ACTUAL_FIELDS = frozenset({
    "operation", "backend", "publication_identity", "profile_identity", "rebuild_id",
    "input_descriptor_sha256", "selected_binding_ids", "snapshot_manifest_id",
    "effective_mode", "match_surface", "fallback",
})
_WORK_FIELDS = frozenset({"per_binding", "hnsw", "fusion", "reference"})
_BINDING_FIELDS = frozenset({
    "source_binding_id", "state", "reason", "elapsed_ns", "candidate_count",
    "query_descriptor_sha256",
})
_HNSW_FIELDS = frozenset({
    "source_binding_id", "plan", "plan_sha256", "provenance", "recall", "receipt_sha256",
    "creation_state", "creation_error", "explain_executed", "cleanup_state",
    "cell_state", "cell_reason", "result_state", "result_reason",
})
_PLAN_FIELDS = frozenset({
    "node_types", "index_names", "actual_rows", "planning_time_ms", "execution_time_ms",
    "shared_hit_blocks", "shared_read_blocks", "used_expected_index", "used_seq_scan",
    "distance_order_present", "planner_forced",
})
_PROVENANCE_FIELDS = frozenset({
    "repository_identity", "run_id", "receipt_identity", "profile_identity", "rebuild_id",
    "index_name", "query_digest", "attempt_identity", "source_scope", "dimensions",
    "ef_search", "iterative_scan", "ann_scan_limit", "baseline_sql_digest", "privacy_class",
    "search", "input_digest_validation",
})
_RECALL_FIELDS = frozenset({"exact_count", "ann_count", "overlap_at_k", "recall_at_k", "truncated"})
_FUSION_FIELDS = frozenset({
    "policy_version", "representation_version", "rrf_k", "per_arm_raw_hit_counts",
    "per_arm_collapsed_file_counts", "pre_cap_fused_file_count", "work_candidates_inspected",
    "truncated", "partial_coverage", "fallback_disclosed", "fallback_from_arms",
    "incomplete_arms", "truncated_arms", "fusion_state", "fusion_reason", "provenance_identity",
})
_REFERENCE_FIELDS = frozenset({"status", "reason", "recall"})


def _refuse(code: str) -> NoReturn:
    raise ExperimentRefusal("observed_operation_" + code)


def _text(value: object, field: str, *, reason: bool = False, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    pattern = _SAFE_REASON if reason else _SAFE_TEXT
    if type(value) is not str or pattern.fullmatch(value) is None:
        _refuse(field)
    return value


def _digest(value: object, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        _refuse(field)
    return value


def _nonnegative_int(value: object, field: str, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if type(value) is not int or value < 0:
        _refuse(field)
    return value


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        _refuse(field)
    return value


def _text_list(
    value: object, field: str, *, max_items: int = 24, unique: bool = True,
) -> list[str]:
    if type(value) is not list or len(value) > max_items:
        _refuse(field)
    result = [_text(item, field) for item in cast(list[object], value)]
    if unique and len(set(result)) != len(result):
        _refuse(field + "_duplicate")
    return cast(list[str], result)


def _reject_forbidden_keys(value: object) -> None:
    pending: list[object] = [value]
    visited = 0
    while pending:
        current = pending.pop()
        visited += 1
        if visited > 5000:
            _refuse("too_many_values")
        if isinstance(current, Mapping):
            for key, child in current.items():
                if type(key) is not str or key in _FORBIDDEN_KEYS:
                    _refuse("forbidden_field")
                pending.append(child)
        elif type(current) is list:
            pending.extend(cast(list[object], current))


def _validate_identity(value: object, expected: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or frozenset(value) != _IDENTITY_FIELDS:
        _refuse("identity_fields")
    identity = dict(value)
    if identity != dict(expected):
        _refuse("identity_mismatch")
    _text(identity["task_id"], "task_id")
    _text(identity["arm_id"], "arm_id")
    generation = identity["generation"]
    repetition = identity["repetition"]
    if type(generation) is not int or generation not in {1, 2}:
        _refuse("generation")
    if type(repetition) is not int or not 1 <= repetition <= 3:
        _refuse("repetition")
    return identity


def _validate_fallback(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or frozenset(value) != {"caller_selected", "from_mode", "to_mode", "reason_code"}:
        _refuse("fallback_fields")
    result = dict(value)
    _boolean(result["caller_selected"], "fallback_caller_selected")
    if result["caller_selected"] is not True:
        _refuse("fallback_caller_selected")
    _text(result["from_mode"], "fallback_from_mode")
    _text(result["to_mode"], "fallback_to_mode")
    _text(result["reason_code"], "fallback_reason", reason=True)
    if result["from_mode"] == result["to_mode"]:
        _refuse("fallback_same_mode")
    return result


def _validate_plan(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or frozenset(value) != _PLAN_FIELDS:
        _refuse("plan_fields")
    result = dict(value)
    try:
        validate_plan_node_list(result["node_types"], "plan_node_types")
    except ValueError:
        _refuse("plan_node_types")
    _text_list(result["index_names"], "plan_index_names", max_items=16, unique=False)
    for field in ("actual_rows", "shared_hit_blocks", "shared_read_blocks"):
        _nonnegative_int(result[field], "plan_" + field)
    for field in ("planning_time_ms", "execution_time_ms"):
        try:
            validate_nonnegative_number(result[field], "plan_" + field)
        except ExperimentRefusal:
            _refuse("plan_" + field)
    for field in ("used_expected_index", "used_seq_scan", "distance_order_present", "planner_forced"):
        _boolean(result[field], "plan_" + field)
    return result


def _validate_provenance(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or frozenset(value) != _PROVENANCE_FIELDS:
        _refuse("provenance_fields")
    result = dict(value)
    for field in ("repository_identity", "rebuild_id", "index_name", "attempt_identity", "iterative_scan", "privacy_class", "search", "input_digest_validation"):
        _text(result[field], "provenance_" + field)
    for field in ("receipt_identity", "profile_identity", "query_digest", "baseline_sql_digest"):
        _digest(result[field], "provenance_" + field)
    _nonnegative_int(result["run_id"], "provenance_run_id")
    _nonnegative_int(result["dimensions"], "provenance_dimensions")
    _nonnegative_int(result["ef_search"], "provenance_ef_search")
    _nonnegative_int(result["ann_scan_limit"], "provenance_ann_scan_limit")
    scope = result["source_scope"]
    if type(scope) is not list or len(scope) > 24:
        _refuse("provenance_source_scope")
    for pair in cast(list[object], scope):
        if type(pair) is not list or len(pair) != 2:
            _refuse("provenance_source_scope")
        _text(pair[0], "provenance_binding")
        _text(pair[1], "provenance_snapshot")
    return result


def _validate_recall(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or frozenset(value) != _RECALL_FIELDS:
        _refuse("recall_fields")
    result = dict(value)
    for field in ("exact_count", "ann_count", "overlap_at_k"):
        _nonnegative_int(result[field], "recall_" + field)
    try:
        validate_nonnegative_number(result["recall_at_k"], "recall_at_k", nullable=True)
    except ExperimentRefusal:
        _refuse("recall_at_k")
    if result["overlap_at_k"] > min(result["exact_count"], result["ann_count"]):
        _refuse("recall_overlap")
    if result["recall_at_k"] is not None and result["recall_at_k"] > 1:
        _refuse("recall_bound")
    _boolean(result["truncated"], "recall_truncated")
    return result


def _validate_binding(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or frozenset(value) != _BINDING_FIELDS:
        _refuse("binding_fields")
    result = dict(value)
    _text(result["source_binding_id"], "binding_id")
    _text(result["state"], "binding_state")
    if result["state"] not in _STATES:
        _refuse("binding_state")
    _text(result["reason"], "binding_reason", reason=True, nullable=True)
    _nonnegative_int(result["elapsed_ns"], "binding_elapsed_ns")
    _nonnegative_int(result["candidate_count"], "binding_candidate_count")
    _digest(result["query_descriptor_sha256"], "binding_query_digest", nullable=True)
    return result


def _validate_hnsw(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or frozenset(value) != _HNSW_FIELDS:
        _refuse("hnsw_fields")
    result = dict(value)
    _text(result["source_binding_id"], "hnsw_binding")
    plan = _validate_plan(result["plan"])
    _digest(result["plan_sha256"], "hnsw_plan_digest", nullable=True)
    if plan is not None and result["plan_sha256"] != digest_json(plan):
        _refuse("hnsw_plan_digest")
    _validate_provenance(result["provenance"])
    _validate_recall(result["recall"])
    _digest(result["receipt_sha256"], "hnsw_receipt_digest", nullable=True)
    for field in ("creation_state", "cleanup_state", "cell_state"):
        _text(result[field], "hnsw_" + field, reason=True)
    _text(result["result_state"], "hnsw_result_state", reason=True, nullable=True)
    if result["creation_state"] not in {"completed", "failed", "not_attempted"}:
        _refuse("hnsw_creation_state")
    _text(result["creation_error"], "hnsw_creation_error", reason=True, nullable=True)
    if result["explain_executed"] is not None:
        _boolean(result["explain_executed"], "hnsw_explain_executed")
    if result["cleanup_state"] not in {"verified", "failed", "not_applicable", "not_attempted"}:
        _refuse("hnsw_cleanup_state")
    if result["result_state"] is not None and result["result_state"] not in _STATES:
        _refuse("hnsw_result_state")
    _text(result["cell_reason"], "hnsw_cell_reason", reason=True, nullable=True)
    _text(result["result_reason"], "hnsw_result_reason", reason=True, nullable=True)
    if result["plan"] is None and result["plan_sha256"] is not None:
        _refuse("hnsw_empty_plan_digest")
    return result


def _validate_fusion(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or frozenset(value) != _FUSION_FIELDS:
        _refuse("fusion_fields")
    result = dict(value)
    for field in ("policy_version", "representation_version"):
        _text(result[field], "fusion_" + field)
    for field in ("rrf_k", "pre_cap_fused_file_count", "work_candidates_inspected"):
        _nonnegative_int(result[field], "fusion_" + field)
    if result["rrf_k"] < 1:
        _refuse("fusion_rrf_k")
    for field in ("per_arm_raw_hit_counts", "per_arm_collapsed_file_counts"):
        counts = result[field]
        if not isinstance(counts, Mapping) or len(counts) > 3:
            _refuse("fusion_counts")
        for arm, count in counts.items():
            _text(arm, "fusion_arm")
            _nonnegative_int(count, "fusion_count")
    for field in ("truncated", "partial_coverage", "fallback_disclosed"):
        _boolean(result[field], "fusion_" + field)
    for field in ("fallback_from_arms", "incomplete_arms", "truncated_arms"):
        _text_list(result[field], "fusion_" + field, max_items=3)
    _text(result["fusion_state"], "fusion_state")
    if result["fusion_state"] not in _STATES:
        _refuse("fusion_state")
    _text(result["fusion_reason"], "fusion_reason", reason=True, nullable=True)
    _digest(result["provenance_identity"], "fusion_provenance", nullable=True)
    return result
def _validate_reference(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or frozenset(value) != _REFERENCE_FIELDS:
        _refuse("reference_fields")
    result = dict(value)
    _text(result["status"], "reference_status")
    if result["status"] not in {"measured", "unavailable", "vacuous_empty", "not_attempted"}:
        _refuse("reference_status")
    _text(result["reason"], "reference_reason", reason=True, nullable=True)
    try:
        validate_nonnegative_number(result["recall"], "reference_recall", nullable=True)
    except ExperimentRefusal:
        _refuse("reference_recall")
    if result["recall"] is not None and result["recall"] > 1:
        _refuse("reference_bound")
    if result["status"] == "measured" and result["recall"] is None:
        _refuse("reference_recall")
    if result["status"] != "measured" and result["recall"] is not None:
        _refuse("reference_unknown")
    return result

def finalize_observed_operation(value: Mapping[str, object]) -> dict[str, object]:
    """Attach the canonical record digest and validate the closed record."""
    if not isinstance(value, Mapping) or not isinstance(value.get("identity"), Mapping):
        _refuse("identity")
    payload = dict(value)
    payload["record_sha256"] = observed_operation_digest(payload)
    return validate_observed_operation(payload, identity=cast(Mapping[str, object], payload["identity"]))

def validate_observed_operation(
    value: object, *, identity: Mapping[str, object]
) -> dict[str, object]:
    """Validate one bounded public-safe operation record against its event identity."""
    if not isinstance(value, Mapping) or frozenset(value) != _TOP_FIELDS:
        _refuse("fields")
    _reject_forbidden_keys(value)
    record = dict(value)
    _validate_identity(record["identity"], identity)
    if record["schema"] != OBSERVED_OPERATION_SCHEMA:
        _refuse("schema")
    _text(record["kind"], "kind")
    if record["kind"] not in _KINDS:
        _refuse("kind")
    _text(record["state"], "state")
    if record["state"] not in _STATES:
        _refuse("state")
    _text(record["reason"], "reason", reason=True, nullable=True)
    _text(record["declared_mode"], "declared_mode", nullable=True)
    actual = record["actual"]
    if not isinstance(actual, Mapping) or frozenset(actual) != _ACTUAL_FIELDS:
        _refuse("actual_fields")
    actual_map = dict(actual)
    _text(actual_map["operation"], "operation")
    if actual_map["operation"] not in _OPERATIONS:
        _refuse("operation")
    _text(actual_map["backend"], "backend", nullable=True)
    _digest(actual_map["publication_identity"], "publication_identity", nullable=True)
    _digest(actual_map["profile_identity"], "profile_identity", nullable=True)
    _text(actual_map["rebuild_id"], "rebuild_id", nullable=True)
    _digest(actual_map["input_descriptor_sha256"], "input_descriptor_sha256", nullable=True)
    _text_list(actual_map["selected_binding_ids"], "selected_binding_ids")
    _text(actual_map["snapshot_manifest_id"], "snapshot_manifest_id", nullable=True)
    _text(actual_map["effective_mode"], "effective_mode", nullable=True)
    _text(actual_map["match_surface"], "match_surface", nullable=True)
    _validate_fallback(actual_map["fallback"])
    work = record["work"]
    if not isinstance(work, Mapping) or frozenset(work) != _WORK_FIELDS:
        _refuse("work_fields")
    work_map = dict(work)
    per_binding = work_map["per_binding"]
    if per_binding is not None:
        if type(per_binding) is not list or len(per_binding) > 24:
            _refuse("binding_count")
        for item in cast(list[object], per_binding):
            _validate_binding(item)
    hnsw = work_map["hnsw"]
    if hnsw is not None:
        if type(hnsw) is not list or len(hnsw) > 24:
            _refuse("hnsw_count")
        for item in cast(list[object], hnsw):
            _validate_hnsw(item)
    _validate_fusion(work_map["fusion"])
    _validate_reference(work_map["reference"])
    validate_operation_relationships(record, identity=record["identity"], actual=actual_map, work=work_map)
    if record["record_sha256"] != observed_operation_digest(record):
        _refuse("record_digest")
    return record
