"""Read persisted node-evidence links inside the caller's bound read transaction."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from common_lore_index.storage.node_locations import NodeLocationsQuery, unavailable
from common_lore_index.storage.sqlite_local.schema import LocalGraphBinding, accepted_identity
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


def node_locations(connection: sqlite3.Connection, query: NodeLocationsQuery) -> dict[str, Any]:
    query.validate()
    accepted = accepted_identity(connection)
    if accepted is None:
        return unavailable("publication_absent")
    node = connection.execute(
        "SELECT id, metadata_json, first_seen_run_id, last_seen_run_id "
        "FROM canonical_nodes WHERE graph_key_version = 1 AND canonical_key = ?",
        (query.canonical_key,),
    ).fetchone()
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
    rows = _evidence_window(connection, node[0], location_run_id, query, historical=False)
    history = _evidence_window(connection, node[0], location_run_id, query, historical=True)
    return {
        "status": "ok", "reason": None,
        "locations": [_location(row, accepted.run_id) for row in rows[:query.limit]],
        "historical_locations": [_location(row, accepted.run_id) for row in history[:query.limit]],
        "historical_has_more": len(history) > query.limit,
        "location_run_id": location_run_id,
        "location_scope": _relation(selected[0], accepted.run_id) if selected else "unavailable",
        "metadata_location": _metadata_location(node), "has_more": len(rows) > query.limit,
        "node_first_seen_run_id": node[2], "node_last_seen_run_id": node[3],
        "accepted_publication": {"generation": accepted.generation, "run_id": accepted.run_id,
                                 "publication_bundle_id": accepted.publication_bundle_id},
    }


def _evidence_window(
    connection: sqlite3.Connection, node_id: int, run_id: int | None, query: NodeLocationsQuery, *, historical: bool,
) -> list[Any]:
    if run_id is None:
        return []
    relation = "<>" if historical else "="
    filtered = query.evidence_role != "all"
    role_column = f", {_EVIDENCE_ROLE_SQL}" if filtered else ""
    role_predicate = f"AND ({_EVIDENCE_ROLE_SQL}) = ? " if filtered else ""
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


def _location(row: sqlite3.Row | tuple[Any, ...], accepted_run_id: int, *,
              snapshot_vector: list[Any] | None = None) -> dict[str, Any]:
    metadata = json.loads(row[13])
    source = {key: metadata[key] for key in (
        "binding_id", "binding_alias", "binding_revision", "snapshot_id", "source_relative_path"
    ) if isinstance(metadata, dict) and type(metadata.get(key)) in {str, int}}
    # A revision may exist only in the publication vector. Match an explicit
    # canonical-evidence binding; never attribute an arbitrary vector entry to a node.
    for binding, revision, snapshot in json.loads(row[18]) if snapshot_vector is None else snapshot_vector:
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
