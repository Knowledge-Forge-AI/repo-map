"""Shared canonicalization edge helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization.records import CanonicalEdge, canonical_edge_key
from repomap_kg.canonicalization.node_edge_helpers import _upsert_edge
from repomap_kg.graph.keys import GRAPH_KEY_VERSION


def _upsert_config_edge(
    edges: dict[str, CanonicalEdge],
    *,
    source_key: str,
    kind: str,
    target_key: str,
    metadata: Mapping[str, Any],
    confidence: str,
) -> str:
    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=metadata,
        confidence=confidence,
    )
    return edge_key


def _upsert_css_edge(
    edges: dict[str, CanonicalEdge],
    *,
    source_key: str,
    kind: str,
    target_key: str,
    metadata: Mapping[str, Any],
    confidence: str,
) -> str:
    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=metadata,
        confidence=confidence,
    )
    return edge_key
