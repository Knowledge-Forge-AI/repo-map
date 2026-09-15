"""Normalize raw observations into canonical graph-shaped records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from repomap_kg.observations.raw import RawObservation


@dataclass(frozen=True)
class NormalizedNode:
    stable_key: str
    kind: str
    name: str
    path: str
    start_line: int | None
    end_line: int | None
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedEdge:
    stable_key: str
    src_node_key: str
    dst_node_key: str
    kind: str
    confidence: str
    evidence_key: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceRecord:
    stable_key: str
    path: str
    start_line: int | None
    end_line: int | None
    extractor: str
    extractor_version: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedGraph:
    nodes: tuple[NormalizedNode, ...]
    edges: tuple[NormalizedEdge, ...]
    evidence: tuple[EvidenceRecord, ...]
    raw_observations: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": {
                "raw_observations": self.raw_observations,
                "nodes": len(self.nodes),
                "edges": len(self.edges),
                "evidence": len(self.evidence),
            },
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "evidence": [record.to_dict() for record in self.evidence],
        }


def normalize_observation(observation: RawObservation) -> NormalizedGraph:
    return normalize_observations([observation])


def normalize_observations(observations: list[RawObservation]) -> NormalizedGraph:
    nodes: dict[str, NormalizedNode] = {}
    edges: dict[str, NormalizedEdge] = {}
    evidence: dict[str, EvidenceRecord] = {}

    for observation in observations:
        node = node_from_observation(observation)
        evidence_record = evidence_from_observation(observation)
        nodes[node.stable_key] = node
        evidence[evidence_record.stable_key] = evidence_record
        if observation.target is not None:
            edge = edge_from_observation(observation, node, evidence_record)
            edges[edge.stable_key] = edge

    return NormalizedGraph(
        nodes=tuple(nodes.values()),
        edges=tuple(edges.values()),
        evidence=tuple(evidence.values()),
        raw_observations=len(observations),
    )


def node_from_observation(observation: RawObservation) -> NormalizedNode:
    stable_key = f"node:{observation.path}:{observation.kind}:{observation.source_id}"
    return NormalizedNode(
        stable_key=stable_key,
        kind=observation.kind,
        name=observation.name or observation.source_id,
        path=observation.path,
        start_line=observation.start_line,
        end_line=observation.end_line,
        metadata=dict(observation.metadata),
    )


def evidence_from_observation(observation: RawObservation) -> EvidenceRecord:
    start_line = observation.start_line or 0
    end_line = observation.end_line or 0
    stable_key = (
        f"evidence:{observation.path}:{start_line}-{end_line}:"
        f"{observation.extractor}:{observation.source_id}"
    )
    return EvidenceRecord(
        stable_key=stable_key,
        path=observation.path,
        start_line=observation.start_line,
        end_line=observation.end_line,
        extractor=observation.extractor,
        extractor_version=observation.extractor_version,
        metadata={"raw_source_id": observation.source_id},
    )


def edge_from_observation(
    observation: RawObservation, node: NormalizedNode, evidence: EvidenceRecord
) -> NormalizedEdge:
    stable_key = f"edge:{node.stable_key}:{observation.kind}:{observation.target}"
    return NormalizedEdge(
        stable_key=stable_key,
        src_node_key=node.stable_key,
        dst_node_key=observation.target or "",
        kind=observation.kind,
        confidence=observation.confidence,
        evidence_key=evidence.stable_key,
        metadata={},
    )
