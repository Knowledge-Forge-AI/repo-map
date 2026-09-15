"""Canonical graph adaptation for bounded Go observations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.dispatch import CanonicalizationState
from repomap_kg.canonicalization.evidence_helpers import _evidence_from_observation
from repomap_kg.canonicalization._go_context import GoCanonicalContext
from repomap_kg.canonicalization._go_context_model import is_repository_relative_path
from repomap_kg.canonicalization.node_edge_helpers import _upsert_edge, _upsert_node
from repomap_kg.canonicalization.records import (
    CanonicalEdgeEvidenceLink,
    CanonicalNodeEvidenceLink,
    canonical_edge_key,
)
from repomap_kg.graph.keys import GRAPH_KEY_VERSION
from repomap_kg.observations.raw import RawObservation


GO_EVIDENCE_OMIT_KEYS = frozenset(
    {
        "raw",
        "raw_source",
        "resolved_path",
        "owner_module_path",
        "owner_workspace_path",
        "source",
        "source_text",
        "text",
    }
)


def canonicalize_go_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    context: GoCanonicalContext,
    state: CanonicalizationState,
) -> bool:
    """Adapt one Go observation using repository-wide canonical context."""
    if not observation.kind.startswith("go."):
        return False
    if not is_repository_relative_path(observation.path):
        return True
    if observation.source_id in context.invalid_source_ids:
        return True

    evidence = _evidence_from_observation(
        observation,
        ordinal,
        metadata=_sanitize_go_metadata(observation.metadata),
    )
    state.evidence.append(evidence)

    for canonical_key in context.node_keys_by_source_id.get(observation.source_id, ()):
        claim = context.node_claims.get(canonical_key)
        if claim is None:
            continue
        _upsert_node(
            state.nodes,
            canonical_key=claim.canonical_key,
            kind=claim.kind,
            display_name=claim.display_name,
            metadata=claim.metadata,
            confidence=observation.confidence,
        )
        state.node_evidence_links.append(
            CanonicalNodeEvidenceLink(
                canonical_key=canonical_key,
                evidence_key=evidence.evidence_key,
                link_kind="observed",
            )
        )

    observed_edge_keys: set[str] = set()
    for claim in context.edge_claims_by_source_id.get(observation.source_id, ()):
        edge_key = canonical_edge_key(
            graph_key_version=GRAPH_KEY_VERSION,
            source_key=claim.source_key,
            kind=claim.kind,
            target_key=claim.target_key,
            identity_metadata=claim.identity_metadata,
        )
        _upsert_edge(
            state.edges,
            edge_key=edge_key,
            source_key=claim.source_key,
            kind=claim.kind,
            target_key=claim.target_key,
            identity_metadata=claim.identity_metadata,
            metadata=claim.metadata,
            confidence=observation.confidence,
        )
        stored_edge = state.edges[edge_key]
        state.edges[edge_key] = replace(
            stored_edge,
            metadata=_stable_go_metadata(stored_edge.metadata),
        )
        if edge_key not in observed_edge_keys:
            state.edge_evidence_links.append(
                CanonicalEdgeEvidenceLink(
                    edge_key=edge_key,
                    evidence_key=evidence.evidence_key,
                    link_kind="observed",
                )
            )
            observed_edge_keys.add(edge_key)
    return True


def finalize_go_canonicalization(
    *,
    context: GoCanonicalContext,
    state: CanonicalizationState,
) -> None:
    """Append bounded aggregate accounting after all Go evidence is adapted."""
    if (
        not context.node_claims
        and not context.diagnostics
        and not any(record.raw_kind.startswith("go.") for record in state.evidence)
    ):
        return

    go_node_keys = set(context.node_claims).intersection(state.nodes)
    go_edge_keys = {
        canonical_edge_key(
            graph_key_version=GRAPH_KEY_VERSION,
            source_key=claim.source_key,
            kind=claim.kind,
            target_key=claim.target_key,
            identity_metadata=claim.identity_metadata,
        )
        for claims in context.edge_claims_by_source_id.values()
        for claim in claims
    }.intersection(state.edges)
    go_evidence_keys = {
        record.evidence_key
        for record in state.evidence
        if record.raw_kind.startswith("go.")
    }
    evidence_link_count = sum(
        1
        for link in state.node_evidence_links
        if link.canonical_key in go_node_keys and link.evidence_key in go_evidence_keys
    ) + sum(
        1
        for link in state.edge_evidence_links
        if link.edge_key in go_edge_keys and link.evidence_key in go_evidence_keys
    )
    state.diagnostics.append(
        CanonicalizationDiagnostic(
            severity="info",
            category="go_canonical_accounting",
            message="bounded Go canonicalization accounting",
            value={
                "canonical_nodes": len(go_node_keys),
                "canonical_edges": len(go_edge_keys),
                "evidence_links": evidence_link_count,
                "duplicate_declaration_evidence": context.duplicate_declaration_evidence,
                "identity_collisions": context.identity_collisions,
                "unresolved_relationships": context.unresolved_relationships,
            },
        )
    )


def _sanitize_go_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _sanitize_go_metadata_value(item)
        for key, item in value.items()
        if key not in GO_EVIDENCE_OMIT_KEYS
    }


def _sanitize_go_metadata_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_go_metadata(value)
    if isinstance(value, tuple):
        return tuple(_sanitize_go_metadata_value(item) for item in value)
    if isinstance(value, list):
        return [_sanitize_go_metadata_value(item) for item in value]
    return value


def _stable_go_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _stable_go_metadata(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return tuple(
            sorted(
                (_stable_go_metadata(item) for item in value),
                key=_stable_go_metadata_sort_key,
            )
        )
    if isinstance(value, list):
        return sorted(
            (_stable_go_metadata(item) for item in value),
            key=_stable_go_metadata_sort_key,
        )
    return value


def _stable_go_metadata_sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
