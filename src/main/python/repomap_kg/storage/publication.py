"""Validated generation receipt for one authoritative graph publication run."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from collections.abc import Mapping
from typing import cast

from repomap_kg.storage.authority import AttemptNumber, JobId, PublicationGenerations

_JOB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_PORTABLE_ID = re.compile(r"[a-z][a-z0-9_]*1:[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_STAGE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_DIGEST_ID = re.compile(r"(?:snapmanifest1|receipt1|bundle1|cand1):[0-9a-f]{64}\Z")

RunPublicationGenerations = PublicationGenerations


@dataclass(frozen=True)
class RunPublicationAttempt:
    """Bounded coordinator identity for one graph publication attempt."""

    job_id: JobId
    attempt: AttemptNumber

    def validate(self) -> "RunPublicationAttempt":
        attempt_value: object = self.attempt
        if (
            not isinstance(self.job_id, str)
            or _JOB_ID.fullmatch(self.job_id) is None
            or "--" in self.job_id
            or isinstance(attempt_value, bool)
            or not isinstance(attempt_value, int)
            or attempt_value <= 0
            or attempt_value > 2_147_483_647
        ):
            raise ValueError("invalid publication attempt")
        return self


@dataclass(frozen=True)
class PortablePublicationBinding:
    """Complete portable evidence committed by the sole graph publisher."""

    route: str
    snapshot_manifest_id: str
    snapshot_vector: tuple[tuple[str, int, str], ...]
    extraction_receipt_id: str
    publication_bundle_id: str
    candidate_id: str
    resolver_identity: str
    canonicalizer_identity: str
    semantic_contract_identity: str
    quality_rule_identity: str
    protocol_version: str
    worker_capability_identity: str
    stage_id: str
    execution_mode: str
    singleton_fencing_epoch: int
    graph_lease_fencing_epoch: int
    family_receipts: Mapping[str, Mapping[str, object]]

    @classmethod
    def field_names(cls) -> tuple[str, ...]:
        return (
            "execution_route",
            "snapshot_manifest_id",
            "snapshot_vector_json",
            "extraction_receipt_id",
            "publication_bundle_id",
            "graph_candidate_id",
            "resolver_identity",
            "portable_canonicalizer_identity",
            "semantic_contract_identity",
            "quality_rule_identity",
            "portable_protocol_version",
            "worker_capability_identity",
            "portable_stage_id",
            "portable_execution_mode",
            "portable_singleton_fencing_epoch",
            "portable_graph_lease_fencing_epoch",
            "family_receipts_json",
        )

    def validate(self) -> "PortablePublicationBinding":
        identities = (
            self.snapshot_manifest_id,
            self.extraction_receipt_id,
            self.publication_bundle_id,
            self.candidate_id,
            self.resolver_identity,
            self.canonicalizer_identity,
            self.semantic_contract_identity,
            self.quality_rule_identity,
            self.worker_capability_identity,
        )
        valid = (
            self.route == "portable-worker-v1"
            and all(_PORTABLE_ID.fullmatch(value) is not None for value in identities)
            and all(
                _DIGEST_ID.fullmatch(value) is not None
                for value in (
                    self.snapshot_manifest_id,
                    self.extraction_receipt_id,
                    self.publication_bundle_id,
                    self.candidate_id,
                )
            )
            and self.protocol_version == "1.0"
            and _STAGE_ID.fullmatch(self.stage_id) is not None
            and self.execution_mode in {"direct", "coordinator"}
            and all(
                isinstance(value, int) and not isinstance(value, bool) and value >= 0
                for value in (
                    self.singleton_fencing_epoch,
                    self.graph_lease_fencing_epoch,
                )
            )
            and bool(self.snapshot_vector)
            and all(
                isinstance(binding_id, str)
                and binding_id.startswith("bind1:")
                and isinstance(revision, int)
                and not isinstance(revision, bool)
                and revision > 0
                and isinstance(snapshot_id, str)
                and snapshot_id.startswith("snap1:")
                for binding_id, revision, snapshot_id in self.snapshot_vector
            )
            and set(self.family_receipts) == {
                "files", "raw_observations", "canonical_nodes",
                "canonical_edges", "canonical_evidence",
                "canonical_node_evidence", "canonical_edge_evidence",
            }
            and all(
                isinstance(item.get("count"), int)
                and isinstance(item.get("byte_length"), int)
                and isinstance(item.get("digest"), str)
                and str(item["digest"]).startswith("sha256:")
                for item in self.family_receipts.values()
            )
        )
        if not valid:
            raise ValueError("invalid portable publication binding")
        self.to_mapping()
        return self

    def to_mapping(self) -> dict[str, str | int]:
        vector = json.dumps(self.snapshot_vector, separators=(",", ":"))
        families = json.dumps(
            self.family_receipts, sort_keys=True, separators=(",", ":")
        )
        return dict(
            zip(
                self.field_names(),
                (
                    self.route,
                    self.snapshot_manifest_id,
                    vector,
                    self.extraction_receipt_id,
                    self.publication_bundle_id,
                    self.candidate_id,
                    self.resolver_identity,
                    self.canonicalizer_identity,
                    self.semantic_contract_identity,
                    self.quality_rule_identity,
                    self.protocol_version,
                    self.worker_capability_identity,
                    self.stage_id,
                    self.execution_mode,
                    self.singleton_fencing_epoch,
                    self.graph_lease_fencing_epoch,
                    families,
                ),
                strict=True,
            )
        )

    def public_mapping(self) -> dict[str, object]:
        return {
            "execution_route": self.route,
            "protocol_version": self.protocol_version,
            "snapshot_manifest_id": self.snapshot_manifest_id,
            "extraction_receipt_id": self.extraction_receipt_id,
            "publication_bundle_id": self.publication_bundle_id,
            "graph_candidate_id": self.candidate_id,
            "source_binding_count": len(self.snapshot_vector),
            "family_counts": {
                family: receipt.get("count")
                for family, receipt in sorted(self.family_receipts.items())
            },
        }


@dataclass(frozen=True)
class RunPublicationReceipt:
    """Exact attempt identity and generations committed with one graph run."""

    attempt: RunPublicationAttempt
    generations: RunPublicationGenerations
    portable: PortablePublicationBinding | None = None

    @classmethod
    def base_field_names(cls) -> tuple[str, ...]:
        return (
            "publication_job_id",
            "publication_attempt",
            *RunPublicationGenerations.field_names(),
        )

    @classmethod
    def field_names(cls) -> tuple[str, ...]:
        return (
            *cls.base_field_names(),
            *PortablePublicationBinding.field_names(),
        )

    def validate(self) -> "RunPublicationReceipt":
        if not isinstance(self.attempt, RunPublicationAttempt) or not isinstance(
            self.generations, RunPublicationGenerations
        ):
            raise ValueError("invalid publication receipt")
        self.attempt.validate()
        self.generations.validate()
        if self.portable is not None:
            if not isinstance(self.portable, PortablePublicationBinding):
                raise ValueError("invalid publication receipt")
            self.portable.validate()
        return self

    def to_mapping(self) -> dict[str, str | int]:
        self.validate()
        mapping: dict[str, str | int] = {
            "publication_job_id": self.attempt.job_id,
            "publication_attempt": self.attempt.attempt,
            **dict(
                zip(
                    self.generations.field_names(),
                    self.generations.values(),
                    strict=True,
                )
            ),
        }
        if self.portable is not None:
            mapping.update(self.portable.to_mapping())
        return mapping

    def public_mapping(self) -> dict[str, object]:
        self.validate()
        return {} if self.portable is None else self.portable.public_mapping()


def publication_generations_from_mapping(
    payload: object,
) -> RunPublicationGenerations | None:
    """Parse an all-null or all-present database receipt."""

    if not isinstance(payload, dict):
        raise ValueError("invalid publication generations")
    values = tuple(payload.get(field) for field in RunPublicationGenerations.field_names())
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("invalid publication generations")
    if not all(isinstance(value, str) for value in values):
        raise ValueError("invalid publication generations")
    typed = cast(tuple[str, str, str, str], values)
    return RunPublicationGenerations(*typed).validate()


def publication_receipt_from_mapping(payload: object) -> RunPublicationReceipt | None:
    """Parse one all-null or all-present publication-attempt receipt."""

    generations = publication_generations_from_mapping(payload)
    if not isinstance(payload, dict):
        raise ValueError("invalid publication receipt")
    job_id = payload.get("publication_job_id")
    attempt = payload.get("publication_attempt")
    if generations is None and job_id is None and attempt is None:
        return None
    if generations is None or job_id is None or attempt is None:
        raise ValueError("invalid publication receipt")
    portable = _portable_binding_from_mapping(payload)
    return RunPublicationReceipt(
        RunPublicationAttempt(JobId(str(job_id)), AttemptNumber(_integer(attempt))),
        generations,
        portable,
    ).validate()


def _portable_binding_from_mapping(
    payload: Mapping[str, object],
) -> PortablePublicationBinding | None:
    values = tuple(payload.get(field) for field in PortablePublicationBinding.field_names())
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("invalid portable publication binding")
    try:
        vector_value = json.loads(str(payload["snapshot_vector_json"]))
        family_value = json.loads(str(payload["family_receipts_json"]))
        vector = tuple((str(item[0]), int(item[1]), str(item[2])) for item in vector_value)
        if not isinstance(family_value, dict):
            raise ValueError
        return PortablePublicationBinding(
            route=str(payload["execution_route"]),
            snapshot_manifest_id=str(payload["snapshot_manifest_id"]),
            snapshot_vector=vector,
            extraction_receipt_id=str(payload["extraction_receipt_id"]),
            publication_bundle_id=str(payload["publication_bundle_id"]),
            candidate_id=str(payload["graph_candidate_id"]),
            resolver_identity=str(payload["resolver_identity"]),
            canonicalizer_identity=str(payload["portable_canonicalizer_identity"]),
            semantic_contract_identity=str(payload["semantic_contract_identity"]),
            quality_rule_identity=str(payload["quality_rule_identity"]),
            protocol_version=str(payload["portable_protocol_version"]),
            worker_capability_identity=str(payload["worker_capability_identity"]),
            stage_id=str(payload["portable_stage_id"]),
            execution_mode=str(payload["portable_execution_mode"]),
            singleton_fencing_epoch=_integer(payload["portable_singleton_fencing_epoch"]),
            graph_lease_fencing_epoch=_integer(payload["portable_graph_lease_fencing_epoch"]),
            family_receipts=family_value,
        ).validate()
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid portable publication binding") from error


def _integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("invalid portable publication binding")
    return value


__all__ = [
    "RunPublicationAttempt",
    "PortablePublicationBinding",
    "RunPublicationGenerations",
    "RunPublicationReceipt",
    "publication_generations_from_mapping",
    "publication_receipt_from_mapping",
]
