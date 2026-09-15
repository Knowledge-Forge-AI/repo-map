"""Graph selection and projection helpers for local refresh operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from repomap_kg.graph.discovery import DEFAULT_DISCOVERY_EXCLUDE_PATHS
from repomap_kg.ops.config import PRIVATE_PRIVACY, OpsConfig, OpsGraphConfig
from repomap_kg.ops.reports import (
    OpsGraphSummary,
    OpsRefreshError,
    OpsRefreshGraphResult,
    OpsRefreshGraphStatus,
    _diagnostic,
)
from repomap_kg.storage.authority import RefreshResult


def _selected_status_graphs(
    config: OpsConfig,
    graph_ids: Sequence[str] | None,
) -> tuple[OpsGraphConfig, ...]:
    if graph_ids is None:
        return config.graphs
    graph_by_id = {graph.id: graph for graph in config.graphs}
    selected: list[OpsGraphConfig] = []
    missing: list[str] = []
    seen: set[str] = set()
    for graph_id in graph_ids:
        if graph_id in seen:
            continue
        seen.add(graph_id)
        graph = graph_by_id.get(graph_id)
        if graph is None:
            missing.append(graph_id)
        else:
            selected.append(graph)
    if missing:
        raise OpsRefreshError(f"unknown graph id(s): {', '.join(missing)}")
    return tuple(selected)


def _preflight_root_path_display(graph: OpsGraphConfig, value: str) -> str:
    return _private_safe_root_path_display(graph, value)


def _private_safe_root_path_display(graph: OpsGraphConfig, value: str) -> str:
    if graph.privacy in PRIVATE_PRIVACY:
        return "[private-root]"
    return value


def _graph_preflight_warnings(graph: OpsGraphConfig) -> tuple[Mapping[str, Any], ...]:
    if graph.privacy not in PRIVATE_PRIVACY:
        return ()
    return (
        _diagnostic(
            "warning",
            "private-graph-preflight",
            f"graphs.{graph.id}",
            f"private graph {graph.id!r} was inspected in preflight mode only",
        ),
    )


def _find_graph(config: OpsConfig, graph_id: str) -> OpsGraphConfig:
    for graph in config.graphs:
        if graph.id == graph_id:
            return graph
    raise OpsRefreshError(f"graph {graph_id!r} is not configured")


def _refresh_root_path(config: OpsConfig, graph: OpsGraphConfig) -> Path:
    expanded = Path(graph.root_path_expanded)
    if expanded.is_absolute():
        return expanded
    return Path(config.config_path).parent.joinpath(expanded)


def _graph_refresh_warnings(graph: OpsGraphConfig) -> tuple[Mapping[str, Any], ...]:
    if graph.privacy not in PRIVATE_PRIVACY:
        return ()
    return (
        _diagnostic(
            "warning",
            "private-graph-refresh",
            f"graphs.{graph.id}",
            f"private graph {graph.id!r} is being refreshed locally",
        ),
    )


def _result_from_graph(
    graph: OpsGraphConfig,
    *,
    database: str,
    result: RefreshResult | str,
    started_at: str | None = None,
    finished_at: str | None = None,
    repository_id: int | None = None,
    run_id: int | None = None,
    files: int | None = None,
    observations: int | None = None,
    warnings: Sequence[Mapping[str, Any]] = (),
    diagnostics: Sequence[Mapping[str, Any]] = (),
    error: str | None = None,
) -> OpsRefreshGraphResult:
    return OpsRefreshGraphResult(
        graph_id=graph.id,
        repository_name=graph.repository_name_display,
        database=database,
        privacy=graph.privacy,
        enabled=graph.enabled,
        mcp_visible=graph.mcp_visible,
        root_path_display=_private_safe_root_path_display(graph, graph.root_path),
        root_path_expanded=_private_safe_root_path_display(
            graph,
            graph.root_path_expanded,
        ),
        result=RefreshResult(result),
        started_at=started_at,
        finished_at=finished_at,
        repository_id=repository_id,
        run_id=run_id,
        files=files,
        observations=observations,
        exclude_paths_enforced=True,
        configured_exclude_paths_count=len(graph.exclude_paths),
        default_exclude_paths_count=len(DEFAULT_DISCOVERY_EXCLUDE_PATHS),
        exclude_paths=graph.exclude_paths,
        warnings=tuple(warnings),
        diagnostics=tuple(diagnostics),
        error=error,
    )


def _status_from_graph(
    graph: OpsGraphConfig,
    *,
    database: str | None = None,
    db_checked: bool = False,
    repository_exists: bool | None = None,
    latest_run_id: int | None = None,
    latest_run_status: str | None = None,
    latest_run_started_at: str | None = None,
    latest_run_finished_at: str | None = None,
    raw_observations: int | None = None,
    raw_observations_total: int | None = None,
    latest_run_raw_observations: int | None = None,
    canonical_nodes: int | None = None,
    canonical_edges: int | None = None,
    publication: Mapping[str, object] | None = None,
    warnings: Sequence[Mapping[str, Any]] = (),
    diagnostics: Sequence[Mapping[str, Any]] = (),
    error: str | None = None,
) -> OpsRefreshGraphStatus:
    return OpsRefreshGraphStatus(
        graph_id=graph.id,
        repository_name=graph.repository_name_display,
        database=database or graph.database or "",
        privacy=graph.privacy,
        enabled=graph.enabled,
        mcp_visible=graph.mcp_visible,
        refresh_policy=graph.refresh_policy,
        root_path_display=_private_safe_root_path_display(graph, graph.root_path),
        root_path_expanded=_private_safe_root_path_display(
            graph,
            graph.root_path_expanded,
        ),
        db_checked=db_checked,
        repository_exists=repository_exists,
        latest_run_id=latest_run_id,
        latest_run_status=latest_run_status,
        latest_run_started_at=latest_run_started_at,
        latest_run_finished_at=latest_run_finished_at,
        raw_observations=raw_observations,
        raw_observations_total=raw_observations_total,
        latest_run_raw_observations=latest_run_raw_observations,
        canonical_nodes=canonical_nodes,
        canonical_edges=canonical_edges,
        publication=publication,
        exclude_paths_enforced=True,
        configured_exclude_paths_count=len(graph.exclude_paths),
        default_exclude_paths_count=len(DEFAULT_DISCOVERY_EXCLUDE_PATHS),
        exclude_paths=graph.exclude_paths,
        warnings=tuple(warnings),
        diagnostics=tuple(diagnostics),
        error=error,
    )


def _summary_from_graph(
    graph: OpsGraphConfig,
    *,
    database: str,
    result: RefreshResult | str,
    db_checked: bool = False,
    repository_exists: bool | None = None,
    latest_run_id: int | None = None,
    latest_run_status: str | None = None,
    latest_run_started_at: str | None = None,
    latest_run_finished_at: str | None = None,
    files: int = 0,
    raw_observations: int = 0,
    raw_observations_total: int | None = None,
    latest_run_raw_observations: int | None = None,
    canonical_nodes: int = 0,
    canonical_edges: int = 0,
    language_counts: Mapping[str, int] | None = None,
    observation_kind_counts: Mapping[str, int] | None = None,
    latest_run_observation_kind_counts: Mapping[str, int] | None = None,
    canonical_node_kind_counts: Mapping[str, int] | None = None,
    canonical_edge_kind_counts: Mapping[str, int] | None = None,
    warnings: Sequence[Mapping[str, Any]] = (),
    diagnostics: Sequence[Mapping[str, Any]] = (),
    error: str | None = None,
) -> OpsGraphSummary:
    return OpsGraphSummary(
        graph_id=graph.id,
        repository_name=graph.repository_name_display,
        database=database,
        privacy=graph.privacy,
        enabled=graph.enabled,
        mcp_visible=graph.mcp_visible,
        root_path_display=_private_safe_root_path_display(graph, graph.root_path),
        root_path_expanded=_private_safe_root_path_display(
            graph,
            graph.root_path_expanded,
        ),
        result=RefreshResult(result),
        db_checked=db_checked,
        repository_exists=repository_exists,
        latest_run_id=latest_run_id,
        latest_run_status=latest_run_status,
        latest_run_started_at=latest_run_started_at,
        latest_run_finished_at=latest_run_finished_at,
        files=files,
        raw_observations=raw_observations,
        raw_observations_total=raw_observations_total,
        latest_run_raw_observations=latest_run_raw_observations,
        canonical_nodes=canonical_nodes,
        canonical_edges=canonical_edges,
        language_counts=language_counts,
        observation_kind_counts=observation_kind_counts,
        latest_run_observation_kind_counts=latest_run_observation_kind_counts,
        canonical_node_kind_counts=canonical_node_kind_counts,
        canonical_edge_kind_counts=canonical_edge_kind_counts,
        warnings=tuple(warnings),
        diagnostics=tuple(diagnostics),
        error=error,
    )


def _graph_readback_warnings(graph: OpsGraphConfig) -> tuple[Mapping[str, Any], ...]:
    if graph.privacy not in PRIVATE_PRIVACY:
        return ()
    return (
        _diagnostic(
            "warning",
            "private-graph-readback",
            f"graphs.{graph.id}",
            f"private graph {graph.id!r} is summarized from stored data only",
        ),
    )


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None
