"""Graph-scoped local refresh helpers for RepoMap operations."""

from __future__ import annotations

from pathlib import Path

from repomap_kg.graph.discovery import discover_observations
from repomap_kg.ops._refresh_preflight import (
    format_preflight_table,
    preflight_graph,
    preflight_to_jsonable,
)
from repomap_kg.ops._refresh_psql import (
    _load_file_observations_with_ops_psql,
    _run_ops_psql,
    run_storage_readback_with_ops_psql,
)
from repomap_kg.ops._refresh_queries import (
    MISSING_DATABASE_DIAGNOSTIC_CODE,
    execute_ops_json_readback,
    prune_graph_baselines,
    query_drift_check,
    query_graph_summary,
    query_refresh_status,
    save_graph_baselines,
)
from repomap_kg.ops.baselines import (
    _atomic_write_text,
    _baseline_display_path,
    _baseline_kinds,
    _baseline_path_segment,
    _build_drift_payload,
    _build_preflight_drift_payload,
    _build_preflight_safety_drift,
    _ensure_path_under_baseline_root,
    _int_or_zero,
    _normalize_preflight_baseline_payload,
    _preflight_drift_detected,
    _prune_baseline_kind,
    _utc_now_text,
)
from repomap_kg.ops.config import (
    OpsConfig,
    build_postgres_status_sql,
    graph_database,
)
from repomap_kg.ops.preflight import _scan_preflight_root
from repomap_kg.ops.readback import _container_psql_execution
from repomap_kg.ops.refresh_graphs import (
    _find_graph,
    _graph_refresh_warnings,
    _result_from_graph,
)
from repomap_kg.ops.refresh_sql import (
    build_graph_summary_sql,
    build_refresh_status_sql,
)
from repomap_kg.ops.reports import (
    OpsGraphSummary,
    OpsRefreshError,
    OpsRefreshGraphResult,
    OpsRefreshGraphStatus,
    OpsRefreshPreflightResult,
    _diagnostic,
    _preflight_safety_markers,
    baseline_prune_to_jsonable,
    baseline_save_to_jsonable,
    drift_check_to_jsonable,
    format_baseline_prune_table,
    format_baseline_save_table,
    format_drift_check_table,
    format_graph_summary_table,
    format_refresh_result_table,
    format_refresh_status_table,
    graph_baseline_to_jsonable,
    graph_summary_to_jsonable,
    refresh_result_to_jsonable,
    refresh_status_to_jsonable,
)
from repomap_kg.storage import StorageSchemaError, run_psql
from repomap_kg.storage.backend_telemetry import BackendTelemetry
from repomap_kg.storage.publication import RunPublicationReceipt
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    run_staged_full_refresh,
)
from repomap_kg.storage.staging_observability import StagingMeasurements


class OpsRefreshGenerationChangedError(ValueError):
    """The fenced source changed before its storage transaction began."""




def refresh_graph(
    config: OpsConfig,
    graph_id: str,
    *,
    psql_command: str | None = None,
    publication_receipt: RunPublicationReceipt | None = None,
    ingestion_mode: str = "staged",
    staged_authority: IngestionAuthority | None = None,
    backend_telemetry: BackendTelemetry | None = None,
    staging_measurements: StagingMeasurements | None = None,
) -> OpsRefreshGraphResult:
    if staging_measurements is None:
        return _refresh_graph_impl(
            config,
            graph_id,
            psql_command=psql_command,
            publication_receipt=publication_receipt,
            ingestion_mode=ingestion_mode,
            staged_authority=staged_authority,
            backend_telemetry=backend_telemetry,
            staging_measurements=None,
        )
    with staging_measurements.phase("refresh.total"):
        return _refresh_graph_impl(
            config,
            graph_id,
            psql_command=psql_command,
            publication_receipt=publication_receipt,
            ingestion_mode=ingestion_mode,
            staged_authority=staged_authority,
            backend_telemetry=backend_telemetry,
            staging_measurements=staging_measurements,
        )


