"""Read persisted node-evidence links inside the caller's bound read transaction."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from common_lore_index.retrieval.context_identity import (
    ContextIdentityError,
    parse_snapshot_vector,
)
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.node_locations import NodeLocationsQuery, unavailable
from common_lore_index.storage.sqlite_local.schema import (
    LocalGraphBinding,
    SqliteReadConnection,
    accepted_identity,
)
from common_lore_index.storage.sqlite_local.connection import read_transaction


# Definition producers put observed on the subject, inferred_from_edge on
# the containing file. Other observed producers remain unknown (ADR 0079).
_EVIDENCE_ROLE_SQL = """CASE
    WHEN link.link_kind = 'inferred_from_edge' THEN 'reference'
    WHEN link.link_kind = 'observed' AND (
        (e.raw_kind IN ('python.module', 'python.class', 'python.function', 'python.method')
         AND subject.kind = e.raw_kind)
        OR (e.raw_kind = 'markdown.document' AND subject.kind = 'doc.page')
        OR (e.raw_kind = 'markdown.heading' AND subject.kind = 'doc.section')
        OR (e.raw_kind = 'markdown.adr_metadata' AND subject.kind = 'doc.adr')
        OR (e.raw_kind = 'markdown.skill_metadata' AND subject.kind = 'doc.skill')
    ) THEN 'direct'
    ELSE 'unknown' END"""


def read_node_locations(path: Path, binding: LocalGraphBinding, query: NodeLocationsQuery) -> dict[str, Any]:
    query.validate()
    with read_transaction(path, binding) as connection:
        return node_locations(connection, query)


def node_locations(
    connection: SqliteReadConnection,
    query: NodeLocationsQuery,
    *,
    role_sql: str = _EVIDENCE_ROLE_SQL,
    include_node_summary: bool = False,
    context_identity: bool = False,
) -> dict[str, Any]:
    query.validate()
    accepted = accepted_identity(connection)
    if accepted is None:
        return unavailable("publication_absent")
    node_sql = (
        "SELECT id, metadata_json, first_seen_run_id, last_seen_run_id, kind, display_name "
        "FROM canonical_nodes WHERE graph_key_version = 1 AND canonical_key = ?"
        if include_node_summary
        else "SELECT id, metadata_json, first_seen_run_id, last_seen_run_id "
        "FROM canonical_nodes WHERE graph_key_version = 1 AND canonical_key = ?"
    )
    node = connection.execute(node_sql, (query.canonical_key,)).fetchone()
    if node is None:
        return unavailable("node_not_found")
    selected = connection.execute(
        "SELECT e.run_id FROM canonical_node_evidence link "
        "JOIN canonical_evidence e ON e.id = link.canonical_evidence_id "
        "WHERE link.canonical_node_id = ? AND e.graph_key_version = 1 "
        "ORDER BY (e.run_id = ?) DESC, e.run_id DESC LIMIT 1",
        (node[0], accepted.run_id),
    ).fetchone()
    location_run_id = selected[0] if selected else None
    rows = _evidence_window(
        connection, node[0], location_run_id, query, historical=False, role_sql=role_sql
    )
    history = _evidence_window(
        connection, node[0], location_run_id, query, historical=True, role_sql=role_sql
    )
    result: dict[str, Any] = {
        "status": "ok", "reason": None,
        "locations": [
            _location(row, accepted.run_id, context_identity=context_identity)
            for row in rows[:query.limit]
        ],
        "historical_locations": [
            _location(row, accepted.run_id, context_identity=context_identity)
            for row in history[:query.limit]
        ],
        "historical_has_more": len(history) > query.limit,
        "location_run_id": location_run_id,
        "location_scope": _relation(selected[0], accepted.run_id) if selected else "unavailable",
        "metadata_location": _metadata_location(node), "has_more": len(rows) > query.limit,
        "node_first_seen_run_id": node[2], "node_last_seen_run_id": node[3],
        "accepted_publication": {"generation": accepted.generation, "run_id": accepted.run_id,
                                 "publication_bundle_id": accepted.publication_bundle_id},
    }
    if include_node_summary:
        result["node_summary"] = {
            "id": int(node[0]), "canonical_key": query.canonical_key,
            "kind": str(node[4]), "display_name": str(node[5]),
        }
    return result


def _evidence_window(
    connection: SqliteReadConnection,
    node_id: int,
    run_id: int | None,
    query: NodeLocationsQuery,
    *,
    historical: bool,
    role_sql: str = _EVIDENCE_ROLE_SQL,
) -> list[Any]:
    if run_id is None:
        return []
    relation = "<>" if historical else "="
    filtered = query.evidence_role != "all"
    role_column = f", {role_sql}" if filtered else ""
    role_predicate = f"AND ({role_sql}) = ? " if filtered else ""
    parameters = (node_id, run_id, query.evidence_role, query.limit + 1) if filtered else (
        node_id, run_id, query.limit + 1,
    )
    return connection.execute(
        "SELECT e.evidence_key, link.link_kind, e.run_id, e.raw_observation_ordinal, "
        "raw.payload_hash, e.raw_kind, e.raw_source_id, e.path, e.start_line, e.end_line, "
        "e.extractor, e.extractor_version, e.confidence, e.metadata_json, "
        "r.publication_bundle_id, r.snapshot_manifest_id, r.extraction_receipt_id, "
        f"r.graph_candidate_id, r.snapshot_vector_json{role_column} "
        "FROM canonical_node_evidence link "
        "JOIN canonical_nodes subject ON subject.id = link.canonical_node_id "
        "JOIN canonical_evidence e ON e.id = link.canonical_evidence_id "
        "LEFT JOIN raw_observations raw ON raw.run_id = e.run_id "
        "AND raw.ordinal = e.raw_observation_ordinal "
        "JOIN runs r ON r.id = e.run_id "
        f"WHERE link.canonical_node_id = ? AND e.graph_key_version = 1 AND e.run_id {relation} ? "
        f"{role_predicate}"
        "ORDER BY e.run_id DESC, e.raw_observation_ordinal, e.evidence_key, link.link_kind "
        "LIMIT ?", parameters,
    ).fetchall()


def _metadata_location(node: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any] | None:
    metadata = json.loads(node[1])
    doc_path = metadata.get("doc_path") if isinstance(metadata, dict) else None
    if doc_path is None:
        return None
    return {
        "basis": "node_metadata.doc_path", "path": doc_path,
        "path_namespace": "source_relative", "binding_status": "unavailable",
        "start_line": None, "end_line": None, "node_last_seen_run_id": node[3],
    }


def _relation(run_id: int, accepted_run_id: int) -> str:
    return "accepted_run" if run_id == accepted_run_id else "historical_run"


def _parse_context_snapshot_vector(raw_vector: Any) -> list[list[Any]]:
    """Validate a persisted evidence vector before context normalization."""
    if isinstance(raw_vector, str):
        try:
            raw_vector = json.loads(raw_vector)
        except (TypeError, ValueError, RecursionError) as exc:
            raise StorageSchemaError("malformed context snapshot vector") from exc
    try:
        parsed = parse_snapshot_vector(raw_vector)
    except (ContextIdentityError, TypeError, ValueError) as exc:
        raise StorageSchemaError("malformed context snapshot vector") from exc
    return [list(item) for item in parsed]


def _location(row: sqlite3.Row | tuple[Any, ...], accepted_run_id: int, *,
              snapshot_vector: list[Any] | None = None,
              context_identity: bool = False) -> dict[str, Any]:
    raw_vector = (
        _parse_context_snapshot_vector(row[18])
        if context_identity
        else json.loads(row[18]) if snapshot_vector is None else snapshot_vector
    )
    vector = (
        _parse_context_snapshot_vector(snapshot_vector)
        if context_identity and snapshot_vector is not None
        else raw_vector if snapshot_vector is None else snapshot_vector
    )
    metadata = json.loads(row[13])
    source = {key: metadata[key] for key in (
        "binding_id", "binding_alias", "binding_revision", "snapshot_id", "source_relative_path"
    ) if isinstance(metadata, dict) and type(metadata.get(key)) in {str, int}}
    # A revision may exist only in the publication vector. Match an explicit
    # canonical-evidence binding; never attribute an arbitrary vector entry to a node.
    for binding, revision, snapshot in vector:
        if binding == source.get("binding_id") and snapshot == source.get("snapshot_id"):
            source.setdefault("binding_revision", revision)
            break
    result = {
        "basis": "canonical_node_evidence", "evidence_key": row[0], "link_kind": row[1],
        "run_id": row[2], "publication_relation": _relation(row[2], accepted_run_id),
        "raw_observation": {"status": "available" if row[4] is not None else "unavailable",
                            "run_id": row[2], "ordinal": row[3], "payload_hash": row[4],
                            "kind": row[5], "source_id": row[6]},
        "path": row[7], "start_line": row[8], "end_line": row[9],
        "path_namespace": "graph_source_relative",
        "extractor": row[10], "extractor_version": row[11], "confidence": row[12],
        "source": source,
        "publication": {"publication_bundle_id": row[14], "snapshot_manifest_id": row[15],
                        "extraction_receipt_id": row[16], "graph_candidate_id": row[17]},
    }
    if len(row) > 19:
        result["evidence_role"] = row[19]
    return result
