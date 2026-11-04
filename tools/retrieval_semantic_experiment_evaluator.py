"""Pure W5 response sealing, exact-vector ranking, and file-level grading."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

from common_lore_index.storage.semantic_candidates import EmbeddingEntry
from retrieval_evaluation_grading import ExecutionState, GradedSlotRecord
from retrieval_evaluation_schema import EvaluationTask
from retrieval_semantic_experiment_contracts import (
    ExperimentCell,
    ExperimentRefusal,
    exact_cosine_distance,
)
from retrieval_semantic_fusion import (
    AdmittedArmObservation,
    FileIdentityTuple,
    FileFusionResult,
    VectorCandidateInput,
    fuse_arm_observations_rrf,
)
from retrieval_semantic_grading import grade_w5_task_slot
from retrieval_semantic_generator_inputs import PublicGenerationInput
from retrieval_semantic_generator_output import (
    GeneratedEnrichmentArtifact,
    seal_generation_result,
)
from retrieval_semantic_generator_output_parser import parse_verified_worker_response
from retrieval_semantic_generator_output_receipt import QueryEmbedding
from retrieval_semantic_provenance import VerifiedPublicationPin
from retrieval_semantic_experiment_scope import (
    accepted_candidate_evidence,
    selected_public_binding_ids,
)


@dataclass(frozen=True)
class SealedComponent:
    artifact: GeneratedEnrichmentArtifact
    response_identity: Mapping[str, str]
    response_cost: Mapping[str, object]
    response_counts: Mapping[str, object]


def seal_component_response(
    inputs: PublicGenerationInput,
    response_files: Mapping[str, bytes],
    *,
    expected_admission_sha256: str,
    expected_source_closure: Mapping[str, str],
) -> SealedComponent:
    """Verify every returned journal member before any vector is considered."""
    required = {
        "request.json",
        "admission.json",
        "declaration.json",
        "source-manifest.json",
        "sources.zip",
        "report.json",
        "terminal.json",
    }
    if not isinstance(response_files, Mapping) or set(response_files) != required:
        raise ExperimentRefusal("component_response_members")
    try:
        response = parse_verified_worker_response(
            request_raw=response_files["request.json"],
            report_raw=response_files["report.json"],
            terminal_raw=response_files["terminal.json"],
            declaration_raw=response_files["declaration.json"],
            source_manifest_raw=response_files["source-manifest.json"],
            sources_archive_raw=response_files["sources.zip"],
            expected_controller_admission_sha256=expected_admission_sha256,
            expected_source_closure=expected_source_closure,
        )
        artifact = seal_generation_result(inputs, response)
        artifact.require_importable()
    except Exception as exc:
        code = getattr(exc, "code", "component_response_refused")
        raise ExperimentRefusal(str(code)) from None
    generation = response.generation
    if generation is None:
        raise ExperimentRefusal("component_response_cost_missing")
    response_cost = {
        name: getattr(generation.cost, name)
        for name in (
            "input_records", "input_bytes", "model_input_bytes",
            "token_count_before_limit", "token_count_used", "overflow_chunks",
            "truncated_records", "load_seconds", "inference_seconds", "total_seconds",
        )
    }
    response_counts = {
        "record_count": response.record_count,
        "embedding_count": response.embedding_count,
        "document_count": response.document_count,
        "query_count": response.query_count,
    }
    return SealedComponent(
        artifact,
        {
            "request": response.request_sha256,
            "report": response.report_sha256,
            "terminal": response.terminal_sha256,
            "declaration": response.declaration_sha256,
            "source_manifest": response.source_manifest_sha256,
            "sources_archive": response.sources_archive_sha256,
            "admission": response.controller_admission_sha256,
        },
        response_cost,
        response_counts,
    )


def query_embedding(artifact: GeneratedEnrichmentArtifact, task_id: str) -> QueryEmbedding:
    for query in artifact.queries:
        if query.task_id == task_id:
            return query
    raise ExperimentRefusal("query_embedding_missing")


def rank_exact_entries(
    artifact: GeneratedEnrichmentArtifact,
    query_vector: Sequence[float],
    *,
    limit: int = 20,
    source_binding_ids: Sequence[str] | None = None,
) -> tuple[tuple[EmbeddingEntry, float], ...]:
    """Order the sealed document entries by independent exact cosine distance."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ExperimentRefusal("invalid_vector_limit")
    selected = None if source_binding_ids is None else frozenset(source_binding_ids)
    ranked = [
        (entry, exact_cosine_distance(query_vector, entry.vector))
        for entry in artifact.entries
        if selected is None or entry.source_binding_id in selected
    ]
    ranked.sort(key=lambda item: (item[1], item[0].canonical_key.encode("utf-8"), item[0].source_binding_id.encode("utf-8")))
    return tuple(ranked[:limit])


