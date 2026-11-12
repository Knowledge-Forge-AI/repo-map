"""Public-text v2 rows into the unchanged file-level RRF, plus a typed per-arm serializer (sections 10, 18.3).

v1 rows keep the unchanged ``vector_candidates`` path on the exact study row
shape (kind, display name and input digest present, so
``canonical_node_v1_digest`` runs). v2 rows are joined to the actual preparation
descriptor map, the study seal, the current pin, the bindings derived from the
actual task (as on the v1 path) and the private marker scope before any RRF
code sees them. The result is a closed ``PublicTextProjection``; only that
validated object enters fusion, as ``raw_file_hits``. Hybrid fusion is exactly
(current PostgreSQL native FTS, one exact-vector arm) with fallback off.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
import math
from typing import Any

from common_lore_index.storage.semantic_candidates import digest_json
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_public_text_census import retained_task_sha256
from retrieval_public_text_contracts import PrivateMarkerScope, PublicTextRefusal, require_scope
from retrieval_public_text_descriptors import PublicTextDocument, PublicTextPreparation
from retrieval_public_text_request import ARM_PTX, ARM_V1
from retrieval_public_text_response import ArmSeal
from retrieval_semantic_arm_validation import AdmittedArmObservation, FileIdentityTuple
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_semantic_experiment_evaluator import build_candidate_rows_arm
from retrieval_semantic_experiment_scope import selected_public_binding_ids
from retrieval_semantic_file_projection import DEFAULT_CUTOFFS, compute_file_level_ranking_metrics
from retrieval_semantic_fusion import MAX_FUSED_RESULTS, RRF_POLICY_VERSION, FileFusionResult, fuse_arm_observations_rrf
from retrieval_semantic_generator_inputs import PublicGenerationInput
from retrieval_semantic_generator_kernel import SemanticMode
from retrieval_semantic_representation import RepresentationValidationError, VerifiedPublicationPin

FUSION_SCHEMA = "cloe-public-text-fusion-v1"
LEXICAL_ARM = "postgres_native_fts:postgresql"
VECTOR_KINDS = ("exact_vector", "hnsw_vector")
NOT_APPLICABLE = "not_applicable"
METRIC_KEYS = tuple(f"file_{name}@{k}" for k in DEFAULT_CUTOFFS for name in ("recall", "mrr", "ndcg"))
ROW_KEYS = frozenset({
    "node_id", "canonical_key", "kind", "display_name", "confidence", "conflict", "source_binding_id",
    "input_digest", "snapshot_id", "descriptor_identity", "distance", "evidence",
})
FUSION_CODES = frozenset({
    "public_text_fusion_scope", "public_text_seal_mismatch", "public_text_publication_mismatch",
    "public_text_selected_bindings", "public_text_row_malformed", "public_text_row_duplicate",
    "public_text_descriptor_unmatched", "public_text_descriptor_mismatch", "public_text_snapshot_mismatch",
    "public_text_binding_scope", "public_text_evidence_withheld", "public_text_file_identity",
    "public_text_fusion_arms", "public_text_serializer_arms", "public_text_metrics", "public_text_projection",
})
_PROJECTION_TOKEN = object()
_ISSUED_PROJECTIONS: dict[int, PublicTextProjection] = {}


class PublicTextFusionRefusal(ValueError):
    def __init__(self, code: str) -> None:
        if code not in FUSION_CODES:
            raise ValueError("unknown public-text fusion code")
        super().__init__(code)
        self.code = code


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise PublicTextFusionRefusal(code)


def study_arm_id(kind: str, representation: str) -> str:
    _require(kind in VECTOR_KINDS and representation in (ARM_V1, ARM_PTX), "public_text_fusion_arms")
    return f"{kind}:{representation}"


def _descriptor_map(preparation: PublicTextPreparation, seal: ArmSeal, pin: VerifiedPublicationPin,
                    scope: PrivateMarkerScope) -> dict[tuple[str, str], PublicTextDocument]:
    try:
        scope = require_scope(scope)
    except PublicTextRefusal:
        raise PublicTextFusionRefusal("public_text_fusion_scope") from None
    _require(type(preparation) is PublicTextPreparation and preparation._scope is scope
             and preparation.privacy_scope_id == scope.scope_id, "public_text_fusion_scope")
    _require(type(seal) is ArmSeal and seal.arm == ARM_PTX and seal.capability in ("complete", "token_partial")
             and [r.source_identity for r in seal.records if r.mode is SemanticMode.DOCUMENT]
             == [doc.identity for doc in preparation.documents], "public_text_seal_mismatch")
    try:
        current = pin.revalidate_current() if type(pin) is VerifiedPublicationPin else None
    except Exception:
        current = None
    _require(current is pin and preparation.publication_identity == str(digest_json(pin.to_dict())),
             "public_text_publication_mismatch")
    descriptors: dict[tuple[str, str], PublicTextDocument] = {}
    for document in preparation.documents:
        key = (document.descriptor["canonical_key"], document.descriptor["source_binding_id"])
        _require(key not in descriptors, "public_text_seal_mismatch")
        descriptors[key] = document
    return descriptors


def _task_bindings(task: EvaluationTask, pin: VerifiedPublicationPin) -> tuple[str, ...]:
    """The unchanged v1 derivation; every binding must be admitted and not denied."""
    try:
        selected = selected_public_binding_ids(task)
    except ExperimentRefusal:
        raise PublicTextFusionRefusal("public_text_selected_bindings") from None
    _require(all(b in pin.admitted_public_bindings and b not in pin.denied_bindings for b in selected),
             "public_text_selected_bindings")
    return selected


def _seal_digest(seal: ArmSeal) -> str:
    return str(digest_json(seal.to_dict()))


@dataclass(frozen=True)
class PublicTextProjection:
    """Validated v2 hits bound to their task, seal, preparation, publication and scope; never caller-built."""

    hits: tuple[tuple[FileIdentityTuple, int, str], ...]
    task_id: str
    task_sha256: str
    selected_binding_ids: tuple[str, ...]
    seal_digest: str
    preparation_identity: str
    publication_identity: str
    scope_id: str
    capability: str
    _token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require(self._token is _PROJECTION_TOKEN, "public_text_projection")


def project_public_text_candidates(
    rows: Sequence[Mapping[str, Any]], *, preparation: PublicTextPreparation, seal: ArmSeal,
    pin: VerifiedPublicationPin, task: EvaluationTask, scope: PrivateMarkerScope,
) -> PublicTextProjection:
    """Each row joins exactly one sealed descriptor by key, binding, snapshot, digest and evidence first."""
    descriptors = _descriptor_map(preparation, seal, pin, scope)
    selected = _task_bindings(task, pin)
    snapshots = pin.snapshot_by_binding()
    projected: list[tuple[FileIdentityTuple, int, str]] = []
    seen: set[tuple[str, str]] = set()
    for rank, row in enumerate(rows, start=1):
        _require(isinstance(row, Mapping) and set(row) == ROW_KEYS and type(row["canonical_key"]) is str
                 and type(row["source_binding_id"]) is str and isinstance(row["evidence"], list), "public_text_row_malformed")
        distance = row["distance"]
        _require(type(distance) in (int, float) and math.isfinite(distance), "public_text_row_malformed")
        key = (row["canonical_key"], row["source_binding_id"])
        _require(key not in seen, "public_text_row_duplicate")
        seen.add(key)
        document = descriptors.get(key)
        _require(document is not None, "public_text_descriptor_unmatched")
        assert document is not None
        d = document.descriptor
        _require(row["descriptor_identity"] == document.identity and row["input_digest"] == d["input_digest"]
                 and row["kind"] == d["kind"] and row["display_name"] == d["display_name"],
                 "public_text_descriptor_mismatch")
        binding = key[1]
        _require(binding in selected, "public_text_binding_scope")
        _require(row["snapshot_id"] == d["snapshot_id"] == snapshots[binding][1], "public_text_snapshot_mismatch")
        _require(any(isinstance(item, Mapping) and item.get("evidence_key") == d["evidence_key"]
                     and type(item.get("path")) is str and not item["path"].startswith("/withheld/")
                     for item in row["evidence"]), "public_text_evidence_withheld")
        try:
            identity = FileIdentityTuple(binding, d["snapshot_id"], d["source_relative_path"]).validate(
                private_markers=scope.markers)
        except RepresentationValidationError:
            raise PublicTextFusionRefusal("public_text_file_identity") from None
        projected.append((identity, rank, key[0]))
    projection = PublicTextProjection(
        tuple(projected), task.task_id, retained_task_sha256(task), selected, _seal_digest(seal),
        str(digest_json(preparation.to_dict())), str(digest_json(pin.to_dict())), scope.scope_id, seal.capability,
        _PROJECTION_TOKEN)
    _ISSUED_PROJECTIONS[id(projection)] = projection
    return projection


def public_text_vector_arm(kind: str, projection: PublicTextProjection, *, seal: ArmSeal,
                           pin: VerifiedPublicationPin, task: EvaluationTask) -> AdmittedArmObservation:
    """Only a validated projection enters, re-bound to its seal, pin and task; token_partial stays partial."""
    _require(type(projection) is PublicTextProjection and projection._token is _PROJECTION_TOKEN
             and _ISSUED_PROJECTIONS.get(id(projection)) is projection,
             "public_text_projection")
    _require(type(seal) is ArmSeal and seal.arm == ARM_PTX and seal.capability in ("complete", "token_partial")
             and projection.seal_digest == _seal_digest(seal) and projection.capability == seal.capability,
             "public_text_seal_mismatch")
    _require(type(pin) is VerifiedPublicationPin and projection.publication_identity == str(digest_json(pin.to_dict())),
             "public_text_publication_mismatch")
    _require(projection.task_id == getattr(task, "task_id", None)
             and projection.selected_binding_ids == _task_bindings(task, pin)
             and projection.task_sha256 == retained_task_sha256(task), "public_text_projection")
    partial = seal.capability == "token_partial"
    return AdmittedArmObservation(
        study_arm_id(kind, ARM_PTX), "vector", verified_pin=pin, raw_file_hits=projection.hits,
        selected_binding_ids=projection.selected_binding_ids, incomplete=partial, truncated=partial)


def v1_vector_arm(kind: str, rows: Sequence[Mapping[str, Any]], *, task: EvaluationTask, pin: VerifiedPublicationPin,
                  inputs: PublicGenerationInput) -> AdmittedArmObservation:
    """Unchanged v1 candidate evidence path on the exact study row shape; only the study label differs."""
    _require(kind in VECTOR_KINDS, "public_text_fusion_arms")
    _require(all(isinstance(row, Mapping) and set(row) == ROW_KEYS and row["descriptor_identity"] is None
                 for row in rows), "public_text_row_malformed")
    v1_rows = [{name: value for name, value in row.items() if name != "descriptor_identity"} for row in rows]
    arm = build_candidate_rows_arm(v1_rows, arm_id=kind, task=task, pin=pin, inputs=inputs)
    return replace(arm, arm_id=study_arm_id(kind, ARM_V1))


def fuse_study_arms(arms: Sequence[AdmittedArmObservation], *, pin: VerifiedPublicationPin,
                    private_markers: Sequence[str] = (), max_results: int = MAX_FUSED_RESULTS) -> FileFusionResult:
    """One vector arm alone, or exactly (native FTS, exact vector) for hybrid; fallback is never enabled."""
    ids = tuple(arm.arm_id for arm in arms) if isinstance(arms, (tuple, list)) else ()
    vector_ids = {study_arm_id(k, r) for k in VECTOR_KINDS for r in (ARM_V1, ARM_PTX)}
    _require((len(ids) == 1 and ids[0] in vector_ids) or (
        len(ids) == 2 and ids[0] == LEXICAL_ARM and ids[1].startswith("exact_vector:") and ids[1] in vector_ids),
        "public_text_fusion_arms")
    return fuse_arm_observations_rrf(tuple(arms), expected_pin=pin, max_results=max_results,
                                     allow_explicit_single_arm_fallback=False, private_markers=tuple(private_markers))


def public_text_fusion_to_dict(result: FileFusionResult, *, representations: Mapping[str, str]) -> dict[str, Any]:
    """``cloe-public-text-fusion-v1``: per-arm representation versions, partial state, no single version label."""
    _require(type(result) is FileFusionResult and isinstance(representations, Mapping) and bool(representations),
             "public_text_serializer_arms")
    for arm_id, representation in representations.items():
        expected = NOT_APPLICABLE if arm_id == LEXICAL_ARM else (
            arm_id.split(":", 1)[1] if ":" in arm_id and arm_id.split(":", 1)[0] in VECTOR_KINDS else None)
        _require(representation == expected and representation in (ARM_V1, ARM_PTX, NOT_APPLICABLE),
                 "public_text_serializer_arms")
    observed = set(result.per_arm_raw_hit_counts) | set(result.collapsed_by_arm)
    _require(observed <= set(representations), "public_text_serializer_arms")
    base = result.to_dict()
    for legacy in ("schema_version", "representation_version", "policy_version", "provenance"):
        base.pop(legacy)
    return {
        "schema": FUSION_SCHEMA, "policy_version": RRF_POLICY_VERSION,
        "provenance_identity": None if result.provenance is None else str(digest_json(result.provenance.to_dict())),
        "arms": [{"arm_id": arm_id, "representation_version": representations[arm_id]}
                 for arm_id in sorted(representations)],
        **base,
    }


def grade_fusion(result: FileFusionResult, task: EvaluationTask, pin: VerifiedPublicationPin, *,
                 private_markers: Sequence[str] = ()) -> dict[str, float] | None:
    """Unchanged file metrics (calibration split enforced); non-completed fusion is ``None``, never zero."""
    if type(result) is not FileFusionResult or result.execution_state is not ExecutionState.COMPLETED:
        return None
    metrics = compute_file_level_ranking_metrics(result.hits, task.gold_targets, verified_pin=pin, task=task,
                                                 private_markers=tuple(private_markers))
    _require(tuple(sorted(metrics)) == tuple(sorted(METRIC_KEYS)) and all(
        type(value) is float and math.isfinite(value) and 0.0 <= value <= 1.0 for value in metrics.values()),
        "public_text_metrics")
    return {name: metrics[name] for name in METRIC_KEYS}


__all__ = [
    "FUSION_CODES", "FUSION_SCHEMA", "LEXICAL_ARM", "METRIC_KEYS", "NOT_APPLICABLE", "PublicTextFusionRefusal",
    "PublicTextProjection", "ROW_KEYS", "VECTOR_KINDS", "fuse_study_arms", "grade_fusion", "project_public_text_candidates",
    "public_text_fusion_to_dict", "public_text_vector_arm", "study_arm_id", "v1_vector_arm",
]
