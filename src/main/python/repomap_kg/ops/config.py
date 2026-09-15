"""Operations configuration facade and storage-status readback."""

from __future__ import annotations

from typing import Any, Mapping, Sequence, cast

from repomap_kg.ops.config_loading import (
    DEFAULT_REPOMAP_HOME as DEFAULT_REPOMAP_HOME,
    GRAPH_ID_PATTERN as GRAPH_ID_PATTERN,
    KNOWN_POSTGRES_FIELDS as KNOWN_POSTGRES_FIELDS,
    KNOWN_RUNTIME_FIELDS as KNOWN_RUNTIME_FIELDS,
    KNOWN_RUNTIME_POSTGRES_FIELDS as KNOWN_RUNTIME_POSTGRES_FIELDS,
    KNOWN_SERVER_MEMORY_FIELDS as KNOWN_SERVER_MEMORY_FIELDS,
    KNOWN_SERVICE_FIELDS as KNOWN_SERVICE_FIELDS,
    KNOWN_TOP_LEVEL_SECTIONS as KNOWN_TOP_LEVEL_SECTIONS,
    OpsConfig as OpsConfig,
    OpsConfigDiagnostic as OpsConfigDiagnostic,
    OpsConfigError as OpsConfigError,
    OpsGraphConfig as OpsGraphConfig,
    OpsGraphSourceBindingConfig as OpsGraphSourceBindingConfig,
    OpsGraphStorageStatus as OpsGraphStorageStatus,
    OpsPostgresConfig as OpsPostgresConfig,
    OpsPostgresStatus as OpsPostgresStatus,
    OpsRuntimeConfig as OpsRuntimeConfig,
    OpsRuntimePostgresConfig as OpsRuntimePostgresConfig,
    OpsServerMemoryConfig as OpsServerMemoryConfig,
    OpsServiceConfig as OpsServiceConfig,
    OpsSourcePlaceholder as OpsSourcePlaceholder,
    OpsSourcesConfig as OpsSourcesConfig,
    PRIVATE_PRIVACY as PRIVATE_PRIVACY,
    Path as Path,
    REDACTED as REDACTED,
    SAFE_POSTGRES_DATABASE_PATTERN as SAFE_POSTGRES_DATABASE_PATTERN,
    SECRET_KEY_PARTS as SECRET_KEY_PARTS,
    SUPPORTED_CONTAINER_RUNTIMES as SUPPORTED_CONTAINER_RUNTIMES,
    SUPPORTED_LOG_LEVELS as SUPPORTED_LOG_LEVELS,
    SUPPORTED_MCP_TRANSPORTS as SUPPORTED_MCP_TRANSPORTS,
    SUPPORTED_PRIVACY as SUPPORTED_PRIVACY,
    SUPPORTED_REFRESH_POLICIES as SUPPORTED_REFRESH_POLICIES,
    SUPPORTED_SCHEMA_VERSION as SUPPORTED_SCHEMA_VERSION,
    SUPPORTED_SERVER_MEMORY_MODES as SUPPORTED_SERVER_MEMORY_MODES,
    SUPPORTED_SERVICE_MODES as SUPPORTED_SERVICE_MODES,
    annotations as annotations,
    bool_text as bool_text,
    build_ops_config_from_payload as build_ops_config_from_payload,
    expand_user_path as expand_user_path,
    format_counts as format_counts,
    format_ops_config_status_table as format_ops_config_status_table,
    format_ops_graph_registry_table as format_ops_graph_registry_table,
    graph_database_source as graph_database_source,
    graph_psql_args as graph_psql_args,
    graph_storage_label as graph_storage_label,
    is_credentialed_url as is_credentialed_url,
    is_secret_key as is_secret_key,
    json as json,
    load_ops_config as load_ops_config,
    load_ops_config_home as load_ops_config_home,
    merge_ops_config_payloads as merge_ops_config_payloads,
    ops_config_status_to_jsonable as ops_config_status_to_jsonable,
    ops_graph_registry_status_to_jsonable as ops_graph_registry_status_to_jsonable,
    optional_bool as optional_bool,
    optional_int as optional_int,
    optional_text as optional_text,
    os as os,
    parse_graph_exclude_paths as parse_graph_exclude_paths,
    parse_graphs_section as parse_graphs_section,
    parse_postgres_section as parse_postgres_section,
    parse_psql_json as parse_psql_json,
    parse_runtime_section as parse_runtime_section,
    parse_server_memory_section as parse_server_memory_section,
    parse_service_section as parse_service_section,
    parse_source_placeholders as parse_source_placeholders,
    parse_sources_section as parse_sources_section,
    read_toml_payload as read_toml_payload,
    redact_mapping as redact_mapping,
    redact_text as redact_text,
    redact_value as redact_value,
    require_mapping as require_mapping,
    required_bool as required_bool,
    required_int as required_int,
    required_text as required_text,
    resolve_ops_config as resolve_ops_config,
    resolve_repo_map_home as resolve_repo_map_home,
    run_psql as run_psql,
    tomllib as tomllib,
    unknown_field_diagnostics as unknown_field_diagnostics,
    unknown_file_field_diagnostics as unknown_file_field_diagnostics,
    unknown_top_level_diagnostics as unknown_top_level_diagnostics,
    validate_file_schema as validate_file_schema,
)
from repomap_kg.ops.config_status import graph_database
from repomap_kg.ops.readback import execute_ops_json_readback
from repomap_kg.storage import StorageSchemaError, sql_literal


