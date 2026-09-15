"""Graph table parsing for RepoMap local operations configuration."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from repomap_kg.ops.config_helpers import (
    KNOWN_GRAPH_FIELDS,
    OpsConfigDiagnostic,
    expand_user_path,
    optional_text,
    required_bool,
    required_text,
    unknown_field_diagnostics,
)
from repomap_kg.ops.config_records import (
    MULTI_SOURCE_REPOSITORY_DISPLAY,
    PRIVATE_PRIVACY,
    OpsGraphConfig,
)
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_source_bindings import parse_graph_source_bindings


SUPPORTED_PRIVACY = frozenset(
    ("public-dev", "private-ops", "private-memory", "private-config", "sensitive-local")
)
SUPPORTED_REFRESH_POLICIES = frozenset(
    ("manual", "polling", "continuous", "startup_check", "watch")
)
GRAPH_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SAFE_POSTGRES_DATABASE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def parse_graphs_section(
    payload: Any,
) -> tuple[list[OpsGraphConfig], list[OpsConfigDiagnostic]]:
    diagnostics: list[OpsConfigDiagnostic] = []
    if payload is None:
        diagnostics.append(
            OpsConfigDiagnostic("error", "missing-section", "graphs", "graphs is required")
        )
        return [], diagnostics
    if not isinstance(payload, list):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "invalid-graphs-section",
                "graphs",
                "graphs must be an array of tables",
            )
        )
        return [], diagnostics
    graphs: list[OpsGraphConfig] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(payload):
        path = f"graphs[{index}]"
        if not isinstance(item, dict):
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error",
                    "invalid-graph-entry",
                    path,
                    "graph entry must be a table",
                )
            )
            continue
        diagnostics.extend(unknown_field_diagnostics(item, KNOWN_GRAPH_FIELDS, path))
        graph_id = required_text(item, "id", f"{path}.id", diagnostics)
        name = required_text(item, "name", f"{path}.name", diagnostics)
        explicit_source_bindings = "source_bindings" in item
        source_bindings: tuple[OpsGraphSourceBindingConfig, ...] = ()
        if explicit_source_bindings:
            conflicting_fields = (
                "root_path",
                "repository_name",
                "privacy",
                "extractor_profile",
                "exclude_paths",
            )
            for field_name in conflicting_fields:
                if field_name in item:
                    diagnostics.append(
                        OpsConfigDiagnostic(
                            "error",
                            "ambiguous-graph-source-syntax",
                            f"{path}.{field_name}",
                            "legacy graph source fields cannot be mixed with source_bindings",
                        )
                    )
            source_bindings = parse_graph_source_bindings(
                item.get("source_bindings"),
                graph_id=graph_id or "",
                graph_path=path,
                diagnostics=diagnostics,
            )
            only_binding = source_bindings[0] if len(source_bindings) == 1 else None
            if only_binding is not None:
                root_path = only_binding.root_path
                repository_name = only_binding.repository_name
                privacy = only_binding.privacy
                extractor_profile = only_binding.extractor_profile
                exclude_paths = only_binding.exclude_paths
            elif source_bindings:
                root_path = ""
                repository_name = MULTI_SOURCE_REPOSITORY_DISPLAY
                privacy = (
                    "public-dev"
                    if all(binding.privacy == "public-dev" for binding in source_bindings)
                    else "private-ops"
                )
                extractor_profile = ""
                exclude_paths = ()
            else:
                root_path = ""
                repository_name = ""
                privacy = ""
                extractor_profile = ""
                exclude_paths = ()
        else:
            root_path = required_text(
                item, "root_path", f"{path}.root_path", diagnostics
            ) or ""
            repository_name = required_text(
                item, "repository_name", f"{path}.repository_name", diagnostics
            ) or ""
            privacy = required_text(
                item, "privacy", f"{path}.privacy", diagnostics
            ) or ""
            extractor_profile = required_text(
                item, "extractor_profile", f"{path}.extractor_profile", diagnostics
            ) or ""
            exclude_paths = parse_graph_exclude_paths(
                item.get("exclude_paths"), f"{path}.exclude_paths", diagnostics
            )
        database = optional_text(item.get("database"))
        enabled = required_bool(item, "enabled", f"{path}.enabled", diagnostics)
        mcp_visible = required_bool(
            item, "mcp_visible", f"{path}.mcp_visible", diagnostics
        )
        refresh_policy = required_text(
            item, "refresh_policy", f"{path}.refresh_policy", diagnostics
        )
        if graph_id:
            if not GRAPH_ID_PATTERN.fullmatch(graph_id):
                diagnostics.append(
                    OpsConfigDiagnostic(
                        "error",
                        "invalid-graph-id",
                        f"{path}.id",
                        "graph id must use lowercase letters, numbers, hyphen, underscore, or dot",
                    )
                )
            if graph_id in seen_ids:
                diagnostics.append(
                    OpsConfigDiagnostic(
                        "error",
                        "duplicate-graph-id",
                        f"{path}.id",
                        f"duplicate graph id {graph_id!r}",
                    )
                )
            seen_ids.add(graph_id)
        if privacy and privacy not in SUPPORTED_PRIVACY:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error",
                    "unsupported-graph-privacy",
                    f"{path}.privacy",
                    "graph privacy is not supported",
                )
            )
        if database and not SAFE_POSTGRES_DATABASE_PATTERN.fullmatch(database):
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error",
                    "invalid-graph-database",
                    f"{path}.database",
                    "graph database must be a safe PostgreSQL identifier",
                )
            )
        if refresh_policy and refresh_policy not in SUPPORTED_REFRESH_POLICIES:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error",
                    "unsupported-refresh-policy",
                    f"{path}.refresh_policy",
                    "refresh_policy must be manual, polling, continuous, startup_check, or watch",
                )
            )
        if enabled and privacy in PRIVATE_PRIVACY:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    "private-graph-enabled",
                    f"{path}.enabled",
                    f"private graph {graph_id!r} is enabled for local operations",
                )
            )
        if mcp_visible and not enabled:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    "mcp-visible-disabled-graph",
                    f"{path}.mcp_visible",
                    f"graph {graph_id!r} is MCP-visible but disabled",
                )
            )
        if mcp_visible and privacy in PRIVATE_PRIVACY:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    "private-graph-mcp-visible",
                    f"{path}.mcp_visible",
                    f"private graph {graph_id!r} is MCP-visible for local read-only use",
                )
            )
        if refresh_policy in ("startup_check", "watch"):
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    "refresh-policy-deferred",
                    f"{path}.refresh_policy",
                    f"refresh_policy {refresh_policy!r} is parsed but not implemented",
                )
            )
        graphs.append(
            OpsGraphConfig(
                id=graph_id or "",
                name=name or "",
                root_path=root_path or "",
                root_path_expanded=expand_user_path(root_path or ""),
                repository_name=repository_name or "",
                privacy=privacy or "",
                enabled=bool(enabled),
                mcp_visible=bool(mcp_visible),
                extractor_profile=extractor_profile or "",
                refresh_policy=refresh_policy or "",
                database=database,
                exclude_paths=exclude_paths,
                source_bindings=source_bindings,
                explicit_source_bindings=explicit_source_bindings,
            )
        )
    return graphs, diagnostics


def parse_graph_exclude_paths(
    payload: Any,
    path: str,
    diagnostics: list[OpsConfigDiagnostic],
) -> tuple[str, ...]:
    if payload is None:
        return ()
    if not isinstance(payload, list):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "invalid-graph-exclude-paths",
                path,
                f"{path} must be an array of strings",
            )
        )
        return ()
    excludes: list[str] = []
    for index, item in enumerate(payload):
        item_path = f"{path}[{index}]"
        if not isinstance(item, str) or not item.strip():
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error",
                    "invalid-graph-exclude-path",
                    item_path,
                    "graph exclude path must be a non-empty relative string",
                )
            )
            continue
        if Path(item).is_absolute() or ".." in Path(item).parts:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error",
                    "invalid-graph-exclude-path",
                    item_path,
                    "graph exclude path must stay relative to the graph root",
                )
            )
            continue
        excludes.append(item)
    return tuple(excludes)
