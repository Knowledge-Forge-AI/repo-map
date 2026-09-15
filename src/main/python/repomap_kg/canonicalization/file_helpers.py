"""Shared canonicalization file-node helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization.records import CanonicalNode
from repomap_kg.canonicalization.value_helpers import (
    _append_distinct_json_values,
    _metadata_value_list,
    _stronger_confidence,
)
from repomap_kg.graph.keys import GRAPH_KEY_VERSION

FILE_METADATA_KEYS = (
    "language",
    "role",
    "content_hash",
    "executable",
    "generated",
    "binding_id",
    "binding_alias",
    "binding_role",
    "snapshot_id",
    "source_relative_path",
    "candidate_id",
)

FILE_CONFLICT_METADATA_KEYS = frozenset(
    (
        "language",
        "content_hash",
        "executable",
        "generated",
    )
)


def _upsert_file_node(
    nodes: dict[str, CanonicalNode],
    *,
    canonical_key: str,
    display_name: str,
    metadata: Mapping[str, Any],
    confidence: str,
) -> tuple[str, ...]:
    existing = nodes.get(canonical_key)
    if existing is None:
        nodes[canonical_key] = CanonicalNode(
            canonical_key=canonical_key,
            graph_key_version=GRAPH_KEY_VERSION,
            kind="file",
            display_name=display_name,
            metadata=dict(metadata),
            confidence=confidence,
            conflict=False,
        )
        return ()

    merged_metadata, conflict_fields = _merge_file_node_metadata(
        existing.metadata, metadata
    )
    nodes[canonical_key] = CanonicalNode(
        canonical_key=existing.canonical_key,
        graph_key_version=existing.graph_key_version,
        kind=existing.kind,
        display_name=existing.display_name,
        metadata=merged_metadata,
        confidence=_stronger_confidence(existing.confidence, confidence),
        conflict=existing.conflict or bool(conflict_fields),
    )
    return tuple(conflict_fields)


def _merge_file_node_metadata(
    existing: Mapping[str, Any], incoming: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    merged = dict(existing)
    conflict_fields: list[str] = []
    for key, value in incoming.items():
        if key not in merged:
            merged[key] = value
            continue

        current_values = _metadata_value_list(merged[key])
        incoming_values = _metadata_value_list(value)
        new_values = [
            incoming_value
            for incoming_value in incoming_values
            if incoming_value not in current_values
        ]
        if not new_values:
            continue

        merged[key] = _append_distinct_json_values(current_values, incoming_values)
        if key in FILE_CONFLICT_METADATA_KEYS:
            conflict_fields.append(key)
    return merged, conflict_fields
