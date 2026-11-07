"""Seal verified semantic generation into a public enrichment artifact."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math

from common_lore_index.storage.semantic_candidates import (
    EmbeddingEntry,
    EmbeddingProfile,
    checked_vector,
)
from retrieval_semantic_generator_inputs import PublicGenerationInput
from retrieval_semantic_generator_kernel import (
    QUERY_PREFIX,
    SemanticCost,
    SemanticGeneration,
    SemanticMode,
)
from retrieval_semantic_generator_output_parser import parse_verified_worker_response
from retrieval_semantic_generator_output_receipt import (
    QueryEmbedding,
    VerifiedWorkerResponse,
    _digest,
    _digest_field,
    _require,
    _response_identity,
)
from retrieval_semantic_provenance import RepresentationValidationError

OUTPUT_POLICY = "cloe-w5-generated-enrichment-v1"
MODEL_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"


@dataclass(frozen=True)
class GeneratedEnrichmentArtifact:
    input_identity: str
    representation_report_identity: str
    artifact_profile_identity: str
    component_receipt_identity: str
    worker_report_identity: str
    worker_declaration_identity: str
    worker_terminal_identity: str
    worker_source_manifest_identity: str
    worker_sources_archive_identity: str
    controller_admission_identity: str
    publication_identity: str
    profile: EmbeddingProfile
    entries: tuple[EmbeddingEntry, ...]
    queries: tuple[QueryEmbedding, ...]
    complete_generation: bool
    partial_publication_coverage: bool
    truncated_record_ids: tuple[str, ...]

    def require_importable(self) -> tuple[EmbeddingEntry, ...]:
        _require(
            self.complete_generation and not self.truncated_record_ids,
            "incomplete_generation_cannot_import",
        )
        _require(1 <= len(self.entries) <= 500, "invalid_generated_import_size")
        return self.entries

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": OUTPUT_POLICY,
            "input_identity": self.input_identity,
            "representation_report_identity": self.representation_report_identity,
            "artifact_profile_identity": self.artifact_profile_identity,
            "component_receipt_identity": self.component_receipt_identity,
            "worker_report_identity": self.worker_report_identity,
            "worker_declaration_identity": self.worker_declaration_identity,
            "worker_terminal_identity": self.worker_terminal_identity,
            "worker_source_manifest_identity": self.worker_source_manifest_identity,
            "worker_sources_archive_identity": self.worker_sources_archive_identity,
            "controller_admission_identity": self.controller_admission_identity,
            "publication_identity": self.publication_identity,
            "profile_identity": self.profile.identity,
            "profile": dict(self.profile.__dict__),
            "entries": [
                {
                    "canonical_key": entry.canonical_key,
                    "source_binding_id": entry.source_binding_id,
                    "input_digest": entry.input_digest,
                    "vector": list(entry.vector),
                }
                for entry in self.entries
            ],
            "queries": [
                {
                    "task_id": query.task_id,
                    "task_sha256": query.task_sha256,
                    "state": query.state,
                    "reason": query.reason,
                    "vector": list(query.vector) if query.vector is not None else None,
                }
                for query in self.queries
            ],
            "complete_generation": self.complete_generation,
            "partial_publication_coverage": self.partial_publication_coverage,
            "truncated_record_ids": list(self.truncated_record_ids),
            "limitations": [
                "public calibration only",
                "canonical-node-v1 metadata only",
                "500 selected node/source records; no full-publication coverage claim",
                "component execution does not establish relevance or ANN execution",
            ],
        }


def _publication_identity(inputs: PublicGenerationInput) -> str:
    payload = json.dumps(
        inputs.provenance.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return _digest(payload)


def _validate_cost_against_inputs(
    cost: SemanticCost,
    inputs: PublicGenerationInput,
) -> None:
    _require(type(cost) is SemanticCost, "invalid_generation_cost")
    input_bytes = sum(
        len(record.record_id.encode("utf-8")) + len(record.text.encode("utf-8"))
        for record in inputs.records
    )
    model_bytes = sum(
        len(((QUERY_PREFIX if record.mode is SemanticMode.QUERY else "") + record.text).encode("utf-8"))
        for record in inputs.records
    )
    _require(
        type(cost.input_records) is int
        and cost.input_records == len(inputs.records),
        "generation_cost_count_mismatch",
    )
    _require(
        type(cost.input_bytes) is int and cost.input_bytes == input_bytes,
        "generation_cost_count_mismatch",
    )
    _require(
        type(cost.model_input_bytes) is int and cost.model_input_bytes == model_bytes,
        "generation_cost_count_mismatch",
    )
    for name in (
        "token_count_before_limit",
        "token_count_used",
        "overflow_chunks",
        "truncated_records",
    ):
        _require(
            type(getattr(cost, name)) is int and getattr(cost, name) >= 0,
            "invalid_generation_cost",
        )
    for name in ("load_seconds", "inference_seconds", "total_seconds"):
        value = getattr(cost, name)
        _require(
            type(value) in (int, float)
            and math.isfinite(value)
            and value >= 0,
            "invalid_generation_cost",
        )
    _require(
        cost.total_seconds + 1e-6 >= cost.load_seconds + cost.inference_seconds,
        "invalid_generation_cost",
    )


def seal_generation_result(
    inputs: PublicGenerationInput,
    response: VerifiedWorkerResponse,
) -> GeneratedEnrichmentArtifact:
    """Refuse stale, reordered, partial or mismatched worker results."""
    inputs.require_current()
    _require(
        type(response) is VerifiedWorkerResponse and response.status == "completed",
        "invalid_worker_response",
    )
    _require(
        response._sealed_identity == _response_identity(response),
        "invalid_worker_response",
    )
    _require(response.request_records == inputs.records, "worker_request_input_mismatch")
    _require(
        response.input_identity == inputs.input_identity,
        "worker_input_identity_mismatch",
    )
    _require(
        response.representation_report_identity == inputs.representation_report_identity,
        "worker_representation_identity_mismatch",
    )
    for identity in (
        response.request_sha256,
        response.report_sha256,
        response.terminal_sha256,
        response.declaration_sha256,
        response.source_manifest_sha256,
        response.sources_archive_sha256,
        response.controller_admission_sha256,
        response.artifact_profile_identity,
    ):
        _digest_field(identity, "invalid_worker_response")
    _require(
        response.publication_identity == _publication_identity(inputs),
        "worker_publication_identity_mismatch",
    )
    result = response.generation
    _require(type(result) is SemanticGeneration, "invalid_generation_result")
    assert isinstance(result, SemanticGeneration)
    _require(
        type(result.embeddings) is tuple
        and len(result.embeddings) == len(inputs.records),
        "generation_record_count_mismatch",
    )
    _require(
        (response.record_count, response.embedding_count)
        == (len(inputs.records), len(result.embeddings))
        and response.document_count == len(inputs.documents)
        and response.query_count
        == sum(decision.record_id is not None for decision in inputs.query_decisions),
        "worker_count_mismatch",
    )
    _validate_cost_against_inputs(result.cost, inputs)
    _require(
        type(result.partial) is bool
        and result.status == ("partial" if result.partial else "complete"),
        "invalid_generation_partial_state",
    )
    vectors: dict[str, tuple[float, ...]] = {}
    truncated: list[str] = []
    before_limit = non_padding = overflow = 0
    for expected, observed in zip(inputs.records, result.embeddings, strict=True):
        _require(
            type(observed.mode) is SemanticMode
            and observed.record_id == expected.record_id
            and observed.mode is expected.mode,
            "generation_record_identity_mismatch",
        )
        _require(observed.record_id not in vectors, "duplicate_generated_record")
        try:
            vector = checked_vector(observed.vector, 384)
        except ValueError as exc:
            raise RepresentationValidationError(
                "invalid_generated_vector", "invalid finite unit vector"
            ) from exc
        _require(type(observed.truncated) is bool, "invalid_generated_truncation")
        _require(
            type(observed.token_count_before_limit) is int
            and observed.token_count_before_limit > 0,
            "invalid_generated_token_count",
        )
        _require(
            type(observed.token_count_used) is int
            and 1 <= observed.token_count_used <= 512
            and observed.token_count_used
            == min(observed.token_count_before_limit, 512),
            "invalid_generated_token_count",
        )
        _require(
            type(observed.overflow_chunks) is int and observed.overflow_chunks >= 0,
            "invalid_generated_overflow",
        )
        _require(
            observed.truncated
            == (observed.overflow_chunks > 0)
            == (observed.token_count_before_limit > 512),
            "generated_truncation_mismatch",
        )
        vectors[observed.record_id] = vector
        before_limit += observed.token_count_before_limit
        non_padding += observed.token_count_used
        overflow += observed.overflow_chunks
        if observed.truncated:
            truncated.append(observed.record_id)
    for measured, expected_count in (
        (result.cost.token_count_before_limit, before_limit),
        (result.cost.token_count_used, non_padding),
        (result.cost.overflow_chunks, overflow),
        (result.cost.truncated_records, len(truncated)),
    ):
        _require(
            type(measured) is int and measured == expected_count,
            "generation_cost_count_mismatch",
        )
    _require(result.partial == bool(truncated), "generation_partial_state_mismatch")
    entries = tuple(
        EmbeddingEntry(
            document.representation.canonical_key,
            document.representation.source_binding_id,
            vectors[document.record_id],
            document.representation.input_digest,
        )
        for document in inputs.documents
    )
    queries = tuple(
        QueryEmbedding(
            decision.task_id,
            decision.task_sha256,
            decision.state,
            decision.reason,
            vectors[decision.record_id] if decision.record_id is not None else None,
        )
        for decision in inputs.query_decisions
    )
    expected_modes = {record.record_id: record.mode for record in inputs.records}
    _require(
        all(
            expected_modes.get(document.record_id) is SemanticMode.DOCUMENT
            for document in inputs.documents
        ),
        "invalid_document_generation_mode",
    )
    _require(
        all(
            decision.record_id is None
            or expected_modes.get(decision.record_id) is SemanticMode.QUERY
            for decision in inputs.query_decisions
        ),
        "invalid_query_generation_mode",
    )
    profile = EmbeddingProfile(
        "BAAI/bge-small-en-v1.5",
        MODEL_REVISION,
        "cloe-bge-onnx-cpu",
        "v1:" + response.artifact_profile_identity[7:],
        384,
    ).validate()
    return GeneratedEnrichmentArtifact(
        inputs.input_identity,
        inputs.representation_report_identity,
        response.artifact_profile_identity,
        response.terminal_sha256,
        response.report_sha256,
        response.declaration_sha256,
        response.terminal_sha256,
        response.source_manifest_sha256,
        response.sources_archive_sha256,
        response.controller_admission_sha256,
        response.publication_identity,
        profile,
        entries,
        queries,
        not result.partial,
        inputs.partial_publication_coverage,
        tuple(truncated),
    )


__all__ = [
    "GeneratedEnrichmentArtifact",
    "QueryEmbedding",
    "VerifiedWorkerResponse",
    "parse_verified_worker_response",
    "seal_generation_result",
]