def check_ops_postgres_status(
    config: OpsConfig,
    *,
    psql_command: str | None = None,
    database: str | None = None,
) -> OpsPostgresStatus:
    effective_database = database or config.postgres.database
    try:
        payload = cast(
            dict[str, Any],
            execute_ops_json_readback(
                config,
                database=effective_database,
                sql=build_postgres_status_sql(),
                label="operations postgres status",
                expected_shape="object",
                mode="host_only",
                psql_command=psql_command,
            ),
        )
    except StorageSchemaError as error:
        return OpsPostgresStatus(
            db_checked=True,
            connected=False,
            schema_available=False,
            required_tables={},
            error=str(error),
        )
    required_tables = payload.get("required_tables", {})
    if not isinstance(required_tables, dict):
        required_tables = {}
    return OpsPostgresStatus(
        db_checked=True,
        connected=bool(payload.get("connected")),
        schema_available=bool(payload.get("schema_available")),
        required_tables={key: bool(value) for key, value in required_tables.items()},
        error=None,
    )


def build_postgres_status_sql() -> str:
    tables = (
        "repositories",
        "runs",
        "files",
        "raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "canonical_evidence",
        "canonical_node_evidence",
        "canonical_edge_evidence",
    )
    table_checks = ", ".join(
        f"'{table}', to_regclass('public.{table}') IS NOT NULL" for table in tables
    )
    all_checks = " AND ".join(
        f"to_regclass('public.{table}') IS NOT NULL" for table in tables
    )
    return (
        "SELECT json_build_object("
        "'connected', true, "
        f"'schema_available', ({all_checks}), "
        f"'required_tables', json_build_object({table_checks})"
        ")::text;"
    )


