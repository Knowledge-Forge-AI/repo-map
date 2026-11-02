"""Incident-selective SQLite depth-1 expansion and batched neighbor locations (W4 Epic B)."""

from __future__ import annotations

from common_lore_index.storage.sqlite_local.schema import SqliteReadConnection

from collections.abc import Sequence
from dataclasses import dataclass
import json
from typing import Any

from common_lore_index.retrieval.intent_policy import CONTEXT_DIRECT_EVIDENCE_ROLE_V1
from common_lore_index.retrieval.context_identity import (
    ContextIdentityError,
    normalize_accepted_publication,
    parse_snapshot_vector,
)
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.navigation_search import EVIDENCE_SCAN_LIMIT
from common_lore_index.storage.sqlite_local.navigation_queries import (
    _direct_location,
    evidence_sql,
)

MAX_EXPANSION_EDGES_PER_SEED = 64
MAX_CANDIDATE_NEIGHBORS = 128


@dataclass(frozen=True, slots=True)
class SqliteContextPublicationIdentity:
    graph_id: str
    repository_id: str
    generation: int
    run_id: int
    publication_bundle_id: str
    snapshot_manifest_id: str
    extraction_receipt_id: str
    publication_job_id: str | None
    publication_attempt: int | None
    snapshot_vector: tuple[tuple[str, int, str], ...]


def read_sqlite_context_publication(
    connection: SqliteReadConnection,
) -> SqliteContextPublicationIdentity | None:
    """Read full context publication + graph binding identity in 1 SQL statement."""
    row = connection.execute(
        "SELECT g.graph_id, g.repository_identity, a.generation, a.run_id, "
        "r.publication_bundle_id, r.snapshot_manifest_id, r.extraction_receipt_id, "
        "r.publication_job_id, r.publication_attempt, r.snapshot_vector_json "
        "FROM accepted_publication a "
        "JOIN runs r ON r.id = a.run_id "
        "JOIN graph_binding g ON g.singleton = 1"
    ).fetchone()
    if row is None:
        return None
    try:
        raw_vec = json.loads(row[9]) if isinstance(row[9], str) else row[9]
        normalized = normalize_accepted_publication(
            {
                "generation": row[2],
                "run_id": row[3],
                "publication_bundle_id": row[4],
                "snapshot_manifest_id": row[5],
                "extraction_receipt_id": row[6],
                "publication_job_id": row[7],
                "publication_attempt": row[8],
                "snapshot_vector": raw_vec,
            }
        )
    except (ContextIdentityError, TypeError, ValueError) as exc:
        raise StorageSchemaError("malformed accepted context publication") from exc
    if not isinstance(row[0], str) or not row[0].strip():
        raise StorageSchemaError("invalid graph_id in accepted context publication")
    if not isinstance(row[1], str) or not row[1].strip():
        raise StorageSchemaError("invalid repository_id in accepted context publication")
    return SqliteContextPublicationIdentity(
        graph_id=row[0],
        repository_id=row[1],
        generation=normalized["generation"],
        run_id=normalized["run_id"],
        publication_bundle_id=normalized["publication_bundle_id"],
        snapshot_manifest_id=normalized["snapshot_manifest_id"],
        extraction_receipt_id=normalized["extraction_receipt_id"],
        publication_job_id=normalized["publication_job_id"],
        publication_attempt=normalized["publication_attempt"],
        snapshot_vector=normalized["snapshot_vector"],
    )


