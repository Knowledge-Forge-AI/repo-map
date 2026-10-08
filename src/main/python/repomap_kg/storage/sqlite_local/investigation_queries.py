"""Search, project-summary and refresh-status reads over one SQLite Local graph.

Same transaction and parameter rules as ``storage.sqlite_local.queries``.
Node and file search use ``LIKE ... ESCAPE '\\'`` which, like PostgreSQL
``ILIKE``, folds ASCII case; non-ASCII case folding parity is not claimed.
Observation search matches the PostgreSQL ``payload_json::text`` rendering
(``storage.sqlite_local.raw_payload``), not the stored compact text, so its
literal match runs in Python over the SQL-filtered, SQL-ordered rows. Status
fields derived from stored JSON are computed in Python, so no SQLite JSON
functions are needed.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.graph_readback_sql import escape_readback_like_pattern
from repomap_kg.storage.sqlite_local import raw_payload
from repomap_kg.storage.sqlite_local.queries import node_payload, require_accepted_publication
from repomap_kg.storage.summary_rows_storage import (
    CanonicalStorageSummaryRecord,
    canonical_storage_summary_from_payload,
)


def storage_summary(
    connection: sqlite3.Connection, *, root_path: str
) -> CanonicalStorageSummaryRecord:
    """Project-summary counts; an unpublished graph has no repository row."""
    name_row = connection.execute("SELECT repository_name FROM graph_binding").fetchone()
    accepted = connection.execute("SELECT run_id FROM accepted_publication").fetchone()
    latest = None if accepted is None else int(accepted[0])

    def count(sql: str, params: tuple[object, ...] = ()) -> int:
        return int(connection.execute(sql, params).fetchone()[0])

    raw = count("SELECT count(*) FROM raw_observations")
    return canonical_storage_summary_from_payload(
        {
            "root_path": root_path,
            "repository_name": None if accepted is None or name_row is None else name_row[0],
            "latest_run_id": latest,
            "runs": count("SELECT count(*) FROM runs"),
            "files": count("SELECT count(*) FROM files"),
            "raw_observations": raw,
            "raw_observations_total": raw,
            "latest_run_raw_observations": count(
                "SELECT count(*) FROM raw_observations WHERE run_id = ?", (latest,)
            ),
            "canonical_nodes": count("SELECT count(*) FROM canonical_nodes"),
            "canonical_edges": count("SELECT count(*) FROM canonical_edges"),
            "canonical_evidence": count("SELECT count(*) FROM canonical_evidence"),
        }
    )


def search(
    connection: sqlite3.Connection,
    *,
    target: str,
    query: str,
    kind: str | None,
    path: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Node or file search with the PostgreSQL page contract (limit + 1 probe)."""
    require_accepted_publication(connection)
    pattern = "%" + escape_readback_like_pattern(query) + "%"
    if target == "nodes":
        filters = [
            "graph_key_version = 1",
            "(canonical_key LIKE :pattern ESCAPE '\\' OR kind LIKE :pattern ESCAPE '\\' "
            "OR display_name LIKE :pattern ESCAPE '\\')",
        ]
        if kind is not None:
            filters.append("kind = :kind")
        sql = (
            "SELECT canonical_key, graph_key_version, kind, display_name, confidence, "
            "conflict, metadata_json, first_seen_run_id, last_seen_run_id "
            f"FROM canonical_nodes WHERE {' AND '.join(filters)} "
            "ORDER BY canonical_key LIMIT :fetch OFFSET :offset"
        )
    elif target == "files":
        filters = [
            "(path LIKE :pattern ESCAPE '\\' OR language LIKE :pattern ESCAPE '\\' "
            "OR role LIKE :pattern ESCAPE '\\')"
        ]
        if path is not None:
            filters.append("path = :path")
        sql = (
            "SELECT path, language, role, executable, generated FROM files "
            f"WHERE {' AND '.join(filters)} ORDER BY path LIMIT :fetch OFFSET :offset"
        )
    else:
        raise StorageSchemaError("search target must be nodes or files")
    rows = connection.execute(
        sql,
        {"pattern": pattern, "kind": kind, "path": path, "fetch": limit + 1, "offset": offset},
    ).fetchall()
    if target == "nodes":
        payload = [node_payload(row) for row in rows]
    else:
        payload = [
            {
                "path": row[0],
                "language": row[1],
                "role": row[2],
                "executable": bool(row[3]),
                "generated": bool(row[4]),
            }
            for row in rows
        ]
    page = payload[:limit]
    return {"results": page, "total": offset + len(page), "has_more": len(payload) > limit}