def _candidate_inputs(
    artifact: GeneratedEnrichmentArtifact,
    inputs: PublicGenerationInput,
    query_vector: Sequence[float],
    *,
    selected_binding_ids: Sequence[str],
    pin: VerifiedPublicationPin,
    limit: int,
) -> tuple[VectorCandidateInput, ...]:
    representations = {
        (doc.representation.canonical_key, doc.representation.source_binding_id): doc.representation
        for doc in inputs.documents
    }
    result: list[VectorCandidateInput] = []
    for rank, (entry, distance) in enumerate(
        rank_exact_entries(
            artifact, query_vector, limit=limit, source_binding_ids=selected_binding_ids
        ),
        start=1,
    ):
        representation = representations.get((entry.canonical_key, entry.source_binding_id))
        if representation is None:
            raise ExperimentRefusal("vector_representation_missing")
        if representation.input_digest != entry.input_digest:
            raise ExperimentRefusal("vector_representation_mismatch")
        snapshot = pin.snapshot_by_binding().get(entry.source_binding_id)
        if snapshot is None or snapshot[1] != representation.snapshot_id:
            raise ExperimentRefusal("vector_snapshot_mismatch")
        evidence = tuple(
            {
                "path": path,
                "metadata_json": {
                    "binding_id": representation.source_binding_id,
                    "snapshot_id": representation.snapshot_id,
                    "source_relative_path": path,
                },
            }
            for path in representation.source_relative_paths
        )
        if not evidence:
            raise ExperimentRefusal("vector_evidence_missing")
        result.append(
            VectorCandidateInput(
                canonical_key=entry.canonical_key,
                source_binding_id=entry.source_binding_id,
                raw_rank=rank,
                evidence=evidence,
                input_digest=entry.input_digest,
                kind=representation.kind,
                display_name=representation.display_name,
                cosine_distance=distance,
            )
        )
    return tuple(result)


def build_vector_arm(
    artifact: GeneratedEnrichmentArtifact,
    inputs: PublicGenerationInput,
    task: EvaluationTask,
    pin: VerifiedPublicationPin,
    *,
    arm_id: str = "exact_vector",
    limit: int = 20,
) -> AdmittedArmObservation | ExperimentCell:
    """Build an admitted exact-vector observation or a truthful unavailable cell."""
    if arm_id not in {"exact_vector", "hnsw_vector"}:
        raise ExperimentRefusal("invalid_vector_arm")
    if type(inputs) is not PublicGenerationInput:
        raise ExperimentRefusal("candidate_input_scope_required")
    selected_binding_ids = selected_public_binding_ids(task)
    if any(
        binding in pin.denied_bindings or binding not in pin.admitted_public_bindings
        for binding in selected_binding_ids
    ):
        raise ExperimentRefusal("candidate_source_scope_mismatch")
    query = query_embedding(artifact, str(task.task_id))
    if query.state != "admitted" or query.vector is None:
        state = ExecutionState.REFUSED if query.state == "refused" else ExecutionState.UNAVAILABLE
        return ExperimentCell(
            arm_id,
            str(task.task_id),
            state,
            query.reason or "query_not_admitted",
            cleanup_status="not_applicable",
        )
    candidates = _candidate_inputs(
        artifact, inputs, query.vector, selected_binding_ids=selected_binding_ids,
        pin=pin, limit=limit,
    )
    return AdmittedArmObservation(
        arm_id=arm_id,
        mode=str(task.requested_mode),
        verified_pin=pin,
        vector_candidates=candidates,
        selected_binding_ids=selected_binding_ids,
        observed_accepted_publication=pin.to_dict(),
    )


def grade_vector_arm(
    arm: AdmittedArmObservation | ExperimentCell,
    task: EvaluationTask,
    pin: VerifiedPublicationPin,
    *,
    lexical_arm: AdmittedArmObservation | None = None,
    fusion_sink: Callable[[FileFusionResult], None] | None = None,
) -> tuple[ExperimentCell, GradedSlotRecord | None]:
    """Fuse exact-vector and current lexical observations, then grade separately."""
    if isinstance(arm, ExperimentCell):
        return arm.validate(), None
    arms: tuple[AdmittedArmObservation, ...] = (arm,) if lexical_arm is None else (lexical_arm, arm)
    fused = fuse_arm_observations_rrf(
        arms,
        expected_pin=pin,
        allow_explicit_single_arm_fallback=lexical_arm is None,
    )
    if fusion_sink is not None:
        fusion_sink(fused)
    try:
        slot = grade_w5_task_slot(
            task,
            arm_id="hybrid_rrf" if lexical_arm is not None else arm.arm_id,
            verified_pin=pin,
            fusion_result=fused,
        )
    except Exception as exc:
        raise ExperimentRefusal("vector_grading_refused") from exc
    state = fused.execution_state
    reason = fused.refusal_code or fused.unavailable_reason or fused.failure_reason
    cell = ExperimentCell(
        "hybrid_rrf" if lexical_arm is not None else arm.arm_id,
        str(task.task_id),
        state,
        reason,
        tuple(hit.to_dict() for hit in fused.hits),
        cleanup_status="not_applicable",
    )
    return cell.validate(), slot


