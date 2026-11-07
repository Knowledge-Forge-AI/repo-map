"""Single-statement request-pinned PostgreSQL node-to-stored-source location readback."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
from typing import Any

from common_lore_index.storage.context_postgres_identity import (
    format_postgres_accepted_publication,
    postgres_accepted_json_sql,
    postgres_accepted_run_cte_sql,
    postgres_repo_predicate_sql,
)
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.node_locations import NodeLocationsQuery, unavailable
from common_lore_index.storage.postgres_navigation_sql import transport_budget_sql
from common_lore_index.storage.readback_driver import execute_json_readback
from common_lore_index.storage.sql_core import sql_literal
from common_lore_index.storage.sqlite_local.node_location_queries import (
    _EVIDENCE_ROLE_SQL,
    _location,
    _metadata_location,
    _parse_context_snapshot_vector,
    _relation,
)


def _compact_json_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], dict):
        value = [
            [
                item.get("binding_id"),
                item.get("binding_revision", item.get("revision")),
                item.get("snapshot_id"),
            ]
            for item in value
        ]
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_postgres_node_locations_sql(
    query: NodeLocationsQuery,
    *,
    repository_identity: str | None,
    root_path: str,
    role_sql: str = _EVIDENCE_ROLE_SQL,
    context_identity: bool = False,
) -> str:
    """Build a single-statement CTE query pinning accepted publication and node evidence windows."""
    query.validate()
    repo_pred = postgres_repo_predicate_sql(
        repository_identity, root_path, context_identity=context_identity
    )
    filtered = query.evidence_role != "all"
    role_filter_sql = (
        f"AND ({role_sql}) = {sql_literal(query.evidence_role)}"
        if filtered
        else ""
    )
    window_limit = int(query.limit) + 1
    target_display_col = ",\n        cn.display_name" if context_identity else ""
    extra_node_cols = (
        ",\n            'kind', tn.kind,\n            'display_name', tn.display_name"
        if context_identity
        else ""
    )

    return f"""WITH matched_repo AS MATERIALIZED (
    SELECT repo.id AS repository_id
    FROM public.repositories repo
    WHERE {repo_pred}
    ORDER BY repo.id DESC
    LIMIT 1
),
{postgres_accepted_run_cte_sql(context_identity=context_identity)},
target_node AS MATERIALIZED (
    SELECT
        cn.id,
        cn.repository_id,
        cn.kind{target_display_col},
        cn.metadata_json,
        cn.first_seen_run_id,
        cn.last_seen_run_id
    FROM public.canonical_nodes cn
    JOIN matched_repo mr ON mr.repository_id = cn.repository_id
    JOIN accepted_run acc ON TRUE
    WHERE cn.graph_key_version = 1
      AND cn.canonical_key = {sql_literal(query.canonical_key)}
    LIMIT 1
),
selected_run AS MATERIALIZED (
    SELECT e.run_id
    FROM public.canonical_node_evidence link
    JOIN target_node tn ON tn.id = link.canonical_node_id
    JOIN public.canonical_evidence e
      ON e.id = link.canonical_evidence_id
     AND e.repository_id = tn.repository_id
    JOIN accepted_run acc ON TRUE
    WHERE e.graph_key_version = 1
    ORDER BY (e.run_id = acc.run_id) DESC, e.run_id DESC
    LIMIT 1
),
current_window AS MATERIALIZED (
    SELECT
        e.evidence_key,
        link.link_kind,
        e.run_id,
        e.raw_observation_ordinal,
        raw.payload_hash,
        e.raw_kind,
        e.raw_source_id,
        e.path,
        e.start_line,
        e.end_line,
        e.extractor,
        e.extractor_version,
        e.confidence::text AS confidence,
        e.metadata_json,
        r.publication_bundle_id,
        r.snapshot_manifest_id,
        r.extraction_receipt_id,
        r.graph_candidate_id,
        r.snapshot_vector_json,
        ({role_sql}) AS evidence_role
    FROM public.canonical_node_evidence link
    JOIN target_node subject ON subject.id = link.canonical_node_id
    JOIN selected_run sr ON TRUE
    JOIN public.canonical_evidence e
      ON e.id = link.canonical_evidence_id
     AND e.repository_id = subject.repository_id
     AND e.run_id = sr.run_id
    LEFT JOIN public.raw_observations raw
      ON raw.repository_id = e.repository_id
     AND raw.run_id = e.run_id
     AND raw.ordinal = e.raw_observation_ordinal
    JOIN public.runs r ON r.id = e.run_id
    WHERE e.graph_key_version = 1
      {role_filter_sql}
    ORDER BY e.run_id DESC, e.raw_observation_ordinal ASC, e.evidence_key COLLATE "C" ASC, link.link_kind COLLATE "C" ASC
    LIMIT {window_limit}
),
historical_window AS MATERIALIZED (
    SELECT
        e.evidence_key,
        link.link_kind,
        e.run_id,
        e.raw_observation_ordinal,
        raw.payload_hash,
        e.raw_kind,
        e.raw_source_id,
        e.path,
        e.start_line,
        e.end_line,
        e.extractor,
        e.extractor_version,
        e.confidence::text AS confidence,
        e.metadata_json,
        r.publication_bundle_id,
        r.snapshot_manifest_id,
        r.extraction_receipt_id,
        r.graph_candidate_id,
        r.snapshot_vector_json,
        ({role_sql}) AS evidence_role
    FROM public.canonical_node_evidence link
    JOIN target_node subject ON subject.id = link.canonical_node_id
    JOIN selected_run sr ON TRUE
    JOIN public.canonical_evidence e
      ON e.id = link.canonical_evidence_id
     AND e.repository_id = subject.repository_id
     AND e.run_id <> sr.run_id
    LEFT JOIN public.raw_observations raw
      ON raw.repository_id = e.repository_id
     AND raw.run_id = e.run_id
     AND raw.ordinal = e.raw_observation_ordinal
    JOIN public.runs r ON r.id = e.run_id
    WHERE e.graph_key_version = 1
      {role_filter_sql}
    ORDER BY e.run_id DESC, e.raw_observation_ordinal ASC, e.evidence_key COLLATE "C" ASC, link.link_kind COLLATE "C" ASC
    LIMIT {window_limit}
),
{transport_budget_sql('target_node', 'current_window', 'historical_window', 'accepted_run')}
SELECT json_build_object(
    'has_accepted', EXISTS (SELECT 1 FROM accepted_run),
    'transport_overflow', (SELECT exceeded FROM transport_budget),
    'accepted', (
        SELECT {postgres_accepted_json_sql(context_identity=context_identity)}
        FROM accepted_run acc
        WHERE NOT (SELECT exceeded FROM transport_budget)
    ),
    'has_node', EXISTS (SELECT 1 FROM target_node),
    'node', (
        SELECT json_build_object(
            'id', tn.id,
            'metadata_json', tn.metadata_json,
            'first_seen_run_id', tn.first_seen_run_id,
            'last_seen_run_id', tn.last_seen_run_id{extra_node_cols}
        )
        FROM target_node tn
        WHERE NOT (SELECT exceeded FROM transport_budget)
    ),
    'selected_run_id', (SELECT run_id FROM selected_run),
    'current_rows', COALESCE(
        (SELECT json_agg(row_to_json(cw)) FROM current_window cw
         WHERE NOT (SELECT exceeded FROM transport_budget)),
        '[]'::json
    ),
    'historical_rows', COALESCE(
        (SELECT json_agg(row_to_json(hw)) FROM historical_window hw
         WHERE NOT (SELECT exceeded FROM transport_budget)),
        '[]'::json
    )
)::text;"""


def _row_tuple_from_json(
    raw: Mapping[str, Any], *, include_role: bool, context_identity: bool = False
) -> tuple[Any, ...]:
    raw_vector = raw.get("snapshot_vector_json")
    if context_identity:
        raw_vector = _parse_context_snapshot_vector(raw_vector)
    base: tuple[Any, ...] = (
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
        _compact_json_str(raw.get("metadata_json")),
        raw.get("publication_bundle_id"),
        raw.get("snapshot_manifest_id"),
        raw.get("extraction_receipt_id"),
        raw.get("graph_candidate_id"),
        _compact_json_str(raw_vector or "[]"),
    )
    if include_role:
        return (*base, raw.get("evidence_role"))
    return base


def read_postgres_node_locations_with_executor(
    query: NodeLocationsQuery,
    *,
    executor: Callable[[str], Any],
    root_path: str = "",
    repository_identity: str | None = None,
    role_sql: str = _EVIDENCE_ROLE_SQL,
    context_identity: bool = False,
) -> dict[str, Any]:
    """Execute single-statement PostgreSQL node_locations using an injected SQL JSON executor."""
    query.validate()
    sql = build_postgres_node_locations_sql(
        query,
        repository_identity=repository_identity,
        root_path=root_path,
        role_sql=role_sql,
        context_identity=context_identity,
    )
    payload = executor(sql)
    if not isinstance(payload, dict):
        raise StorageSchemaError("malformed PostgreSQL node locations readback")
    if not payload.get("has_accepted"):
        return unavailable("publication_absent")
    if payload.get("transport_overflow"):
        return unavailable("admission_work_limit")
    if not payload.get("has_node"):
        res = unavailable("node_not_found")
        if context_identity and isinstance(payload.get("accepted"), Mapping):
            res["accepted_publication"] = format_postgres_accepted_publication(
                payload["accepted"], context_identity=True
            )
        return res

    accepted = payload["accepted"]
    accepted_run_id = int(accepted["run_id"])
    node_obj = payload["node"]
    node_tuple = (
        int(node_obj["id"]),
        _compact_json_str(node_obj.get("metadata_json")),
        int(node_obj["first_seen_run_id"]),
        int(node_obj["last_seen_run_id"]),
    )
    selected_run_id = payload.get("selected_run_id")
    loc_run_id = int(selected_run_id) if selected_run_id is not None else None
    include_role = query.evidence_role != "all"

    cur_tuples = [
        _row_tuple_from_json(r, include_role=include_role, context_identity=context_identity)
        for r in (payload.get("current_rows") or ())
        if isinstance(r, Mapping)
    ]
    hist_tuples = [
        _row_tuple_from_json(r, include_role=include_role, context_identity=context_identity)
        for r in (payload.get("historical_rows") or ())
        if isinstance(r, Mapping)
    ]
    result: dict[str, Any] = {
        "status": "ok",
        "reason": None,
        "locations": [
            _location(row, accepted_run_id, context_identity=context_identity)
            for row in cur_tuples[: query.limit]
        ],
        "historical_locations": [
            _location(row, accepted_run_id, context_identity=context_identity)
            for row in hist_tuples[: query.limit]
        ],
        "historical_has_more": len(hist_tuples) > query.limit,
        "location_run_id": loc_run_id,
        "location_scope": _relation(loc_run_id, accepted_run_id) if loc_run_id is not None else "unavailable",
        "metadata_location": _metadata_location(node_tuple),
        "has_more": len(cur_tuples) > query.limit,
        "node_first_seen_run_id": node_tuple[2],
        "node_last_seen_run_id": node_tuple[3],
        "accepted_publication": format_postgres_accepted_publication(
            accepted, context_identity=context_identity
        ),
    }
    if context_identity:
        result["node_kind"] = str(node_obj.get("kind") or "")
        result["node_display_name"] = node_obj.get("display_name")
    return result


def query_postgres_node_locations(
    psql_args: Sequence[str],
    *,
    query: NodeLocationsQuery,
    psql_command: str = "psql",
    password: str | None = None,
    root_path: str = "",
    repository_identity: str | None = None,
    role_sql: str = _EVIDENCE_ROLE_SQL,
    context_identity: bool = False,
) -> dict[str, Any]:
    """Execute single-statement PostgreSQL node_locations readback with SQLite wire parity."""
    return read_postgres_node_locations_with_executor(
        query,
        executor=lambda sql: execute_json_readback(
            sql,
            psql_args=psql_args,
            psql_command=psql_command,
            label="node locations",
            expected_shape="object",
            password=password,
        ),
        root_path=root_path,
        repository_identity=repository_identity,
        role_sql=role_sql,
        context_identity=context_identity,
    )


__all__ = [
    "build_postgres_node_locations_sql",
    "query_postgres_node_locations",
    "read_postgres_node_locations_with_executor",
]
