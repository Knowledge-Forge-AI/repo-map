"""SQLite Local ``ops config-check`` and ``ops graphs`` projections.

Both commands share the PostgreSQL envelope (:mod:`repomap_kg.ops._registry_status`)
and add only SQLite storage keys: ``storage = {"backend": "sqlite"}`` and a
``storage_status`` built from :mod:`repomap_kg.ops.local_readiness`. PostgreSQL
keys (``postgres``, ``runtime``, ``postgres_status``) are absent rather than
invented. Physical database paths are never projected: a graph's database is
``[graph-database]`` (``[private-database]`` for private graphs) with
``database_source = "sqlite-graph-file"``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from repomap_kg.ops._registry_status import config_status_base, graph_registry_payload
from repomap_kg.ops.config_helpers import bool_text, format_counts
from repomap_kg.ops.config_local import (
    SQLITE_DATABASE_SOURCE,
    SQLITE_GRAPH_DATABASE_DISPLAY,
    LocalSqliteConfig,
)
from repomap_kg.ops.config_records import PRIVATE_DATABASE_DISPLAY, OpsGraphConfig
from repomap_kg.ops.config_storage import SQLITE_BACKEND
from repomap_kg.ops.local_readiness import LocalGraphReadiness


def local_storage_status_to_jsonable(
    readiness: Sequence[LocalGraphReadiness] | None,
) -> dict[str, Any]:
    """``db_checked`` is false without ``--check-db``; otherwise per-graph states."""
    if readiness is None:
        return {"backend": SQLITE_BACKEND, "db_checked": False}
    state_counts: dict[str, int] = {}
    for item in readiness:
        state_counts[item.state] = state_counts.get(item.state, 0) + 1
    return {
        "backend": SQLITE_BACKEND,
        "db_checked": True,
        "graphs": [item.to_jsonable() for item in readiness],
        "state_counts": dict(sorted(state_counts.items())),
    }


def local_config_status_to_jsonable(
    config: LocalSqliteConfig,
    *,
    readiness: Sequence[LocalGraphReadiness] | None = None,
) -> dict[str, Any]:
    payload = config_status_base(config)
    payload["storage"] = {"backend": SQLITE_BACKEND}
    payload["storage_status"] = local_storage_status_to_jsonable(readiness)
    return payload


def local_graph_registry_status_to_jsonable(
    config: LocalSqliteConfig,
    *,
    readiness: Sequence[LocalGraphReadiness] | None = None,
) -> dict[str, Any]:
    by_graph = {item.graph_id: item for item in readiness or ()}

    def storage_fields(graph: OpsGraphConfig, private: bool) -> dict[str, Any]:
        status = by_graph.get(graph.id)
        return {
            "database": PRIVATE_DATABASE_DISPLAY if private else SQLITE_GRAPH_DATABASE_DISPLAY,
            "database_source": SQLITE_DATABASE_SOURCE,
            "storage_status": None if status is None else status.to_jsonable(),
        }

    payload = graph_registry_payload(config, storage_fields, db_checked=readiness is not None)
    payload["storage"] = {"backend": SQLITE_BACKEND}
    return payload


def local_readiness_label(status: dict[str, Any] | None) -> str:
    if status is None:
        return "unchecked"
    if status["state"] == "current":
        generation = status["accepted_generation"]
        return "current(unpublished)" if generation is None else f"current(generation={generation})"
    return str(status["state"])


def format_local_config_status_table(
    config: LocalSqliteConfig,
    *,
    readiness: Sequence[LocalGraphReadiness] | None = None,
) -> str:
    payload = local_config_status_to_jsonable(config, readiness=readiness)
    by_severity: dict[str, int] = {}
    for diagnostic in payload["diagnostics"]:
        by_severity[diagnostic["severity"]] = by_severity.get(diagnostic["severity"], 0) + 1
    storage_status = payload["storage_status"]
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
            f"storage: backend={SQLITE_BACKEND} "
            f"db_checked={bool_text(storage_status['db_checked'])}"
            + (
                " states="
                + ",".join(f"{key}:{count}" for key, count in storage_status["state_counts"].items())
                if storage_status["db_checked"]
                else ""
            )
        ),
        (
            "graphs: "
            f"total={payload['graph_counts']['total']} "
            f"enabled={payload['graph_counts']['enabled']} "
            f"private_enabled={payload['graph_counts']['private_enabled']}"
        ),
        f"server_memory: enabled={bool_text(config.server_memory.enabled)} mode={config.server_memory.mode}",
        "diagnostics: " + format_counts(by_severity),
        "safety: local_only=true no_destructive_operations=true no_graph_refresh=true",
    ]
    return "\n".join(lines)


def format_local_graph_registry_table(
    config: LocalSqliteConfig,
    *,
    readiness: Sequence[LocalGraphReadiness] | None = None,
) -> str:
    payload = local_graph_registry_status_to_jsonable(config, readiness=readiness)
    lines = [
        "RepoMap ops graph registry",
        (
            "graphs: "
            f"total={payload['graph_count']} "
            f"enabled={payload['enabled_graph_count']} "
            f"mcp_visible={payload['mcp_visible_graph_count']} "
            f"private={payload['private_graph_count']} "
            f"storage={SQLITE_BACKEND} "
            f"db_checked={bool_text(payload['db_checked'])}"
        ),
        "id | repository | database | privacy | enabled | mcp_visible | refresh | db | warnings",
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
                    local_readiness_label(graph["storage_status"]),
                    str(len(graph["warnings"])),
                )
            )
        )
    lines.append(
        "security: private_roots_read=false source_trees_mutated=false "
        "destructive_db_actions=false remote_exposure=false"
    )
    return "\n".join(lines)


__all__ = (
    "format_local_config_status_table",
    "format_local_graph_registry_table",
    "local_config_status_to_jsonable",
    "local_graph_registry_status_to_jsonable",
    "local_readiness_label",
    "local_storage_status_to_jsonable",
)