def build_candidate_rows_arm(
    rows: Sequence[Mapping[str, Any]],
    *,
    arm_id: str,
    task: EvaluationTask,
    pin: VerifiedPublicationPin,
    inputs: PublicGenerationInput | None = None,
) -> AdmittedArmObservation:
    """Convert maintained candidate readback into the same validated vector arm."""
    if arm_id not in {"exact_vector", "hnsw_vector"}:
        raise ExperimentRefusal("invalid_vector_arm")
    if type(inputs) is not PublicGenerationInput:
        raise ExperimentRefusal("candidate_input_scope_required")
    selected_binding_ids = selected_public_binding_ids(task)
    if any(
        binding in pin.denied_bindings or binding not in pin.admitted_public_bindings
        for binding in selected_binding_ids
    ):
        raise ExperimentRefusal("candidate_source_scope_mismatch")
    candidates: list[VectorCandidateInput] = []
    for rank, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ExperimentRefusal("candidate_row_malformed")
        candidate = accepted_candidate_evidence(row, task=task, inputs=inputs)
        canonical_key = candidate.canonical_key
        source_binding_id = candidate.source_binding_id
        input_digest = candidate.input_digest
        kind = candidate.kind
        display_name = candidate.display_name
        evidence = candidate.evidence
        snapshot = pin.snapshot_by_binding().get(source_binding_id)
        if snapshot is None or row.get("snapshot_id") != snapshot[1]:
            raise ExperimentRefusal("candidate_snapshot_mismatch")
        distance = row.get("distance")
        if distance is not None and (
            type(distance) not in (int, float) or not math.isfinite(float(distance))
        ):
            raise ExperimentRefusal("candidate_distance_invalid")
        candidates.append(
            VectorCandidateInput(
                canonical_key=canonical_key,
                source_binding_id=source_binding_id,
                raw_rank=rank,
                evidence=tuple(evidence),
                input_digest=input_digest,
                kind=kind,
                display_name=display_name,
                cosine_distance=float(distance) if distance is not None else None,
            )
        )
    return AdmittedArmObservation(
        arm_id=arm_id,
        mode=str(task.requested_mode),
        verified_pin=pin,
        vector_candidates=tuple(candidates),
        selected_binding_ids=selected_binding_ids,
        observed_accepted_publication=pin.to_dict(),
    )


def vector_candidate_file_identities(
    arm: AdmittedArmObservation,
    pin: VerifiedPublicationPin,
) -> tuple[FileIdentityTuple, ...]:
    """Project sealed vector evidence to explicit file identities for diagnostics."""
    if arm.vector_candidates is None:
        raise ExperimentRefusal("vector_candidates_missing")
    identities: list[FileIdentityTuple] = []
    for candidate in arm.vector_candidates:
        if not isinstance(candidate, VectorCandidateInput):
            raise ExperimentRefusal("vector_candidate_type")
        snapshot = pin.snapshot_by_binding().get(candidate.source_binding_id)
        if snapshot is None:
            raise ExperimentRefusal("vector_binding_missing")
        for evidence in candidate.evidence:
            metadata = evidence.get("metadata_json") if isinstance(evidence, Mapping) else None
            if not isinstance(metadata, Mapping):
                raise ExperimentRefusal("vector_evidence_metadata")
            snapshot_id = metadata.get("snapshot_id")
            source_relative_path = metadata.get("source_relative_path")
            if (
                type(snapshot_id) is not str
                or not snapshot_id
                or type(source_relative_path) is not str
                or not source_relative_path
            ):
                raise ExperimentRefusal("vector_evidence_identity")
            identities.append(
                FileIdentityTuple(
                    candidate.source_binding_id,
                    snapshot_id,
                    source_relative_path,
                ).validate()
            )
            if snapshot_id != snapshot[1]:
                raise ExperimentRefusal("vector_snapshot_mismatch")
    return tuple(identities)


__all__ = [
    "SealedComponent", "build_candidate_rows_arm", "build_vector_arm", "grade_vector_arm", "query_embedding",
    "rank_exact_entries", "seal_component_response", "vector_candidate_file_identities",
]
