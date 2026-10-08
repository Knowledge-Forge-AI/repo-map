"""Status projection helpers for RepoMap local operations config."""

from __future__ import annotations

from repomap_kg.runtime.postgres_route import execution_postgres

from typing import Any, Mapping

from repomap_kg.ops.config_helpers import (
    REDACTED,
    bool_text,
    format_counts,
)
from repomap_kg.ops.config_records import (
    PRIVATE_DATABASE_DISPLAY,
    OpsConfig,
    OpsGraphConfig,
    OpsGraphStorageStatus,
    OpsPostgresStatus,
)
from repomap_kg.ops._registry_status import (
    LOCAL_CONFIG_DISPLAY as LOCAL_CONFIG_DISPLAY,
    config_status_base,
    graph_registry_payload,
)
from repomap_kg.ops.resolved_config import resolve_ops_config


def graph_database(config: OpsConfig, graph: OpsGraphConfig) -> str:
    """Return the effective storage database for a configured graph."""

    return str(resolve_ops_config(config).graph(graph.id).database)


def graph_database_source(graph: OpsGraphConfig) -> str:
    return "graph" if graph.database else "postgres-default"


def graph_psql_args(config: OpsConfig, graph: OpsGraphConfig) -> list[str]:
    return execution_postgres(config).psql_args_for_database(graph_database(config, graph))


def ops_config_status_to_jsonable(
    config: OpsConfig,
    *,
    postgres_status: OpsPostgresStatus | None = None,
) -> dict[str, Any]:
    db_status = postgres_status or OpsPostgresStatus.unchecked()
    payload = config_status_base(config)
    payload["postgres"] = config.postgres.to_jsonable()
    payload["runtime"] = config.runtime.to_jsonable()
    payload["postgres_status"] = db_status.to_jsonable()
    return payload


def ops_graph_registry_status_to_jsonable(
    config: OpsConfig,
    *,
    graph_storage_status: Mapping[str, OpsGraphStorageStatus] | None = None,
) -> dict[str, Any]:
    storage_status = graph_storage_status or {}

    def storage_fields(graph: OpsGraphConfig, private: bool) -> dict[str, Any]:
        return {
            "database": (
                PRIVATE_DATABASE_DISPLAY if private else graph_database(config, graph)
            ),
            "database_source": graph_database_source(graph),
            "storage_status": _graph_storage_status_to_jsonable(
                config, graph, storage_status.get(graph.id), private=private
            ),
        }

    return graph_registry_payload(
        config,
        storage_fields,
        db_checked=any(status.db_checked for status in storage_status.values()),
    )


def _graph_storage_status_to_jsonable(
    config: OpsConfig,
    graph: OpsGraphConfig,
    status: OpsGraphStorageStatus | None,
    *,
    private: bool,
) -> dict[str, Any] | None:
    if status is None:
        return None
    payload = status.to_jsonable()
    payload["database"] = (
        PRIVATE_DATABASE_DISPLAY if private else graph_database(config, graph)
    )
    payload.pop("repository_id", None)
    return payload


def format_ops_graph_registry_table(
    config: OpsConfig,
    *,
    graph_storage_status: Mapping[str, OpsGraphStorageStatus] | None = None,
) -> str:
    payload = ops_graph_registry_status_to_jsonable(
        config, graph_storage_status=graph_storage_status
    )
    lines = [
        "RepoMap ops graph registry",
        (
            "graphs: "
            f"total={payload['graph_count']} "
            f"enabled={payload['enabled_graph_count']} "
            f"mcp_visible={payload['mcp_visible_graph_count']} "
            f"private={payload['private_graph_count']} "
            f"db_checked={bool_text(payload['db_checked'])}"
        ),
        (
            "id | repository | database | privacy | enabled | mcp_visible | "
            "refresh | db | warnings"
        ),
    ]
    for graph in payload["graphs"]:
        lines.append(
            " | ".join(
                (
                    graph["id"],
                    graph["repository_name"],
                    graph["database"],
                    graph["privacy"],
                    bool_text(bool(graph["enabled"])),
                    bool_text(bool(graph["mcp_visible"])),
                    f"{graph['refresh_policy']}/{graph['refresh_policy_status']}",
                    graph_storage_label(graph["storage_status"]),
                    str(len(graph["warnings"])),
                )
            )
        )
    lines.append(
        "security: "
        "private_roots_read=false "
        "source_trees_mutated=false "
        "destructive_db_actions=false "
        "remote_exposure=false"
    )
    return "\n".join(lines)


