"""Shared shell-family canonical edge construction helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization.edge_helpers import _upsert_config_edge
from repomap_kg.canonicalization.node_edge_helpers import _upsert_node
from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
)
from repomap_kg.observations.raw import RawObservation


def _append_two_node_edge(
    *,
    observation: RawObservation,
    evidence_record: CanonicalEvidence,
    source_key: str,
    source_kind: str,
    source_display: str,
    source_metadata: Mapping[str, Any],
    target_key: str,
    target_kind: str,
    target_display: str,
    target_metadata: Mapping[str, Any],
    edge_kind: str,
    edge_metadata: Mapping[str, Any],
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
) -> None:
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind=source_kind,
        display_name=source_display,
        metadata=source_metadata,
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=target_kind,
        display_name=target_display,
        metadata=target_metadata,
        confidence=observation.confidence,
    )
    node_evidence_links.extend(
        (
            CanonicalNodeEvidenceLink(
                canonical_key=source_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
        )
    )
    edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind=edge_kind,
        target_key=target_key,
        metadata=edge_metadata,
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )
