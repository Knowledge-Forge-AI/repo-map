"""Verify an observed execution envelope without relabeling its backend."""
from __future__ import annotations
from collections.abc import Callable, Mapping
from typing import Any
from common_lore_index.retrieval.query_contracts import QueryEnvelope
from retrieval_evaluation_schema import EvaluationTask
from retrieval_evaluation_scope import source_path_matches_prefix
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_semantic_provenance import VerifiedPublicationPin
from retrieval_semantic_baseline_scope import verify_baseline_source_scope
from retrieval_semantic_baseline_work import _CostClock

def _verify_envelope_scope(
    envelope: QueryEnvelope,
    task: EvaluationTask,
    pin: VerifiedPublicationPin,
    *,
    arm_backend: str,
    select_bindings: Callable[[EvaluationTask], tuple[str, ...]],
    sidecar: Any = None, clock: _CostClock | None = None,
) -> None:
    try:
        envelope.validate()
    except Exception as exc:
        raise ExperimentRefusal("invalid_query_envelope") from exc
    scope = envelope.scope
    selected = select_bindings(task)
    if scope.graph_id != task.graph_id:
        raise ExperimentRefusal("envelope_graph_id_mismatch")
    if scope.backend != arm_backend:
        raise ExperimentRefusal("envelope_observed_backend_mismatch")
    if len(scope.selected_binding_ids) != len(set(scope.selected_binding_ids)) or set(scope.selected_binding_ids) != set(selected):
        raise ExperimentRefusal("baseline_envelope_scope_mismatch")
    verify_baseline_source_scope(sidecar, envelope, task, pin, clock, selected)
    if scope.publication_bundle_id is not None and scope.publication_bundle_id != pin.publication_bundle_id:
        raise ExperimentRefusal("envelope_publication_bundle_mismatch")
    if scope.snapshot_manifest_id is not None and scope.snapshot_manifest_id != pin.snapshot_manifest_id:
        raise ExperimentRefusal("envelope_snapshot_manifest_mismatch")
    for hit in envelope.hits:
        loc = hit.locator
        if loc.binding_id not in selected:
            raise ExperimentRefusal("envelope_hit_binding_scope_mismatch")
        if not source_path_matches_prefix(loc.source_relative_path, task.source_path_prefix):
            raise ExperimentRefusal("envelope_hit_path_scope_mismatch")
    provenance = envelope.provenance
    if not isinstance(provenance, Mapping):
        raise ExperimentRefusal("invalid_query_envelope")
    for key, expected, code in (
        ("graph_id", pin.graph_id, "envelope_graph_id_mismatch"),
        ("generation", pin.generation, "envelope_generation_mismatch"),
        ("publication_bundle_id", pin.publication_bundle_id, "envelope_publication_bundle_mismatch"),
        ("snapshot_manifest_id", pin.snapshot_manifest_id, "envelope_snapshot_manifest_mismatch"),
        ("extraction_receipt_id", pin.extraction_receipt_id, "envelope_extraction_receipt_mismatch"),
        ("graph_candidate_id", pin.graph_candidate_id, "envelope_candidate_mismatch"),
        ("repository_identity", pin.repository_identity, "envelope_repository_identity_mismatch"),
    ):
        if key in provenance and (type(provenance[key]) is not type(expected) or provenance[key] != expected):
            raise ExperimentRefusal(code)
    run_ids = []
    for key in ("accepted_run_id", "run_id"):
        if key not in provenance:
            continue
        value = provenance[key]
        if type(value) is not int or value < 1:
            raise ExperimentRefusal("envelope_run_id_invalid")
        run_ids.append(value)
    if run_ids and (len(set(run_ids)) != 1 or run_ids[0] != pin.run_id):
        raise ExperimentRefusal("envelope_run_id_mismatch")
