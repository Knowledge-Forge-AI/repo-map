"""Canonicalization dispatch state and fallback diagnostics."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from common_lore_index.canonicalization.claim_guard import find_claim_refusals
from common_lore_index.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
    CanonicalizationResult,
)
from common_lore_index.canonicalization.diagnostics import CanonicalizationDiagnostic
from common_lore_index.graph.keys import GRAPH_KEY_VERSION
from common_lore_index.observations.raw import RawObservation


@dataclass
class CanonicalizationState:
    nodes: dict[str, CanonicalNode] = field(default_factory=dict)
    edges: dict[str, CanonicalEdge] = field(default_factory=dict)
    evidence: list[CanonicalEvidence] = field(default_factory=list)
    node_evidence_links: list[CanonicalNodeEvidenceLink] = field(default_factory=list)
    edge_evidence_links: list[CanonicalEdgeEvidenceLink] = field(default_factory=list)
    diagnostics: list[CanonicalizationDiagnostic] = field(default_factory=list)
    refused_claim_ordinals: frozenset[int] | None = None
    _unrefused_pairs: tuple[tuple[int, RawObservation], ...] = field(
        default=(), init=False, repr=False, compare=False
    )

    def refuse_capability_claims(
        self, observations: Sequence[RawObservation]
    ) -> tuple[RawObservation, ...]:
        """Record claim refusals once and return the observations left to dispatch."""

        if self.refused_claim_ordinals is not None:
            raise RuntimeError("capability claims were already checked")
        refusals = find_claim_refusals(observations)
        refused = frozenset(item.ordinal for item in refusals)
        self.refused_claim_ordinals = refused
        self.diagnostics.extend(item.diagnostic() for item in refusals)
        self._unrefused_pairs = tuple(
            (ordinal, item) for ordinal, item in enumerate(observations) if ordinal not in refused
        )
        return tuple(item for _, item in self._unrefused_pairs)

    def unrefused(
        self, observations: Sequence[RawObservation]
    ) -> Iterator[tuple[int, RawObservation]]:
        """Return ``(ordinal, observation)`` pairs, skipping refused claims.

        Ordinals stay those of the original raw sequence, so evidence keys and
        diagnostics for admitted observations are unchanged. The checked input
        is cached; the argument remains for compatibility and is not replayed.
        """

        refused = self.refused_claim_ordinals
        if refused is None:
            raise RuntimeError("capability claims must be checked before dispatch")
        return iter(self._unrefused_pairs)


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
