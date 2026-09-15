"""Deterministic, database-independent seven-family publication bundle."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from types import MappingProxyType
from typing import ClassVar, Mapping, Sequence, cast

from repomap_kg.artifacts._canonical import (
    canonical_json,
    decode_canonical_json,
    prefixed_digest,
)
from repomap_kg.storage.staging_family_contracts import PrivacyClassification
from repomap_kg.storage.staging_family_rows import StageFamily


PUBLICATION_FAMILIES: tuple[StageFamily, ...] = (
    "files",
    "raw_observations",
    "canonical_nodes",
    "canonical_edges",
    "canonical_evidence",
    "canonical_node_evidence",
    "canonical_edge_evidence",
)
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_RECORDS = 1_000_000
MAX_BUNDLE_LINE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class FamilySummary:
    family: StageFamily
    record_count: int
    byte_length: int
    content_digest: str

    def mapping(self) -> dict[str, object]:
        return {
            "byte_length": self.byte_length,
            "content_digest": self.content_digest,
            "family": self.family,
            "record_count": self.record_count,
        }


@dataclass(frozen=True)
class PublicationBundle:
    """Canonical publication candidate material; never publication authority."""

    SCHEMA_VERSION: ClassVar[int] = 1
    FRAMING_VERSION: ClassVar[str] = "repomap-publication-bundle-jsonl-v1"
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
    privacy: PrivacyClassification
    row_stage_contract: str
    families: Mapping[StageFamily, tuple[dict[str, object], ...]]
    family_summaries: tuple[FamilySummary, ...]
    terminal_complete: bool
    schema_version: int
    bundle_id: str

    @property
    def family_counts(self) -> dict[str, int]:
        return {item.family: item.record_count for item in self.family_summaries}

    def header_mapping(self) -> dict[str, object]:
        header = {
            "attempt": self.attempt,
            "candidate_id": self.candidate_id,
            "canonicalizer_generation": self.canonicalizer_generation,
            "canonicalizer_identity": self.canonicalizer_identity,
            "config_generation": self.config_generation,
            "extractor_capability_identity": self.extractor_capability_identity,
            "extractor_generation": self.extractor_generation,
            "frame": "header",
            "framing_version": self.FRAMING_VERSION,
            "graph_id": self.graph_id,
            "job_id": self.job_id,
            "privacy": self.privacy.value,
            "quality_rule_identity": self.quality_rule_identity,
            "request_id": self.request_id,
            "resolver_identity": self.resolver_identity,
            "schema_version": self.schema_version,
            "semantic_contract_identity": self.semantic_contract_identity,
            "snapshot_manifest_id": self.snapshot_manifest_id,
            "snapshot_vector": [list(item) for item in self.snapshot_vector],
            "source_generation": self.source_generation,
        }
        if self.row_stage_contract != "legacy-absent-v1":
            header["row_stage_contract"] = self.row_stage_contract
        return header

    def canonical_bytes(self) -> bytes:
        frames = [canonical_json(self.header_mapping())]
        frames.extend(_family_frames(self.families))
        frames.append(canonical_json(self._trailer_mapping()))
        if any(len(frame) > MAX_BUNDLE_LINE_BYTES for frame in frames):
            raise ValueError("publication bundle line bounds exceeded")
        data = b"".join(frames)
        if len(data) > MAX_BUNDLE_BYTES:
            raise ValueError("publication bundle byte bounds exceeded")
        return data

    def _trailer_mapping(self) -> dict[str, object]:
        return {
            "complete": self.terminal_complete,
            "families": [item.mapping() for item in self.family_summaries],
            "frame": "trailer",
            "total_family_bytes": sum(item.byte_length for item in self.family_summaries),
            "total_records": sum(item.record_count for item in self.family_summaries),
        }

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        job_id: str,
        attempt: int,
        graph_id: str,
        candidate_id: str,
        snapshot_manifest_id: str,
        snapshot_vector: Sequence[tuple[str, int, str]],
        source_generation: str,
        config_generation: str,
        extractor_generation: str,
        canonicalizer_generation: str,
        extractor_capability_identity: str,
        resolver_identity: str,
        canonicalizer_identity: str,
        semantic_contract_identity: str,
        quality_rule_identity: str,
        privacy: PrivacyClassification,
        families: Mapping[StageFamily, Sequence[Mapping[str, object]]],
        row_stage_contract: str,
        terminal_complete: bool = True,
        schema_version: int = 1,
    ) -> "PublicationBundle":
        _validate_metadata(
            request_id=request_id, job_id=job_id, attempt=attempt, graph_id=graph_id,
            candidate_id=candidate_id, snapshot_manifest_id=snapshot_manifest_id,
            source_generation=source_generation, config_generation=config_generation,
            extractor_generation=extractor_generation,
            canonicalizer_generation=canonicalizer_generation,
            extractor_capability_identity=extractor_capability_identity,
            resolver_identity=resolver_identity,
            canonicalizer_identity=canonicalizer_identity,
            semantic_contract_identity=semantic_contract_identity,
            quality_rule_identity=quality_rule_identity,
        )
        if not isinstance(privacy, PrivacyClassification):
            raise ValueError("bundle privacy is invalid")
        if row_stage_contract not in {"legacy-absent-v1", "stage-unassigned-v1"}:
            raise ValueError("bundle row stage contract is invalid")
        if not isinstance(terminal_complete, bool):
            raise ValueError("bundle terminal completeness is invalid")
        if set(families) != set(PUBLICATION_FAMILIES):
            raise ValueError("publication bundle family inventory is invalid")
        normalized: dict[StageFamily, tuple[dict[str, object], ...]] = {}
        count = 0
        for family in PUBLICATION_FAMILIES:
            rows = tuple(dict(item) for item in families[family])
            ordered = tuple(sorted(rows, key=canonical_json))
            count += len(ordered)
            normalized[family] = ordered
        if count > MAX_BUNDLE_RECORDS:
            raise ValueError("publication bundle record bounds exceeded")
        family_frames = _family_frame_groups(normalized)
        summaries = tuple(
            FamilySummary(
                family,
                len(normalized[family]),
                len(family_frames[family]),
                "sha256:" + hashlib.sha256(family_frames[family]).hexdigest(),
            )
            for family in PUBLICATION_FAMILIES
        )
        value = cls(
            request_id, job_id, attempt, graph_id, candidate_id,
            snapshot_manifest_id, tuple(snapshot_vector), source_generation,
            config_generation, extractor_generation, canonicalizer_generation,
            extractor_capability_identity, resolver_identity,
            canonicalizer_identity, semantic_contract_identity,
            quality_rule_identity, privacy, row_stage_contract,
            MappingProxyType(normalized), summaries,
            terminal_complete, schema_version, "",
        )
        data = value.canonical_bytes()
        return replace(
            value,
            bundle_id=prefixed_digest(
                "bundle1:", b"repomap-publication-bundle-v1", data
            ),
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "PublicationBundle":
        if not isinstance(data, bytes) or len(data) > MAX_BUNDLE_BYTES or not data.endswith(b"\n"):
            raise ValueError("publication bundle framing is invalid")
        lines = data.splitlines(keepends=True)
        if len(lines) < 2 or any(len(line) > MAX_BUNDLE_LINE_BYTES for line in lines):
            raise ValueError("publication bundle framing is invalid")
        frames = [decode_canonical_json(line) for line in lines]
        header, trailer = frames[0], frames[-1]
        if header.get("frame") != "header" or trailer.get("frame") != "trailer":
            raise ValueError("publication bundle framing is invalid")
        if header.get("schema_version") != 1 or header.get("framing_version") != cls.FRAMING_VERSION:
            raise ValueError("unsupported publication bundle version")
        rows: dict[StageFamily, list[Mapping[str, object]]] = {
            family: [] for family in PUBLICATION_FAMILIES
        }
        prior_index = -1
        for frame in frames[1:-1]:
            if set(frame) != {"family", "frame", "record"} or frame["frame"] != "record":
                raise ValueError("publication bundle record frame is invalid")
            family = frame["family"]
            if family not in PUBLICATION_FAMILIES or not isinstance(frame["record"], dict):
                raise ValueError("publication bundle family is invalid")
            index = PUBLICATION_FAMILIES.index(family)
            if index < prior_index:
                raise ValueError("publication bundle family ordering is invalid")
            prior_index = index
            rows[family].append(cast(dict[str, object], frame["record"]))
        value = cls.create(
            request_id=_string(header, "request_id"), job_id=_string(header, "job_id"),
            attempt=_integer(header, "attempt"), graph_id=_string(header, "graph_id"),
            candidate_id=_string(header, "candidate_id"),
            snapshot_manifest_id=_string(header, "snapshot_manifest_id"),
            snapshot_vector=_vector(header.get("snapshot_vector")),
            source_generation=_string(header, "source_generation"),
            config_generation=_string(header, "config_generation"),
            extractor_generation=_string(header, "extractor_generation"),
            canonicalizer_generation=_string(header, "canonicalizer_generation"),
            extractor_capability_identity=_string(header, "extractor_capability_identity"),
            resolver_identity=_string(header, "resolver_identity"),
            canonicalizer_identity=_string(header, "canonicalizer_identity"),
            semantic_contract_identity=_string(header, "semantic_contract_identity"),
            quality_rule_identity=_string(header, "quality_rule_identity"),
            privacy=PrivacyClassification(_string(header, "privacy")),
            families=rows,
            row_stage_contract=(
                _string(header, "row_stage_contract")
                if "row_stage_contract" in header
                else "legacy-absent-v1"
            ),
        )
        if trailer != value._trailer_mapping() or value.canonical_bytes() != data:
            raise ValueError("publication bundle summary is inconsistent")
        return value

    def with_schema_version_for_test(self, version: int) -> "PublicationBundle":
        changed = replace(self, schema_version=version, bundle_id="")
        return replace(
            changed,
            bundle_id=prefixed_digest(
                "bundle1:", b"repomap-publication-bundle-v1", changed.canonical_bytes()
            ),
        )

    @staticmethod
    def malformed_for_test(data: bytes, mutation: str) -> bytes:
        lines = data.splitlines(keepends=True)
        if mutation == "truncated":
            return data[:-1]
        if mutation == "duplicate":
            return b"".join((lines[0], lines[1], lines[1], *lines[2:]))
        if mutation == "partial":
            return b"".join(lines[:-1])
        if mutation == "unknown-family":
            frame = decode_canonical_json(lines[1])
            frame["family"] = "unknown"
            lines[1] = canonical_json(frame)
            return b"".join(lines)
        raise ValueError("unknown test mutation")


def _family_frame_groups(families: Mapping[StageFamily, Sequence[Mapping[str, object]]]) -> dict[StageFamily, bytes]:
    return {
        family: b"".join(
            canonical_json({"family": family, "frame": "record", "record": row})
            for row in families[family]
        )
        for family in PUBLICATION_FAMILIES
    }


def _family_frames(families: Mapping[StageFamily, Sequence[Mapping[str, object]]]) -> list[bytes]:
    groups = _family_frame_groups(families)
    return [groups[family] for family in PUBLICATION_FAMILIES if groups[family]]


def _validate_metadata(**values: object) -> None:
    for name, value in values.items():
        if name == "attempt":
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError("bundle attempt is invalid")
        elif not isinstance(value, str) or not value or len(value.encode("utf-8")) > 256:
            raise ValueError(f"bundle {name} is invalid")


def _string(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str):
        raise ValueError("publication bundle field is invalid")
    return item


def _integer(value: Mapping[str, object], field: str) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool):
        raise ValueError("publication bundle field is invalid")
    return item


def _vector(value: object) -> tuple[tuple[str, int, str], ...]:
    if not isinstance(value, list):
        raise ValueError("snapshot vector is invalid")
    result: list[tuple[str, int, str]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 3 or not isinstance(item[0], str) or not isinstance(item[1], int) or isinstance(item[1], bool) or not isinstance(item[2], str):
            raise ValueError("snapshot vector is invalid")
        result.append((item[0], item[1], item[2]))
    return tuple(result)
