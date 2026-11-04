"""Strict, public-safe observed-operation record contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from retrieval_evaluation_grading import ExecutionState
from retrieval_semantic_experiment_contracts import ExperimentRefusal, digest_json
from retrieval_semantic_observed_operation import (
    OBSERVED_OPERATION_SCHEMA,
    finalize_observed_operation,
    validate_observed_operation,
)
from retrieval_semantic_observed_operation_capture import make_unadmitted_operation_identity
from retrieval_semantic_observed_operation_results import append_unadmitted_vector_observations


_DIGEST = "sha256:" + "a" * 64
_IDENTITY = {"generation": 1, "task_id": "task-1", "arm_id": "hnsw_vector", "repetition": 1}


class _Journal:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def append(self, record: dict[str, object]) -> None:
        self.records.append(record)


def _record() -> dict[str, object]:
    return {
        "schema": OBSERVED_OPERATION_SCHEMA,
        "identity": dict(_IDENTITY),
        "kind": "hnsw_vector",
        "state": "completed",
        "reason": None,
        "declared_mode": None,
        "actual": {
            "operation": "hnsw_vector_sql", "backend": "postgresql",
            "publication_identity": _DIGEST, "profile_identity": _DIGEST,
            "rebuild_id": "rebuild-1", "input_descriptor_sha256": _DIGEST,
            "selected_binding_ids": ["bind1"], "snapshot_manifest_id": "snap1",
            "effective_mode": None, "match_surface": None, "fallback": None,
        },
        "work": {
            "per_binding": [],
            "hnsw": [{
                "source_binding_id": "bind1",
                "plan": {
                    "node_types": ["Limit", "Index Scan"], "index_names": ["index-1"],
                    "actual_rows": 2, "planning_time_ms": 0.1, "execution_time_ms": 0.2,
                    "shared_hit_blocks": 4, "shared_read_blocks": 0,
                    "used_expected_index": True, "used_seq_scan": False,
                    "distance_order_present": True, "planner_forced": False,
                },
                "plan_sha256": _DIGEST,
                "provenance": {
                    "repository_identity": "repo1:fixture", "run_id": 1,
                    "receipt_identity": _DIGEST, "profile_identity": _DIGEST,
                    "rebuild_id": "rebuild-1", "index_name": "index-1",
                    "query_digest": _DIGEST, "attempt_identity": "attempt-1",
                    "source_scope": [["bind1", "snap1"]], "dimensions": 384,
                    "ef_search": 40, "iterative_scan": "off", "ann_scan_limit": 20,
                    "baseline_sql_digest": _DIGEST, "privacy_class": "public",
                    "search": "hnsw-disposable", "input_digest_validation": "verified",
                },
                "recall": {
                    "exact_count": 2, "ann_count": 2, "overlap_at_k": 2,
                    "recall_at_k": 1.0, "truncated": False,
                },
                "receipt_sha256": _DIGEST, "creation_state": "completed",
                "creation_error": None, "explain_executed": True,
                "cleanup_state": "verified", "result_state": "completed",
                "cell_state": "completed", "cell_reason": None, "result_reason": None,
            }],
            "fusion": {
                "policy_version": "cloe-w5-rrf-file-v1",
                "representation_version": "canonical-node-v1", "rrf_k": 60,
                "per_arm_raw_hit_counts": {"hnsw_vector": 1},
                "per_arm_collapsed_file_counts": {"hnsw_vector": 1},
                "pre_cap_fused_file_count": 1, "work_candidates_inspected": 1,
                "truncated": False, "partial_coverage": False,
                "fallback_disclosed": False, "fallback_from_arms": [],
                "incomplete_arms": [], "truncated_arms": [],
                "fusion_state": "completed", "fusion_reason": None,
                "provenance_identity": _DIGEST,
            },
            "reference": None,
        },
    }


def _set_path(root: dict[str, object], path: tuple[str | int, ...], value: object) -> None:
    cursor: object = root
    for key in path[:-1]:
        cursor = (
            cast(dict[str, object], cursor)[key]
            if type(key) is str else cast(list[object], cursor)[cast(int, key)]
        )
    last = path[-1]
    if type(last) is str:
        cast(dict[str, object], cursor)[last] = value
    else:
        cast(list[object], cursor)[cast(int, last)] = value


def _valid_record() -> dict[str, object]:
    record = _record()
    work = cast(dict[str, object], record["work"])
    hnsw = cast(list[object], work["hnsw"])
    item = cast(dict[str, object], hnsw[0])
    item["plan_sha256"] = digest_json(cast(dict[str, object], item["plan"]))
    return record


def test_real_postgres_plan_labels_and_digest_are_accepted() -> None:
    record = finalize_observed_operation(_valid_record())
    assert validate_observed_operation(record, identity=_IDENTITY) == record


def test_operation_identity_and_digest_are_bound() -> None:
    record = finalize_observed_operation(_valid_record())
    with pytest.raises(ExperimentRefusal, match="identity_mismatch"):
        validate_observed_operation(record, identity={**_IDENTITY, "repetition": 2})
    forged = dict(record)
    forged["reason"] = "changed_reason"
    with pytest.raises(ExperimentRefusal, match="record_digest"):
        validate_observed_operation(forged, identity=_IDENTITY)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("work", "hnsw", 0, "plan", "execution_time_ms"), -0.1),
        (("work", "hnsw", 0, "recall", "recall_at_k"), 1.1),
        (("work", "hnsw", 0, "recall", "overlap_at_k"), 3),
    ],
)
def test_negative_or_inconsistent_plan_and_recall_values_refuse(
    path: tuple[str | int, ...], value: object,
) -> None:
    record = _valid_record()
    _set_path(record, path, value)
    with pytest.raises(ExperimentRefusal):
        finalize_observed_operation(record)


def test_nested_hits_and_unadmitted_records_do_not_claim_execution() -> None:
    forged = _valid_record()
    forged["work"] = deepcopy(cast(dict[str, object], forged["work"]))
    work = cast(dict[str, object], forged["work"])
    hnsw = cast(list[object], work["hnsw"])
    cast(dict[str, object], hnsw[0])["hits"] = []
    with pytest.raises(ExperimentRefusal, match="forbidden_field"):
        finalize_observed_operation(forged)
    record = make_unadmitted_operation_identity(
        "task-1", 1, "exact_vector", 1, state=ExecutionState.REFUSED,
        reason="query_not_admitted",
    )
    assert cast(dict[str, object], record["actual"])["operation"] == "vector_query_not_attempted"
    assert cast(dict[str, object], record["work"])["hnsw"] == []


def test_unadmitted_writer_records_no_execution_for_each_vector_arm() -> None:
    journal = _Journal()
    cells: list[object] = []
    append_unadmitted_vector_observations(
        journal, task_id="task-1", generation=1, repetition=1,
        state=ExecutionState.REFUSED, reason="query_not_admitted",
        arm_ids=("exact_vector", "hnsw_vector", "hybrid_rrf"),
        cell_sink=lambda _identity, cell: cells.append(cell),
        include_operation=True,
    )
    observed = [record for record in journal.records if record["event"] == "query_observed"]
    assert len(observed) == 3 and len(cells) == 3
    assert all(
        cast(dict[str, object], record["observed_operation"])["state"] == "refused"
        for record in observed
    )
    assert all(
        cast(dict[str, object], record["observed_operation"])["actual"]
        == {
            "operation": "vector_query_not_attempted", "backend": None,
            "publication_identity": None, "profile_identity": None, "rebuild_id": None,
            "input_descriptor_sha256": None, "selected_binding_ids": [],
            "snapshot_manifest_id": None, "effective_mode": None, "match_surface": None,
            "fallback": None,
        }
        for record in observed
    )


def test_serialized_hnsw_scope_provenance_and_plan_conflicts_refuse() -> None:
    forged = _valid_record()
    item = cast(dict[str, object], cast(list[object], cast(dict[str, object], forged["work"])["hnsw"])[0])
    item["source_binding_id"] = "bind2"
    with pytest.raises(ExperimentRefusal, match="hnsw_bindings_scope"):
        finalize_observed_operation(forged)

    forged = _valid_record()
    item = cast(dict[str, object], cast(list[object], cast(dict[str, object], forged["work"])["hnsw"])[0])
    provenance = cast(dict[str, object], item["provenance"])
    provenance["receipt_identity"] = "sha256:" + "b" * 64
    with pytest.raises(ExperimentRefusal, match="hnsw_provenance_mismatch"):
        finalize_observed_operation(forged)

    forged = _valid_record()
    item = cast(dict[str, object], cast(list[object], cast(dict[str, object], forged["work"])["hnsw"])[0])
    item["explain_executed"] = False
    with pytest.raises(ExperimentRefusal, match="hnsw_explain_conflict"):
        finalize_observed_operation(forged)


def test_hnsw_cleanup_failure_preserves_raw_result_state() -> None:
    forged = _valid_record()
    forged["state"] = "failed"
    forged["reason"] = "cleanup_failed"
    item = cast(dict[str, object], cast(list[object], cast(dict[str, object], forged["work"])["hnsw"])[0])
    item["cell_state"] = "failed"
    item["cell_reason"] = "cleanup_failed"
    item["cleanup_state"] = "failed"
    cast(dict[str, object], forged["work"])["fusion"] = None
    record = finalize_observed_operation(forged)
    validated_item = cast(dict[str, object], cast(list[object], cast(dict[str, object], record["work"])["hnsw"])[0])
    assert validated_item["cell_state"] == "failed"
    assert validated_item["result_state"] == "completed"
