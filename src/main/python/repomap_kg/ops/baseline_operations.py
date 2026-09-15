"""Graph baseline save, prune, and drift operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from repomap_kg.ops.baselines import (
    _baseline_display_path,
    _baseline_kinds,
    _baseline_path_segment,
    _baseline_storage_root,
    _baseline_timestamp,
    _build_drift_payload,
    _build_preflight_drift_payload,
    _build_preflight_safety_drift,
    _drift_payload_detected,
    _normalize_baseline_payload,
    _normalize_preflight_baseline_payload,
    _preflight_drift_detected,
    _prune_baseline_kind,
    _write_baseline_payload,
)
from repomap_kg.ops.config import OpsConfig, graph_database
from repomap_kg.ops.refresh_graphs import _find_graph
from repomap_kg.ops.reports import (
    OpsBaselinePruneKindResult,
    OpsBaselinePruneResult,
    OpsBaselineSaveEntry,
    OpsBaselineSaveResult,
    OpsGraphDriftCheck,
    OpsRefreshError,
    _diagnostic,
    graph_baseline_to_jsonable,
)


@dataclass(frozen=True)
class BaselineOperationDependencies:
    """Call-time operations supplied by the patchable refresh facade."""

    query_graph_summary: Callable[..., Any]
    preflight_graph: Callable[..., Any]
    preflight_to_jsonable: Callable[..., dict[str, Any]]


def save_graph_baselines(
    config: OpsConfig,
    graph_id: str,
    *,
    kind: str,
    psql_command: str | None = None,
    timestamp: str | None = None,
    dependencies: BaselineOperationDependencies,
) -> OpsBaselineSaveResult:
    graph = _find_graph(config, graph_id)
    if not graph.enabled:
        raise OpsRefreshError(f"graph {graph_id!r} is disabled")
    if not config.config_home:
        raise OpsRefreshError("baseline-save requires --repo-map-home or REPOMAP_HOME")

    graph_segment = _baseline_path_segment(graph.id, "graph id")
    kinds = _baseline_kinds(kind)
    saved_at = timestamp or _baseline_timestamp()
    baseline_root = _baseline_storage_root(config)
    baseline_graph_root = baseline_root / graph_segment
    entries: list[OpsBaselineSaveEntry] = []
    graph_root_read = False
    warnings: list[Mapping[str, Any]] = []
    diagnostics: list[Mapping[str, Any]] = []

    for baseline_kind in kinds:
        payload: dict[str, Any]
        if baseline_kind == "stored":
            summary = dependencies.query_graph_summary(
                config,
                graph.id,
                psql_command=psql_command,
            )
            if summary.result != "success":
                raise OpsRefreshError(
                    f"stored graph baseline for {graph.id!r} failed; "
                    "baseline was not saved"
                )
            warnings.extend(summary.warnings)
            diagnostics.extend(summary.diagnostics)
            payload = graph_baseline_to_jsonable(config, summary)
        elif baseline_kind == "preflight":
            preflight = dependencies.preflight_graph(config, graph.id)
            if preflight.result != "success":
                raise OpsRefreshError(
                    f"refresh preflight baseline for {graph.id!r} failed; "
                    "baseline was not saved"
                )
            graph_root_read = True
            warnings.extend(preflight.warnings)
            diagnostics.extend(preflight.diagnostics)
            payload = dependencies.preflight_to_jsonable(config, preflight)
        else:
            raise OpsRefreshError(f"unsupported baseline kind {baseline_kind!r}")
        entries.append(
            _write_baseline_payload(
                baseline_graph_root,
                graph_segment=graph_segment,
                kind=baseline_kind,
                timestamp=saved_at,
                payload=payload,
            )
        )

    return OpsBaselineSaveResult(
        graph_id=graph.id,
        database=graph_database(config, graph),
        privacy=graph.privacy,
        result="success",
        timestamp=saved_at,
        kinds=kinds,
        baseline_root_display=_baseline_display_path(graph_segment),
        saved=tuple(entries),
        graph_root_read=graph_root_read,
        warnings=tuple(warnings),
        diagnostics=tuple(diagnostics),
    )


def prune_graph_baselines(
    config: OpsConfig,
    graph_id: str,
    *,
    kind: str,
    keep: int,
    dry_run: bool = True,
) -> OpsBaselinePruneResult:
    graph = _find_graph(config, graph_id)
    if not graph.enabled:
        raise OpsRefreshError(f"graph {graph_id!r} is disabled")
    if not config.config_home:
        raise OpsRefreshError("baseline-prune requires --repo-map-home or REPOMAP_HOME")
    if keep < 1:
        raise OpsRefreshError("baseline-prune requires --keep N where N >= 1")

    graph_segment = _baseline_path_segment(graph.id, "graph id")
    kinds = _baseline_kinds(kind)
    baseline_root = _baseline_storage_root(config)
    baseline_graph_root = baseline_root / graph_segment
    processed: list[OpsBaselinePruneKindResult] = []

    for baseline_kind in kinds:
        processed.append(
            _prune_baseline_kind(
                baseline_graph_root,
                graph_segment=graph_segment,
                kind=baseline_kind,
                keep=keep,
                dry_run=dry_run,
                baseline_root=baseline_root,
            )
        )

    return OpsBaselinePruneResult(
        graph_id=graph.id,
        database=graph_database(config, graph),
        privacy=graph.privacy,
        result="success",
        kinds=kinds,
        keep=keep,
        dry_run=dry_run,
        baseline_root_display=_baseline_display_path(graph_segment),
        processed=tuple(processed),
    )


def query_drift_check(
    config: OpsConfig,
    graph_id: str,
    *,
    baseline: Mapping[str, Any],
    include_preflight: bool = False,
    preflight_baseline: Mapping[str, Any] | None = None,
    psql_command: str | None = None,
    dependencies: BaselineOperationDependencies,
) -> OpsGraphDriftCheck:
    normalized_baseline = _normalize_baseline_payload(baseline)
    baseline_graph_id = normalized_baseline.get("graph_id")
    if baseline_graph_id and baseline_graph_id != graph_id:
        raise OpsRefreshError(
            f"baseline graph id {baseline_graph_id!r} does not match {graph_id!r}"
        )

    current = dependencies.query_graph_summary(
        config,
        graph_id,
        psql_command=psql_command,
    )
    if current.result != "success":
        return OpsGraphDriftCheck(
            graph_id=graph_id,
            database=current.database,
            privacy=current.privacy,
            current=current,
            baseline=normalized_baseline,
            drift={},
            drift_detected=False,
            result="failure",
            stored_drift_detected=False,
            warnings=current.warnings,
            diagnostics=current.diagnostics,
        )

    drift = _build_drift_payload(current, normalized_baseline)
    stored_drift_detected = _drift_payload_detected(drift)
    warnings = current.warnings
    if stored_drift_detected:
        warnings = (
            *warnings,
            _diagnostic(
                "warning",
                "graph-baseline-drift",
                f"graphs.{graph_id}",
                f"stored graph summary for {graph_id!r} differs from baseline",
            ),
        )

    current_preflight: dict[str, Any] | None = None
    normalized_preflight_baseline: dict[str, Any] | None = None
    preflight_drift: dict[str, Any] | None = None
    preflight_drift_detected = False
    preflight_safety_drift: dict[str, bool] | None = None

    if include_preflight:
        if preflight_baseline is None:
            raise OpsRefreshError(
                "preflight baseline is required when preflight drift is enabled"
            )
        normalized_preflight_baseline = _normalize_preflight_baseline_payload(
            preflight_baseline
        )
        preflight_graph_id = normalized_preflight_baseline.get("graph_id")
        if preflight_graph_id and preflight_graph_id != graph_id:
            raise OpsRefreshError(
                "preflight baseline graph id "
                f"{preflight_graph_id!r} does not match {graph_id!r}"
            )
        preflight_result = dependencies.preflight_graph(config, graph_id)
        current_preflight_payload = dependencies.preflight_to_jsonable(
            config,
            preflight_result,
        )
        current_preflight = _normalize_preflight_baseline_payload(
            current_preflight_payload
        )
        preflight_drift = _build_preflight_drift_payload(
            current_preflight,
            normalized_preflight_baseline,
        )
        preflight_safety_drift = _build_preflight_safety_drift(
            current_preflight,
            normalized_preflight_baseline,
            privacy=current.privacy,
        )
        preflight_drift_detected = _preflight_drift_detected(
            preflight_drift,
            preflight_safety_drift,
        )
        if preflight_drift_detected:
            warnings = (
                *warnings,
                _diagnostic(
                    "warning",
                    "preflight-baseline-drift",
                    f"graphs.{graph_id}",
                    f"preflight candidate set for {graph_id!r} differs from baseline",
                ),
            )

    drift_detected = stored_drift_detected or preflight_drift_detected

    return OpsGraphDriftCheck(
        graph_id=graph_id,
        database=current.database,
        privacy=current.privacy,
        current=current,
        baseline=normalized_baseline,
        drift=drift,
        drift_detected=drift_detected,
        stored_drift_detected=stored_drift_detected,
        current_preflight=current_preflight,
        preflight_baseline=normalized_preflight_baseline,
        preflight_drift=preflight_drift,
        preflight_drift_detected=preflight_drift_detected,
        preflight_safety_drift=preflight_safety_drift,
        result="warning" if drift_detected else "success",
        warnings=warnings,
        diagnostics=current.diagnostics,
    )
