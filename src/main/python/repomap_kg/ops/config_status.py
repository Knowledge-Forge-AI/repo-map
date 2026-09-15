"""Status projection helpers for RepoMap local operations config."""

from __future__ import annotations

from typing import Any, Mapping

from repomap_kg.ops.config_helpers import (
    REDACTED,
    bool_text,
    format_counts,
    redact_text,
)
from repomap_kg.ops.config_records import (
    PRIVATE_PRIVACY,
    PRIVATE_DATABASE_DISPLAY,
    PRIVATE_PATH_DISPLAY,
    PRIVATE_ROOT_DISPLAY,
    OpsConfig,
    OpsGraphConfig,
    OpsGraphStorageStatus,
    OpsPostgresStatus,
)
from repomap_kg.ops.resolved_config import resolve_ops_config


LOCAL_CONFIG_DISPLAY = "[local-config]"


def _local_config_display(value: str | None) -> str | None:
    return LOCAL_CONFIG_DISPLAY if value else None


def graph_database(config: OpsConfig, graph: OpsGraphConfig) -> str:
    """Return the effective storage database for a configured graph."""

    return str(resolve_ops_config(config).graph(graph.id).database)


def graph_database_source(graph: OpsGraphConfig) -> str:
    return "graph" if graph.database else "postgres-default"


def graph_psql_args(config: OpsConfig, graph: OpsGraphConfig) -> list[str]:
    return config.postgres.psql_args_for_database(graph_database(config, graph))


def ops_config_status_to_jsonable(
    config: OpsConfig,
    *,
    postgres_status: OpsPostgresStatus | None = None,
) -> dict[str, Any]:
    db_status = postgres_status or OpsPostgresStatus.unchecked()
    graph_count = len(config.graphs)
    enabled_graphs = sum(1 for graph in config.graphs if graph.enabled)
    private_enabled = sum(
        1 for graph in config.graphs if graph.enabled and graph.privacy in PRIVATE_PRIVACY
    )
    return {
        "config_path": _local_config_display(config.config_path),
        "config_home": _local_config_display(config.config_home),
        "config_files": list(config.config_files),
        "valid": True,
        "schema_version": config.schema_version,
        "service": config.service.to_jsonable(),
        "postgres": config.postgres.to_jsonable(),
        "runtime": config.runtime.to_jsonable(),
        "postgres_status": db_status.to_jsonable(),
        "graphs": [graph.to_jsonable() for graph in config.graphs],
        "graph_counts": {
            "total": graph_count,
            "enabled": enabled_graphs,
            "private_enabled": private_enabled,
        },
        "server_memory": config.server_memory.to_jsonable(),
        "sources": config.sources.to_jsonable(),
        "diagnostics": [
            diagnostic.to_jsonable() for diagnostic in config.diagnostics
        ],
        "compatibility": {
            "legacy_json_mcp_config_supported": False,
            "ops_json_config_removed": True,
            "legacy_project_profile_toml_supported": True,
            "legacy_source_toml_supported": True,
            "json_extraction_preserved": True,
            "json_source_artifacts_preserved": True,
            "single_file_toml_config_deprecated": config.config_home is None,
            "migration_required": True,
        },
        "safety": {
            "local_only": True,
            "no_public_tunnel": True,
            "no_remote_postgres": True,
            "no_destructive_operations": True,
            "no_graph_refresh": True,
            "no_server_memory_read": True,
            "no_source_acquisition": True,
        },
    }


def ops_graph_registry_status_to_jsonable(
    config: OpsConfig,
    *,
    graph_storage_status: Mapping[str, OpsGraphStorageStatus] | None = None,
) -> dict[str, Any]:
    storage_status = graph_storage_status or {}
    db_checked = any(status.db_checked for status in storage_status.values())
    warnings = [
        diagnostic.to_jsonable()
        for diagnostic in config.diagnostics
        if diagnostic.severity == "warning"
    ]
    diagnostics = [diagnostic.to_jsonable() for diagnostic in config.diagnostics]
    graphs: list[dict[str, Any]] = []
    for index, graph in enumerate(config.graphs):
        private = graph.privacy in PRIVATE_PRIVACY
        graph_path = f"graphs[{index}]"
        graph_warnings = [
            diagnostic.to_jsonable()
            for diagnostic in config.diagnostics
            if diagnostic.severity == "warning" and diagnostic.path.startswith(graph_path)
        ]
        graph_status = storage_status.get(graph.id)
        source_bindings = graph.effective_source_bindings
        graphs.append(
            {
                "id": graph.id,
                "name": redact_text(graph.name),
                "repository_name": graph.repository_name_display,
                "database": (
                    PRIVATE_DATABASE_DISPLAY
                    if private
                    else graph_database(config, graph)
                ),
                "database_source": graph_database_source(graph),
                "privacy": graph.privacy,
                "enabled": graph.enabled,
                "mcp_visible": graph.mcp_visible,
                "extractor_profile": graph.extractor_profile,
                "refresh_policy": graph.refresh_policy,
                "refresh_policy_status": (
                    "implemented"
                    if graph.refresh_policy in ("manual", "polling", "continuous")
                    else "deferred"
                ),
                "exclude_paths": [
                    PRIVATE_PATH_DISPLAY if private else redact_text(exclude_path)
                    for exclude_path in graph.exclude_paths
                ],
                "exclude_paths_count": len(graph.exclude_paths),
                "exclude_paths_enforced": True,
                "root_path_display": (
                    PRIVATE_ROOT_DISPLAY if private else graph.root_path
                ),
                "root_path_expanded": (
                    PRIVATE_ROOT_DISPLAY if private else graph.root_path_expanded
                ),
                "root_path_checked": False,
                "private": private,
                "source_binding_mode": graph.source_binding_mode,
                "source_binding_count": len(source_bindings),
                "source_bindings": [
                    binding.to_jsonable(graph_privacy=graph.privacy)
                    for binding in source_bindings
                ],
                "multi_source_refresh_supported": (
                    graph.refresh_unsupported_classification is None
                ),
                "warnings": graph_warnings,
                "storage_status": _graph_storage_status_to_jsonable(
                    config,
                    graph,
                    graph_status,
                    private=private,
                ),
            }
        )
    return {
        "config_path": _local_config_display(config.config_path),
        "config_home": _local_config_display(config.config_home),
        "config_files": list(config.config_files),
        "schema_version": config.schema_version,
        "graph_count": len(config.graphs),
        "enabled_graph_count": sum(1 for graph in config.graphs if graph.enabled),
        "mcp_visible_graph_count": sum(
            1 for graph in config.graphs if graph.mcp_visible
        ),
        "private_graph_count": sum(
            1 for graph in config.graphs if graph.privacy in PRIVATE_PRIVACY
        ),
        "db_checked": db_checked,
        "graphs": graphs,
        "warnings": warnings,
        "diagnostics": diagnostics,
        "compatibility": {
            "legacy_json_mcp_config_supported": False,
            "ops_json_config_removed": True,
            "legacy_project_profile_toml_supported": True,
            "legacy_source_toml_supported": True,
            "json_extraction_preserved": True,
            "json_source_artifacts_preserved": True,
            "single_file_toml_config_deprecated": config.config_home is None,
            "migration_required": True,
        },
        "security": {
            "private_roots_read": False,
            "source_trees_mutated": False,
            "destructive_db_actions": False,
            "remote_exposure": False,
            "server_memory_read": False,
            "source_acquisition": False,
            "graph_refresh": False,
        },
    }


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
