"""Non-mutating publisher-side byte and semantic conformance validation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping

from repomap_kg.artifacts.bundle import PUBLICATION_FAMILIES, PublicationBundle
from repomap_kg.artifacts.receipt import ExtractionReceipt
from repomap_kg.artifacts.references import ArtifactReference
from repomap_kg.artifacts.store import ArtifactStore
from repomap_kg.storage.staging_family_rows import StageFamily


@dataclass(frozen=True)
class PublicationExpectation:
    request_id: str
    job_id: str
    attempt: int
    graph_id: str
    candidate_id: str
    snapshot_manifest_id: str
    snapshot_vector: tuple[tuple[str, int, str], ...]
    source_generation: str
    config_generation: str
    extractor_generation: str
    canonicalizer_generation: str
    extractor_capability_identity: str
    resolver_identity: str
    canonicalizer_identity: str
    semantic_contract_identity: str
    quality_rule_identity: str
    mutating_owner_count: int
    contract_version: str = "1.0"
    worker_capability_identity: str = "cap1:portable-worker-v1"
    expected_privacy: str | None = None

    @classmethod
    def from_bundle(
        cls,
        bundle: PublicationBundle,
        *,
        mutating_owner_count: int,
        contract_version: str = "1.0",
        worker_capability_identity: str = "cap1:portable-worker-v1",
        expected_privacy: str | None = None,
    ) -> "PublicationExpectation":
        return cls(
            bundle.request_id, bundle.job_id, bundle.attempt, bundle.graph_id,
            bundle.candidate_id, bundle.snapshot_manifest_id,
            bundle.snapshot_vector, bundle.source_generation,
            bundle.config_generation, bundle.extractor_generation,
            bundle.canonicalizer_generation,
            bundle.extractor_capability_identity, bundle.resolver_identity,
            bundle.canonicalizer_identity, bundle.semantic_contract_identity,
            bundle.quality_rule_identity, mutating_owner_count,
            contract_version=contract_version,
            worker_capability_identity=worker_capability_identity,
            expected_privacy=expected_privacy or bundle.privacy.value,
        )


@dataclass(frozen=True)
class BundleValidationResult:
    bundle_id: str
    receipt_id: str
    byte_integrity_valid: bool
    semantic_authority_valid: bool
    idempotent_replay: bool
    mutated: bool = False


class PublisherBundleValidator:
    """Validate a candidate without loading or mutating graph tables."""

    def __init__(self) -> None:
        self._attempts: dict[tuple[str, int], tuple[str, str | None, str]] = {}

    def validate_terminal_receipt(
        self,
        *,
        store: ArtifactStore,
        receipt_reference: ArtifactReference,
    ) -> ExtractionReceipt:
        """Validate and remember one non-completed terminal receipt."""

        receipt_bytes = store.read(receipt_reference)
        receipt = ExtractionReceipt.from_bytes(receipt_bytes)
        if receipt_reference.content_digest != _sha256(receipt_bytes):
            raise ValueError("receipt byte integrity failed")
        if (
            receipt.outcome not in {"failed", "cancelled"}
            or receipt.bundle_id is not None
            or receipt.bundle_reference is not None
        ):
            raise ValueError("terminal receipt is not a non-completed attempt")
        self._record_attempt(
            (receipt.job_id, receipt.attempt),
            (receipt.receipt_id, None, receipt.outcome),
        )
        return receipt

    def validate_bundle(
        self,
        *,
        store: ArtifactStore,
        bundle_reference: ArtifactReference,
        receipt_reference: ArtifactReference,
        expectation: PublicationExpectation,
    ) -> BundleValidationResult:
        bundle_bytes = store.read(bundle_reference)
        receipt_bytes = store.read(receipt_reference)
        bundle = PublicationBundle.from_bytes(bundle_bytes)
        receipt = ExtractionReceipt.from_bytes(receipt_bytes)
        if bundle_reference.content_digest != _sha256(bundle_bytes):
            raise ValueError("bundle byte integrity failed")
        if receipt_reference.content_digest != _sha256(receipt_bytes):
            raise ValueError("receipt byte integrity failed")
        self._validate_semantics(bundle, receipt, expectation)
        key = (bundle.job_id, bundle.attempt)
        identity = (receipt.receipt_id, bundle.bundle_id, "completed")
        prior = self._attempts.get(key)
        self._record_attempt(key, identity)
        replay = prior == identity
        return BundleValidationResult(
            bundle.bundle_id,
            receipt.receipt_id,
            byte_integrity_valid=True,
            semantic_authority_valid=True,
            idempotent_replay=replay,
        )

    def _record_attempt(
        self,
        key: tuple[str, int],
        identity: tuple[str, str | None, str],
    ) -> None:
        prior = self._attempts.get(key)
        if prior is not None and prior != identity:
            if prior[2] in {"failed", "cancelled"} and identity[2] == "completed":
                raise ValueError("non-completed attempt cannot become completed")
            raise ValueError("conflicting attempt reuse")
        self._attempts[key] = identity

    @staticmethod
    def _validate_semantics(
        bundle: PublicationBundle,
        receipt: ExtractionReceipt,
        expected: PublicationExpectation,
    ) -> None:
        if expected.mutating_owner_count != 1:
            raise ValueError("exactly one mutating owner is required")
        for field in (
            "request_id", "job_id", "attempt", "graph_id", "candidate_id",
            "snapshot_manifest_id", "snapshot_vector", "source_generation",
            "config_generation", "extractor_generation",
            "canonicalizer_generation", "extractor_capability_identity",
            "resolver_identity", "canonicalizer_identity",
            "semantic_contract_identity", "quality_rule_identity",
        ):
            if getattr(bundle, field) != getattr(expected, field):
                raise ValueError("bundle semantic authority mismatch")
        receipt_fields = (
            "request_id", "job_id", "attempt", "graph_id", "snapshot_manifest_id",
            "snapshot_vector", "source_generation", "config_generation",
            "extractor_generation", "canonicalizer_generation",
            "extractor_capability_identity", "resolver_identity",
            "canonicalizer_identity", "semantic_contract_identity",
            "quality_rule_identity",
        )
        if any(getattr(receipt, field) != getattr(bundle, field) for field in receipt_fields):
            raise ValueError("receipt semantic authority mismatch")
        if receipt.contract_version != expected.contract_version:
            raise ValueError("receipt contract version mismatch")
        if receipt.worker_capability_identity != expected.worker_capability_identity:
            raise ValueError("receipt worker capability identity mismatch")
        if expected.expected_privacy is not None and bundle.privacy.value != expected.expected_privacy:
            raise ValueError("bundle privacy mismatch")
        if set(bundle.families) != set(PUBLICATION_FAMILIES):
            raise ValueError("required publication families are absent")
        if (
            receipt.outcome != "completed"
            or receipt.cancellation not in {"not-requested", "not-observed"}
            or receipt.bundle_id != bundle.bundle_id
            or receipt.bundle_reference is None
            or receipt.bundle_reference.content_digest != _sha256(bundle.canonical_bytes())
            or dict(receipt.family_counts) != bundle.family_counts
            or not bundle.terminal_complete
        ):
            raise ValueError("receipt and bundle terminal state is inconsistent")
        for rows in bundle.families.values():
            for row in rows:
                stage_id = row.get("stage_id")
                if bundle.row_stage_contract == "stage-unassigned-v1":
                    if stage_id != "stage-unassigned":
                        raise ValueError(
                            "bundle stage representation is ambiguous: stage identity"
                        )
                elif stage_id is not None:
                    raise ValueError("legacy bundle stage representation is ambiguous")
        _validate_family_links(bundle.families)


def _validate_family_links(
    families: Mapping[StageFamily, tuple[dict[str, object], ...]] | Mapping[str, tuple[dict[str, object], ...]],
) -> None:
    raw_ordinals = {item.get("source_ordinal") for item in families["raw_observations"]}
    node_keys = {item.get("canonical_key") for item in families["canonical_nodes"]}
    evidence_keys = {item.get("evidence_key") for item in families["canonical_evidence"]}
    edge_keys = {
        (
            item.get("source_canonical_key"), item.get("edge_kind"),
            item.get("target_canonical_key"), item.get("identity_metadata_hash"),
        )
        for item in families["canonical_edges"]
    }
    if any(item.get("raw_observation_ordinal") not in raw_ordinals for item in families["canonical_evidence"]):
        raise ValueError("bundle semantic evidence reference is invalid")
    if any(
        item.get("canonical_key") not in node_keys
        or item.get("evidence_key") not in evidence_keys
        for item in families["canonical_node_evidence"]
    ):
        raise ValueError("bundle semantic node evidence reference is invalid")
    if any(
        (
            item.get("source_canonical_key"), item.get("edge_kind"),
            item.get("target_canonical_key"), item.get("identity_metadata_hash"),
        ) not in edge_keys
        or item.get("evidence_key") not in evidence_keys
        for item in families["canonical_edge_evidence"]
    ):
        raise ValueError("bundle semantic edge evidence reference is invalid")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()
