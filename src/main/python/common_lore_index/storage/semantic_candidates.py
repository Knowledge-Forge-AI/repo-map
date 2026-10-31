"""Versioned precomputed embedding and exact candidate read contracts.

No embedding generator or optional database driver is imported here. Production
extension admission remains subject to ADR 0077 / ADR 0051 D15.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any

from common_lore_index.storage.publication_readback import RunPublicationRecord

CAPABILITY = "pgvector-candidates-v1"
PGVECTOR_VERSION = "0.8.7"
MAX_DIMENSIONS = 2000
MAX_IMPORT_ROWS = 500
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def checked_identity(value: str) -> str:
    if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
        raise ValueError("invalid enrichment identity")
    return value


@dataclass(frozen=True)
class EmbeddingProfile:
    model: str
    model_version: str
    generator: str
    generator_version: str
    dimensions: int
    representation_version: str = "canonical-node-v1"
    normalization: str = "l2-unit"
    metric: str = "cosine"

    def validate(self) -> EmbeddingProfile:
        for value in (self.model, self.model_version, self.generator, self.generator_version):
            checked_identity(value)
        if type(self.dimensions) is not int or not 1 <= self.dimensions <= MAX_DIMENSIONS:
            raise ValueError("embedding dimensions must be between 1 and 2000")
        if (self.representation_version, self.normalization, self.metric) != (
            "canonical-node-v1", "l2-unit", "cosine"
        ):
            raise ValueError("unsupported embedding representation or distance contract")
        return self

    @property
    def identity(self) -> str:
        self.validate()
        return digest_json(self.__dict__)


def digest_json(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def checked_vector(values: tuple[float, ...], dimensions: int) -> tuple[float, ...]:
    if not isinstance(values, tuple) or len(values) != dimensions:
        raise ValueError("embedding dimension mismatch")
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError("embedding values must be finite numbers")
    norm = math.hypot(*values)
    if not math.isfinite(norm) or abs(norm - 1.0) > 0.00001:
        raise ValueError("embedding must have L2 unit normalization")
    return tuple(float(value) for value in values)


@dataclass(frozen=True)
class CandidatePublication:
    repository_identity: str
    publication: RunPublicationRecord

    def validate(self) -> CandidatePublication:
        identity = checked_identity(self.repository_identity)
        if not identity.startswith("repo1:"):
            raise ValueError("enrichment requires a stable repository identity")
        if type(self.publication.run_id) is not int or self.publication.run_id <= 0:
            raise ValueError("invalid enrichment publication")
        receipt = self.publication.receipt.validate()
        if receipt.portable is None:
            raise ValueError("enrichment requires a complete portable publication receipt")
        return self

    @property
    def receipt_identity(self) -> str:
        self.validate()
        return digest_json(self.publication.receipt.to_mapping())


@dataclass(frozen=True)
class EmbeddingEntry:
    canonical_key: str
    source_binding_id: str
    vector: tuple[float, ...]
    input_digest: str

    def validate(self, profile: EmbeddingProfile, publication: CandidatePublication) -> None:
        if not isinstance(self.canonical_key, str) or not 1 <= len(self.canonical_key) <= 4096:
            raise ValueError("invalid enrichment canonical key")
        if "\x00" in self.canonical_key:
            raise ValueError("invalid enrichment canonical key")
        portable = publication.publication.receipt.portable
        assert portable is not None
        if self.source_binding_id not in {binding for binding, _, _ in portable.snapshot_vector}:
            raise ValueError("embedding source binding is outside the publication")
        if not isinstance(self.input_digest, str) or _DIGEST.fullmatch(self.input_digest) is None:
            raise ValueError("invalid embedding input digest")
        checked_vector(self.vector, profile.dimensions)


@dataclass(frozen=True)
class CandidateQuery:
    publication: CandidatePublication
    profile: EmbeddingProfile
    rebuild_id: str
    vector: tuple[float, ...]
    selected: bool = False
    limit: int = 20
    evidence_limit: int = 5
    kind: str | None = None
    path: str | None = None
    source_binding_id: str | None = None

    def validate(self) -> CandidateQuery:
        self.publication.validate()
        self.profile.validate()
        checked_identity(self.rebuild_id)
        checked_vector(self.vector, self.profile.dimensions)
        if type(self.selected) is not bool:
            raise ValueError("candidate selection must be explicit boolean")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("candidate limit must be between 1 and 100")
        if type(self.evidence_limit) is not int or not 1 <= self.evidence_limit <= 20:
            raise ValueError("evidence limit must be between 1 and 20")
        for value in (self.kind, self.path, self.source_binding_id):
            if value is not None and (
                not isinstance(value, str) or not 1 <= len(value) <= 4096 or "\x00" in value
            ):
                raise ValueError("invalid candidate filter")
        return self


@dataclass(frozen=True)
class CandidateResult:
    status: str
    reason: str | None
    candidates: tuple[dict[str, Any], ...] = ()
    provenance: dict[str, Any] | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "capability": CAPABILITY, "status": self.status, "reason": self.reason,
            "read_only": True, "candidates": list(self.candidates),
            "provenance": self.provenance,
            "limitations": [
                "heuristic candidate discovery; no canonical dependency assertion",
                "precomputed import coverage only; missing nodes are not negative evidence",
                "at most 500 imported node/source records in one rebuild per query",
                "bounded stored evidence expansion; no source acquisition or inference",
                "synthetic fixture correctness does not establish semantic quality",
            ],
        }


def unavailable(reason: str) -> CandidateResult:
    return CandidateResult("capability_unavailable", reason)

@dataclass(frozen=True)
class EmbeddingProfilesQuery:
    selected: bool = False
    limit: int = 20

    def validate(self) -> EmbeddingProfilesQuery:
        if type(self.selected) is not bool:
            raise ValueError("profile selection must be explicit boolean")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("profile limit must be between 1 and 100")
        return self


@dataclass(frozen=True)
class EmbeddingProfilesResult:
    status: str
    reason: str | None = None
    profiles: tuple[dict[str, Any], ...] = ()
    has_more: bool = False
    provenance: dict[str, Any] | None = None
    has_excluded_rebuilds: bool = False

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "capability": "pgvector-candidates-v1", "status": self.status,
            "reason": self.reason, "read_only": True, "profiles": list(self.profiles),
            "has_more": self.has_more, "provenance": self.provenance,
            "has_excluded_rebuilds": self.has_excluded_rebuilds,
            "limitations": [
                "explicit caller choice required; no preferred rebuild or profile",
                "at most 500 imported node/source records per rebuild; partial coverage only",
                "input digest and generator claims are enrichment principal assertions",
                "synthetic fixture correctness does not establish semantic quality",
                "metadata discovery only; no vectors, source acquisition or inference",
                "identity validation covers the limit+1 SQL page; any invalid page entry refuses the result",
                "excluded flag covers SQL-ineligible repository rebuilds; unreturned identities are unvalidated",
                "output is bounded; evidence checks may examine every bound rebuild before paging",
            ],
        }


def profiles_unavailable(reason: str) -> EmbeddingProfilesResult:
    return EmbeddingProfilesResult("capability_unavailable", reason)


def validated_profile_entry(row: object, publication: CandidatePublication) -> dict[str, Any]:
    """Project a whitelist only after profile digest and source identities agree."""
    if not isinstance(row, dict):
        raise ValueError("invalid profile identity")
    rebuild_id = row.get("rebuild_id")
    if not isinstance(rebuild_id, str):
        raise ValueError("invalid rebuild identity")
    checked_identity(rebuild_id)
    fields = EmbeddingProfile.__dataclass_fields__
    profile = EmbeddingProfile(**{field: row[field] for field in fields}).validate()
    if row.get("profile_identity") != profile.identity:
        raise ValueError("invalid profile identity")
    row_count = row.get("row_count")
    if type(row_count) is not int or not 1 <= row_count <= MAX_IMPORT_ROWS:
        raise ValueError("invalid rebuild row count")
    portable = publication.publication.receipt.portable
    assert portable is not None
    accepted = {(binding, snapshot) for binding, _, snapshot in portable.snapshot_vector}
    scope = row.get("source_scope")
    if not isinstance(scope, list) or not 1 <= len(scope) <= row_count:
        raise ValueError("invalid rebuild source scope")
    identities = []
    for item in scope:
        if not isinstance(item, dict):
            raise ValueError("invalid rebuild source scope")
        identity = (item.get("source_binding_id"), item.get("snapshot_id"))
        if any(not isinstance(value, str) for value in identity) or identity not in accepted:
            raise ValueError("invalid rebuild source scope")
        identities.append(identity)
    if len(set(identities)) != len(identities):
        raise ValueError("ambiguous rebuild source scope")
    return {
        "rebuild_id": rebuild_id, "profile_identity": profile.identity,
        **profile.__dict__, "row_count": row_count, "privacy_class": "public",
        "source_scope": [dict(zip(("source_binding_id", "snapshot_id"), identity, strict=True))
                         for identity in sorted(identities)],
    }