def observation_search_sql(*, kind: bool, path: bool) -> str:
    """The exact observation-search SQL; ``path = ?`` is served by the v2 path index."""
    filters = ["1 = 1", *(["kind = ?"] if kind else []), *(["path = ?"] if path else [])]
    return (
        "SELECT ordinal, kind, source_id, path, payload_json FROM raw_observations "
        f"WHERE {' AND '.join(filters)} ORDER BY run_id DESC, ordinal"
    )


def observation_search(
    connection: sqlite3.Connection,
    *,
    query: str,
    kind: str | None,
    path: str | None,
    limit: int,
    offset: int,
    include_raw: bool,
) -> dict[str, Any]:
    """Observation search with the PostgreSQL row shape, order and page contract.

    A row matches when the ASCII-folded query is a substring of the kind,
    source id, path or ``jsonb::text`` payload, which is the escaped
    ``%literal%`` ``ILIKE`` on a C-ctype database. ``metadata`` and the
    consented ``payload`` are the values a PostgreSQL JSON readback decodes.
    """
    require_accepted_publication(connection)
    needle = raw_payload.ascii_lower(query)
    params = [value for value in (kind, path) if value is not None]
    rows = connection.execute(
        observation_search_sql(kind=kind is not None, path=path is not None), params
    )
    skipped = 0
    page: list[dict[str, Any]] = []
    try:
        for ordinal, row_kind, source_id, row_path, text in rows:
            payload = raw_payload.load(text)
            if not any(
                needle in raw_payload.ascii_lower(field)
                for field in (row_kind, source_id, row_path, raw_payload.jsonb_text(payload))
            ):
                continue
            if skipped < offset:
                skipped += 1
                continue
            metadata = payload.get("metadata") if isinstance(payload, dict) else None
            row: dict[str, Any] = {
                "ordinal": ordinal,
                "kind": row_kind,
                "source_id": source_id,
                "path": row_path,
                "metadata": None if metadata is None else raw_payload.jsonb_value(metadata),
            }
            if include_raw:
                row["payload"] = raw_payload.jsonb_value(payload)
            page.append(row)
            if len(page) > limit:
                break
    finally:
        rows.close()
    results = page[:limit]
    return {"results": results, "total": offset + len(results), "has_more": len(page) > limit}


def status_fields(connection: sqlite3.Connection) -> dict[str, Any]:
    """Refresh-status fields; publication identity comes from the accepted run."""
    accepted = connection.execute("SELECT run_id FROM accepted_publication").fetchone()
    if accepted is None:
        return {
            "repository_exists": False,
            "raw_observations": 0,
            "raw_observations_total": 0,
            "latest_run_raw_observations": 0,
            "canonical_nodes": 0,
            "canonical_edges": 0,
        }
    run = connection.execute(
        "SELECT id, status, started_at, finished_at, execution_route, "
        "portable_protocol_version, snapshot_manifest_id, extraction_receipt_id, "
        "publication_bundle_id, graph_candidate_id, snapshot_vector_json, "
        "family_receipts_json FROM runs WHERE id = ?",
        (int(accepted[0]),),
    ).fetchone()
    raw = int(connection.execute("SELECT count(*) FROM raw_observations").fetchone()[0])
    receipts = json.loads(run[11])
    return {
        "repository_exists": True,
        "latest_run_id": int(run[0]),
        "latest_run_status": run[1],
        "latest_run_started_at": run[2],
        "latest_run_finished_at": run[3],
        "raw_observations": raw,
        "raw_observations_total": raw,
        "latest_run_raw_observations": int(
            connection.execute(
                "SELECT count(*) FROM raw_observations WHERE run_id = ?", (int(run[0]),)
            ).fetchone()[0]
        ),
        "canonical_nodes": int(connection.execute("SELECT count(*) FROM canonical_nodes").fetchone()[0]),
        "canonical_edges": int(connection.execute("SELECT count(*) FROM canonical_edges").fetchone()[0]),
        "publication": {
            "execution_route": run[4],
            "protocol_version": run[5],
            "snapshot_manifest_id": run[6],
            "extraction_receipt_id": run[7],
            "publication_bundle_id": run[8],
            "graph_candidate_id": run[9],
            "source_binding_count": len(json.loads(run[10])),
            "family_counts": {family: int(item["count"]) for family, item in receipts.items()},
        },
    }


__all__ = ("observation_search", "observation_search_sql", "search", "status_fields", "storage_summary")
