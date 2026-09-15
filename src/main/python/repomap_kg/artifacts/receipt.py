"""Deterministic untrusted extraction receipt contract."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar, Mapping, Sequence

from repomap_kg.artifacts._canonical import (
    canonical_json,
    decode_canonical_json,
    prefixed_digest,
)
from repomap_kg.artifacts.references import ArtifactReference


RECEIPT_OUTCOMES = frozenset(
    {"completed", "cancelled", "failed", "unsupported_contract", "malformed_input"}
)
DIAGNOSTIC_CATEGORIES = frozenset(
    {
        "source_unavailable", "source_changed", "source_invalid", "source_capture",
        "artifact_missing", "artifact_stale", "artifact_corrupt", "cancelled",
        "unsupported_contract", "unsupported_capability", "contract_validation",
        "artifact_bounds", "manifest_bounds", "malformed_protocol",
        "identity_mismatch", "semantic_workload",
    }
)
PUBLIC_DIAGNOSTIC_PROJECTION = {
    "source_unavailable": "source_error",
    "source_changed": "source_error",
    "source_invalid": "source_error",
    "source_capture": "source_error",
    "artifact_missing": "source_error",
    "artifact_stale": "source_error",
    "artifact_corrupt": "source_error",
    "cancelled": "cancelled",
    "unsupported_contract": "contract_error",
    "unsupported_capability": "contract_error",
    "contract_validation": "contract_error",
    "artifact_bounds": "source_error",
    "manifest_bounds": "contract_error",
    "malformed_protocol": "contract_error",
    "identity_mismatch": "contract_error",
    "semantic_workload": "internal_error",
}


@dataclass(frozen=True)
class ExtractionReceipt:
    """Producer evidence whose digest grants no publication authority."""

    SCHEMA_VERSION: ClassVar[int] = 1
    CANONICALIZATION_VERSION: ClassVar[str] = "repomap-extraction-receipt-json-v1"
    request_id: str
    job_id: str
    attempt: int
    graph_id: str
    worker_capability_identity: str
    contract_version: str
    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str
    snapshot_manifest_id: str
    snapshot_vector: tuple[tuple[str, int, str], ...]
    resolver_identity: str
    extractor_capability_identity: str
    canonicalizer_identity: str
    semantic_contract_identity: str
    quality_rule_identity: str
    outcome: str
    cancellation: str
    bundle_reference: ArtifactReference | None
    bundle_id: str | None
    family_counts: Mapping[str, int]
    diagnostic_category: str | None
    diagnostic_summary: tuple[str, ...]
    producer_identity: str
    attestation_class: str
    receipt_id: str

    def canonical_mapping(self) -> dict[str, object]:
        return {
            "attempt": self.attempt,
            "attestation_class": self.attestation_class,
            "bundle_id": self.bundle_id,
            "bundle_reference": None if self.bundle_reference is None else self.bundle_reference.semantic_mapping(),
            "cancellation": self.cancellation,
            "canonicalization_version": self.CANONICALIZATION_VERSION,
            "canonicalizer_generation": self.canonicalizer_generation,
            "canonicalizer_identity": self.canonicalizer_identity,
            "config_generation": self.config_generation,
            "contract_version": self.contract_version,
            "diagnostic_category": self.diagnostic_category,
            "diagnostic_summary": list(self.diagnostic_summary),
            "extractor_capability_identity": self.extractor_capability_identity,
            "extractor_generation": self.extractor_generation,
            "family_counts": dict(sorted(self.family_counts.items())),
            "graph_id": self.graph_id,
            "job_id": self.job_id,
            "outcome": self.outcome,
            "producer_identity": self.producer_identity,
            "quality_rule_identity": self.quality_rule_identity,
            "request_id": self.request_id,
            "resolver_identity": self.resolver_identity,
            "schema_version": self.SCHEMA_VERSION,
            "semantic_contract_identity": self.semantic_contract_identity,
            "snapshot_manifest_id": self.snapshot_manifest_id,
            "snapshot_vector": [list(item) for item in self.snapshot_vector],
            "source_generation": self.source_generation,
            "worker_capability_identity": self.worker_capability_identity,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.canonical_mapping())

    def reidentify(self) -> "ExtractionReceipt":
        _validate_receipt(self)
        return replace(
            self,
            receipt_id=prefixed_digest(
                "receipt1:", b"repomap-extraction-receipt-v1", self.canonical_bytes()
            ),
        )

    def to_public_mapping(self) -> dict[str, object]:
        return {
            "attempt": self.attempt,
            "error_category": None if self.diagnostic_category is None else PUBLIC_DIAGNOSTIC_PROJECTION[self.diagnostic_category],
            "family_counts": dict(self.family_counts),
            "graph_id": self.graph_id,
            "outcome": self.outcome,
            "receipt_id": self.receipt_id,
            "schema_version": self.SCHEMA_VERSION,
        }

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        job_id: str,
        attempt: int,
        graph_id: str,
        worker_capability_identity: str,
        contract_version: str,
        source_generation: str,
        config_generation: str,
        extractor_generation: str,
        canonicalizer_generation: str,
        snapshot_manifest_id: str,
        snapshot_vector: Sequence[tuple[str, int, str]],
        resolver_identity: str,
        extractor_capability_identity: str,
        canonicalizer_identity: str,
        semantic_contract_identity: str,
        quality_rule_identity: str,
        outcome: str,
        cancellation: str,
        bundle_reference: ArtifactReference | None,
        bundle_id: str | None,
        family_counts: Mapping[str, int],
        diagnostic_category: str | None,
        diagnostic_summary: Sequence[str],
        producer_identity: str,
        attestation_class: str,
    ) -> "ExtractionReceipt":
        semantic_reference = (
            None
            if bundle_reference is None
            else ArtifactReference.from_semantic_mapping(bundle_reference.semantic_mapping())
        )
        value = cls(
            request_id, job_id, attempt, graph_id, worker_capability_identity,
            contract_version, source_generation, config_generation,
            extractor_generation, canonicalizer_generation, snapshot_manifest_id,
            tuple(snapshot_vector), resolver_identity, extractor_capability_identity,
            canonicalizer_identity, semantic_contract_identity, quality_rule_identity,
            outcome, cancellation, semantic_reference, bundle_id,
            dict(sorted(family_counts.items())), diagnostic_category,
            tuple(diagnostic_summary), producer_identity, attestation_class, "",
        )
        return value.reidentify()

    @classmethod
    def from_bytes(cls, data: bytes) -> "ExtractionReceipt":
        payload = decode_canonical_json(data)
        if payload.get("schema_version") != 1 or payload.get("canonicalization_version") != cls.CANONICALIZATION_VERSION:
            raise ValueError("unsupported extraction receipt version")
        try:
            reference_value = payload["bundle_reference"]
            if reference_value is not None and not isinstance(reference_value, Mapping):
                raise ValueError("bundle reference is invalid")
            reference = (
                None
                if reference_value is None
                else ArtifactReference.from_semantic_mapping(reference_value)
            )
            vector = _vector(payload["snapshot_vector"])
            counts = payload["family_counts"]
            diagnostics = payload["diagnostic_summary"]
            if not isinstance(counts, dict) or not isinstance(diagnostics, list):
                raise ValueError("receipt collection is invalid")
            value = cls.create(
                request_id=_str(payload["request_id"]), job_id=_str(payload["job_id"]),
                attempt=_int(payload["attempt"]), graph_id=_str(payload["graph_id"]),
                worker_capability_identity=_str(payload["worker_capability_identity"]),
                contract_version=_str(payload["contract_version"]),
                source_generation=_str(payload["source_generation"]),
                config_generation=_str(payload["config_generation"]),
                extractor_generation=_str(payload["extractor_generation"]),
                canonicalizer_generation=_str(payload["canonicalizer_generation"]),
                snapshot_manifest_id=_str(payload["snapshot_manifest_id"]),
                snapshot_vector=vector, resolver_identity=_str(payload["resolver_identity"]),
                extractor_capability_identity=_str(payload["extractor_capability_identity"]),
                canonicalizer_identity=_str(payload["canonicalizer_identity"]),
                semantic_contract_identity=_str(payload["semantic_contract_identity"]),
                quality_rule_identity=_str(payload["quality_rule_identity"]),
                outcome=_str(payload["outcome"]), cancellation=_str(payload["cancellation"]),
                bundle_reference=reference,
                bundle_id=None if payload["bundle_id"] is None else _str(payload["bundle_id"]),
                family_counts={_str(key): _int(item) for key, item in counts.items()},
                diagnostic_category=None if payload["diagnostic_category"] is None else _str(payload["diagnostic_category"]),
                diagnostic_summary=tuple(_str(item) for item in diagnostics),
                producer_identity=_str(payload["producer_identity"]),
                attestation_class=_str(payload["attestation_class"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("extraction receipt is malformed") from error
        if value.canonical_bytes() != data:
            raise ValueError("extraction receipt is not canonical")
        return value


def _validate_receipt(value: ExtractionReceipt) -> None:
    strings = (
        value.request_id, value.job_id, value.graph_id, value.worker_capability_identity,
        value.contract_version, value.source_generation, value.config_generation,
        value.extractor_generation, value.canonicalizer_generation,
        value.snapshot_manifest_id, value.resolver_identity,
        value.extractor_capability_identity, value.canonicalizer_identity,
        value.semantic_contract_identity, value.quality_rule_identity,
        value.cancellation, value.producer_identity, value.attestation_class,
    )
    if any(not isinstance(item, str) or not item or len(item.encode("utf-8")) > 256 for item in strings):
        raise ValueError("receipt identity field is invalid")
    if not isinstance(value.attempt, int) or isinstance(value.attempt, bool) or value.attempt < 1:
        raise ValueError("receipt attempt is invalid")
    if value.outcome not in RECEIPT_OUTCOMES:
        raise ValueError("receipt outcome is invalid")
    if value.diagnostic_category is not None and value.diagnostic_category not in DIAGNOSTIC_CATEGORIES:
        raise ValueError("receipt diagnostic category is invalid")
    if len(value.diagnostic_summary) > 32 or any(
        len(item.encode("utf-8")) > 256 for item in value.diagnostic_summary
    ):
        raise ValueError("receipt diagnostics exceed bounds")
    if value.outcome == "completed":
        if value.bundle_reference is None or value.bundle_id is None or value.diagnostic_category is not None:
            raise ValueError("completed receipt is inconsistent")
    elif value.bundle_reference is not None or value.bundle_id is not None or value.family_counts:
        raise ValueError("non-completed receipt cannot accept a bundle")
    if value.outcome in {"failed", "unsupported_contract", "malformed_input"} and value.diagnostic_category is None:
        raise ValueError("terminal receipt diagnostic is missing")
    if value.outcome == "cancelled" and value.cancellation == "not-requested":
        raise ValueError("cancelled receipt cancellation state is invalid")


def _vector(value: object) -> tuple[tuple[str, int, str], ...]:
    if not isinstance(value, list):
        raise ValueError("snapshot vector is invalid")
    result: list[tuple[str, int, str]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 3:
            raise ValueError("snapshot vector is invalid")
        result.append((_str(item[0]), _int(item[1]), _str(item[2])))
    return tuple(result)


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("receipt string field is invalid")
    return value


def _int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("receipt integer field is invalid")
    return value
