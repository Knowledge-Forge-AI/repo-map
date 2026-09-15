"""Canonicalization dispatch state and fallback diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field

from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
    CanonicalizationResult,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.graph.keys import GRAPH_KEY_VERSION
from repomap_kg.observations.raw import RawObservation


@dataclass
class CanonicalizationState:
    nodes: dict[str, CanonicalNode] = field(default_factory=dict)
    edges: dict[str, CanonicalEdge] = field(default_factory=dict)
    evidence: list[CanonicalEvidence] = field(default_factory=list)
    node_evidence_links: list[CanonicalNodeEvidenceLink] = field(default_factory=list)
    edge_evidence_links: list[CanonicalEdgeEvidenceLink] = field(default_factory=list)
    diagnostics: list[CanonicalizationDiagnostic] = field(default_factory=list)


def append_unsupported_observation_diagnostic(
    diagnostics: list[CanonicalizationDiagnostic],
    observation: RawObservation,
    ordinal: int,
) -> None:
    diagnostics.append(
        CanonicalizationDiagnostic(
            severity="warning",
            category="unsupported_raw_observation_kind",
            message=f"raw observation kind is not supported: {observation.kind}",
            raw_observation_ordinal=ordinal,
            raw_source_id=observation.source_id,
            path=observation.path,
            field="kind",
            value=observation.kind,
        )
    )


def canonicalization_result_from_state(
    state: CanonicalizationState,
    *,
    raw_observation_count: int,
) -> CanonicalizationResult:
    return CanonicalizationResult(
        graph=CanonicalGraph(
            graph_key_version=GRAPH_KEY_VERSION,
            nodes=tuple(state.nodes.values()),
            edges=tuple(state.edges.values()),
            evidence=tuple(state.evidence),
            node_evidence_links=tuple(state.node_evidence_links),
            edge_evidence_links=tuple(state.edge_evidence_links),
            raw_observation_count=raw_observation_count,
        ),
        diagnostics=tuple(state.diagnostics),
    )
