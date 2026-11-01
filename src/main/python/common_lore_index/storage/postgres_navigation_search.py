"""Single-statement request-pinned PostgreSQL navigation_search with SQLite admission parity."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
from typing import Any

from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.navigation_search import (
    EVIDENCE_SCAN_LIMIT,
    NODE_SCAN_LIMIT,
    NavigationSearchQuery,
    unavailable,
)
from common_lore_index.storage.postgres_navigation_sql import (
    build_postgres_navigation_sql,
)
from common_lore_index.storage.readback_driver import execute_json_readback
from common_lore_index.storage.sqlite_local.navigation_queries import (
    _Admission,
    _direct_location,
)


def _compact_json_str(value: Any, *, default: str = "{}") -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return default
    if isinstance(value, list) and value and isinstance(value[0], dict):
        value = [
            [
                item.get("binding_id"),
                item.get("binding_revision", item.get("revision")),
                item.get("snapshot_id"),
            ]
            for item in value
        ]
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _evidence_tuple_from_json(raw: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        raw.get("evidence_key"),
        raw.get("link_kind"),
        int(raw["run_id"]),
        int(raw["raw_observation_ordinal"]),
        raw.get("payload_hash"),
        raw.get("raw_kind"),
        raw.get("raw_source_id"),
        raw.get("path"),
        raw.get("start_line"),
        raw.get("end_line"),
        raw.get("extractor"),
        raw.get("extractor_version"),
        raw.get("confidence"),
        _compact_json_str(raw.get("metadata_json"), default="{}"),
        raw.get("publication_bundle_id"),
        raw.get("snapshot_manifest_id"),
        raw.get("extraction_receipt_id"),
        raw.get("graph_candidate_id"),
        _compact_json_str(raw.get("snapshot_vector_json"), default="[]"),
        raw.get("evidence_role") or "direct",
        int(raw["node_id"]),
    )


def _node_tuple_from_json(raw: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(raw["id"]),
        str(raw["canonical_key"]),
        str(raw["kind"]),
        raw.get("display_name"),
        int(raw["first_seen_run_id"]),
        int(raw["last_seen_run_id"]),
    )


def _admit_scoped_candidates(
    candidate_nodes: Sequence[tuple[Any, ...]],
    evidence_tuples: Sequence[tuple[Any, ...]],
    admission: _Admission,
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    ev_by_node: dict[int, list[tuple[Any, ...]]] = {}
    for ev in evidence_tuples:
        ev_by_node.setdefault(int(ev[20]), []).append(ev)

    admitted_nodes: list[tuple[Any, ...]] = []
    for node in candidate_nodes:
        node_id = int(node[0])
        node_ev = ev_by_node.get(node_id, ())
        if not node_ev:
            continue
        matched = False
        for ev in node_ev:
            try:
                if admission.matches(int(ev[2]), ev[7], str(ev[13]), str(ev[18])):
                    matched = True
                    break
            except ValueError:
                if admission.exhausted:
                    return admitted_nodes, []
                raise
        if matched:
            admitted_nodes.append(node)
            if len(admitted_nodes) >= NODE_SCAN_LIMIT + 1:
                break

    if len(admitted_nodes) > NODE_SCAN_LIMIT:
        return admitted_nodes, []

    admitted_ids = {int(n[0]) for n in admitted_nodes}
    admitted_evidence: list[tuple[Any, ...]] = []
    for ev in evidence_tuples:
        if int(ev[20]) in admitted_ids:
            admitted_evidence.append(ev)
            if len(admitted_evidence) >= EVIDENCE_SCAN_LIMIT + 1:
                break
    return admitted_nodes, admitted_evidence


def read_postgres_navigation_search_with_executor(
    query: NavigationSearchQuery,
    *,
    executor: Callable[[str], Any],
    admits_location: Callable[[dict[str, Any]], bool] | None = None,
    root_path: str = "",
    repository_identity: str | None = None,
) -> dict[str, Any]:
    """Execute single-statement PostgreSQL navigation_search using an injected SQL JSON executor."""
    query.validate()
    admission: _Admission | None = None
    if query.source_binding_id is not None:
        if admits_location is None:
            return unavailable("source_scope_predicate_unavailable")
        admission = _Admission(admits_location)

    sql = build_postgres_navigation_sql(
        query,
        repository_identity=repository_identity,
        root_path=root_path,
    )
    payload = executor(sql)
    if not isinstance(payload, dict):
        raise StorageSchemaError("malformed PostgreSQL navigation search readback")
    if not payload.get("has_accepted"):
        return unavailable("publication_absent")
    if payload.get("transport_overflow"):
        return {"status": "incomplete", "reason": "admission_work_limit",
                "nodes": [], "accepted_publication": None,
                "scan": {"complete": False, "transport_overflow": True}}

    accepted = payload["accepted"]
    accepted_run_id = int(accepted["run_id"])
    raw_nodes = [
        _node_tuple_from_json(r)
        for r in (payload.get("candidate_nodes") or ())
        if isinstance(r, Mapping)
    ]
    raw_evidence = [
        _evidence_tuple_from_json(r)
        for r in (payload.get("direct_evidence") or ())
        if isinstance(r, Mapping)
    ]

    if admission is not None:
        rows, evidence = _admit_scoped_candidates(raw_nodes, raw_evidence, admission)
    else:
        rows = raw_nodes[: NODE_SCAN_LIMIT + 1]
        evidence = raw_evidence[: EVIDENCE_SCAN_LIMIT + 1] if len(rows) <= NODE_SCAN_LIMIT else []

    result: dict[str, Any] = {
        "status": "ok",
        "reason": None,
        "nodes": [],
        "accepted_publication": {
            "generation": int(accepted["generation"]),
            "run_id": accepted_run_id,
            "publication_bundle_id": str(accepted["publication_bundle_id"]),
        },
        "scan": {
            "complete": False,
            "nodes": min(len(rows), NODE_SCAN_LIMIT),
            "evidence": 0,
            "node_limit": NODE_SCAN_LIMIT,
            "evidence_limit": EVIDENCE_SCAN_LIMIT,
        },
    }
    if admission is not None:
        result["scan"]["admission"] = admission.diagnostics()
        if admission.exhausted or bool(payload.get("transport_overflow")):
            return {**result, "status": "incomplete", "reason": "admission_work_limit"}
    if len(rows) > NODE_SCAN_LIMIT:
        return {**result, "status": "incomplete", "reason": "node_scan_limit"}

    result["scan"]["evidence"] = min(len(evidence), EVIDENCE_SCAN_LIMIT)
    if len(evidence) > EVIDENCE_SCAN_LIMIT:
        return {**result, "status": "incomplete", "reason": "evidence_scan_limit"}

    nodes_map = {
        row[0]: {
            "canonical_key": row[1],
            "kind": row[2],
            "display_name": row[3],
            "first_seen_run_id": row[4],
            "last_seen_run_id": row[5],
            "locations": [],
        }
        for row in rows
    }
    for ev_row in evidence:
        vector = admission.vectors.get(ev_row[2]) if admission is not None else None
        location = _direct_location(ev_row[:20], accepted_run_id, snapshot_vector=vector)
        if ev_row[20] in nodes_map:
            nodes_map[ev_row[20]]["locations"].append(location)
    result["nodes"] = list(nodes_map.values())
    result["scan"]["complete"] = True
    return result


def query_postgres_navigation_candidates(
    psql_args: Sequence[str],
    *,
    query: NavigationSearchQuery,
    admits_location: Callable[[dict[str, Any]], bool] | None = None,
    psql_command: str = "psql",
    password: str | None = None,
    root_path: str = "",
    repository_identity: str | None = None,
) -> dict[str, Any]:
    """Execute single-statement PostgreSQL navigation_search with SQLite admission parity."""
    return read_postgres_navigation_search_with_executor(
        query,
        executor=lambda sql: execute_json_readback(
            sql,
            psql_args=psql_args,
            psql_command=psql_command,
            label="navigation search",
            expected_shape="object",
            password=password,
        ),
        admits_location=admits_location,
        root_path=root_path,
        repository_identity=repository_identity,
    )


__all__ = [
    "query_postgres_navigation_candidates",
    "read_postgres_navigation_search_with_executor",
]