def _refresh_graph_impl(
    config: OpsConfig,
    graph_id: str,
    *,
    psql_command: str | None,
    publication_receipt: RunPublicationReceipt | None,
    ingestion_mode: str,
    staged_authority: IngestionAuthority | None,
    backend_telemetry: BackendTelemetry | None,
    staging_measurements: StagingMeasurements | None,
) -> OpsRefreshGraphResult:
    """Execute the selected portable production route without legacy fallback."""
    del psql_command
    graph = _find_graph(config, graph_id)
    if graph.refresh_unsupported_classification is not None:
        raise OpsRefreshError(graph.refresh_unsupported_classification)
    if not graph.enabled:
        raise OpsRefreshError(f"graph {graph_id!r} is disabled")
    for binding in graph.effective_source_bindings:
        root = Path(binding.root_path_expanded)
        if not root.exists():
            raise OpsRefreshError(f"graph {graph_id!r} root path does not exist")
        if not root.is_dir():
            raise OpsRefreshError(f"graph {graph_id!r} root path is not a directory")
    if publication_receipt is not None and staged_authority is None:
        raise OpsRefreshGenerationChangedError("refresh generation changed")
    if (
        publication_receipt is not None
        and staged_authority is not None
        and publication_receipt != staged_authority.receipt()
    ):
        raise OpsRefreshGenerationChangedError("refresh generation changed")
    database = graph_database(config, graph)
    warnings = _graph_refresh_warnings(graph)
    started_at = _utc_now_text()
    try:
        if ingestion_mode != "staged":
            raise ValueError("refresh ingestion mode is invalid")
        from repomap_kg.ops.portable_refresh import execute_portable_refresh

        outcome = execute_portable_refresh(
            config,
            graph,
            database,
            authority=staged_authority,
            backend_telemetry=backend_telemetry,
            staging_measurements=staging_measurements,
        )
    except OpsRefreshGenerationChangedError:
        raise
    except (OSError, StorageSchemaError, ValueError) as error:
        return _result_from_graph(
            graph,
            database=database,
            result="failure",
            started_at=started_at,
            finished_at=_utc_now_text(),
            warnings=warnings,
            diagnostics=(
                _diagnostic("error", "refresh-failed", f"graphs.{graph.id}", str(error)),
            ),
            error=str(error),
        )
    return _result_from_graph(
        graph,
        database=database,
        result="success",
        started_at=started_at,
        finished_at=_utc_now_text(),
        repository_id=outcome.summary.repository_id,
        run_id=outcome.summary.run_id,
        files=outcome.files,
        observations=outcome.observations,
        warnings=warnings,
    )


def refresh_enabled_graphs(
    config: OpsConfig,
    *,
    psql_command: str | None = None,
    ingestion_mode: str = "staged",
) -> tuple[OpsRefreshGraphResult, ...]:
    results: list[OpsRefreshGraphResult] = []
    for graph in config.graphs:
        if not graph.enabled:
            continue
        try:
            results.append(
                refresh_graph(
                    config,
                    graph.id,
                    psql_command=psql_command,
                    ingestion_mode=ingestion_mode,
                )
            )
        except OpsRefreshError as error:
            results.append(
                _result_from_graph(
                    graph,
                    database=graph_database(config, graph),
                    result="failure",
                    started_at=_utc_now_text(),
                    finished_at=_utc_now_text(),
                    diagnostics=(
                        _diagnostic(
                            "error",
                            "refresh-rejected",
                            f"graphs.{graph.id}",
                            str(error),
                        ),
                    ),
                    error=str(error),
                )
            )
    return tuple(results)


__all__ = [
    "MISSING_DATABASE_DIAGNOSTIC_CODE",
    "OpsGraphSummary",
    "OpsRefreshError",
    "OpsRefreshGenerationChangedError",
    "OpsRefreshGraphResult",
    "OpsRefreshGraphStatus",
    "OpsRefreshPreflightResult",
    "_atomic_write_text",
    "_baseline_display_path",
    "_baseline_kinds",
    "_baseline_path_segment",
    "_build_drift_payload",
    "_build_preflight_drift_payload",
    "_build_preflight_safety_drift",
    "_container_psql_execution",
    "_ensure_path_under_baseline_root",
    "_int_or_zero",
    "_normalize_preflight_baseline_payload",
    "_preflight_drift_detected",
    "_prune_baseline_kind",
    "_load_file_observations_with_ops_psql",
    "_preflight_safety_markers",
    "_run_ops_psql",
    "_scan_preflight_root",
    "baseline_prune_to_jsonable",
    "baseline_save_to_jsonable",
    "build_graph_summary_sql",
    "build_postgres_status_sql",
    "build_refresh_status_sql",
    "discover_observations",
    "drift_check_to_jsonable",
    "execute_ops_json_readback",
    "format_baseline_prune_table",
    "format_baseline_save_table",
    "format_drift_check_table",
    "format_graph_summary_table",
    "format_preflight_table",
    "format_refresh_result_table",
    "format_refresh_status_table",
    "graph_baseline_to_jsonable",
    "graph_summary_to_jsonable",
    "preflight_graph",
    "preflight_to_jsonable",
    "prune_graph_baselines",
    "query_drift_check",
    "query_graph_summary",
    "query_refresh_status",
    "refresh_enabled_graphs",
    "refresh_graph",
    "refresh_result_to_jsonable",
    "refresh_status_to_jsonable",
    "run_psql",
    "run_staged_full_refresh",
    "run_storage_readback_with_ops_psql",
    "save_graph_baselines",
]
