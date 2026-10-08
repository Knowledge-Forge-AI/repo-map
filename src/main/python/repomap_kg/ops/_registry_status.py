"""Backend-neutral ``config-check`` and ``graphs`` envelopes.

PostgreSQL (:mod:`repomap_kg.ops.config_status`) and SQLite Local
(:mod:`repomap_kg.ops.local_ops_status`) projections both build on these, so the
shared keys, redaction and counts cannot drift; each backend adds only its own
storage keys.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from repomap_kg.ops.config_helpers import OpsConfigDiagnostic, redact_text
from repomap_kg.ops.config_records import (
    PRIVATE_PATH_DISPLAY,
    PRIVATE_PRIVACY,
    PRIVATE_ROOT_DISPLAY,
    OpsGraphConfig,
    OpsSourcesConfig,
)
from repomap_kg.ops.graph_registry import GraphRegistryConfig


LOCAL_CONFIG_DISPLAY = "[local-config]"


class StatusConfig(GraphRegistryConfig, Protocol):
    """The registry fields both backends' status projections share."""

    @property
    def diagnostics(self) -> tuple[OpsConfigDiagnostic, ...]: ...

    @property
    def sources(self) -> OpsSourcesConfig: ...


def local_config_display(value: str | None) -> str | None:
    return LOCAL_CONFIG_DISPLAY if value else None


def config_status_base(config: StatusConfig) -> dict[str, Any]:
    """The backend-neutral ``config-check`` envelope; backends add storage keys."""
    graph_count = len(config.graphs)
    enabled_graphs = sum(1 for graph in config.graphs if graph.enabled)
    private_enabled = sum(
        1 for graph in config.graphs if graph.enabled and graph.privacy in PRIVATE_PRIVACY
    )
    return {
        "config_path": local_config_display(config.config_path),
        "config_home": local_config_display(config.config_home),
        "config_files": list(config.config_files),
        "valid": True,
        "schema_version": config.schema_version,
        "service": config.service.to_jsonable(),
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


def graph_registry_payload(
    config: StatusConfig,
    storage_fields: Callable[[OpsGraphConfig, bool], dict[str, Any]],
    *,
    db_checked: bool,
) -> dict[str, Any]:
    """The backend-neutral ``graphs`` envelope; ``storage_fields`` adds per-graph storage keys."""
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
        source_bindings = graph.effective_source_bindings
        graphs.append(
            {
                "id": graph.id,
                "name": redact_text(graph.name),
                "repository_name": graph.repository_name_display,
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
                **storage_fields(graph, private),
            }
        )
    return {
        "config_path": local_config_display(config.config_path),
        "config_home": local_config_display(config.config_home),
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


__all__ = (
    "LOCAL_CONFIG_DISPLAY",
    "StatusConfig",
    "config_status_base",
    "graph_registry_payload",
    "local_config_display",
)
