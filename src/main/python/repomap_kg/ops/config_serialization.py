"""JSON-safe projections for local operations configuration records."""

from __future__ import annotations

from typing import Any

from repomap_kg.ops.config_helpers import (
    PRIVATE_DATABASE_DISPLAY,
    PRIVATE_PATH_DISPLAY,
    PRIVATE_PRIVACY,
    PRIVATE_ROOT_DISPLAY,
    REDACTED,
    redact_mapping,
    redact_text,
)
from repomap_kg.ops.config_serialization_types import (
    OpsGraphConfig,
    OpsGraphStorageStatus,
    OpsPostgresConfig,
    OpsPostgresStatus,
    OpsRuntimeConfig,
    OpsRuntimePostgresConfig,
    OpsServerMemoryConfig,
    OpsServiceConfig,
    OpsSourcePlaceholder,
    OpsSourcesConfig,
)


def service_config_to_jsonable(config: OpsServiceConfig) -> dict[str, Any]:
    return {
        "mode": config.mode,
        "mcp_transport": config.mcp_transport,
        "log_level": config.log_level,
        "local_only": config.mode == "local",
        "public_tunnel_configured": False,
    }


def postgres_config_to_jsonable(config: OpsPostgresConfig) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "host": config.host,
        "port": config.port,
        "database": config.database,
        "user": config.user,
        "password_env": config.password_env,
        "password_file": config.password_file,
        "password_configured": bool(
            config.password_env or config.password_file or config.password
        ),
    }
    if config.password is not None:
        payload["password"] = REDACTED
    return {key: value for key, value in payload.items() if value is not None}


def runtime_postgres_config_to_jsonable(
    config: OpsRuntimePostgresConfig,
) -> dict[str, Any]:
    return {
        "direct_host_port_enabled": config.direct_host_port_enabled,
        "host_port": config.host_port,
        "bind_host": config.bind_host,
        "localhost_only": config.bind_host in ("127.0.0.1", "localhost", "::1"),
    }


def runtime_config_to_jsonable(config: OpsRuntimeConfig) -> dict[str, Any]:
    return {
        "containerized_target": True,
        "container_runtime": config.container_runtime,
        "postgres_host_port": config.postgres_host_port,
        "server_host_port": config.server_host_port,
        "bind_host": config.bind_host,
        "postgres": config.postgres.to_jsonable(),
        "containers_started": False,
        "ports_probed": False,
    }


def graph_config_to_jsonable(config: OpsGraphConfig) -> dict[str, Any]:
    private = config.privacy in PRIVATE_PRIVACY
    bindings = config.effective_source_bindings
    return {
        "id": config.id,
        "name": config.name,
        "root_path": PRIVATE_ROOT_DISPLAY if private else config.root_path,
        "root_path_expanded": (
            PRIVATE_ROOT_DISPLAY if private else config.root_path_expanded
        ),
        "repository_name": config.repository_name_display,
        "database": (
            PRIVATE_DATABASE_DISPLAY if private and config.database else config.database
        ),
        "privacy": config.privacy,
        "enabled": config.enabled,
        "mcp_visible": config.mcp_visible,
        "extractor_profile": config.extractor_profile,
        "refresh_policy": config.refresh_policy,
        "exclude_paths": [
            PRIVATE_PATH_DISPLAY if private else redact_text(path)
            for path in config.exclude_paths
        ],
        "exclude_paths_count": len(config.exclude_paths),
        "exclude_paths_enforced": True,
        "private": private,
        "refresh_implemented": config.refresh_policy
        in ("manual", "polling", "continuous"),
        "source_binding_mode": config.source_binding_mode,
        "source_binding_count": len(bindings),
        "source_bindings": [
            binding.to_jsonable(graph_privacy=config.privacy) for binding in bindings
        ],
        "multi_source_refresh_supported": (
            config.refresh_unsupported_classification is None
        ),
    }


def server_memory_config_to_jsonable(
    config: OpsServerMemoryConfig,
) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "path": PRIVATE_PATH_DISPLAY if config.path else config.path,
        "path_expanded": (
            PRIVATE_PATH_DISPLAY if config.path_expanded else config.path_expanded
        ),
        "mode": config.mode,
        "bridge_implemented": True,
    }


def source_placeholder_to_jsonable(
    source: OpsSourcePlaceholder,
) -> dict[str, Any]:
    return {
        "source_type": source.source_type,
        "id": source.id,
        "graph_id": source.graph_id,
        "enabled": source.enabled,
        "acquisition_implemented": False,
        "metadata": redact_mapping(source.metadata),
    }


def sources_config_to_jsonable(config: OpsSourcesConfig) -> dict[str, Any]:
    return {
        "feed": [source.to_jsonable() for source in config.feed],
        "github": [source.to_jsonable() for source in config.github],
        "api": [source.to_jsonable() for source in config.api],
        "counts": {
            "feed": len(config.feed),
            "github": len(config.github),
            "api": len(config.api),
        },
    }


def postgres_status_to_jsonable(status: OpsPostgresStatus) -> dict[str, Any]:
    return {
        "db_checked": status.db_checked,
        "connected": status.connected,
        "schema_available": status.schema_available,
        "required_tables": dict(status.required_tables or {}),
        "error": redact_text(status.error) if status.error else None,
    }


def graph_storage_status_to_jsonable(
    status: OpsGraphStorageStatus,
) -> dict[str, Any]:
    return {
        "db_checked": status.db_checked,
        "repository_name": status.repository_name,
        "database": status.database,
        "schema_available": status.schema_available,
        "repository_exists": status.repository_exists,
        "repository_id": status.repository_id,
        "raw_observations": status.raw_observations,
        "raw_observations_total": (
            status.raw_observations_total
            if status.raw_observations_total is not None
            else status.raw_observations
        ),
        "latest_run_raw_observations": status.latest_run_raw_observations,
        "canonical_nodes": status.canonical_nodes,
        "canonical_edges": status.canonical_edges,
        "error": redact_text(status.error) if status.error else None,
    }
