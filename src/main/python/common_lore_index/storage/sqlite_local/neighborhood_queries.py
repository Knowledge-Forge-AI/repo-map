"""Opt-in bounded configured neighborhood queries over SQLite Local.

Provides configured neighborhood read operations with optional opt-in limits
for node and edge dimensions. When both limits are omitted, calls delegate
directly to canonical_neighborhood, preserving default behavior and return types.
When one or both limits are specified, independent candidate windows are fetched
with at most limit + 1 records to determine bounds and completeness.

The canonical query's opt-in incident-selective path owns membership, ordering
and SQL windows. It uses existing endpoint indexes before combining candidates;
SQLite may materialize and sort incident keys. Limits bound fetched records,
not incident-degree scan/sort work. The caller owns the transaction.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from common_lore_index.storage.canonical_readback_rows import CanonicalNeighborhoodRecord
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.jsonable_rows import canonical_neighborhood_to_jsonable
from common_lore_index.storage.sqlite_local.queries import canonical_neighborhood

__all__ = ("configured_neighborhood",)


def _validate_limit(name: str, value: int | None) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not (1 <= value <= 100):
        raise StorageSchemaError(f"{name} must be an integer between 1 and 100")
    return value


def configured_neighborhood(
    connection: sqlite3.Connection,
    *,
    node: str,
    direction: str,
    depth: int,
    graph_key_version: int,
    node_limit: int | None = None,
    edge_limit: int | None = None,
) -> CanonicalNeighborhoodRecord | dict[str, Any]:
    """Read a configured neighborhood with optional independent dimension bounds.

    When both limits are None, delegates to canonical_neighborhood preserving
    default semantics and CanonicalNeighborhoodRecord return type. When either
    limit is provided, validates parameters, fetches candidate records bounded
    by limit + 1, and returns a dictionary with deserialized center, nodes,
    edges, and a bounds report.
    """
    if node_limit is None and edge_limit is None:
        return canonical_neighborhood(
            connection,
            node=node,
            direction=direction,
            depth=depth,
            graph_key_version=graph_key_version,
            node_limit=None,
            node_offset=0,
            edge_limit=None,
            edge_offset=0,
        )

    safe_node_limit = _validate_limit("node_limit", node_limit)
    safe_edge_limit = _validate_limit("edge_limit", edge_limit)
    record = canonical_neighborhood(
        connection,
        node=node,
        direction=direction,
        depth=depth,
        graph_key_version=graph_key_version,
        node_limit=None if safe_node_limit is None else safe_node_limit + 1,
        node_offset=0,
        edge_limit=None if safe_edge_limit is None else safe_edge_limit + 1,
        edge_offset=0,
        incident_selective=True,
    )
    base = canonical_neighborhood_to_jsonable(record)
    bounds = {}
    for name, limit in (("nodes", safe_node_limit), ("edges", safe_edge_limit)):
        has_more = limit is not None and len(base[name]) > limit
        if limit is not None:
            base[name] = base[name][:limit]
        bounds[name] = {
            "requested_limit": limit,
            "returned_count": len(base[name]),
            "has_more": has_more,
            "completeness": "truncated" if has_more else "complete",
        }
    return {**base, "bounds": bounds}
