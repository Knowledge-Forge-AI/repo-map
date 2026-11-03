"""Task-scoped binding and accepted-representation checks for W5 candidates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from common_lore_index.graph.multi_source import graph_source_binding_id
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_semantic_generator_inputs import PublicGenerationInput


@dataclass(frozen=True)
class AcceptedCandidate:
    canonical_key: str
    source_binding_id: str
    input_digest: str
    kind: str
    display_name: str
    evidence: tuple[Mapping[str, object], ...]


def selected_public_binding_ids(task: EvaluationTask) -> tuple[str, ...]:
    """Resolve only the task-declared aliases to canonical binding identities."""
    if type(task) is not EvaluationTask:
        raise ExperimentRefusal("invalid_calibration_task")
    try:
        task.validate()
    except Exception as exc:
        raise ExperimentRefusal("invalid_calibration_task") from exc
    if task.split != "calibration" or not task.selected_bindings:
        raise ExperimentRefusal("invalid_task_binding_scope")
    try:
        selected = tuple(
            binding if binding.startswith("bind1:") else graph_source_binding_id(task.graph_id, binding)
            for binding in task.selected_bindings
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ExperimentRefusal("invalid_task_binding_scope") from exc
    if len(selected) != len(set(selected)) or any(not binding for binding in selected):
        raise ExperimentRefusal("invalid_task_binding_scope")
    return selected


def accepted_candidate_evidence(
    row: Mapping[str, Any], *, task: EvaluationTask, inputs: PublicGenerationInput
) -> AcceptedCandidate:
    """Project only current verified representation paths into arm evidence."""
    if type(inputs) is not PublicGenerationInput:
        raise ExperimentRefusal("candidate_input_scope_required")
    canonical_key = row.get("canonical_key")
    source_binding_id = row.get("source_binding_id")
    input_digest = row.get("input_digest")
    kind = row.get("kind")
    display_name = row.get("display_name")
    if any(type(value) is not str or not value for value in (
        canonical_key, source_binding_id, input_digest, kind, display_name
    )):
        raise ExperimentRefusal("candidate_row_identity")
    assert isinstance(canonical_key, str)
    assert isinstance(source_binding_id, str)
    assert isinstance(input_digest, str)
    assert isinstance(kind, str)
    assert isinstance(display_name, str)
    if source_binding_id not in selected_public_binding_ids(task):
        raise ExperimentRefusal("candidate_source_scope_mismatch")
    representations = {
        (document.representation.canonical_key, document.representation.source_binding_id): document.representation
        for document in inputs.documents
    }
    representation = representations.get((canonical_key, source_binding_id))
    if representation is None or representation.input_digest != input_digest:
        raise ExperimentRefusal("candidate_representation_mismatch")
    if row.get("snapshot_id") != representation.snapshot_id:
        raise ExperimentRefusal("candidate_snapshot_mismatch")
    if kind != representation.kind or display_name != representation.display_name:
        raise ExperimentRefusal("candidate_representation_mismatch")
    raw_evidence = row.get("evidence")
    if not isinstance(raw_evidence, (list, tuple)):
        raise ExperimentRefusal("candidate_evidence_missing")
    evidence_keys: set[str] = set()
    for item in raw_evidence:
        if not isinstance(item, Mapping) or type(item.get("evidence_key")) is not str:
            raise ExperimentRefusal("candidate_evidence_missing")
        evidence_key = item["evidence_key"]
        if evidence_key not in representation.evidence_keys or evidence_key in evidence_keys:
            raise ExperimentRefusal("candidate_evidence_mismatch")
        evidence_keys.add(evidence_key)
    if not evidence_keys or not representation.source_relative_paths:
        raise ExperimentRefusal("candidate_evidence_missing")
    evidence = tuple(
        {
            "path": path,
            "metadata_json": {
                "binding_id": source_binding_id,
                "snapshot_id": representation.snapshot_id,
                "source_relative_path": path,
                "evidence_keys": list(representation.evidence_keys),
            },
        }
        for path in representation.source_relative_paths
    )
    return AcceptedCandidate(
        canonical_key, source_binding_id, input_digest, kind, display_name, evidence
    )


__all__ = ("AcceptedCandidate", "accepted_candidate_evidence", "selected_public_binding_ids")
