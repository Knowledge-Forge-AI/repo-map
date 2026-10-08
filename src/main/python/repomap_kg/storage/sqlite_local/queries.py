"""Canonical read operations over one accepted SQLite Local graph.

Every function runs inside the caller's :func:`read_transaction`, uses bound
parameters only, and returns the same records the PostgreSQL canonical query
owners return, decoded through the maintained
``canonical_*_from_storage_payload`` decoders. Ordering matches the
PostgreSQL owners column for column; SQLite's BINARY collation equals
PostgreSQL's ``C`` byte order. Search, summary and status reads live in
``storage.sqlite_local.investigation_queries``.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from repomap_kg.storage.canonical_readback_rows import (
    CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    canonical_edge_explanation_from_storage_payload,
    canonical_edge_record_from_storage_payload,
    canonical_neighborhood_from_storage_payload,
    canonical_node_record_from_storage_payload,
)
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.sql_core import (
    canonical_file_path_prefix,
    positive_limit,
    require_supported_graph_key_version,
)
from repomap_kg.storage.sqlite_local.schema import PUBLICATION_ABSENT, LocalStoreError

_NODE = (
    "canonical_nodes.canonical_key, canonical_nodes.graph_key_version, canonical_nodes.kind, "
    "canonical_nodes.display_name, canonical_nodes.confidence, canonical_nodes.conflict, "
    "canonical_nodes.metadata_json, canonical_nodes.first_seen_run_id, "
    "canonical_nodes.last_seen_run_id"
)
_EDGE = (
    "canonical_edges.source_canonical_key, canonical_edges.edge_kind, "
    "canonical_edges.target_canonical_key, canonical_edges.graph_key_version, "
    "canonical_edges.identity_metadata_json, canonical_edges.identity_metadata_hash, "
    "canonical_edges.metadata_json, canonical_edges.confidence, canonical_edges.conflict, "
    "canonical_edges.first_seen_run_id, canonical_edges.last_seen_run_id"
)
_EDGE_ORDER = (
    "canonical_edges.source_canonical_key, canonical_edges.edge_kind, "
    "canonical_edges.target_canonical_key, canonical_edges.identity_metadata_hash"
)


def require_accepted_publication(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT generation FROM accepted_publication").fetchone()
    if row is None:
        raise LocalStoreError(PUBLICATION_ABSENT)
    return int(row[0])


def _window(limit: int | None, offset: int) -> tuple[int, int]:
    """Validate a window exactly as the PostgreSQL pagination owner does."""
    if limit is None:
        if int(offset) != 0:
            raise StorageSchemaError("limit is required when offset is non-zero")
        return -1, 0
    safe_limit = positive_limit(limit)
    try:
        safe_offset = int(offset)
    except (TypeError, ValueError) as error:
        raise StorageSchemaError("offset must be a non-negative integer") from error
    if safe_offset < 0:
        raise StorageSchemaError("offset must be a non-negative integer")
    return safe_limit, safe_offset


def node_payload(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    return {
        "canonical_key": row[0],
        "graph_key_version": row[1],
        "kind": row[2],
        "display_name": row[3],
        "confidence": row[4],
        "conflict": bool(row[5]),
        "metadata": json.loads(row[6]),
        "first_seen_run_id": row[7],
        "last_seen_run_id": row[8],
    }


def _edge_payload(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    return {
        "source_key": row[0],
        "edge_kind": row[1],
        "target_key": row[2],
        "graph_key_version": row[3],
        "identity_metadata": json.loads(row[4]),
        "identity_metadata_hash": row[5],
        "metadata": json.loads(row[6]),
        "confidence": row[7],
        "conflict": bool(row[8]),
        "first_seen_run_id": row[9],
        "last_seen_run_id": row[10],
    }


def canonical_nodes(
    connection: sqlite3.Connection,
    *,
    kind: str | None,
    canonical_key: str | None,
    path_prefix: str | None,
    graph_key_version: int,
    limit: int | None,
    offset: int,
) -> tuple[CanonicalNodeRecord, ...]:
    require_supported_graph_key_version(graph_key_version)
    require_accepted_publication(connection)
    filters = ["canonical_nodes.graph_key_version = ?"]
    params: list[object] = [graph_key_version]
    if kind is not None:
        filters.append("canonical_nodes.kind = ?")
        params.append(kind)
    if canonical_key is not None:
        filters.append("canonical_nodes.canonical_key = ?")
        params.append(canonical_key)
    if path_prefix is not None:
        prefix = canonical_file_path_prefix(path_prefix)
        filters.append("substr(canonical_nodes.canonical_key, 1, length(?)) = ?")
        params.extend((prefix, prefix))
    safe_limit, safe_offset = _window(limit, offset)
    rows = connection.execute(
        f"SELECT {_NODE} FROM canonical_nodes WHERE {' AND '.join(filters)} "
        "ORDER BY canonical_nodes.canonical_key LIMIT ? OFFSET ?",
        (*params, safe_limit, safe_offset),
    ).fetchall()
    return tuple(canonical_node_record_from_storage_payload(node_payload(row)) for row in rows)


def canonical_edges(
    connection: sqlite3.Connection,
    *,
    kind: str | None,
    source_key: str | None,
    target_key: str | None,
    graph_key_version: int,
    limit: int | None,
    offset: int,
) -> tuple[CanonicalEdgeRecord, ...]:
    require_supported_graph_key_version(graph_key_version)
    require_accepted_publication(connection)
    filters = ["canonical_edges.graph_key_version = ?"]
    params: list[object] = [graph_key_version]
    for column, value in (
        ("edge_kind", kind),
        ("source_canonical_key", source_key),
        ("target_canonical_key", target_key),
    ):
        if value is not None:
            filters.append(f"canonical_edges.{column} = ?")
            params.append(value)
    safe_limit, safe_offset = _window(limit, offset)
    rows = connection.execute(
        f"SELECT {_EDGE} FROM canonical_edges WHERE {' AND '.join(filters)} "
        f"ORDER BY {_EDGE_ORDER} LIMIT ? OFFSET ?",
        (*params, safe_limit, safe_offset),
    ).fetchall()
    return tuple(canonical_edge_record_from_storage_payload(_edge_payload(row)) for row in rows)


def canonical_edge_explanation(
    connection: sqlite3.Connection,
    *,
    source_key: str,
    kind: str,
    target_key: str,
    identity_metadata_hash: str,
    graph_key_version: int,
    evidence_limit: int | None,
    evidence_offset: int,
) -> CanonicalEdgeExplanationRecord:
    require_supported_graph_key_version(graph_key_version)
    require_accepted_publication(connection)
    safe_limit, safe_offset = _window(evidence_limit, evidence_offset)
    edge_row = connection.execute(
        f"SELECT canonical_edges.id, {_EDGE} FROM canonical_edges "
        "WHERE canonical_edges.graph_key_version = ? AND canonical_edges.source_canonical_key = ? "
        "AND canonical_edges.edge_kind = ? AND canonical_edges.target_canonical_key = ? "
        "AND canonical_edges.identity_metadata_hash = ? LIMIT 1",
        (graph_key_version, source_key, kind, target_key, identity_metadata_hash),
    ).fetchone()
    evidence: list[dict[str, Any]] = []
    if edge_row is not None:
        rows = connection.execute(
            "SELECT evidence.evidence_key, link.link_kind, evidence.run_id, "
            "evidence.raw_observation_ordinal, raw.payload_hash, "
            "coalesce(raw.kind, evidence.raw_kind), "
            "coalesce(raw.source_id, evidence.raw_source_id), evidence.path, "
            "evidence.start_line, evidence.end_line, evidence.extractor, "
            "evidence.extractor_version, evidence.confidence, evidence.metadata_json "
            "FROM canonical_edge_evidence link "
            "JOIN canonical_evidence evidence ON evidence.id = link.canonical_evidence_id "
            "LEFT JOIN raw_observations raw ON raw.run_id = evidence.run_id "
            "AND raw.ordinal = evidence.raw_observation_ordinal "
            "WHERE link.canonical_edge_id = ? "
            "ORDER BY evidence.run_id, evidence.raw_observation_ordinal, "
            "evidence.evidence_key, link.link_kind LIMIT ? OFFSET ?",
            (edge_row[0], safe_limit, safe_offset),
        ).fetchall()
        evidence = [
            {
                "evidence_key": row[0],
                "link_kind": row[1],
                "raw_observation": {
                    "run_id": row[2],
                    "ordinal": row[3],
                    "payload_hash": row[4],
                    "kind": row[5],
                    "source_id": row[6],
                },
                "path": row[7],
                "start_line": row[8],
                "end_line": row[9],
                "extractor": row[10],
                "extractor_version": row[11],
                "confidence": row[12],
                "metadata": json.loads(row[13]),
            }
            for row in rows
        ]
    return canonical_edge_explanation_from_storage_payload(
        {
            "edge": None if edge_row is None else _edge_payload(edge_row[1:]),
            "evidence": evidence,
        }
    )


def canonical_neighborhood(
    connection: sqlite3.Connection,
    *,
    node: str,
    direction: str,
    depth: int,
    graph_key_version: int,
    node_limit: int | None,
    node_offset: int,
    edge_limit: int | None,
    edge_offset: int,
) -> CanonicalNeighborhoodRecord:
    if depth != 1:
        raise StorageSchemaError("storage neighborhood only supports depth 1")
    require_supported_graph_key_version(graph_key_version)
    if direction not in {"both", "in", "out"}:
        raise StorageSchemaError("neighborhood direction must be one of both, in, out")
    require_accepted_publication(connection)
    node_window = _window(node_limit, node_offset)
    edge_window = _window(edge_limit, edge_offset)
    center = connection.execute(
        f"SELECT {_NODE} FROM canonical_nodes WHERE canonical_nodes.graph_key_version = ? "
        "AND canonical_nodes.canonical_key = ?",
        (graph_key_version, node),
    ).fetchone()
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    if center is not None:
        sides = []
        if direction in {"both", "out"}:
            sides.append("canonical_edges.source_canonical_key = :node")
        if direction in {"both", "in"}:
            sides.append("canonical_edges.target_canonical_key = :node")
        edge_filter = (
            f"canonical_edges.graph_key_version = :version AND ({' OR '.join(sides)})"
        )
        params = {"version": graph_key_version, "node": node}
        edges = [
            _edge_payload(row)
            for row in connection.execute(
                f"SELECT {_EDGE} FROM canonical_edges WHERE {edge_filter} "
                f"ORDER BY {_EDGE_ORDER} LIMIT :limit OFFSET :offset",
                {**params, "limit": edge_window[0], "offset": edge_window[1]},
            )
        ]
        nodes = [
            node_payload(row)
            for row in connection.execute(
                f"WITH neighbor_keys AS (SELECT source_canonical_key AS canonical_key "
                f"FROM canonical_edges WHERE {edge_filter} UNION SELECT target_canonical_key "
                f"FROM canonical_edges WHERE {edge_filter}) "
                f"SELECT {_NODE} FROM canonical_nodes JOIN neighbor_keys "
                "ON neighbor_keys.canonical_key = canonical_nodes.canonical_key "
                "WHERE canonical_nodes.graph_key_version = :version "
                "AND canonical_nodes.canonical_key <> :node "
                "ORDER BY canonical_nodes.canonical_key LIMIT :limit OFFSET :offset",
                {**params, "limit": node_window[0], "offset": node_window[1]},
            )
        ]
    return canonical_neighborhood_from_storage_payload(
        {
            "center": None if center is None else node_payload(center),
            "nodes": nodes,
            "edges": edges,
        }
    )


__all__ = (
    "canonical_edge_explanation",
    "canonical_edges",
    "canonical_neighborhood",
    "canonical_nodes",
    "node_payload",
    "require_accepted_publication",
)
