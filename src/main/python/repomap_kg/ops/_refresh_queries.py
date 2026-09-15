"""Graph summary, refresh status, and baseline queries for RepoMap operations."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from typing import Any

import repomap_kg.ops.baseline_operations as _baseline_operations
from repomap_kg.ops._refresh_preflight import preflight_graph, preflight_to_jsonable
from repomap_kg.ops.config import (
    OpsConfig,
    OpsGraphConfig,
    build_postgres_status_sql,
    graph_database,
)
from repomap_kg.ops.readback import (
    MissingDatabaseReadbackError,
    execute_ops_json_readback as _base_execute_ops_json_readback,
)
from repomap_kg.ops.refresh_graphs import (
    _find_graph,
    _graph_readback_warnings,
    _optional_int,
    _optional_str,
    _selected_status_graphs,
    _status_from_graph,
    _summary_from_graph,
)
from repomap_kg.ops.refresh_sql import build_graph_summary_sql, build_refresh_status_sql
from repomap_kg.ops.reports import (
    OpsBaselinePruneResult,
    OpsBaselineSaveResult,
    OpsGraphDriftCheck,
    OpsGraphSummary,
    OpsRefreshError,
    OpsRefreshGraphStatus,
    _count_map,
    _diagnostic,
)
from repomap_kg.storage import StorageSchemaError

MISSING_DATABASE_DIAGNOSTIC_CODE = "graph-database-missing"


def execute_ops_json_readback(*args: Any, **kwargs: Any) -> Any:
    facade = sys.modules.get("repomap_kg.ops.refresh")
    if facade is not None:
        target = getattr(facade, "execute_ops_json_readback", None)
        if target is not None and target is not execute_ops_json_readback:
            return target(*args, **kwargs)
    return _base_execute_ops_json_readback(*args, **kwargs)


def _ensure_graph_readback_supported(graph: OpsGraphConfig) -> None:
    if graph.readback_unsupported_classification is not None:
        raise OpsRefreshError(graph.readback_unsupported_classification)


def _baseline_operation_dependencies(
) -> _baseline_operations.BaselineOperationDependencies:
    facade = sys.modules.get("repomap_kg.ops.refresh")
    q_summary = getattr(facade, "query_graph_summary", query_graph_summary) if facade else query_graph_summary
    pf_graph = getattr(facade, "preflight_graph", preflight_graph) if facade else preflight_graph
    pf_json = getattr(facade, "preflight_to_jsonable", preflight_to_jsonable) if facade else preflight_to_jsonable
    return _baseline_operations.BaselineOperationDependencies(
        query_graph_summary=q_summary,
        preflight_graph=pf_graph,
        preflight_to_jsonable=pf_json,
    )


def query_refresh_status(
    config: OpsConfig,
    *,
    graph_ids: Sequence[str] | None = None,
    psql_command: str | None = None,
) -> dict[str, OpsRefreshGraphStatus]:
    statuses: dict[str, OpsRefreshGraphStatus] = {}
    graphs_by_database: dict[str, list[OpsGraphConfig]] = {}
    for graph in _selected_status_graphs(config, graph_ids):
        if graph.readback_unsupported_classification is not None:
            statuses[graph.id] = _status_from_graph(
                graph,
                database=graph_database(config, graph),
                error=graph.readback_unsupported_classification,
            )
            continue
        graphs_by_database.setdefault(graph_database(config, graph), []).append(graph)

    for database, graphs in graphs_by_database.items():
        try:
            postgres_payload = execute_ops_json_readback(
                config,
                database=database,
                sql=build_postgres_status_sql(),
                label="operations postgres status",
                expected_shape="object",
                mode="host_then_container",
                psql_command=psql_command,
            )
        except StorageSchemaError as error:
            for graph in graphs:
                statuses[graph.id] = _status_from_graph(
                    graph,
                    database=database,
                    db_checked=True,
                    repository_exists=False,
                    error=str(error),
                )
            continue

        if (
            not isinstance(postgres_payload, dict)
            or not postgres_payload.get("connected")
            or not postgres_payload.get("schema_available")
        ):
            for graph in graphs:
                statuses[graph.id] = _status_from_graph(
                    graph,
                    database=database,
                    db_checked=True,
                    repository_exists=False,
                    error="storage schema is unavailable",
                )
            continue

        try:
            payload = execute_ops_json_readback(
                config,
                database=database,
                sql=build_refresh_status_sql(
                    [(graph.id, graph.repository_name) for graph in graphs]
                ),
                label="operations refresh status",
                expected_shape="object",
                mode="host_then_container",
                psql_command=psql_command,
            )
        except StorageSchemaError as error:
            for graph in graphs:
                statuses[graph.id] = _status_from_graph(
                    graph,
                    database=database,
                    db_checked=True,
                    repository_exists=False,
                    error=str(error),
                )
            continue

        payload_dict = payload if isinstance(payload, dict) else {}
        rows = payload_dict.get("graphs", [])
        if not isinstance(rows, list):
            rows = []
        by_graph = {
            row.get("graph_id"): row
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("graph_id"), str)
        }
        for graph in graphs:
            row = by_graph.get(graph.id, {})
            statuses[graph.id] = _status_from_graph(
                graph,
                database=database,
                db_checked=True,
                repository_exists=bool(row.get("repository_exists")),
                latest_run_id=_optional_int(row.get("latest_run_id")),
                latest_run_status=_optional_str(row.get("latest_run_status")),
                latest_run_started_at=_optional_str(row.get("latest_run_started_at")),
                latest_run_finished_at=_optional_str(row.get("latest_run_finished_at")),
                raw_observations=int(row.get("raw_observations") or 0),
                raw_observations_total=int(
                    row.get("raw_observations_total", row.get("raw_observations")) or 0
                ),
                latest_run_raw_observations=int(
                    row.get("latest_run_raw_observations") or 0
                ),
                canonical_nodes=int(row.get("canonical_nodes") or 0),
                canonical_edges=int(row.get("canonical_edges") or 0),
                publication=(
                    row["publication"]
                    if isinstance(row.get("publication"), dict)
                    else None
                ),
            )
    return statuses


def query_graph_summary(
    config: OpsConfig,
    graph_id: str,
    *,
    psql_command: str | None = None,
) -> OpsGraphSummary:
    graph = _find_graph(config, graph_id)
    if not graph.enabled:
        raise OpsRefreshError(f"graph {graph_id!r} is disabled")
    _ensure_graph_readback_supported(graph)
    database = graph_database(config, graph)
    warnings = _graph_readback_warnings(graph)

    try:
        postgres_payload = execute_ops_json_readback(
            config,
            database=database,
            sql=build_postgres_status_sql(),
            label="operations graph summary postgres status",
            expected_shape="object",
            mode="host_then_container",
            psql_command=psql_command,
        )
    except MissingDatabaseReadbackError as error:
        return _summary_from_graph(
            graph,
            database=database,
            result="failure",
            db_checked=True,
            repository_exists=False,
            warnings=warnings,
            diagnostics=(
                _diagnostic(
                    "error",
                    MISSING_DATABASE_DIAGNOSTIC_CODE,
                    f"graphs.{graph.id}",
                    str(error),
                ),
            ),
            error=str(error),
        )
    except StorageSchemaError as error:
        return _summary_from_graph(
            graph,
            database=database,
            result="failure",
            db_checked=True,
            repository_exists=False,
            warnings=warnings,
            diagnostics=(
                _diagnostic(
                    "error",
                    "storage-status-unavailable",
                    f"graphs.{graph.id}",
                    str(error),
                ),
            ),
            error=str(error),
        )

    if (
        not isinstance(postgres_payload, dict)
        or not postgres_payload.get("connected")
        or not postgres_payload.get("schema_available")
    ):
        return _summary_from_graph(
            graph,
            database=database,
            result="failure",
            db_checked=True,
            repository_exists=False,
            warnings=warnings,
            diagnostics=(
                _diagnostic(
                    "error",
                    "storage-schema-unavailable",
                    f"graphs.{graph.id}",
                    "storage schema is unavailable",
                ),
            ),
            error="storage schema is unavailable",
        )

    try:
        payload = execute_ops_json_readback(
            config,
            database=database,
            sql=build_graph_summary_sql(graph.repository_name),
            label="operations graph summary",
            expected_shape="object",
            mode="host_then_container",
            psql_command=psql_command,
        )
    except MissingDatabaseReadbackError as error:
        return _summary_from_graph(
            graph,
            database=database,
            result="failure",
            db_checked=True,
            repository_exists=False,
            warnings=warnings,
            diagnostics=(
                _diagnostic(
                    "error",
                    MISSING_DATABASE_DIAGNOSTIC_CODE,
                    f"graphs.{graph.id}",
                    str(error),
                ),
            ),
            error=str(error),
        )
    except StorageSchemaError as error:
        return _summary_from_graph(
            graph,
            database=database,
            result="failure",
            db_checked=True,
            repository_exists=False,
            warnings=warnings,
            diagnostics=(
                _diagnostic(
                    "error",
                    "graph-summary-failed",
                    f"graphs.{graph.id}",
                    str(error),
                ),
            ),
            error=str(error),
        )

    payload_dict = payload if isinstance(payload, dict) else {}
    return _summary_from_graph(
        graph,
        database=database,
        result="success",
        db_checked=True,
        repository_exists=bool(payload_dict.get("repository_exists")),
        latest_run_id=_optional_int(payload_dict.get("latest_run_id")),
        latest_run_status=_optional_str(payload_dict.get("latest_run_status")),
        latest_run_started_at=_optional_str(payload_dict.get("latest_run_started_at")),
        latest_run_finished_at=_optional_str(payload_dict.get("latest_run_finished_at")),
        files=int(payload_dict.get("files") or 0),
        raw_observations=int(payload_dict.get("raw_observations") or 0),
        raw_observations_total=int(
            payload_dict.get("raw_observations_total", payload_dict.get("raw_observations")) or 0
        ),
        latest_run_raw_observations=int(
            payload_dict.get("latest_run_raw_observations") or 0
        ),
        canonical_nodes=int(payload_dict.get("canonical_nodes") or 0),
        canonical_edges=int(payload_dict.get("canonical_edges") or 0),
        language_counts=_count_map(payload_dict.get("language_counts")),
        observation_kind_counts=_count_map(payload_dict.get("observation_kind_counts")),
        latest_run_observation_kind_counts=_count_map(
            payload_dict.get("latest_run_observation_kind_counts")
        ),
        canonical_node_kind_counts=_count_map(
            payload_dict.get("canonical_node_kind_counts")
        ),
        canonical_edge_kind_counts=_count_map(
            payload_dict.get("canonical_edge_kind_counts")
        ),
        warnings=warnings,
    )


def save_graph_baselines(
    config: OpsConfig,
    graph_id: str,
    *,
    kind: str,
    psql_command: str | None = None,
    timestamp: str | None = None,
) -> OpsBaselineSaveResult:
    _ensure_graph_readback_supported(_find_graph(config, graph_id))
    return _baseline_operations.save_graph_baselines(
        **locals(),
        dependencies=_baseline_operation_dependencies(),
    )


def prune_graph_baselines(
    config: OpsConfig,
    graph_id: str,
    *,
    kind: str,
    keep: int,
    dry_run: bool = True,
) -> OpsBaselinePruneResult:
    _ensure_graph_readback_supported(_find_graph(config, graph_id))
    return _baseline_operations.prune_graph_baselines(**locals())


def query_drift_check(
    config: OpsConfig,
    graph_id: str,
    *,
    baseline: Mapping[str, Any],
    include_preflight: bool = False,
    preflight_baseline: Mapping[str, Any] | None = None,
    psql_command: str | None = None,
) -> OpsGraphDriftCheck:
    _ensure_graph_readback_supported(_find_graph(config, graph_id))
    return _baseline_operations.query_drift_check(
        **locals(),
        dependencies=_baseline_operation_dependencies(),
    )
