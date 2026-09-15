"""Graph preflight scanning and formatting helpers for RepoMap refresh operations."""

from __future__ import annotations

import sys
from typing import Any

from repomap_kg.graph.discovery import DEFAULT_DISCOVERY_EXCLUDE_PATHS
from repomap_kg.graph.multi_source_pipeline import (
    MultiSourceCaptureError,
    scan_multi_source_generations,
)
from repomap_kg.ops import reports as _ops_reports
from repomap_kg.ops.config import OpsConfig, graph_database
from repomap_kg.ops.preflight import _scan_preflight_root
from repomap_kg.ops.refresh_graphs import (
    _find_graph,
    _graph_preflight_warnings,
    _preflight_root_path_display,
    _refresh_root_path,
)
from repomap_kg.ops.reports import (
    OpsRefreshError,
    OpsRefreshPreflightResult,
    _preflight_safety_markers,
)


def _dispatch_preflight_safety_markers() -> Any:
    facade = sys.modules.get("repomap_kg.ops.refresh")
    return getattr(facade, "_preflight_safety_markers", _preflight_safety_markers) if facade is not None else _preflight_safety_markers


def preflight_graph(config: OpsConfig, graph_id: str) -> OpsRefreshPreflightResult:
    graph = _find_graph(config, graph_id)
    if graph.refresh_unsupported_classification is not None:
        raise OpsRefreshError(graph.refresh_unsupported_classification)
    if not graph.enabled:
        raise OpsRefreshError(f"graph {graph_id!r} is disabled")
    if graph.explicit_source_bindings:
        try:
            generation_scan = scan_multi_source_generations(graph)
        except MultiSourceCaptureError as error:
            raise OpsRefreshError(str(error)) from error
        files = generation_scan.files
        language_counts: dict[str, int] = {}
        role_counts: dict[str, int] = {}
        for item in files:
            language_counts[item.language] = language_counts.get(item.language, 0) + 1
            role_counts[item.role] = role_counts.get(item.role, 0) + 1
        return OpsRefreshPreflightResult(
            graph_id=graph.id,
            repository_name=graph.repository_name,
            database=graph_database(config, graph),
            privacy=graph.privacy,
            enabled=graph.enabled,
            mcp_visible=graph.mcp_visible,
            root_path_display="[multi-source]",
            root_path_expanded="[multi-source]",
            result="success",
            root_exists=True,
            root_is_dir=True,
            configured_exclude_paths_count=sum(
                len(item.exclude_paths) for item in graph.effective_source_bindings
            ),
            files_considered=len(files),
            files_included=len(files),
            language_counts=language_counts,
            role_counts=role_counts,
            warnings=_graph_preflight_warnings(graph),
        )
    root = _refresh_root_path(config, graph)
    root_exists = root.exists()
    if not root_exists:
        raise OpsRefreshError(f"graph {graph_id!r} root path does not exist")
    root_is_dir = root.is_dir()
    if not root_is_dir:
        raise OpsRefreshError(f"graph {graph_id!r} root path is not a directory")

    root_resolved = root.resolve()
    scan = _scan_preflight_root(root_resolved, graph.exclude_paths)
    return OpsRefreshPreflightResult(
        graph_id=graph.id,
        repository_name=graph.repository_name,
        database=graph_database(config, graph),
        privacy=graph.privacy,
        enabled=graph.enabled,
        mcp_visible=graph.mcp_visible,
        root_path_display=_preflight_root_path_display(graph, graph.root_path),
        root_path_expanded=_preflight_root_path_display(graph, graph.root_path_expanded),
        result="success",
        root_exists=root_exists,
        root_is_dir=root_is_dir,
        configured_exclude_paths_count=len(graph.exclude_paths),
        default_exclude_paths_count=len(DEFAULT_DISCOVERY_EXCLUDE_PATHS),
        warnings=_graph_preflight_warnings(graph),
        **scan,
    )


def preflight_to_jsonable(
    config: OpsConfig,
    result: OpsRefreshPreflightResult,
) -> dict[str, Any]:
    return _ops_reports.preflight_to_jsonable(
        config,
        result,
        safety_markers=_dispatch_preflight_safety_markers(),
    )


def format_preflight_table(
    config: OpsConfig,
    result: OpsRefreshPreflightResult,
) -> str:
    return _ops_reports.format_preflight_table(
        config,
        result,
        safety_markers=_dispatch_preflight_safety_markers(),
    )
