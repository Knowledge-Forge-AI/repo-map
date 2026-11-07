"""Cross-field consistency checks for serialized observed operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import NoReturn, cast

from retrieval_semantic_experiment_contracts import ExperimentRefusal


_VECTOR_ARMS = frozenset({"exact_vector", "hnsw_vector", "hybrid_rrf"})
_STATES = frozenset({"completed", "not_run", "unavailable", "refused", "failed"})


def _refuse(code: str) -> NoReturn:
    raise ExperimentRefusal("observed_operation_" + code)


def _mapping(value: object, code: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        _refuse(code)
    return dict(value)


def _ids(value: object, code: str) -> list[str]:
    if type(value) is not list:
        _refuse(code)
    values = cast(list[object], value)
    if any(type(item) is not str for item in values):
        _refuse(code)
    result = cast(list[str], values)
    if len(set(result)) != len(result):
        _refuse(code + "_duplicate")
    return result


def _same_binding_scope(value: object, selected: list[str], code: str) -> None:
    ids = _record_ids(value, code)
    if not ids or set(ids) != set(selected):
        _refuse(code + "_scope")


def _record_ids(value: object, code: str) -> list[str]:
    if type(value) is not list:
        _refuse(code)
    result: list[str] = []
    for item in cast(list[object], value):
        mapping = _mapping(item, code)
        binding = mapping.get("source_binding_id")
        if type(binding) is not str:
            _refuse(code)
        result.append(binding)
    if len(set(result)) != len(result):
        _refuse(code + "_duplicate")
    return result


def _aggregate(states: list[str]) -> str:
    for state in ("failed", "refused", "unavailable", "not_run", "completed"):
        if state in states:
            return state
    return "not_run"


def _validate_hnsw_item(
    item: dict[str, object], *, actual: dict[str, object], selected: list[str],
) -> None:
    binding = item["source_binding_id"]
    if binding not in selected:
        _refuse("hnsw_foreign_binding")
    cell_state = item["cell_state"]
    result_state = item["result_state"]
    creation_state = item["creation_state"]
    cleanup_state = item["cleanup_state"]
    if cell_state not in _STATES or (result_state is not None and result_state not in _STATES):
        _refuse("hnsw_state")
    if cell_state == "completed" and result_state != "completed":
        _refuse("hnsw_cell_result_conflict")
    if cell_state == "completed" and (creation_state != "completed" or cleanup_state != "verified"):
        _refuse("hnsw_completion_evidence")
    if cleanup_state == "failed" and cell_state == "completed":
        _refuse("hnsw_cleanup_conflict")
    if creation_state == "failed" and item["creation_error"] is None:
        _refuse("hnsw_creation_error")
    if creation_state == "completed" and item["creation_error"] is not None:
        _refuse("hnsw_creation_error")
    if creation_state != "completed" and result_state == "completed":
        _refuse("hnsw_creation_result_conflict")
    if result_state is None and (item["provenance"] is not None or item["recall"] is not None):
        _refuse("hnsw_result_evidence")
    plan = item["plan"]
    explain = item["explain_executed"]
    if (plan is None and explain is True) or (plan is not None and explain is not True):
        _refuse("hnsw_explain_conflict")
    if result_state == "completed" and (
        not isinstance(plan, Mapping)
        or plan.get("used_expected_index") is not True
        or plan.get("distance_order_present") is not True
    ):
        _refuse("hnsw_index_execution_evidence")
    provenance = item["provenance"]
    if provenance is None:
        if result_state == "completed":
            _refuse("hnsw_provenance_missing")
        return
    prov = _mapping(provenance, "hnsw_provenance")
    for field in ("receipt_identity", "profile_identity", "rebuild_id"):
        actual_field = {
            "receipt_identity": "publication_identity",
            "profile_identity": "profile_identity",
            "rebuild_id": "rebuild_id",
        }[field]
        if prov[field] != actual[actual_field]:
            _refuse("hnsw_provenance_mismatch")
    if prov["privacy_class"] != "public":
        _refuse("hnsw_privacy")
    for field in ("run_id", "dimensions", "ef_search", "ann_scan_limit"):
        if type(prov[field]) is not int or cast(int, prov[field]) <= 0:
            _refuse("hnsw_positive_" + field)
    if isinstance(plan, Mapping) and plan.get("used_expected_index") is True:
        names = plan.get("index_names")
        if type(names) is not list or prov["index_name"] not in names:
            _refuse("hnsw_index_identity")
    scope = prov["source_scope"]
    if type(scope) is not list or len(scope) != 1:
        _refuse("hnsw_source_scope")
    pair = cast(list[object], scope)[0]
    if type(pair) is not list or len(pair) != 2 or pair[0] != binding:
        _refuse("hnsw_source_scope")


def validate_operation_relationships(
    record: Mapping[str, object], *, identity: Mapping[str, object],
    actual: Mapping[str, object], work: Mapping[str, object],
) -> None:
    """Refuse internally inconsistent records even when each field is well-typed."""
    arm_id = identity["arm_id"]
    kind = record["kind"]
    operation = actual["operation"]
    expected_kind = arm_id if arm_id in _VECTOR_ARMS else "baseline_query"
    if kind != expected_kind:
        _refuse("kind_identity")
    expected_operation = {
        "exact_vector": "exact_vector_sql", "hnsw_vector": "hnsw_vector_sql",
        "hybrid_rrf": "rrf_file_fusion",
    }.get(cast(str, arm_id))
    if expected_operation is None:
        if operation != "query_envelope":
            _refuse("baseline_operation")
    elif operation not in {expected_operation, "vector_query_not_attempted"}:
        _refuse("operation_identity")
    selected = _ids(actual["selected_binding_ids"], "selected_binding_ids")
    per_binding = work["per_binding"]
    hnsw = work["hnsw"]
    per_ids = [] if per_binding is None or per_binding == [] else _record_ids(per_binding, "per_binding")
    hnsw_ids = [] if hnsw is None or hnsw == [] else _record_ids(hnsw, "hnsw_bindings")
    if operation == "vector_query_not_attempted":
        if selected or per_ids or hnsw_ids or any(actual[field] is not None for field in (
            "backend", "publication_identity", "profile_identity", "rebuild_id", "input_descriptor_sha256",
            "snapshot_manifest_id", "effective_mode", "match_surface", "fallback",
        )):
            _refuse("not_attempted_execution")
        if record["state"] == "completed":
            _refuse("not_attempted_completed")
        if work["fusion"] is not None or work["reference"] is not None:
            _refuse("not_attempted_work")
        return
    if kind != "baseline_query" and any(record[field] is not None for field in ("declared_mode",)):
        _refuse("vector_mode_claim")
    if kind != "baseline_query" and any(actual[field] is None for field in (
        "backend", "publication_identity", "profile_identity", "rebuild_id", "snapshot_manifest_id",
    )):
        _refuse("vector_actual_missing")
    if kind != "baseline_query" and any(actual[field] is not None for field in ("effective_mode", "match_surface", "fallback")):
        _refuse("vector_mode_claim")
    if operation == "exact_vector_sql":
        _same_binding_scope(per_binding, selected, "per_binding")
        if hnsw_ids:
            _refuse("exact_hnsw_scope")
        query_state = _aggregate([cast(str, cast(dict[str, object], item)["state"]) for item in cast(list[object], per_binding)])
        if record["state"] == "completed" and (
            actual["input_descriptor_sha256"] is None
            or any(cast(dict[str, object], item)["query_descriptor_sha256"] is None
                   for item in cast(list[object], per_binding))
        ):
            _refuse("exact_query_descriptor_missing")
        fusion = work["fusion"]
        if fusion is None:
            if query_state == "completed":
                _refuse("exact_fusion_missing")
            if record["state"] != query_state:
                _refuse("exact_state")
        if fusion is not None:
            if query_state != "completed":
                _refuse("fusion_without_completed_query")
            fusion_map = _mapping(fusion, "exact_fusion")
            if fusion_map["fusion_state"] != record["state"]:
                _refuse("exact_fusion_state")
            if record["state"] == "completed" and fusion_map["provenance_identity"] is None:
                _refuse("exact_fusion_provenance")
            if fusion_map["provenance_identity"] is not None and fusion_map["provenance_identity"] != actual["publication_identity"]:
                _refuse("exact_fusion_provenance")
    elif operation == "hnsw_vector_sql":
        _same_binding_scope(hnsw, selected, "hnsw_bindings")
        if per_ids:
            _refuse("hnsw_exact_scope")
        for item in cast(list[object], hnsw):
            _validate_hnsw_item(_mapping(item, "hnsw_item"), actual=dict(actual), selected=selected)
        query_state = _aggregate([
            cast(str, cast(dict[str, object], item)["cell_state"]) for item in cast(list[object], hnsw)
        ])
        if record["state"] == "completed" and actual["input_descriptor_sha256"] is None:
            _refuse("hnsw_query_descriptor_missing")
        fusion = work["fusion"]
        if fusion is None:
            if query_state == "completed":
                _refuse("hnsw_fusion_missing")
            if record["state"] != query_state:
                _refuse("hnsw_state")
        if fusion is not None:
            if query_state != "completed":
                _refuse("fusion_without_completed_query")
            fusion_map = _mapping(fusion, "hnsw_fusion")
            if fusion_map["fusion_state"] != record["state"]:
                _refuse("hnsw_fusion_state")
            if record["state"] == "completed" and fusion_map["provenance_identity"] is None:
                _refuse("hnsw_fusion_provenance")
            if fusion_map["provenance_identity"] is not None and fusion_map["provenance_identity"] != actual["publication_identity"]:
                _refuse("hnsw_fusion_provenance")
    elif operation == "rrf_file_fusion":
        if per_ids or hnsw_ids or not selected:
            _refuse("fusion_scope")
        fusion = _mapping(work["fusion"], "fusion_required")
        if fusion["fusion_state"] != record["state"]:
            _refuse("fusion_state")
        if fusion["provenance_identity"] is not None and fusion["provenance_identity"] != actual["publication_identity"]:
            _refuse("fusion_provenance")


__all__ = ["validate_operation_relationships"]