def expand_seed_incident_edges(
    connection: SqliteReadConnection,
    *,
    seed_canonical_key: str,
    edge_kinds: Sequence[str],
    per_seed_limit: int = MAX_EXPANSION_EDGES_PER_SEED,
) -> dict[str, Any]:
    """Read incident edges for one seed with edge-kind filter pushed before LIMIT."""
    ordered_kinds = tuple(sorted(dict.fromkeys(edge_kinds)))
    if not ordered_kinds or per_seed_limit <= 0:
        return {"edges": [], "truncated": False, "scanned": 0}

    kind_placeholders = ", ".join("?" for _ in ordered_kinds)
    fetch_limit = per_seed_limit + 1
    sql = f"""SELECT * FROM (
        SELECT
            'outgoing' AS direction,
            e.identity_metadata_hash AS edge_key,
            e.edge_kind AS edge_kind,
            e.source_canonical_key AS source_canonical_key,
            e.target_canonical_key AS target_canonical_key,
            e.confidence AS edge_confidence,
            e.conflict AS edge_conflict,
            e.first_seen_run_id AS edge_first_seen_run_id,
            e.last_seen_run_id AS edge_last_seen_run_id,
            target.id AS neighbor_id,
            target.canonical_key AS neighbor_canonical_key,
            target.kind AS neighbor_kind,
            target.display_name AS neighbor_display_name,
            target.first_seen_run_id AS neighbor_first_seen_run_id,
            target.last_seen_run_id AS neighbor_last_seen_run_id
        FROM canonical_edges e
        JOIN canonical_nodes target
          ON target.graph_key_version = 1 AND target.canonical_key = e.target_canonical_key
        WHERE e.graph_key_version = 1
          AND e.source_canonical_key = ?
          AND e.edge_kind IN ({kind_placeholders})
        ORDER BY e.edge_kind, e.target_canonical_key, e.identity_metadata_hash
        LIMIT ?
    )
    UNION ALL
    SELECT * FROM (
        SELECT
            'incoming' AS direction,
            e.identity_metadata_hash AS edge_key,
            e.edge_kind AS edge_kind,
            e.source_canonical_key AS source_canonical_key,
            e.target_canonical_key AS target_canonical_key,
            e.confidence AS edge_confidence,
            e.conflict AS edge_conflict,
            e.first_seen_run_id AS edge_first_seen_run_id,
            e.last_seen_run_id AS edge_last_seen_run_id,
            source.id AS neighbor_id,
            source.canonical_key AS neighbor_canonical_key,
            source.kind AS neighbor_kind,
            source.display_name AS neighbor_display_name,
            source.first_seen_run_id AS neighbor_first_seen_run_id,
            source.last_seen_run_id AS neighbor_last_seen_run_id
        FROM canonical_edges e INDEXED BY idx_canonical_edges_target
        JOIN canonical_nodes source
          ON source.graph_key_version = 1 AND source.canonical_key = e.source_canonical_key
        WHERE e.graph_key_version = 1
          AND e.target_canonical_key = ?
          AND e.edge_kind IN ({kind_placeholders})
        ORDER BY e.edge_kind, e.source_canonical_key, e.identity_metadata_hash
        LIMIT ?
    )"""
    params: tuple[Any, ...] = (
        seed_canonical_key, *ordered_kinds, fetch_limit,
        seed_canonical_key, *ordered_kinds, fetch_limit,
    )
    rows = connection.execute(sql, params).fetchall()
    kind_priority = {k: idx for idx, k in enumerate(ordered_kinds)}

    parsed: list[dict[str, Any]] = []
    for row in rows:
        direction = str(row[0])
        edge_kind = str(row[2])
        neighbor_ck = str(row[10])
        parsed.append(
            {
                "direction": direction,
                "direction_rank": 0 if direction == "outgoing" else 1,
                "edge_key": str(row[1]),
                "edge_kind": edge_kind,
                "edge_kind_priority": kind_priority.get(edge_kind, len(ordered_kinds)),
                "source_canonical_key": str(row[3]),
                "target_canonical_key": str(row[4]),
                "confidence": str(row[5]),
                "conflict": bool(row[6]),
                "first_seen_run_id": int(row[7]),
                "last_seen_run_id": int(row[8]),
                "neighbor_id": int(row[9]),
                "neighbor_canonical_key": neighbor_ck,
                "neighbor_kind": str(row[11]),
                "neighbor_display_name": row[12],
                "neighbor_first_seen_run_id": int(row[13]),
                "neighbor_last_seen_run_id": int(row[14]),
            }
        )

    parsed.sort(
        key=lambda item: (
            item["edge_kind_priority"],
            item["edge_kind"],
            item["direction_rank"],
            item["neighbor_canonical_key"].encode("utf-8"),
            item["edge_key"].encode("utf-8"),
        )
    )
    truncated = len(parsed) > per_seed_limit
    kept = parsed[:per_seed_limit]
    return {"edges": kept, "truncated": truncated, "scanned": len(kept)}


def batch_neighbor_direct_locations(
    connection: SqliteReadConnection,
    *,
    neighbor_ids: Sequence[int],
    accepted_run_id: int,
    role_sql: str = CONTEXT_DIRECT_EVIDENCE_ROLE_V1,
    snapshot_vector: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Read direct locations for neighbor node IDs in a single SQL statement."""
    if type(accepted_run_id) is not int or accepted_run_id < 1:
        raise StorageSchemaError("invalid accepted_run_id for context expansion")
    try:
        normalized_vector = (
            parse_snapshot_vector(snapshot_vector) if snapshot_vector is not None else None
        )
    except (ContextIdentityError, TypeError) as exc:
        raise StorageSchemaError("malformed snapshot vector for context expansion") from exc
    unique_ids = [int(nid) for nid in dict.fromkeys(neighbor_ids)][:MAX_CANDIDATE_NEIGHBORS]
    if not unique_ids:
        return {"locations_by_node_id": {}, "evidence_scanned": 0, "incomplete": False}

    predicate = "subject.id IN (" + ",".join(str(nid) for nid in unique_ids) + ")"
    sql = evidence_sql(predicate, role_sql=role_sql)
    rows = connection.execute(
        sql,
        {"accepted": accepted_run_id, "evidence_fetch": EVIDENCE_SCAN_LIMIT + 1},
    ).fetchall()
    incomplete = len(rows) > EVIDENCE_SCAN_LIMIT
    kept_rows = rows[:EVIDENCE_SCAN_LIMIT]

    by_node: dict[int, list[dict[str, Any]]] = {nid: [] for nid in unique_ids}
    vec_arg = list(normalized_vector) if normalized_vector is not None else None
    for row in kept_rows:
        node_id = int(row[20])
        loc = _direct_location(
            row[:20], accepted_run_id, snapshot_vector=vec_arg, context_identity=True
        )
        if node_id in by_node:
            by_node[node_id].append(loc)
    return {
        "locations_by_node_id": by_node,
        "evidence_scanned": len(kept_rows),
        "incomplete": incomplete,
    }
