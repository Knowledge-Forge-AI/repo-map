"""Typed, compact operation records for the W5 evaluator writers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from common_lore_index.storage.semantic_candidates import CandidatePublication, EmbeddingProfile
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_ann_models import HnswResult
from retrieval_semantic_experiment_contracts import ExperimentCell, ExperimentRefusal, digest_json
from retrieval_semantic_fusion import FileFusionResult
from retrieval_semantic_observed_operation_fusion import (
    fusion_work as _fusion_work, query_and_fusion_outcome, safe_operation_reason as _safe_reason,
)
from retrieval_semantic_observed_operation import (
    OBSERVED_OPERATION_SCHEMA, finalize_observed_operation,
)
from retrieval_semantic_provenance import VerifiedPublicationPin


class HnswObservationLike(Protocol):
    @property
    def cell(self) -> ExperimentCell: ...
    @property
    def plan(self) -> object: ...
    @property
    def plan_sha256(self) -> str: ...
    @property
    def result(self) -> HnswResult | None: ...


def _state(value: ExecutionState | str) -> str:
    return value.value if isinstance(value, ExecutionState) else value


def _aggregate_state(states: Sequence[str]) -> str:
    for state in ("failed", "refused", "unavailable", "not_run", "completed"):
        if state in states:
            return state
    return "not_run"


def _binding_outcome_reason(items: Sequence[Mapping[str, object]]) -> str | None:
    states = [str(item["state"]) for item in items]
    if all(
        state == "completed" and item["reason"] is None
        for state, item in zip(states, items, strict=True)
    ):
        return None
    for state, reason in (
        ("failed", "binding_execution_failed"),
        ("refused", "binding_refused"),
        ("unavailable", "binding_unavailable"),
        ("not_run", "binding_not_run"),
    ):
        if state in states:
            return reason
    return "binding_execution_failed"


def _no_attempt_actual() -> dict[str, object]:
    return {
        "operation": "vector_query_not_attempted", "backend": None,
        "publication_identity": None, "profile_identity": None, "rebuild_id": None,
        "input_descriptor_sha256": None, "selected_binding_ids": [],
        "snapshot_manifest_id": None, "effective_mode": None, "match_surface": None,
        "fallback": None,
    }


def _identity(task: EvaluationTask, arm_id: str, repetition: int) -> dict[str, object]:
    if type(task) is not EvaluationTask or type(arm_id) is not str or not arm_id:
        raise ExperimentRefusal("observed_operation_identity")
    return {
        "generation": task.generation, "task_id": task.task_id,
        "arm_id": arm_id, "repetition": repetition,
    }


def _pin_context(
    publication: CandidatePublication, pin: VerifiedPublicationPin, profile: EmbeddingProfile,
    rebuild_id: str, vector: Sequence[float], *, operation: str,
    selected_binding_ids: Sequence[str], task_sha256: str | None,
    query_descriptor_sha256: str | None,
) -> tuple[VerifiedPublicationPin, dict[str, object]]:
    if type(publication) is not CandidatePublication or type(profile) is not EmbeddingProfile:
        raise ExperimentRefusal("observed_operation_inputs")
    if type(pin) is not VerifiedPublicationPin or type(rebuild_id) is not str or not rebuild_id:
        raise ExperimentRefusal("observed_operation_inputs")
    if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)):
        raise ExperimentRefusal("observed_operation_vector")
    selected = list(selected_binding_ids)
    if not pin.is_factory_issued():
        raise ExperimentRefusal("observed_operation_unverified_pin")
    actual_pin = pin.revalidate_current()
    publication.validate()
    profile.validate()
    if (
        publication.repository_identity != actual_pin.repository_identity
        or publication.publication.run_id != actual_pin.run_id
        or publication.receipt_identity != actual_pin.receipt_identity
    ):
        raise ExperimentRefusal("observed_operation_publication_mismatch")
    snapshots = actual_pin.snapshot_by_binding()
    if not selected or len(set(selected)) != len(selected) or any(
        binding not in actual_pin.admitted_public_bindings
        or binding not in snapshots
        for binding in selected
    ):
        raise ExperimentRefusal("observed_operation_binding_scope")
    return actual_pin, {
        "operation": operation,
        "backend": actual_pin.backend,
        "publication_identity": actual_pin.receipt_identity,
        "profile_identity": profile.identity,
        "rebuild_id": rebuild_id,
        "input_descriptor_sha256": query_descriptor_sha256,
        "selected_binding_ids": selected,
        "snapshot_manifest_id": actual_pin.snapshot_manifest_id,
        "effective_mode": None,
        "match_surface": None,
        "fallback": None,
    }


def _base_identity(
    identity: Mapping[str, object], arm_id: str, *, state: ExecutionState | str,
    reason: str | None, declared_mode: str | None, actual: Mapping[str, object],
    work: Mapping[str, object],
) -> dict[str, object]:
    return finalize_observed_operation({
        "schema": OBSERVED_OPERATION_SCHEMA,
        "identity": dict(identity),
        "kind": arm_id if arm_id in {"exact_vector", "hnsw_vector", "hybrid_rrf"} else "baseline_query",
        "state": _state(state), "reason": _safe_reason(reason),
        "declared_mode": declared_mode, "actual": dict(actual), "work": dict(work),
    })


def _base(
    task: EvaluationTask, arm_id: str, repetition: int, *, state: ExecutionState | str,
    reason: str | None, declared_mode: str | None, actual: Mapping[str, object],
    work: Mapping[str, object],
) -> dict[str, object]:
    return _base_identity(
        _identity(task, arm_id, repetition), arm_id, state=state, reason=reason,
        declared_mode=declared_mode, actual=actual, work=work,
    )


def make_unadmitted_operation(
    task: EvaluationTask, arm_id: str, repetition: int, state: ExecutionState, reason: str,
) -> dict[str, object]:
    return _base(
        task, arm_id, repetition, state=state, reason=reason, declared_mode=None,
        actual=_no_attempt_actual(),
        work={"per_binding": [], "hnsw": [], "fusion": None, "reference": None},
    )


def make_unadmitted_operation_identity(
    task_id: str, generation: int, arm_id: str, repetition: int,
    state: ExecutionState, reason: str,
) -> dict[str, object]:
    return _base_identity(
        {"generation": generation, "task_id": task_id, "arm_id": arm_id, "repetition": repetition},
        arm_id, state=state, reason=reason, declared_mode=None,
        actual=_no_attempt_actual(),
        work={"per_binding": [], "hnsw": [], "fusion": None, "reference": None},
    )


def make_exact_operation(
    task: EvaluationTask, repetition: int, *, publication: CandidatePublication,
    pin: VerifiedPublicationPin, profile: EmbeddingProfile, rebuild_id: str,
    vector: Sequence[float], task_sha256: str | None,
    results: Mapping[str, tuple[ExperimentCell, Sequence[Mapping[str, object]]]],
    query_descriptors: Mapping[str, str] | None = None,
    fused: FileFusionResult | None = None,
) -> dict[str, object]:
    bindings = list(results)
    complete_descriptors = query_descriptors is not None and all(
        binding in query_descriptors for binding in bindings
    )
    aggregate_descriptor = (
        digest_json({"queries": [[binding, query_descriptors[binding]] for binding in bindings]})
        if complete_descriptors and query_descriptors is not None else None
    )
    actual_pin, actual = _pin_context(
        publication, pin, profile, rebuild_id, vector, operation="exact_vector_sql",
        selected_binding_ids=bindings, task_sha256=task_sha256,
        query_descriptor_sha256=aggregate_descriptor,
    )
    per_binding: list[dict[str, object]] = []
    for binding, (cell, rows) in results.items():
        cell.validate()
        descriptor = query_descriptors.get(binding) if query_descriptors is not None else None
        per_binding.append({
            "source_binding_id": binding, "state": cell.execution_state.value,
            "reason": _safe_reason(cell.reason), "elapsed_ns": cell.elapsed_ns,
            "candidate_count": len(rows), "query_descriptor_sha256": descriptor,
        })
    actual["backend"] = actual_pin.backend
    if not per_binding:
        raise ExperimentRefusal("observed_operation_bindings")
    state, reason = query_and_fusion_outcome(
        _aggregate_state([str(item["state"]) for item in per_binding]),
        _binding_outcome_reason(per_binding), fused,
    )
    return _base(
        task, "exact_vector", repetition, state=state, reason=reason,
        declared_mode=None, actual=actual,
        work={
            "per_binding": per_binding, "hnsw": [],
            "fusion": None if fused is None else _fusion_work(fused),
            "reference": None,
        },
    )


def _hnsw_binding_work(
    binding: str, observation: HnswObservationLike, receipt: Mapping[str, object],
) -> dict[str, object]:
    cell = observation.cell.validate()
    result = observation.result
    plan = observation.plan if isinstance(observation.plan, Mapping) and observation.plan else None
    plan_sha = observation.plan_sha256 if plan is not None else None
    recall = result.recall.to_dict() if isinstance(result, HnswResult) and result.recall is not None else None
    cleanup = receipt.get("cleanup")
    cleanup_map = cleanup if isinstance(cleanup, Mapping) else {}
    creation_state = "completed" if "creation" in receipt else "failed" if "creation_error" in receipt else "not_attempted"
    result_state = result.state.value if isinstance(result, HnswResult) else None
    result_reason = _safe_reason(result.reason) if isinstance(result, HnswResult) else None
    raw_provenance = result.provenance.to_dict() if isinstance(result, HnswResult) and result.provenance is not None else None
    provenance = None if raw_provenance is None else {
        key: raw_provenance[key]
        for key in (
            "repository_identity", "run_id", "receipt_identity", "profile_identity", "rebuild_id",
            "index_name", "query_digest", "attempt_identity", "source_scope", "dimensions",
            "ef_search", "iterative_scan", "ann_scan_limit", "baseline_sql_digest", "privacy_class",
            "search", "input_digest_validation",
        )
    }
    raw_creation_error = receipt.get("creation_error")
    return {
        "source_binding_id": binding, "plan": plan, "plan_sha256": plan_sha,
        "provenance": provenance, "recall": recall,
        "receipt_sha256": digest_json(dict(receipt)), "creation_state": creation_state,
        "creation_error": _safe_reason(raw_creation_error) if creation_state == "failed" else None,
        "explain_executed": True if plan is not None else None,
        "cleanup_state": (
            "verified" if cleanup_map.get("status") == "verified_absent"
            else "failed" if cleanup_map else "not_attempted"
        ),
        "cell_state": cell.execution_state.value, "cell_reason": _safe_reason(cell.reason),
        "result_state": result_state, "result_reason": result_reason,
    }


def _verify_hnsw_provenance(
    binding: str, observation: HnswObservationLike, receipt: Mapping[str, object],
    publication: CandidatePublication, pin: VerifiedPublicationPin, profile: EmbeddingProfile,
    rebuild_id: str,
) -> None:
    result = observation.result
    if not isinstance(result, HnswResult):
        return
    if result.state.value == "completed" and result.provenance is None:
        raise ExperimentRefusal("observed_operation_provenance_missing")
    if result.provenance is None:
        return
    provenance = result.provenance.to_dict()
    expected = {
        "repository_identity": publication.repository_identity,
        "run_id": publication.publication.run_id,
        "receipt_identity": pin.receipt_identity,
        "profile_identity": profile.identity,
        "rebuild_id": rebuild_id,
        "dimensions": profile.dimensions,
        "attempt_identity": receipt.get("attempt_identity"),
    }
    if any(provenance.get(field) != value for field, value in expected.items()):
        raise ExperimentRefusal("observed_operation_provenance_mismatch")
    if receipt.get("query_digest") is not None and provenance.get("query_digest") != receipt.get("query_digest"):
        raise ExperimentRefusal("observed_operation_query_mismatch")
    snapshot_id = pin.snapshot_by_binding().get(binding)
    if snapshot_id is None or provenance.get("source_scope") != [[binding, snapshot_id[1]]]:
        raise ExperimentRefusal("observed_operation_scope_mismatch")


def make_hnsw_operation(
    task: EvaluationTask, repetition: int, *, publication: CandidatePublication,
    pin: VerifiedPublicationPin, profile: EmbeddingProfile, rebuild_id: str,
    vector: Sequence[float], task_sha256: str | None,
    results: Mapping[str, tuple[HnswObservationLike, object, object, int, int, Mapping[str, object]]],
    exact_state: ExecutionState, exact_count: int, reference_recall: float | None = None,
    fused: FileFusionResult | None = None,
) -> dict[str, object]:
    bindings = list(results)
    actual_pin, actual = _pin_context(
        publication, pin, profile, rebuild_id, vector, operation="hnsw_vector_sql",
        selected_binding_ids=bindings, task_sha256=task_sha256,
        query_descriptor_sha256=(digest_json({
            "queries": [[binding, value[5].get("query_digest")] for binding, value in results.items()]
        }) if results and all(value[5].get("query_digest") is not None for value in results.values()) else None),
    )
    if not results:
        raise ExperimentRefusal("observed_operation_bindings")
    hnsw: list[dict[str, object]] = []
    for binding, value in results.items():
        _verify_hnsw_provenance(
            binding, value[0], value[5], publication, actual_pin, profile, rebuild_id,
        )
        hnsw.append(_hnsw_binding_work(binding, value[0], value[5]))
    completed = all(item["cell_state"] == "completed" for item in hnsw)
    reference: dict[str, object]
    if exact_state != ExecutionState.COMPLETED:
        reference = {"status": "unavailable", "reason": _safe_reason(exact_state.value), "recall": None}
    elif exact_count == 0:
        reference = {"status": "vacuous_empty", "reason": "exact_reference_empty", "recall": None}
    elif reference_recall is not None:
        reference = {"status": "measured", "reason": None, "recall": reference_recall}
    else:
        reference = {"status": "not_attempted", "reason": "reference_recall_not_recorded", "recall": None}
    state = "completed" if completed else _aggregate_state([str(item["cell_state"]) for item in hnsw])
    reason = None if completed else next((
        item["cell_reason"] for item in hnsw
        if item["cell_state"] == state and item["cell_reason"]
    ), None)
    state, reason = query_and_fusion_outcome(state, _safe_reason(reason), fused)
    return _base(
        task, "hnsw_vector", repetition, state=state, reason=reason, declared_mode=None,
        actual=actual, work={
            "per_binding": [], "hnsw": hnsw,
            "fusion": None if fused is None else _fusion_work(fused),
            "reference": reference,
        },
    )




def make_hybrid_operation(
    task: EvaluationTask, repetition: int, *, publication: CandidatePublication,
    pin: VerifiedPublicationPin, profile: EmbeddingProfile, rebuild_id: str,
    vector: Sequence[float], task_sha256: str | None, selected_binding_ids: Sequence[str],
    fused: FileFusionResult | None, upstream_state: ExecutionState | None = None,
    upstream_reason: str | None = None,
) -> dict[str, object]:
    if fused is None:
        return _base(
            task, "hybrid_rrf", repetition, state=upstream_state or ExecutionState.NOT_RUN,
            reason=upstream_reason, declared_mode=None, actual=_no_attempt_actual(),
            work={"per_binding": [], "hnsw": [], "fusion": None, "reference": None},
        )
    operation = "rrf_file_fusion"
    _actual_pin, actual = _pin_context(
        publication, pin, profile, rebuild_id, vector, operation=operation,
        selected_binding_ids=selected_binding_ids, task_sha256=task_sha256,
        query_descriptor_sha256=None,
    )
    state, reason, fusion = fused.execution_state, fused.refusal_code or fused.unavailable_reason or fused.failure_reason, _fusion_work(fused)
    return _base(
        task, "hybrid_rrf", repetition, state=state, reason=reason, declared_mode=None,
        actual=actual, work={"per_binding": [], "hnsw": [], "fusion": fusion, "reference": None},
    )


__all__ = [
    "make_exact_operation", "make_hnsw_operation", "make_hybrid_operation",
    "make_unadmitted_operation", "make_unadmitted_operation_identity",
]
