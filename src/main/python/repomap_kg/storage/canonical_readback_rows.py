"""Canonical graph storage readback records and payload decoders."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.row_helpers import (
    payload_bool,
    payload_int,
    payload_json_object,
    payload_optional_int,
    payload_optional_text,
    payload_text,
)

__all__ = (
    "CanonicalNodeRecord",
    "CanonicalEdgeRecord",
    "CanonicalEdgeEvidenceRecord",
    "CanonicalEdgeExplanationRecord",
    "CanonicalNeighborhoodRecord",
    "canonical_node_record_from_storage_payload",
    "canonical_edge_record_from_storage_payload",
    "canonical_edge_explanation_from_storage_payload",
    "canonical_neighborhood_from_storage_payload",
    "canonical_edge_evidence_record_from_storage_payload",
    "raw_observation_reference_from_storage_payload",
)


@dataclass(frozen=True)
class CanonicalNodeRecord:
    canonical_key: str
    graph_key_version: int
    kind: str
    display_name: str
    confidence: str
    conflict: bool
    metadata: dict[str, Any]
    first_seen_run_id: int | None
    last_seen_run_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalEdgeRecord:
    source_key: str
    edge_kind: str
    target_key: str
    graph_key_version: int
    identity_metadata: dict[str, Any]
    identity_metadata_hash: str
    metadata: dict[str, Any]
    confidence: str
    conflict: bool
    first_seen_run_id: int | None
    last_seen_run_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalEdgeEvidenceRecord:
    evidence_key: str
    link_kind: str
    raw_observation: dict[str, Any]
    path: str
    start_line: int | None
    end_line: int | None
    extractor: str
    extractor_version: str
    confidence: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalEdgeExplanationRecord:
    edge: CanonicalEdgeRecord | None
    evidence: tuple[CanonicalEdgeEvidenceRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge": self.edge.to_dict() if self.edge is not None else None,
            "evidence": [record.to_dict() for record in self.evidence],
        }


@dataclass(frozen=True)
class CanonicalNeighborhoodRecord:
    center: CanonicalNodeRecord | None
    nodes: tuple[CanonicalNodeRecord, ...]
    edges: tuple[CanonicalEdgeRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "center": self.center.to_dict() if self.center is not None else None,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }


def canonical_node_record_from_storage_payload(payload: Any) -> CanonicalNodeRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed canonical node record")
    return CanonicalNodeRecord(
        canonical_key=payload_text(
            payload, "canonical_key", label="canonical node record"
        ),
        graph_key_version=payload_int(
            payload, "graph_key_version", label="canonical node record"
        ),
        kind=payload_text(payload, "kind", label="canonical node record"),
        display_name=payload_text(
            payload, "display_name", label="canonical node record"
        ),
        confidence=payload_text(
            payload, "confidence", label="canonical node record"
        ),
        conflict=payload_bool(payload, "conflict", label="canonical node record"),
        metadata=payload_json_object(
            payload, "metadata", label="canonical node record"
        ),
        first_seen_run_id=payload_optional_int(
            payload, "first_seen_run_id", label="canonical node record"
        ),
        last_seen_run_id=payload_optional_int(
            payload, "last_seen_run_id", label="canonical node record"
        ),
    )


def canonical_edge_record_from_storage_payload(payload: Any) -> CanonicalEdgeRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed canonical edge record")
    return CanonicalEdgeRecord(
        source_key=payload_text(
            payload, "source_key", label="canonical edge record"
        ),
        edge_kind=payload_text(
            payload, "edge_kind", label="canonical edge record"
        ),
        target_key=payload_text(
            payload, "target_key", label="canonical edge record"
        ),
        graph_key_version=payload_int(
            payload, "graph_key_version", label="canonical edge record"
        ),
        identity_metadata=payload_json_object(
            payload, "identity_metadata", label="canonical edge record"
        ),
        identity_metadata_hash=payload_text(
            payload, "identity_metadata_hash", label="canonical edge record"
        ),
        metadata=payload_json_object(
            payload, "metadata", label="canonical edge record"
        ),
        confidence=payload_text(
            payload, "confidence", label="canonical edge record"
        ),
        conflict=payload_bool(payload, "conflict", label="canonical edge record"),
        first_seen_run_id=payload_optional_int(
            payload, "first_seen_run_id", label="canonical edge record"
        ),
        last_seen_run_id=payload_optional_int(
            payload, "last_seen_run_id", label="canonical edge record"
        ),
    )


def canonical_edge_explanation_from_storage_payload(
    payload: Any,
) -> CanonicalEdgeExplanationRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed canonical edge explanation")
    edge_payload = payload.get("edge")
    if edge_payload is None:
        edge = None
    elif isinstance(edge_payload, dict):
        edge = canonical_edge_record_from_storage_payload(edge_payload)
    else:
        raise StorageSchemaError(
            "psql returned a malformed canonical edge explanation: edge"
        )
    evidence_payload = payload.get("evidence")
    if not isinstance(evidence_payload, list):
        raise StorageSchemaError(
            "psql returned a malformed canonical edge explanation: evidence"
        )
    return CanonicalEdgeExplanationRecord(
        edge=edge,
        evidence=tuple(
            canonical_edge_evidence_record_from_storage_payload(item)
            for item in evidence_payload
        ),
    )


def canonical_neighborhood_from_storage_payload(
    payload: Any,
) -> CanonicalNeighborhoodRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed canonical neighborhood")
    center_payload = payload.get("center")
    if center_payload is None:
        center = None
    elif isinstance(center_payload, dict):
        center = canonical_node_record_from_storage_payload(center_payload)
    else:
        raise StorageSchemaError(
            "psql returned a malformed canonical neighborhood: center"
        )
    nodes_payload = payload.get("nodes")
    edges_payload = payload.get("edges")
    if not isinstance(nodes_payload, list):
        raise StorageSchemaError(
            "psql returned a malformed canonical neighborhood: nodes"
        )
    if not isinstance(edges_payload, list):
        raise StorageSchemaError(
            "psql returned a malformed canonical neighborhood: edges"
        )
    return CanonicalNeighborhoodRecord(
        center=center,
        nodes=tuple(
            canonical_node_record_from_storage_payload(node_payload)
            for node_payload in nodes_payload
        ),
        edges=tuple(
            canonical_edge_record_from_storage_payload(edge_payload)
            for edge_payload in edges_payload
        ),
    )


def canonical_edge_evidence_record_from_storage_payload(
    payload: Any,
) -> CanonicalEdgeEvidenceRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError(
            "psql returned a malformed canonical edge evidence record"
        )
    return CanonicalEdgeEvidenceRecord(
        evidence_key=payload_text(
            payload, "evidence_key", label="canonical edge evidence record"
        ),
        link_kind=payload_text(
            payload, "link_kind", label="canonical edge evidence record"
        ),
        raw_observation=raw_observation_reference_from_storage_payload(
            payload.get("raw_observation")
        ),
        path=payload_text(payload, "path", label="canonical edge evidence record"),
        start_line=payload_optional_int(
            payload, "start_line", label="canonical edge evidence record"
        ),
        end_line=payload_optional_int(
            payload, "end_line", label="canonical edge evidence record"
        ),
        extractor=payload_text(
            payload, "extractor", label="canonical edge evidence record"
        ),
        extractor_version=payload_text(
            payload, "extractor_version", label="canonical edge evidence record"
        ),
        confidence=payload_text(
            payload, "confidence", label="canonical edge evidence record"
        ),
        metadata=payload_json_object(
            payload, "metadata", label="canonical edge evidence record"
        ),
    )


def raw_observation_reference_from_storage_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise StorageSchemaError(
            "psql returned a malformed canonical edge evidence record: "
            "raw_observation"
        )
    return {
        "run_id": payload_int(
            payload,
            "run_id",
            label="canonical edge evidence raw observation reference",
        ),
        "ordinal": payload_int(
            payload,
            "ordinal",
            label="canonical edge evidence raw observation reference",
        ),
        "payload_hash": payload_optional_text(
            payload,
            "payload_hash",
            label="canonical edge evidence raw observation reference",
        ),
        "kind": payload_text(
            payload,
            "kind",
            label="canonical edge evidence raw observation reference",
        ),
        "source_id": payload_text(
            payload,
            "source_id",
            label="canonical edge evidence raw observation reference",
        ),
    }