def graph_storage_label(storage_status: Mapping[str, Any] | None) -> str:
    if storage_status is None:
        return "unchecked"
    if storage_status.get("error"):
        return "error"
    if not storage_status.get("schema_available"):
        return "schema-missing"
    if storage_status.get("repository_exists"):
        raw_total = storage_status.get("raw_observations_total")
        if raw_total is None:
            raw_total = storage_status.get("raw_observations", 0)
        raw_latest = storage_status.get("latest_run_raw_observations")
        if raw_latest is None:
            raw_latest = 0
        return (
            "ready("
            f"raw_total={raw_total},"
            f"raw_latest={raw_latest},"
            f"nodes={storage_status.get('canonical_nodes', 0)},"
            f"edges={storage_status.get('canonical_edges', 0)})"
        )
    return "missing"


def format_ops_config_status_table(
    config: OpsConfig,
    *,
    postgres_status: OpsPostgresStatus | None = None,
) -> str:
    payload = ops_config_status_to_jsonable(
        config, postgres_status=postgres_status
    )
    diagnostics = payload["diagnostics"]
    diagnostics_by_severity: dict[str, int] = {}
    for diagnostic in diagnostics:
        severity = diagnostic["severity"]
        diagnostics_by_severity[severity] = diagnostics_by_severity.get(severity, 0) + 1
    lines = [
        "RepoMap ops config status",
        f"valid: {bool_text(payload['valid'])}",
        f"config_home: {payload['config_home'] or '[single-file-deprecated]'}",
        "config_files: " + ", ".join(payload["config_files"]),
        f"schema_version: {payload['schema_version']}",
        (
            "service: "
            f"mode={config.service.mode} "
            f"mcp_transport={config.service.mcp_transport} "
            f"log_level={config.service.log_level}"
        ),
        (
            "runtime: "
            f"containerized_target={bool_text(payload['runtime']['containerized_target'])} "
            f"container_runtime={payload['runtime']['container_runtime'] or 'unset'} "
            f"postgres_host_port={payload['runtime']['postgres_host_port'] or 'unset'} "
            f"server_host_port={payload['runtime']['server_host_port'] or 'unset'} "
            f"bind_host={payload['runtime']['bind_host']}"
        ),
        (
            "postgres: "
            f"host={config.postgres.host} "
            f"port={config.postgres.port} "
            f"database={config.postgres.database} "
            f"user={config.postgres.user} "
            f"password={REDACTED if config.postgres.password else 'env/file/none'} "
            f"db_checked={bool_text(payload['postgres_status']['db_checked'])}"
        ),
        (
            "graphs: "
            f"total={payload['graph_counts']['total']} "
            f"enabled={payload['graph_counts']['enabled']} "
            f"private_enabled={payload['graph_counts']['private_enabled']}"
        ),
        (
            "server_memory: "
            f"enabled={bool_text(config.server_memory.enabled)} "
            f"mode={config.server_memory.mode} "
            "bridge_implemented=true"
        ),
        (
            "sources: "
            f"feed={len(config.sources.feed)} "
            f"github={len(config.sources.github)} "
            f"api={len(config.sources.api)} "
            "acquisition_implemented=false"
        ),
        "diagnostics: " + format_counts(diagnostics_by_severity),
        (
            "safety: "
            "local_only=true "
            "no_public_tunnel=true "
            "no_destructive_operations=true "
            "no_graph_refresh=true"
        ),
    ]
    return "\n".join(lines)
