"""Structural row types for the retained staging families."""

from __future__ import annotations

from typing import Literal, Mapping, TypeAlias, TypedDict


StageFamily: TypeAlias = Literal[
    "files",
    "raw_observations",
    "canonical_nodes",
    "canonical_edges",
    "canonical_evidence",
    "canonical_node_evidence",
    "canonical_edge_evidence",
]
JsonObject: TypeAlias = Mapping[str, object]


class StageFileRow(TypedDict):
    stage_id: str
    family_ordinal: int
    path: str
    language: str
    role: str
    confidence: str
    content_hash: str | None
    executable: bool
    generated: bool
    metadata_json: JsonObject


class StageRawObservationRow(TypedDict):
    stage_id: str
    source_ordinal: int
    schema_version: int
    kind: str
    source_id: str
    path: str
    payload_json: JsonObject
    payload_hash: str


class StageCanonicalNodeRow(TypedDict):
    stage_id: str
    family_ordinal: int
    graph_key_version: int
    canonical_key: str
    kind: str
    display_name: str
    metadata_json: JsonObject
    confidence: str
    conflict: bool


class StageCanonicalEdgeRow(TypedDict):
    stage_id: str
    family_ordinal: int
    graph_key_version: int
    source_canonical_key: str
    edge_kind: str
    target_canonical_key: str
    identity_metadata_json: JsonObject
    identity_metadata_hash: str
    metadata_json: JsonObject
    confidence: str
    conflict: bool


class StageCanonicalEvidenceRow(TypedDict):
    stage_id: str
    family_ordinal: int
    graph_key_version: int
    evidence_key: str
    raw_observation_ordinal: int
    raw_schema_version: int
    raw_kind: str
    raw_source_id: str
    path: str
    start_line: int | None
    end_line: int | None
    extractor: str
    extractor_version: str
    confidence: str
    metadata_json: JsonObject


class StageCanonicalNodeEvidenceRow(TypedDict):
    stage_id: str
    family_ordinal: int
    graph_key_version: int
    canonical_key: str
    evidence_key: str
    link_kind: str


class StageCanonicalEdgeEvidenceRow(TypedDict):
    stage_id: str
    family_ordinal: int
    graph_key_version: int
    source_canonical_key: str
    edge_kind: str
    target_canonical_key: str
    identity_metadata_hash: str
    evidence_key: str
    link_kind: str
