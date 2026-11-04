"""Task-scoped binding and accepted-representation checks for W5 candidates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from common_lore_index.graph.multi_source import graph_source_binding_id
from common_lore_index.retrieval.projection_build import CapturedTextProjection
from common_lore_index.retrieval.projection_policy import BodyProjectionPolicy
from common_lore_index.retrieval.publication_binding import ProjectionInputs
from common_lore_index.retrieval.query_contracts import QueryEnvelope
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_evaluation_views import MaterializedNativeView, NativeMaterializationWitness
from retrieval_semantic_baseline_capture import IssuedBaselineCapture, is_verified_sidecar
from retrieval_semantic_baseline_correspondence import verify_strict_baseline_correspondence_sidecar
from retrieval_semantic_experiment_contracts import ExperimentRefusal, digest_json
from retrieval_semantic_generator_inputs import PublicGenerationInput
from retrieval_semantic_provenance import VerifiedPublicationPin

W5_BASELINE_CORRESPONDENCE_SCHEMA_V1 = "cloe-w5-baseline-correspondence-v1"
W5_EXPERIMENT_RESULT_SCHEMA_V2 = "cloe-w5-semantic-experiment-v2"

BASELINE_ARM_OBSERVED_BACKENDS: Mapping[str, str] = MappingProxyType({
    "native_tools_baseline": "native_filesystem",
    "current_graph_baseline:sqlite": "sqlite",
    "current_graph_baseline:postgresql": "postgresql",
    "captured_projection_reference:sqlite": "captured_reference",
    "captured_projection_reference:postgresql": "captured_reference",
    "postgres_native_fts:postgresql": "postgresql",
})
BASELINE_ARM_TARGET_BACKENDS: Mapping[str, str] = MappingProxyType({
    "native_tools_baseline": "sqlite",
    "current_graph_baseline:sqlite": "sqlite",
    "current_graph_baseline:postgresql": "postgresql",
    "captured_projection_reference:sqlite": "sqlite",
    "captured_projection_reference:postgresql": "postgresql",
    "postgres_native_fts:postgresql": "postgresql",
})

from retrieval_semantic_baseline_expectations import (
    W5_EXPECTED_BASELINE_GAPS_BY_ARM as W5_EXPECTED_BASELINE_GAPS_BY_ARM,
    W5_EXPECTED_BASELINE_GAPS_BY_ARM_V1 as W5_EXPECTED_BASELINE_GAPS_BY_ARM_V1,
    W5_EXPECTED_BASELINE_GAPS_BY_ARM_V2 as W5_EXPECTED_BASELINE_GAPS_BY_ARM_V2,
    is_expected_baseline_gap as is_expected_baseline_gap,
)



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
    canonical_key, source_binding_id = row.get("canonical_key"), row.get("source_binding_id")
    input_digest, kind, display_name = row.get("input_digest"), row.get("kind"), row.get("display_name")
    if any(type(v) is not str or not v for v in (canonical_key, source_binding_id, input_digest, kind, display_name)):
        raise ExperimentRefusal("candidate_row_identity")
    assert isinstance(canonical_key, str) and isinstance(source_binding_id, str)
    assert isinstance(input_digest, str) and isinstance(kind, str) and isinstance(display_name, str)
    if source_binding_id not in selected_public_binding_ids(task):
        raise ExperimentRefusal("candidate_source_scope_mismatch")
    representations = {
        (doc.representation.canonical_key, doc.representation.source_binding_id): doc.representation
        for doc in inputs.documents
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
                "binding_id": source_binding_id, "snapshot_id": representation.snapshot_id,
                "source_relative_path": path, "evidence_keys": list(representation.evidence_keys),
            },
        }
        for path in representation.source_relative_paths
    )
    return AcceptedCandidate(canonical_key, source_binding_id, input_digest, kind, display_name, evidence)


@dataclass(frozen=True)
class CorrespondenceCostSample:
    """Measured correspondence verification IO/time and failures separate from query time."""

    correspondence_verification_ns: int = 0
    correspondence_verification_bytes_read: int | None = None
    known_artifact_bytes_read: int = 0
    known_materialized_bytes_read: int = 0
    correspondence_failures: int = 0

    def validate(self) -> CorrespondenceCostSample:
        if self.correspondence_verification_bytes_read is not None and (
            type(self.correspondence_verification_bytes_read) is not int
            or self.correspondence_verification_bytes_read < 0
        ):
            raise ExperimentRefusal("invalid_correspondence_verification_bytes_read")
        for name, val in (
            ("correspondence_verification_ns", self.correspondence_verification_ns),
            ("known_artifact_bytes_read", self.known_artifact_bytes_read),
            ("known_materialized_bytes_read", self.known_materialized_bytes_read),
            ("correspondence_failures", self.correspondence_failures),
        ):
            if type(val) is not int or val < 0:
                raise ExperimentRefusal(f"invalid_{name}")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "correspondence_verification_ns": self.correspondence_verification_ns,
            "correspondence_verification_bytes_read": self.correspondence_verification_bytes_read,
            "known_artifact_bytes_read": self.known_artifact_bytes_read,
            "known_materialized_bytes_read": self.known_materialized_bytes_read,
            "correspondence_failures": self.correspondence_failures,
        }


@dataclass(frozen=True)
class BaselineCorrespondenceSidecar:
    """Evaluator-only correspondence witness for non-vector W5 baseline arms (ADR 0141)."""

    arm_id: str
    task_id: str
    sqlite_pin: VerifiedPublicationPin | None = None
    postgres_pin: VerifiedPublicationPin | None = None
    pre_query_pin: VerifiedPublicationPin | None = None
    post_query_pin: VerifiedPublicationPin | None = None
    native_witness: NativeMaterializationWitness | None = None
    native_view: MaterializedNativeView | None = None
    projection_inputs: ProjectionInputs | None = None
    projection_policy: BodyProjectionPolicy | None = None
    projection: CapturedTextProjection | None = None
    fenced_observation_run_id: int | None = None
    fenced_observation_repository_identity: str | None = None
    caller_mapping_identity: str | None = None
    capture: Any | None = None
    generation_aliases: tuple[str, ...] = ()
    schema: str = W5_BASELINE_CORRESPONDENCE_SCHEMA_V1

    def captured_gap_cost(
        self, task: EvaluationTask, arm_id: str, envelope: QueryEnvelope,
    ) -> CorrespondenceCostSample:
        """Retain issued read work for a gap without issuing file-credit proof."""
        capture = self.capture
        if not isinstance(capture, IssuedBaselineCapture):
            raise ExperimentRefusal("baseline_capture_required")
        capture.validate()
        envelope.validate()
        if (capture.arm_id, capture.task_id, capture.envelope_digest) != (
            arm_id, task.task_id, digest_json(envelope.to_dict()),
        ) or (self.arm_id, self.task_id) != (arm_id, task.task_id):
            raise ExperimentRefusal("baseline_capture_identity_mismatch")
        return CorrespondenceCostSample(
            correspondence_verification_ns=capture.read_ns,
            correspondence_verification_bytes_read=None,
        ).validate()

    def to_dict(
        self,
        *,
        observed_backend: str,
        target_backend: str,
        status: str,
        gap_reason: str | None = None,
        verified_pin: VerifiedPublicationPin | None = None,
        cost: CorrespondenceCostSample | None = None,
    ) -> dict[str, Any]:
        """Return a compact public-safe sidecar record after an explicit outcome."""
        statuses = {"verified", "gap", "unavailable", "refused", "stale", "not_applicable"}
        if type(status) is not str or status not in statuses:
            raise ExperimentRefusal("invalid_correspondence_status")
        if any(type(value) is not str or not value for value in (observed_backend, target_backend)):
            raise ExperimentRefusal("invalid_correspondence_backend")
        if target_backend not in {"sqlite", "postgresql"}:
            raise ExperimentRefusal("invalid_correspondence_target_backend")
        if gap_reason is not None and (type(gap_reason) is not str or not gap_reason):
            raise ExperimentRefusal("invalid_correspondence_gap_reason")
        if status == "verified" and gap_reason is not None:
            raise ExperimentRefusal("verified_sidecar_gap_reason")
        if cost is not None:
            if not isinstance(cost, CorrespondenceCostSample):
                raise ExperimentRefusal("invalid_correspondence_cost")
            cost.validate()
        target_pin = self.sqlite_pin if target_backend == "sqlite" else self.postgres_pin
        capture = self.capture
        capture_summary: dict[str, Any] | None = None
        if capture is not None:
            if not isinstance(capture, IssuedBaselineCapture):
                raise ExperimentRefusal("baseline_capture_required")
            capture.validate()
            capture_identity = digest_json({
                "arm_id": capture.arm_id, "task_id": capture.task_id,
                "envelope_digest": capture.envelope_digest,
                "generation_aliases": list(capture.generation_aliases),
                "pre_receipts": [capture.pre.sqlite.receipt_identity, capture.pre.postgres.receipt_identity],
                "post_receipts": [capture.post.sqlite.receipt_identity, capture.post.postgres.receipt_identity],
            })
            capture_summary = {
                "identity": capture_identity, "envelope_digest": capture.envelope_digest,
                "generation_aliases": list(capture.generation_aliases),
                "capture_state": "issued_after_execution",
                "read_attempts": capture.read_attempts, "read_ns": capture.read_ns,
                "execution_work": [work.to_dict() for work in capture.execution_work],
            }
        if status == "verified":
            if (
                not isinstance(verified_pin, VerifiedPublicationPin)
                or verified_pin is not target_pin
                or verified_pin.backend != target_backend
                or not is_verified_sidecar(self, verified_pin, cost)
            ):
                raise ExperimentRefusal("verified_sidecar_pin_required")
            if capture_summary is None or cost is None:
                raise ExperimentRefusal("verified_sidecar_evidence_required")
        elif verified_pin is not None:
            raise ExperimentRefusal("unverified_sidecar_pin_not_admitted")

        def pin_summary(pin: VerifiedPublicationPin | None) -> dict[str, Any] | None:
            if pin is None:
                return None
            if not isinstance(pin, VerifiedPublicationPin):
                raise ExperimentRefusal("invalid_sidecar_pin")
            return {
                "backend": pin.backend, "graph_id": pin.graph_id,
                "repository_identity": pin.repository_identity, "run_id": pin.run_id,
                "generation": pin.generation, "publication_bundle_id": pin.publication_bundle_id,
                "snapshot_manifest_id": pin.snapshot_manifest_id,
                "extraction_receipt_id": pin.extraction_receipt_id,
                "receipt_identity": pin.receipt_identity,
                "snapshot_vector_digest": digest_json(pin.snapshot_vector),
                "admitted_binding_ids": sorted(pin.admitted_public_bindings),
                "denied_bindings": dict(sorted(pin.denied_bindings.items())),
                "policy_digest": pin.policy_digest,
            }

        native = None
        if isinstance(self.native_witness, NativeMaterializationWitness):
            native = {
                "witness_digest": self.native_witness.witness_digest,
                "generation_aliases": list(self.generation_aliases),
                "witness_selected_aliases": list(self.native_witness.selected_aliases),
                "policy_digest": self.native_witness.policy_digest,
                "excluded_binding_ids": sorted(self.native_witness.excluded_bindings),
                "file_count": len(self.native_witness.files),
                "materialized_bytes": self.native_witness.total_bytes,
            }
        projection = None
        if isinstance(self.projection, CapturedTextProjection):
            projection = {
                "accepted_reference_digest": digest_json(self.projection.accepted_reference.to_dict()),
                "publication_bundle_id": self.projection.publication_bundle_id,
                "snapshot_manifest_id": self.projection.snapshot_manifest_id,
                "extraction_receipt_id": self.projection.extraction_receipt_id,
                "candidate_id": self.projection.candidate_id,
                "policy_digest": self.projection.policy_digest,
            }
        return {
            "schema": self.schema, "arm_id": self.arm_id, "task_id": self.task_id,
            "observed_backend": observed_backend, "target_backend": target_backend,
            "capture": capture_summary, "stores": {
                "sqlite": pin_summary(self.sqlite_pin), "postgresql": pin_summary(self.postgres_pin),
            },
            "pre_query_pin": pin_summary(self.pre_query_pin),
            "post_query_pin": pin_summary(self.post_query_pin),
            "native": native, "projection": projection,
            "verification": {
                "status": status, "gap_reason": gap_reason,
                "verified": status == "verified", "cost": cost.to_dict() if cost is not None else None,
            },
        }


def verify_baseline_correspondence_sidecar(
    sidecar: BaselineCorrespondenceSidecar,
    *,
    task: EvaluationTask,
    arm_id: str,
    state: ExecutionState,
    envelope: QueryEnvelope,
) -> tuple[VerifiedPublicationPin, CorrespondenceCostSample]:
    """Revalidate per-arm baseline correspondence fail-closed and return (pin, cost_sample)."""
    return verify_strict_baseline_correspondence_sidecar(
        sidecar,
        task=task,
        arm_id=arm_id,
        state=state,
        envelope=envelope,
        sidecar_type=BaselineCorrespondenceSidecar,
        schema_version=W5_BASELINE_CORRESPONDENCE_SCHEMA_V1,
        observed_backends=BASELINE_ARM_OBSERVED_BACKENDS,
        target_backends=BASELINE_ARM_TARGET_BACKENDS,
        select_bindings=selected_public_binding_ids,
        cost_type=CorrespondenceCostSample,
    )


__all__ = (
    "BASELINE_ARM_OBSERVED_BACKENDS", "BASELINE_ARM_TARGET_BACKENDS",
    "W5_BASELINE_CORRESPONDENCE_SCHEMA_V1", "W5_EXPECTED_BASELINE_GAPS_BY_ARM",
    "W5_EXPERIMENT_RESULT_SCHEMA_V2", "AcceptedCandidate", "BaselineCorrespondenceSidecar",
    "CorrespondenceCostSample", "accepted_candidate_evidence", "is_expected_baseline_gap",
    "selected_public_binding_ids", "verify_baseline_correspondence_sidecar",
)
