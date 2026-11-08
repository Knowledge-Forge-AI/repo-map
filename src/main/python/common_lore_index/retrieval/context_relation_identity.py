"""Canonical relation identity shared by bounded context readers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def relation_identity(
    source_canonical_key: Any,
    edge_kind: Any,
    target_canonical_key: Any,
    identity_metadata_hash: Any,
) -> tuple[str, str, str, str]:
    """Return the W4 four-part relation identity used for expansion deduplication."""
    return (
        str(source_canonical_key),
        str(edge_kind),
        str(target_canonical_key),
        str(identity_metadata_hash),
    )


def relation_identity_from_edge(edge: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return a relation identity from the existing edge-record shape."""
    return relation_identity(
        edge["source_canonical_key"],
        edge["edge_kind"],
        edge["target_canonical_key"],
        edge["edge_key"],
    )


def incident_edge_record(
    edge: Mapping[str, Any], *, edge_kind_priority: int | None = None
) -> dict[str, Any]:
    """Normalize the shared incident-edge fields without changing wire names."""
    result: dict[str, Any] = {
        "direction": str(edge["direction"]),
        "direction_rank": int(edge["direction_rank"]),
        "edge_key": str(edge["edge_key"]),
        "edge_kind": str(edge["edge_kind"]),
        "source_canonical_key": str(edge["source_canonical_key"]),
        "target_canonical_key": str(edge["target_canonical_key"]),
        "confidence": str(edge["confidence"]),
        "conflict": bool(edge["conflict"]),
        "first_seen_run_id": (
            None if edge["first_seen_run_id"] is None else int(edge["first_seen_run_id"])
        ),
        "last_seen_run_id": (
            None if edge["last_seen_run_id"] is None else int(edge["last_seen_run_id"])
        ),
        "neighbor_id": int(edge["neighbor_id"]),
        "neighbor_canonical_key": str(edge["neighbor_canonical_key"]),
        "neighbor_kind": str(edge["neighbor_kind"]),
        "neighbor_display_name": edge["neighbor_display_name"],
        "neighbor_first_seen_run_id": (
            None
            if edge["neighbor_first_seen_run_id"] is None
            else int(edge["neighbor_first_seen_run_id"])
        ),
        "neighbor_last_seen_run_id": (
            None
            if edge["neighbor_last_seen_run_id"] is None
            else int(edge["neighbor_last_seen_run_id"])
        ),
    }
    if edge_kind_priority is not None:
        result["edge_kind_priority"] = int(edge_kind_priority)
    return result