def check_ops_graph_storage_status(
    config: OpsConfig,
    *,
    psql_command: str | None = None,
) -> dict[str, OpsGraphStorageStatus]:
    statuses: dict[str, OpsGraphStorageStatus] = {}
    graphs_by_database: dict[str, list[OpsGraphConfig]] = {}
    for graph in config.graphs:
        if graph.readback_unsupported_classification is not None:
            statuses[graph.id] = OpsGraphStorageStatus(
                db_checked=False,
                repository_name=graph.repository_name_display,
                database=graph_database(config, graph),
                repository_exists=None,
                error=graph.readback_unsupported_classification,
            )
            continue
        graphs_by_database.setdefault(graph_database(config, graph), []).append(graph)

    for database, graphs in graphs_by_database.items():
        postgres_status = check_ops_postgres_status(
            config,
            psql_command=psql_command,
            database=database,
        )
        if not postgres_status.connected or not postgres_status.schema_available:
            for graph in graphs:
                statuses[graph.id] = OpsGraphStorageStatus(
                    db_checked=True,
                    repository_name=graph.repository_name,
                    database=database,
                    schema_available=bool(postgres_status.schema_available),
                    repository_exists=False,
                    error=postgres_status.error,
                )
            continue

        try:
            payload = cast(
                dict[str, Any],
                execute_ops_json_readback(
                    config,
                    database=database,
                    sql=build_graph_storage_status_sql(
                        [graph.repository_name for graph in graphs]
                    ),
                    label="operations graph storage status",
                    expected_shape="object",
                    mode="host_only",
                    psql_command=psql_command,
                ),
            )
        except StorageSchemaError as error:
            for graph in graphs:
                statuses[graph.id] = OpsGraphStorageStatus(
                    db_checked=True,
                    repository_name=graph.repository_name,
                    database=database,
                    schema_available=True,
                    repository_exists=False,
                    error=str(error),
                )
            continue

        rows = payload.get("graphs", [])
        if not isinstance(rows, list):
            rows = []
        by_repository: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("repository_name"), str):
                by_repository[row["repository_name"]] = row
        for graph in graphs:
            row = by_repository.get(graph.repository_name, {})
            repository_id = row.get("repository_id")
            statuses[graph.id] = OpsGraphStorageStatus(
                db_checked=True,
                repository_name=graph.repository_name,
                database=database,
                schema_available=True,
                repository_exists=bool(row.get("repository_exists")),
                repository_id=repository_id if isinstance(repository_id, int) else None,
                raw_observations=int(row.get("raw_observations") or 0),
                raw_observations_total=int(
                    row.get("raw_observations_total", row.get("raw_observations")) or 0
                ),
                latest_run_raw_observations=int(
                    row.get("latest_run_raw_observations") or 0
                ),
                canonical_nodes=int(row.get("canonical_nodes") or 0),
                canonical_edges=int(row.get("canonical_edges") or 0),
            )
    return statuses


def build_graph_storage_status_sql(repository_names: Sequence[str]) -> str:
    if repository_names:
        values = ", ".join(
            f"({sql_literal(repository_name)})"
            for repository_name in repository_names
        )
        configured = f"configured(repository_name) AS (VALUES {values})"
    else:
        configured = (
            "configured(repository_name) AS ("
            "SELECT NULL::text AS repository_name WHERE false)"
        )
    return (
        f"WITH {configured}, "
        "repo AS ("
        "SELECT configured.repository_name, repositories.id AS repository_id "
        "FROM configured "
        "LEFT JOIN repositories "
        "ON repositories.name = configured.repository_name"
        "), "
        "latest_recorded_run AS ("
        "SELECT DISTINCT ON (repo.repository_name) "
        "repo.repository_name, runs.* "
        "FROM repo "
        "JOIN runs ON runs.repository_id = repo.repository_id "
        "ORDER BY repo.repository_name, runs.id DESC"
        ") "
        "SELECT json_build_object("
        "'graphs', COALESCE(json_agg(json_build_object("
        "'repository_name', repo.repository_name, "
        "'repository_exists', repo.repository_id IS NOT NULL, "
        "'repository_id', repo.repository_id, "
        "'raw_observations', ("
        "SELECT COUNT(*) FROM raw_observations "
        "WHERE raw_observations.repository_id = repo.repository_id"
        "), "
        "'raw_observations_total', ("
        "SELECT COUNT(*) FROM raw_observations "
        "WHERE raw_observations.repository_id = repo.repository_id"
        "), "
        "'latest_run_raw_observations', ("
        "SELECT COUNT(*) FROM raw_observations "
        "WHERE raw_observations.repository_id = repo.repository_id "
        "AND raw_observations.run_id = (SELECT id FROM latest_recorded_run "
        "WHERE repository_name = repo.repository_name)"
        "), "
        "'canonical_nodes', ("
        "SELECT COUNT(*) FROM canonical_nodes "
        "WHERE canonical_nodes.repository_id = repo.repository_id"
        "), "
        "'canonical_edges', ("
        "SELECT COUNT(*) FROM canonical_edges "
        "WHERE canonical_edges.repository_id = repo.repository_id"
        ")"
        ") ORDER BY repo.repository_name), '[]'::json)"
        ")::text FROM repo;"
    )
