"""In-memory canonical graph records and deterministic serialization."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from repomap_kg.canonicalization.diagnostics import (
    CanonicalizationDiagnostic,
    diagnostic_sort_key,
    diagnostics_have_errors,
)


@dataclass(frozen=True)
class CanonicalNode:
    canonical_key: str
    graph_key_version: int
    kind: str
    display_name: str
    metadata: Mapping[str, Any]
    confidence: str
    conflict: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_key": self.canonical_key,
            "graph_key_version": self.graph_key_version,
            "kind": self.kind,
            "display_name": self.display_name,
            "metadata": _canonicalize_metadata(self.metadata),
            "confidence": self.confidence,
            "conflict": self.conflict,
        }


@dataclass(frozen=True)
class CanonicalEdge:
    edge_key: str
    graph_key_version: int
    source_key: str
    kind: str
    target_key: str
    identity_metadata: Mapping[str, Any]
    metadata: Mapping[str, Any]
    confidence: str
    conflict: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_key": self.edge_key,
            "graph_key_version": self.graph_key_version,
            "source_key": self.source_key,
            "kind": self.kind,
            "target_key": self.target_key,
            "identity_metadata": _canonicalize_metadata(self.identity_metadata),
            "metadata": _canonicalize_metadata(self.metadata),
            "confidence": self.confidence,
            "conflict": self.conflict,
        }


@dataclass(frozen=True)
class CanonicalEvidence:
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
    metadata: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_key": self.evidence_key,
            "raw_observation_ordinal": self.raw_observation_ordinal,
            "raw_schema_version": self.raw_schema_version,
            "raw_kind": self.raw_kind,
            "raw_source_id": self.raw_source_id,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "extractor": self.extractor,
            "extractor_version": self.extractor_version,
            "confidence": self.confidence,
            "metadata": _canonicalize_metadata(self.metadata),
        }


@dataclass(frozen=True)
class CanonicalNodeEvidenceLink:
    canonical_key: str
    evidence_key: str
    link_kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_key": self.canonical_key,
            "evidence_key": self.evidence_key,
            "link_kind": self.link_kind,
        }


@dataclass(frozen=True)
class CanonicalEdgeEvidenceLink:
    edge_key: str
    evidence_key: str
    link_kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_key": self.edge_key,
            "evidence_key": self.evidence_key,
            "link_kind": self.link_kind,
        }


@dataclass(frozen=True)
class CanonicalGraph:
    graph_key_version: int
    nodes: tuple[CanonicalNode, ...]
    edges: tuple[CanonicalEdge, ...]
    evidence: tuple[CanonicalEvidence, ...]
    node_evidence_links: tuple[CanonicalNodeEvidenceLink, ...]
    edge_evidence_links: tuple[CanonicalEdgeEvidenceLink, ...]
    raw_observation_count: int

    @classmethod
    def empty(cls, raw_observation_count: int = 0) -> CanonicalGraph:
        return cls(
            graph_key_version=1,
            nodes=(),
            edges=(),
            evidence=(),
            node_evidence_links=(),
            edge_evidence_links=(),
            raw_observation_count=raw_observation_count,
        )


@dataclass(frozen=True)
class CanonicalizationResult:
    graph: CanonicalGraph
    diagnostics: tuple[CanonicalizationDiagnostic, ...] = ()
    ok: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ok", not diagnostics_have_errors(self.diagnostics))

    def to_dict(self) -> dict[str, Any]:
        diagnostics = tuple(sorted(self.diagnostics, key=diagnostic_sort_key))
        return {
            "graph_key_version": self.graph.graph_key_version,
            "ok": self.ok,
            "summary": self._summary(diagnostics),
            "nodes": [
                node.to_dict() for node in sorted(self.graph.nodes, key=_node_sort_key)
            ],
            "edges": [
                edge.to_dict() for edge in sorted(self.graph.edges, key=_edge_sort_key)
            ],
            "evidence": [
                record.to_dict()
                for record in sorted(self.graph.evidence, key=_evidence_sort_key)
            ],
            "node_evidence_links": [
                link.to_dict()
                for link in sorted(
                    self.graph.node_evidence_links, key=_node_link_sort_key
                )
            ],
            "edge_evidence_links": [
                link.to_dict()
                for link in sorted(
                    self.graph.edge_evidence_links, key=_edge_link_sort_key
                )
            ],
            "diagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def _summary(
        self, diagnostics: tuple[CanonicalizationDiagnostic, ...]
    ) -> dict[str, int]:
        return {
            "raw_observations": self.graph.raw_observation_count,
            "nodes": len(self.graph.nodes),
            "edges": len(self.graph.edges),
            "evidence": len(self.graph.evidence),
            "node_evidence_links": len(self.graph.node_evidence_links),
            "edge_evidence_links": len(self.graph.edge_evidence_links),
            "diagnostics": len(diagnostics),
            "errors": sum(1 for item in diagnostics if item.severity == "error"),
            "warnings": sum(1 for item in diagnostics if item.severity == "warning"),
            "infos": sum(1 for item in diagnostics if item.severity == "info"),
        }


def canonical_edge_key(
    *,
    graph_key_version: int,
    source_key: str,
    kind: str,
    target_key: str,
    identity_metadata: Mapping[str, Any],
) -> str:
    identity = {
        "graph_key_version": graph_key_version,
        "source_key": source_key,
        "kind": kind,
        "target_key": target_key,
        "identity_metadata": _canonicalize_metadata(identity_metadata),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"canonical-edge:{digest}"


def _canonicalize_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize_metadata(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, tuple):
        return [_canonicalize_metadata(item) for item in value]
    if isinstance(value, list):
        return [_canonicalize_metadata(item) for item in value]
    return value


def _node_sort_key(node: CanonicalNode) -> tuple[object, ...]:
    return (node.graph_key_version, node.canonical_key)


def _edge_sort_key(edge: CanonicalEdge) -> tuple[object, ...]:
    return (
        edge.graph_key_version,
        edge.source_key,
        edge.kind,
        edge.target_key,
        json.dumps(
            _canonicalize_metadata(edge.identity_metadata),
            sort_keys=True,
            separators=(",", ":"),
        ),
        edge.edge_key,
    )


def _evidence_sort_key(evidence: CanonicalEvidence) -> tuple[object, ...]:
    return (evidence.raw_observation_ordinal, evidence.evidence_key)


def _node_link_sort_key(link: CanonicalNodeEvidenceLink) -> tuple[str, str, str]:
    return (link.canonical_key, link.evidence_key, link.link_kind)


def _edge_link_sort_key(link: CanonicalEdgeEvidenceLink) -> tuple[str, str, str]:
    return (link.edge_key, link.evidence_key, link.link_kind)
