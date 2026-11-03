"""Bounded accepted-publication raw-observation reads for evaluator arms."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter_ns
from typing import Any

from common_lore_index.ops.config_local import (
    LocalSqliteConfig,
    load_graph_registry_config_home,
    local_graph_binding,
    sqlite_graph_database_path,
)
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.storage.context_postgres_identity import (
    format_postgres_accepted_publication,
    postgres_accepted_json_sql,
    postgres_accepted_run_cte_sql,
    postgres_repo_predicate_sql,
)
from common_lore_index.storage.graph_readback_sql import (
    escape_readback_like_pattern,
)
from common_lore_index.storage.readback_driver import execute_json_readback
from common_lore_index.storage.sql_core import sql_literal
from common_lore_index.storage.sqlite_local import raw_payload
from common_lore_index.storage.sqlite_local.connection import read_transaction
from common_lore_index.storage.sqlite_local.context_expansion_queries import (
    read_sqlite_context_publication,
)
from retrieval_evaluation_observation_contracts import (
    CurrentObservationReadError, ObservationPublicationPin,
)
from retrieval_evaluation_correspondence_observation_records import (
    CurrentObservationQuery,
    FencedObservationResult,
    _matches,
    _page_rows,
    _postgres_candidate,
    _snapshot_map,
    _validate_metadata,
    _validate_selected_bindings,
)

def _verify_pin(
    expected: ObservationPublicationPin | None,
    *, backend: str, graph_id: str, repository_identity: str,
    run_id: int, generation: int, bundle: str, manifest: str,
) -> None:
    if expected is None:
        return
    if (expected.backend, expected.graph_id, expected.repository_identity) != (backend, graph_id, repository_identity):
        raise CurrentObservationReadError("fenced_observation_pin_mismatch", "publication pin scope differs from store readback")
    if (expected.run_id, expected.generation, expected.publication_bundle_id, expected.snapshot_manifest_id) != (run_id, generation, bundle, manifest):
        raise CurrentObservationReadError("fenced_observation_pin_mismatch", "publication pin is stale")
    try:
        expected.revalidate_current()
    except Exception as error:
        raise CurrentObservationReadError("fenced_observation_pin_mismatch", "bound publication failed live revalidation") from error


def _sqlite_identity(connection: Any, expected_binding: Any, graph_id: str) -> Any:
    identity = read_sqlite_context_publication(connection)
    if identity is None:
        raise CurrentObservationReadError("missing_accepted_publication", "SQLite has no accepted publication")
    if identity.graph_id != graph_id or identity.repository_id != expected_binding.repository_identity:
        raise CurrentObservationReadError("sqlite_binding_mismatch", "SQLite graph binding differs from configured graph")
    return identity


def _sqlite_observation_statement(
    request: CurrentObservationQuery, run_id: int
) -> tuple[str, list[Any]]:
    clauses = ["run_id = ?"]
    params: list[Any] = [run_id]
    if request.kind is not None:
        clauses.append("kind = ?")
        params.append(request.kind)
    if request.path is not None:
        clauses.append("path = ?")
        params.append(request.path)
    return (
        "SELECT ordinal, kind, source_id, path, payload_json FROM raw_observations WHERE "
        + " AND ".join(clauses) + " ORDER BY ordinal",
        params,
    )


def _scan_sqlite_observations(
    cursor: Any,
    request: CurrentObservationQuery,
    snapshots: Mapping[str, tuple[int, str]],
    selected: set[str],
    fetch_limit: int,
) -> tuple[list[tuple[Mapping[str, Any], Any]], bool, int]:
    candidates: list[tuple[Mapping[str, Any], Any]] = []
    known_payload_bytes = 0
    has_more = False
    try:
        for ordinal, kind, source_id, row_path, text in cursor:
            payload = raw_payload.load(str(text))
            known_payload_bytes += len(str(text).encode("utf-8"))
            if not _matches(request, {"kind": kind, "source_id": source_id, "path": row_path}, payload):
                continue
            metadata = _validate_metadata(payload, snapshots)
            binding_id = str(metadata["binding_id"])
            relative = str(metadata["source_relative_path"])
            if selected and binding_id not in selected:
                continue
            if request.source_path_prefix and not (
                relative == request.source_path_prefix
                or relative.startswith(request.source_path_prefix + "/")
            ):
                continue
            if len(candidates) >= fetch_limit:
                has_more = True
                continue
            candidates.append((
                {"ordinal": int(ordinal), "kind": str(kind), "source_id": str(source_id), "path": str(row_path)},
                payload,
            ))
            if len(candidates) >= fetch_limit:
                has_more = True
    finally:
        cursor.close()
    return candidates, has_more, known_payload_bytes


def _sqlite_query(
    config: LocalSqliteConfig, request: CurrentObservationQuery, graph_id: str,
    expected_pin: ObservationPublicationPin | None,
) -> FencedObservationResult:
    graph = next((item for item in config.graphs if item.id == graph_id), None)
    if graph is None:
        raise CurrentObservationReadError("graph_id_mismatch", "unknown SQLite graph")
    binding = local_graph_binding(graph)
    path = sqlite_graph_database_path(config, graph)
    fence_elapsed_ns = 0
    query_statement_ns: int | None = None
    snapshots: Mapping[str, tuple[int, str]]
    with read_transaction(path, binding) as connection:
        identity = _sqlite_identity(connection, binding, graph_id)
        fence_started = perf_counter_ns()
        _verify_pin(expected_pin, backend="sqlite", graph_id=graph_id, repository_identity=identity.repository_id, run_id=identity.run_id, generation=identity.generation, bundle=identity.publication_bundle_id, manifest=identity.snapshot_manifest_id)
        fence_elapsed_ns += perf_counter_ns() - fence_started
        snapshots = _snapshot_map(identity.snapshot_vector)
        _validate_selected_bindings(request, snapshots)
        selected = set(request.selected_binding_ids)
        statement, params = _sqlite_observation_statement(request, identity.run_id)
        fetch_limit = request.offset + request.limit + 1
        statement_started = perf_counter_ns()
        cursor = connection.execute(statement, params)
        query_statement_ns = perf_counter_ns() - statement_started
        candidates, has_more, known_payload_bytes = _scan_sqlite_observations(
            cursor, request, snapshots, selected, fetch_limit
        )
    rows, omissions, complete, has_more = _page_rows(
        request, candidates, snapshots, has_more=has_more,
    )
    post_fence_started = perf_counter_ns()
    marker = _read_sqlite_marker(config, graph_id)
    if marker != (identity.run_id, identity.generation, identity.publication_bundle_id, identity.snapshot_manifest_id):
        raise CurrentObservationReadError("stale_publication_receipt", "SQLite publication advanced during observation query")
    _verify_pin(expected_pin, backend="sqlite", graph_id=graph_id, repository_identity=identity.repository_id, run_id=identity.run_id, generation=identity.generation, bundle=identity.publication_bundle_id, manifest=identity.snapshot_manifest_id)
    fence_elapsed_ns += perf_counter_ns() - post_fence_started
    return FencedObservationResult(
        "sqlite", graph_id, identity.repository_id, identity.run_id, identity.generation,
        identity.publication_bundle_id, identity.snapshot_manifest_id, rows, omissions,
        complete, has_more, fence_elapsed_ns, query_statement_ns, known_payload_bytes, None,
    )


def _read_sqlite_marker(config: LocalSqliteConfig, graph_id: str) -> tuple[int, int, str, str]:
    graph = next(item for item in config.graphs if item.id == graph_id)
    binding = local_graph_binding(graph)
    with read_transaction(sqlite_graph_database_path(config, graph), binding) as connection:
        identity = _sqlite_identity(connection, binding, graph_id)
        return identity.run_id, identity.generation, identity.publication_bundle_id, identity.snapshot_manifest_id


def _postgres_marker(config: OpsConfig, graph_id: str, psql_command: str) -> tuple[dict[str, Any], dict[str, str]]:
    graph = next((item for item in config.graphs if item.id == graph_id), None)
    if graph is None:
        raise CurrentObservationReadError("graph_id_mismatch", "unknown PostgreSQL graph")
    binding = local_graph_binding(graph)
    database = graph.database or config.postgres.database
    args = config.postgres.psql_args_for_database(database)
    predicate = postgres_repo_predicate_sql(binding.repository_identity, str(binding.root_path), context_identity=True)
    sql = f"WITH matched_repo AS MATERIALIZED (SELECT repo.id AS repository_id FROM public.repositories repo WHERE {predicate} ORDER BY repo.id DESC LIMIT 1),\n{postgres_accepted_run_cte_sql(context_identity=True)}\nSELECT json_build_object('accepted', (SELECT {postgres_accepted_json_sql(context_identity=True)} FROM accepted_run acc))::text;"
    value = execute_json_readback(sql, psql_args=args, psql_command=psql_command, label="w5_current_marker", expected_shape="object", password=config.postgres.password)
    accepted = value.get("accepted") if isinstance(value, Mapping) else None
    if not isinstance(accepted, Mapping):
        raise CurrentObservationReadError("missing_accepted_publication", "PostgreSQL has no accepted publication")
    formatted = format_postgres_accepted_publication(accepted, context_identity=True)
    return formatted, {"repository_identity": binding.repository_identity, "database": database}


def _postgres_valid_metadata_sql(snapshots: Mapping[str, tuple[int, str]]) -> str:
    """Identify invalid matching metadata before caller scope can hide it.

    Only one invalid witness is returned. Valid rows still receive selection
    and prefix filtering before pagination; database scan I/O remains unknown.
    """
    metadata = "ro.payload_json->'metadata'"
    relative = f"{metadata}->>'source_relative_path'"
    identities = " OR ".join(
        f"({metadata}->>'binding_id' = {sql_literal(binding)} AND "
        f"{metadata}->>'binding_revision' = {sql_literal(str(revision))} AND "
        f"{metadata}->>'snapshot_id' = {sql_literal(snapshot)})"
        for binding, (revision, snapshot) in sorted(snapshots.items())
    ) or "FALSE"
    return (
        f"jsonb_typeof({metadata}) = 'object' AND "
        f"jsonb_typeof({metadata}->'binding_id') = 'string' AND "
        f"jsonb_typeof({metadata}->'binding_revision') = 'number' AND "
        f"jsonb_typeof({metadata}->'snapshot_id') = 'string' AND "
        f"jsonb_typeof({metadata}->'source_relative_path') = 'string' AND "
        f"({identities}) AND {relative} <> '' AND left({relative}, 1) <> '/' AND "
        f"strpos({relative}, chr(92)) = 0 AND "
        f"NOT (string_to_array({relative}, '/') && ARRAY['', '.', '..'])"
    )


def _postgres_observation_sql(
    request: CurrentObservationQuery,
    before: Mapping[str, Any],
    before_snapshots: Mapping[str, tuple[int, str]],
    predicate: str,
    fetch_limit: int,
) -> str:
    pattern = sql_literal("%" + escape_readback_like_pattern(request.query) + "%")
    filters = [
        f"ro.run_id = {int(before['run_id'])}",
        f"(ro.kind ILIKE {pattern} ESCAPE '\\' OR ro.source_id ILIKE {pattern} ESCAPE '\\' OR ro.path ILIKE {pattern} ESCAPE '\\' OR ro.payload_json::text ILIKE {pattern} ESCAPE '\\')",
    ]
    if request.kind is not None:
        filters.append(f"ro.kind = {sql_literal(request.kind)}")
    if request.path is not None:
        filters.append(f"ro.path = {sql_literal(request.path)}")
    matching_where = " AND ".join(filters)
    filters = []
    if request.selected_binding_ids:
        selected_sql = ", ".join(sql_literal(binding) for binding in request.selected_binding_ids)
        filters.append(f"ro.payload_json->'metadata'->>'binding_id' IN ({selected_sql})")
    if request.source_path_prefix is not None:
        prefix = sql_literal(request.source_path_prefix)
        prefix_pattern = sql_literal(
            escape_readback_like_pattern(request.source_path_prefix + "/") + "%"
        )
        filters.append(
            f"(ro.payload_json->'metadata'->>'source_relative_path' = {prefix} OR "
            f"ro.payload_json->'metadata'->>'source_relative_path' LIKE {prefix_pattern} ESCAPE '\\')"
        )
    selected_where = " AND ".join(filters) or "TRUE"
    valid_metadata = _postgres_valid_metadata_sql(before_snapshots)
    columns = "ro.ordinal, ro.kind, ro.source_id, ro.path, ro.payload_json AS payload"
    return (
        f"WITH matched_repo AS MATERIALIZED (SELECT repo.id AS repository_id FROM public.repositories repo WHERE {predicate} ORDER BY repo.id DESC LIMIT 1),\n"
        f"{postgres_accepted_run_cte_sql(context_identity=True)},\n"
        f"matching_rows AS MATERIALIZED (SELECT ro.* FROM public.raw_observations ro JOIN accepted_run acc ON acc.repository_id = ro.repository_id AND acc.run_id = ro.run_id WHERE {matching_where})\n"
        f"SELECT json_build_object('accepted', (SELECT {postgres_accepted_json_sql(context_identity=True)} FROM accepted_run acc), "
        f"'invalid_rows', COALESCE((SELECT json_agg(row_to_json(invalid)) FROM (SELECT {columns} FROM matching_rows ro WHERE NOT COALESCE(({valid_metadata}), FALSE) ORDER BY ro.ordinal LIMIT 1) invalid), '[]'::json), "
        f"'rows', COALESCE((SELECT json_agg(row_to_json(rows)) FROM (SELECT {columns} FROM matching_rows ro WHERE {selected_where} ORDER BY ro.ordinal LIMIT {fetch_limit}) rows), '[]'::json))::text;"
    )


def _postgres_readback_candidates(
    value: Any,
    before: Mapping[str, Any],
    request: CurrentObservationQuery,
) -> tuple[
    Mapping[str, Any],
    Mapping[str, tuple[int, str]],
    list[Any],
    list[tuple[Mapping[str, Any], Any]],
]:
    accepted = value.get("accepted") if isinstance(value, Mapping) else None
    raw_rows = value.get("rows") if isinstance(value, Mapping) else None
    if not isinstance(accepted, Mapping) or not isinstance(raw_rows, list):
        raise CurrentObservationReadError(
            "malformed_observation_readback",
            "PostgreSQL observation envelope is invalid",
        )
    formatted = format_postgres_accepted_publication(accepted, context_identity=True)
    if int(formatted["run_id"]) != int(before["run_id"]):
        raise CurrentObservationReadError(
            "stale_publication_receipt",
            "PostgreSQL publication advanced during observation query",
        )
    vector = _snapshot_map(formatted["snapshot_vector"])
    _validate_selected_bindings(request, vector)
    invalid_rows = value.get("invalid_rows") if isinstance(value, Mapping) else None
    if not isinstance(invalid_rows, list) or len(invalid_rows) > 1:
        raise CurrentObservationReadError(
            "malformed_observation_readback",
            "invalid metadata witness is malformed",
        )
    for raw in invalid_rows:
        _row, payload = _postgres_candidate(raw)
        _validate_metadata(payload, vector)
        raise CurrentObservationReadError(
            "malformed_observation_metadata",
            "invalid metadata witness disagrees with readback",
        )
    candidates: list[tuple[Mapping[str, Any], Any]] = []
    for raw in raw_rows:
        candidates.append(_postgres_candidate(raw))
    return formatted, vector, raw_rows, candidates


def _postgres_query(config: OpsConfig, request: CurrentObservationQuery, graph_id: str, expected_pin: ObservationPublicationPin | None, psql_command: str) -> FencedObservationResult:
    graph = next((item for item in config.graphs if item.id == graph_id), None)
    if graph is None:
        raise CurrentObservationReadError("graph_id_mismatch", "unknown PostgreSQL graph")
    binding = local_graph_binding(graph)
    database = graph.database or config.postgres.database
    args = config.postgres.psql_args_for_database(database)
    predicate = postgres_repo_predicate_sql(binding.repository_identity, str(binding.root_path), context_identity=True)
    fence_elapsed_ns = 0
    query_statement_ns: int | None = None
    fence_started = perf_counter_ns()
    before, _ = _postgres_marker(config, graph_id, psql_command)
    _verify_pin(expected_pin, backend="postgresql", graph_id=graph_id, repository_identity=binding.repository_identity, run_id=int(before["run_id"]), generation=int(before["generation"]), bundle=str(before["publication_bundle_id"]), manifest=str(before["snapshot_manifest_id"]))
    fence_elapsed_ns += perf_counter_ns() - fence_started
    before_snapshots = _snapshot_map(before["snapshot_vector"])
    _validate_selected_bindings(request, before_snapshots)
    fetch_limit = request.offset + request.limit + 1
    sql = _postgres_observation_sql(
        request, before, before_snapshots, predicate, fetch_limit
    )
    statement_started = perf_counter_ns()
    value = execute_json_readback(sql, psql_args=args, psql_command=psql_command, label="w5_current_observations", expected_shape="object", password=config.postgres.password)
    query_statement_ns = perf_counter_ns() - statement_started
    formatted, vector, raw_rows, candidates = _postgres_readback_candidates(
        value, before, request
    )
    rows, omissions, complete, has_more = _page_rows(
        request, candidates, vector, has_more=len(raw_rows) > request.offset + request.limit,
    )
    fence_started = perf_counter_ns()
    after, _ = _postgres_marker(config, graph_id, psql_command)
    if (int(after["run_id"]), int(after["generation"]), str(after["publication_bundle_id"]), str(after["snapshot_manifest_id"])) != (int(before["run_id"]), int(before["generation"]), str(before["publication_bundle_id"]), str(before["snapshot_manifest_id"])):
        raise CurrentObservationReadError("stale_publication_receipt", "PostgreSQL publication advanced after observation query")
    _verify_pin(expected_pin, backend="postgresql", graph_id=graph_id, repository_identity=binding.repository_identity, run_id=int(after["run_id"]), generation=int(after["generation"]), bundle=str(after["publication_bundle_id"]), manifest=str(after["snapshot_manifest_id"]))
    fence_elapsed_ns += perf_counter_ns() - fence_started
    return FencedObservationResult(
        "postgresql", graph_id, binding.repository_identity, int(formatted["run_id"]),
        int(formatted["generation"]), str(formatted["publication_bundle_id"]),
        str(formatted["snapshot_manifest_id"]), rows, omissions, complete, has_more,
        fence_elapsed_ns, query_statement_ns, None, None,
    )


def query_fenced_current_observations(
    config_or_home: LocalSqliteConfig | OpsConfig | Path,
    *, graph_id: str, query: str, kind: str | None = None, path: str | None = None,
    limit: int = 10, offset: int = 0, selected_binding_ids: Sequence[str] = (),
    source_path_prefix: str | None = None, expected_pin: ObservationPublicationPin | None = None,
    psql_command: str = "psql",
) -> FencedObservationResult:
    request = CurrentObservationQuery(query, kind, path, limit, offset, tuple(selected_binding_ids), source_path_prefix).validate()
    config = load_graph_registry_config_home(config_or_home) if isinstance(config_or_home, Path) else config_or_home
    if isinstance(config, LocalSqliteConfig):
        return _sqlite_query(config, request, graph_id, expected_pin)
    if isinstance(config, OpsConfig):
        return _postgres_query(config, request, graph_id, expected_pin, psql_command)
    raise TypeError(f"unsupported config type: {type(config)!r}")


__all__ = ["CurrentObservationQuery", "FencedObservationResult", "query_fenced_current_observations"]
