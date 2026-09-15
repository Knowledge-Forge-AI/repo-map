"""Raw observation and canonical storage write rows."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.canonicalization.records import CanonicalizationResult
from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.row_helpers import (
    identity_metadata_hash,
    raw_observation_payload_hash,
)

__all__ = (
    "RawObservationRow",
    "CanonicalNodeRow",
    "CanonicalEdgeRow",
    "CanonicalEvidenceRow",
    "CanonicalNodeEvidenceLinkRow",
    "CanonicalEdgeEvidenceLinkRow",
    "CanonicalLoadRows",
    "PreparedCanonicalLoad",
    "raw_observation_rows_from_observations",
    "canonical_rows_from_result",
    "canonical_edge_link_row",
)


@dataclass(frozen=True)
class RawObservationRow:
    ordinal: int
    schema_version: int
    kind: str
    source_id: str
    path: str
    payload_json: dict[str, Any]
    payload_hash: str


@dataclass(frozen=True)
class CanonicalNodeRow:
    graph_key_version: int
    canonical_key: str
    kind: str
    display_name: str
    metadata_json: dict[str, Any]
    confidence: str
    conflict: bool


@dataclass(frozen=True)
class CanonicalEdgeRow:
    edge_key: str
    graph_key_version: int
    source_key: str
    edge_kind: str
    target_key: str
    identity_metadata_json: dict[str, Any]
    identity_metadata_hash: str
    metadata_json: dict[str, Any]
    confidence: str
    conflict: bool


@dataclass(frozen=True)
class CanonicalEvidenceRow:
    evidence_key: str
    graph_key_version: int
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
    metadata_json: dict[str, Any]


@dataclass(frozen=True)
class CanonicalNodeEvidenceLinkRow:
    canonical_key: str
    evidence_key: str
    link_kind: str


@dataclass(frozen=True)
class CanonicalEdgeEvidenceLinkRow:
    graph_key_version: int
    source_key: str
    edge_kind: str
    target_key: str
    identity_metadata_hash: str
    evidence_key: str
    link_kind: str


@dataclass(frozen=True)
class CanonicalLoadRows:
    nodes: tuple[CanonicalNodeRow, ...]
    edges: tuple[CanonicalEdgeRow, ...]
    evidence: tuple[CanonicalEvidenceRow, ...]
    node_evidence_links: tuple[CanonicalNodeEvidenceLinkRow, ...]
    edge_evidence_links: tuple[CanonicalEdgeEvidenceLinkRow, ...]


@dataclass(frozen=True)
class PreparedCanonicalLoad:
    result: CanonicalizationResult
    raw_rows: tuple[RawObservationRow, ...]
    canonical_rows: CanonicalLoadRows


def raw_observation_rows_from_observations(
    observations: Sequence[RawObservation],
) -> tuple[RawObservationRow, ...]:
    return tuple(_iter_raw_observation_rows(observations))


def _iter_raw_observation_rows(
    observations: Iterable[RawObservation],
) -> Iterator[RawObservationRow]:
    for ordinal, observation in enumerate(observations):
        yield RawObservationRow(
            ordinal=ordinal,
            schema_version=observation.schema_version,
            kind=observation.kind,
            source_id=observation.source_id,
            path=observation.path,
            payload_json=observation.to_dict(),
            payload_hash=raw_observation_payload_hash(observation),
        )


def canonical_rows_from_result(result: CanonicalizationResult) -> CanonicalLoadRows:
    edges_by_key = {edge.edge_key: edge for edge in result.graph.edges}
    return CanonicalLoadRows(
        nodes=tuple(_iter_canonical_node_rows(result)),
        edges=tuple(_iter_canonical_edge_rows(result)),
        evidence=tuple(_iter_canonical_evidence_rows(result)),
        node_evidence_links=tuple(_iter_canonical_node_evidence_rows(result)),
        edge_evidence_links=tuple(
            _iter_canonical_edge_evidence_rows(result, edges_by_key)
        ),
    )


def _iter_canonical_node_rows(
    result: CanonicalizationResult,
) -> Iterator[CanonicalNodeRow]:
    for node in result.graph.nodes:
        yield CanonicalNodeRow(
            graph_key_version=node.graph_key_version,
            canonical_key=node.canonical_key,
            kind=node.kind,
            display_name=node.display_name,
            metadata_json=dict(node.metadata),
            confidence=node.confidence,
            conflict=node.conflict,
        )


def _iter_canonical_edge_rows(
    result: CanonicalizationResult,
) -> Iterator[CanonicalEdgeRow]:
    for edge in result.graph.edges:
        yield CanonicalEdgeRow(
            edge_key=edge.edge_key,
            graph_key_version=edge.graph_key_version,
            source_key=edge.source_key,
            edge_kind=edge.kind,
            target_key=edge.target_key,
            identity_metadata_json=dict(edge.identity_metadata),
            identity_metadata_hash=identity_metadata_hash(edge.identity_metadata),
            metadata_json=dict(edge.metadata),
            confidence=edge.confidence,
            conflict=edge.conflict,
        )


def _iter_canonical_evidence_rows(
    result: CanonicalizationResult,
) -> Iterator[CanonicalEvidenceRow]:
    for evidence in result.graph.evidence:
        yield CanonicalEvidenceRow(
            evidence_key=evidence.evidence_key,
            graph_key_version=result.graph.graph_key_version,
            raw_observation_ordinal=evidence.raw_observation_ordinal,
            raw_schema_version=evidence.raw_schema_version,
            raw_kind=evidence.raw_kind,
            raw_source_id=evidence.raw_source_id,
            path=evidence.path,
            start_line=evidence.start_line,
            end_line=evidence.end_line,
            extractor=evidence.extractor,
            extractor_version=evidence.extractor_version,
            confidence=evidence.confidence,
            metadata_json=dict(evidence.metadata),
        )


def _iter_canonical_node_evidence_rows(
    result: CanonicalizationResult,
) -> Iterator[CanonicalNodeEvidenceLinkRow]:
    for link in result.graph.node_evidence_links:
        yield CanonicalNodeEvidenceLinkRow(
            canonical_key=link.canonical_key,
            evidence_key=link.evidence_key,
            link_kind=link.link_kind,
        )


def _iter_canonical_edge_evidence_rows(
    result: CanonicalizationResult,
    edges_by_key,
) -> Iterator[CanonicalEdgeEvidenceLinkRow]:
    for link in result.graph.edge_evidence_links:
        yield canonical_edge_link_row(link, edges_by_key)


def canonical_edge_link_row(
    link,
    edges_by_key,
) -> CanonicalEdgeEvidenceLinkRow:
    edge = edges_by_key[link.edge_key]
    return CanonicalEdgeEvidenceLinkRow(
        graph_key_version=edge.graph_key_version,
        source_key=edge.source_key,
        edge_kind=edge.kind,
        target_key=edge.target_key,
        identity_metadata_hash=identity_metadata_hash(edge.identity_metadata),
        evidence_key=link.evidence_key,
        link_kind=link.link_kind,
    )


def prepare_canonical_load(
    observations: Sequence[RawObservation],
    *,
    repository_scope: str | None = None,
) -> PreparedCanonicalLoad:
    result = canonicalize_observations(
        observations,
        repository_scope=repository_scope,
    )
    raw_rows = raw_observation_rows_from_observations(observations)
    canonical_rows = (
        canonical_rows_from_result(result)
        if result.ok
        else CanonicalLoadRows((), (), (), (), ())
    )
    return PreparedCanonicalLoad(
        result=result,
        raw_rows=raw_rows,
        canonical_rows=canonical_rows,
    )


def canonicalization_error_message(result: CanonicalizationResult) -> str:
    messages = "; ".join(
        diagnostic.message
        for diagnostic in result.diagnostics
        if diagnostic.severity == "error"
    )
    return messages or "unknown canonicalization error"
