"""Study-only seal over a real ``VerifiedWorkerResponse`` (study sections 5-7).

The production ``seal_generation_result`` and ``GeneratedEnrichmentArtifact``
are never called or built, and no ``VerifiedWorkerResponse`` is constructed.
Checks run in the contract order and the first failure refuses the whole
generation. Per arm: a truncated v1 record refuses the v1 arm only; a
truncated public-text record makes that arm ``token_partial`` while every
returned vector is kept. The global status/partial flags are stored verbatim.
Per-arm records, bytes and tokens are exact and sum to the global cost; the
three timings are shared once and per-arm time is unknown. The fifth
completeness fact, ``retrieval_truncated``, is per report cell, not per seal.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any

from common_lore_index.storage.semantic_candidates import checked_vector, digest_json
from retrieval_public_text_contracts import DESCRIPTOR_SET_CHANGED, PrivateMarkerScope, PublicTextRefusal
from retrieval_public_text_descriptors import require_unchanged_recomputation
from retrieval_public_text_request import (
    ARM_PTX, ARM_V1, DualArmInput, DualArmRequestRefusal, build_dual_arm_input,
)
from retrieval_semantic_generator_kernel import (
    MODEL_DIMENSIONS, QUERY_PREFIX, SemanticCost, SemanticEmbedding, SemanticGeneration, SemanticMode, SemanticText,
)
from retrieval_semantic_generator_kernel_contracts import MODEL_MAX_TOKENS
from retrieval_semantic_generator_output_receipt import VerifiedWorkerResponse, _response_identity

STUDY_SEAL_SCHEMA = "cloe-public-text-study-seal-v1"
V1_OWN_RECORD_TRUNCATED = "v1_own_record_truncated"
SEAL_CODES = frozenset({
    "study_response_identity", "study_request_mismatch", "study_current_revalidation_failed",
    "study_descriptor_set_changed", "study_record_identity_mismatch", "study_vector_invalid", "study_token_invariant",
    "study_cost_records", "study_cost_bytes", "study_cost_tokens", "study_partial_state", "study_cost_seconds",
    "study_arm_coverage",
})
COST_FIELDS = (
    "input_bytes", "model_input_bytes", "token_count_before_limit", "token_count_used", "overflow_chunks",
    "truncated_records",
)


class StudySealRefusal(ValueError):
    """Closed refusal; the attempt is retained and never repaired."""

    def __init__(self, code: str) -> None:
        if code not in SEAL_CODES:
            raise ValueError("unknown study seal code")
        super().__init__(code)
        self.code = code


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise StudySealRefusal(code)


@dataclass(frozen=True)
class SealedRecord:
    record_id: str
    arm: str
    mode: SemanticMode
    source_identity: str
    vector: tuple[float, ...] = field(repr=False)
    token_count_before_limit: int
    token_count_used: int
    overflow_chunks: int
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id, "mode": self.mode.value, "source_identity": self.source_identity,
            "token_count_before_limit": self.token_count_before_limit, "token_count_used": self.token_count_used,
            "overflow_chunks": self.overflow_chunks, "truncated": self.truncated,
        }


@dataclass(frozen=True)
class ArmSeal:
    arm: str
    capability: str  # complete | token_partial | refused
    refusal: str | None
    records: tuple[SealedRecord, ...] = field(repr=False)
    counts: Mapping[str, int]
    exact_cost: Mapping[str, int]
    truncated_document_identities: tuple[str, ...]
    truncated_query_task_ids: tuple[str, ...]
    publication_coverage: str  # complete | partial

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm, "capability": self.capability, "refusal": self.refusal,
            "token_partial": any(record.truncated for record in self.records), "counts": dict(self.counts),
            "exact_cost": dict(self.exact_cost), "time": {"unknown": "shared_worker_cost"},
            "io": {"unknown": "not_observed"},
            "truncated_document_identities": list(self.truncated_document_identities),
            "truncated_query_task_ids": list(self.truncated_query_task_ids),
            "publication_coverage": self.publication_coverage,
            "records": [record.to_dict() for record in self.records],
        }


@dataclass(frozen=True)
class StudyGenerationSeal:
    generation: int
    attempt_id: str
    response_identity: str
    receipt_digests: Mapping[str, str]
    input_identity: str
    representation_report_identity: str
    publication_identity: str
    artifact_profile_identity: str
    records_returned: bool
    global_status: str
    global_partial: bool
    shared_cost: SemanticCost
    arms: Mapping[str, ArmSeal]
    seal_identity: str

    def public_mapping(self) -> dict[str, Any]:
        """Public seal without text or vectors; ``seal_identity`` is its digest."""
        return {
            "schema": STUDY_SEAL_SCHEMA, "generation": self.generation, "attempt_id": self.attempt_id,
            "response_identity": self.response_identity, "receipt_digests": dict(self.receipt_digests),
            "input_identity": self.input_identity, "representation_report_identity": self.representation_report_identity,
            "publication_identity": self.publication_identity,
            "artifact_profile_identity": self.artifact_profile_identity, "worker_terminal": "completed",
            "records_returned": {"value": self.records_returned}, "global_status": self.global_status,
            "global_partial": self.global_partial,
            "shared_cost": {name: getattr(self.shared_cost, name)
                            for name in ("load_seconds", "inference_seconds", "total_seconds")},
            "arms": {arm: seal.to_dict() for arm, seal in self.arms.items()},
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.public_mapping(), "seal_identity": self.seal_identity}


def check_embedding(expected: SemanticText, observed: SemanticEmbedding) -> tuple[float, ...]:
    """Section 5 step 5 for one record: identity, finite unit vector, exact-int token invariants."""
    _require(
        type(observed) is SemanticEmbedding and observed.record_id == expected.record_id
        and type(observed.mode) is SemanticMode and observed.mode is SemanticMode(expected.mode),
        "study_record_identity_mismatch",
    )
    try:
        vector = checked_vector(observed.vector, MODEL_DIMENSIONS)
    except (TypeError, ValueError) as error:
        raise StudySealRefusal("study_vector_invalid") from error
    before, used, overflow = observed.token_count_before_limit, observed.token_count_used, observed.overflow_chunks
    _require(
        type(before) is int and type(used) is int and type(overflow) is int and type(observed.truncated) is bool
        and before > 0 and used == min(before, MODEL_MAX_TOKENS) and overflow >= 0
        and observed.truncated == (overflow > 0) == (before > MODEL_MAX_TOKENS),
        "study_token_invariant",
    )
    return vector


def _model_bytes(record: SemanticText) -> int:
    prefix = QUERY_PREFIX if SemanticMode(record.mode) is SemanticMode.QUERY else ""
    return len((prefix + record.text).encode("utf-8"))


def _input_bytes(record: SemanticText) -> int:
    return len(record.record_id.encode("utf-8")) + len(record.text.encode("utf-8"))


def _is_exact(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def check_generation_cost(
    cost: SemanticCost, records: Sequence[SemanticText], embeddings: Sequence[SemanticEmbedding],
    *, status: object, partial: object,
) -> None:
    """Section 5 step 6: reconcile every aggregate field against the verified records."""
    _require(type(cost) is SemanticCost and _is_exact(cost.input_records, len(records)), "study_cost_records")
    _require(
        _is_exact(cost.input_bytes, sum(_input_bytes(r) for r in records))
        and _is_exact(cost.model_input_bytes, sum(_model_bytes(r) for r in records)),
        "study_cost_bytes",
    )
    truncated = sum(1 for e in embeddings if e.truncated is True)
    _require(
        _is_exact(cost.token_count_before_limit, sum(e.token_count_before_limit for e in embeddings))
        and _is_exact(cost.token_count_used, sum(e.token_count_used for e in embeddings))
        and _is_exact(cost.overflow_chunks, sum(e.overflow_chunks for e in embeddings))
        and _is_exact(cost.truncated_records, truncated),
        "study_cost_tokens",
    )
    _require(
        type(partial) is bool and partial == (truncated > 0) and status == ("partial" if partial else "complete"),
        "study_partial_state",
    )
    seconds = (cost.load_seconds, cost.inference_seconds, cost.total_seconds)
    _require(
        all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in seconds)
        and cost.total_seconds + 1e-6 >= cost.load_seconds + cost.inference_seconds,
        "study_cost_seconds",
    )


def _rebuild(value: DualArmInput) -> DualArmInput:
    """Recompute an input from its own owners; a malformed owner is the closed whole-generation code."""
    try:
        return build_dual_arm_input(
            generation=value.generation, attempt_id=value.attempt_id, study_identity=value.study_identity,
            v1_input=value.v1, preparation=value.preparation, census=value.census, tasks=value.tasks,
            publication_pin=value.pin, artifact_profile_identity=value.artifact_profile_identity)
    except DualArmRequestRefusal:
        raise StudySealRefusal("study_current_revalidation_failed") from None


def _check_current(expected: DualArmInput, refresh: Callable[[], DualArmInput], scope: PrivateMarkerScope) -> None:
    """Only the external current-store and refresh callbacks are broad catches (F1-F2)."""
    try:
        expected.v1.require_current()
    except Exception:
        raise StudySealRefusal("study_current_revalidation_failed") from None
    canonical = _rebuild(expected)
    _require(
        canonical.records == expected.records and canonical.layout == expected.layout
        and canonical.manifest() == expected.manifest() and canonical.input_identity == expected.input_identity,
        "study_current_revalidation_failed")
    try:
        fresh = refresh()
    except Exception:
        raise StudySealRefusal("study_current_revalidation_failed") from None
    _require(type(fresh) is DualArmInput, "study_current_revalidation_failed")
    rebuilt = _rebuild(fresh)
    _require(rebuilt.records == fresh.records and rebuilt.layout == fresh.layout
             and rebuilt.input_identity == fresh.input_identity, "study_current_revalidation_failed")
    try:
        require_unchanged_recomputation(expected.preparation, fresh.preparation, scope=scope)
    except PublicTextRefusal as error:
        changed = error.code == DESCRIPTOR_SET_CHANGED
        raise StudySealRefusal(
            "study_descriptor_set_changed" if changed else "study_current_revalidation_failed") from error
    _require(
        fresh.input_identity == expected.input_identity and fresh.pin.to_dict() == expected.pin.to_dict()
        and fresh.tasks.identity() == expected.tasks.identity() and fresh.layout == expected.layout
        and fresh.records == expected.records,
        "study_current_revalidation_failed",
    )


def _check_counts(expected: DualArmInput, response: VerifiedWorkerResponse) -> SemanticGeneration:
    generation = response.generation
    documents = sum(1 for row in expected.layout if row.mode is SemanticMode.DOCUMENT)
    count = len(expected.layout)
    _require(
        type(generation) is SemanticGeneration and type(generation.embeddings) is tuple
        and len(expected.records) == count == len(generation.embeddings)
        and response.record_count == count == response.embedding_count
        and (response.document_count, response.query_count) == (documents, count - documents),
        "study_record_identity_mismatch",
    )
    assert isinstance(generation, SemanticGeneration)
    return generation


def _arm_coverage(expected: DualArmInput) -> dict[str, str]:
    prepared = expected.preparation
    ptx_partial = bool(prepared.exclusions) or len(prepared.documents) < prepared.v1_verified_pair_count
    return {
        ARM_V1: "partial" if expected.v1.partial_publication_coverage else "complete",
        ARM_PTX: "partial" if ptx_partial else "complete",
    }


def _split_arms(
    expected: DualArmInput, embeddings: Sequence[SemanticEmbedding], vectors: Sequence[tuple[float, ...]],
) -> dict[str, list[tuple[SemanticText, SealedRecord, str | None]]]:
    """Section 5 step 7: each arm is one-to-one with its expected records; v1 ids map back."""
    v1_ids = {record.record_id for record in expected.v1.records}
    arms: dict[str, list[tuple[SemanticText, SealedRecord, str | None]]] = {ARM_V1: [], ARM_PTX: []}
    for record, row, observed, vector in zip(expected.records, expected.layout, embeddings, vectors, strict=True):
        mapped = (
            row.record_id == record.record_id and row.arm in arms and row.mode is SemanticMode(record.mode)
            and (
                (row.arm == ARM_V1 and row.v1_record_id in v1_ids and record.record_id == f"v1.{row.v1_record_id}")
                or (row.arm == ARM_PTX and row.v1_record_id is None and record.record_id.startswith("ptx."))
            )
        )
        _require(mapped, "study_arm_coverage")
        arms[row.arm].append((record, SealedRecord(
            row.record_id, row.arm, row.mode, row.source_identity, vector, observed.token_count_before_limit,
            observed.token_count_used, observed.overflow_chunks, observed.truncated), row.task_id))
    v1_mapped = sorted(item[0].record_id[3:] for item in arms[ARM_V1])
    ptx_docs = [item[1].source_identity for item in arms[ARM_PTX] if item[1].mode is SemanticMode.DOCUMENT]
    ptx_queries = [item[2] for item in arms[ARM_PTX] if item[1].mode is SemanticMode.QUERY]
    admitted = [row.task_id for row in expected.census.tasks if row.public_text_state == "admitted"]
    _require(
        v1_mapped == sorted(v1_ids) and ptx_docs == [doc.identity for doc in expected.preparation.documents]
        and ptx_queries == admitted,
        "study_arm_coverage",
    )
    return arms


def _arm_seal(arm: str, items: Sequence[tuple[SemanticText, SealedRecord, str | None]], coverage: str) -> ArmSeal:
    """Section 6 per arm and section 7 exact per-arm cost."""
    sealed = tuple(item[1] for item in items)
    truncated = any(record.truncated for record in sealed)
    if arm == ARM_V1:
        capability, refusal = ("refused", V1_OWN_RECORD_TRUNCATED) if truncated else ("complete", None)
    else:
        capability, refusal = ("token_partial" if truncated else "complete"), None
    documents = sum(1 for record in sealed if record.mode is SemanticMode.DOCUMENT)
    counts = {"records": len(sealed), "documents": documents, "queries": len(sealed) - documents}
    exact_cost = {
        **counts,
        "input_bytes": sum(_input_bytes(item[0]) for item in items),
        "model_input_bytes": sum(_model_bytes(item[0]) for item in items),
        "token_count_before_limit": sum(record.token_count_before_limit for record in sealed),
        "token_count_used": sum(record.token_count_used for record in sealed),
        "overflow_chunks": sum(record.overflow_chunks for record in sealed),
        "truncated_records": sum(1 for record in sealed if record.truncated),
    }
    return ArmSeal(
        arm, capability, refusal, sealed, MappingProxyType(counts), MappingProxyType(exact_cost),
        tuple(r.source_identity for r in sealed if r.truncated and r.mode is SemanticMode.DOCUMENT),
        tuple(str(item[2]) for item in items if item[1].truncated and item[1].mode is SemanticMode.QUERY),
        coverage,
    )


def seal_dual_arm_result(
    expected: DualArmInput,
    response: VerifiedWorkerResponse,
    *,
    refresh: Callable[[], DualArmInput],
    scope: PrivateMarkerScope,
) -> StudyGenerationSeal:
    """Seal one generation in the contract order; the first failure refuses it whole."""
    _require(
        type(response) is VerifiedWorkerResponse and response.status == "completed"
        and response._sealed_identity == _response_identity(response),
        "study_response_identity",
    )
    _require(
        type(expected) is DualArmInput and response.request_records == expected.records
        and response.attempt_id == expected.attempt_id
        and (response.input_identity, response.representation_report_identity, response.publication_identity,
             response.artifact_profile_identity)
        == (expected.input_identity, expected.representation_report_identity, expected.publication_identity,
            expected.artifact_profile_identity),
        "study_request_mismatch",
    )
    _check_current(expected, refresh, scope)
    generation = _check_counts(expected, response)
    vectors = tuple(
        check_embedding(record, observed)
        for record, observed in zip(expected.records, generation.embeddings, strict=True)
    )
    check_generation_cost(generation.cost, expected.records, generation.embeddings,
                          status=generation.status, partial=generation.partial)
    coverage = _arm_coverage(expected)
    split = _split_arms(expected, generation.embeddings, vectors)
    arms = {arm: _arm_seal(arm, split[arm], coverage[arm]) for arm in (ARM_V1, ARM_PTX)}
    for name in ("input_records", *COST_FIELDS):
        arm_name = "records" if name == "input_records" else name
        _require(sum(seal.exact_cost[arm_name] for seal in arms.values()) == getattr(generation.cost, name),
                 "study_arm_coverage")
    receipts = {
        "request": response.request_sha256, "report": response.report_sha256, "terminal": response.terminal_sha256,
        "declaration": response.declaration_sha256, "manifest": response.source_manifest_sha256,
        "archive": response.sources_archive_sha256, "admission": response.controller_admission_sha256,
    }
    draft = StudyGenerationSeal(
        expected.generation, expected.attempt_id, response._sealed_identity, MappingProxyType(receipts),
        expected.input_identity, expected.representation_report_identity, expected.publication_identity,
        expected.artifact_profile_identity, response.embedding_count == response.record_count,
        generation.status, generation.partial, generation.cost, MappingProxyType(arms), "",
    )
    return StudyGenerationSeal(**{**draft.__dict__, "seal_identity": str(digest_json(draft.public_mapping()))})
