"""Ops refresh records and bounded report projections."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from repomap_kg.graph.discovery import DEFAULT_DISCOVERY_EXCLUDE_PATHS
from repomap_kg.ops.config import (
    PRIVATE_PRIVACY,
    OpsConfig,
    OpsGraphConfig,
    bool_text,
    graph_database,
)
from repomap_kg.ops.report_records import (
    SafetyMarkerBuilder,
    OpsBaselinePruneKindResult,
    OpsBaselinePruneResult,
    OpsBaselineSaveEntry,
    OpsBaselineSaveResult,
    OpsGraphDriftCheck,
    OpsGraphSummary,
    OpsPsqlExecution,
    OpsRefreshError,
    OpsRefreshGraphResult,
    OpsRefreshGraphStatus,
    OpsRefreshPreflightResult,
    _count_map,
    _diagnostic,
    _graph_readback_safety_markers,
    _preflight_safety_markers,
    _redact_mapping,
    _redact_text,
    _refresh_safety_markers,
    latest_run_consistency_payload,
)

def preflight_to_jsonable(
    config: OpsConfig,
    result: OpsRefreshPreflightResult,
    *,
    safety_markers: SafetyMarkerBuilder | None = None,
) -> dict[str, Any]:
    graph_payload = result.to_jsonable()
    return {
        "command": "refresh-preflight",
        "config_path": config.config_path,
        "schema_version": config.schema_version,
        "result": graph_payload["result"],
        "graph": graph_payload,
        "include_exclude": {
            "implemented": True,
            "status": "implemented",
            "default_exclude_paths_count": len(DEFAULT_DISCOVERY_EXCLUDE_PATHS),
        },
        "safety": (safety_markers or _preflight_safety_markers)(),
    }

def format_preflight_table(
    config: OpsConfig,
    result: OpsRefreshPreflightResult,
    *,
    safety_markers: SafetyMarkerBuilder | None = None,
) -> str:
    payload = preflight_to_jsonable(
        config,
        result,
        safety_markers=safety_markers,
    )
    graph = payload["graph"]
    lines = [
        "RepoMap ops refresh preflight",
        (
            "summary: "
            f"result={payload['result']} "
            f"graph={graph['graph_id']} "
            f"database={graph['database']} "
            f"privacy={graph['privacy']}"
        ),
        (
            "counts: "
            f"considered={graph['files_considered']} "
            f"included={graph['files_included']} "
            f"files_skipped={graph['files_skipped']} "
            f"directories_skipped={graph['directories_skipped']}"
        ),
        (
            "excludes: "
            f"configured={graph['configured_exclude_paths_count']} "
            f"default={graph['default_exclude_paths_count']} "
            f"enforced={bool_text(graph['exclude_paths_enforced'])}"
        ),
        (
            "nix hazards: "
            f"symlinks={graph['symlink_count']} "
            f"outside_root={graph['symlinks_skipped_outside_root']} "
            f"nix_store={graph['symlinks_skipped_nix_store']} "
            f"generated_output_skips={graph['generated_output_skips']} "
            f"secret_like_paths={graph['secret_like_path_count']} "
            f"path_examples_included={bool_text(graph['path_examples_included'])}"
        ),
        "languages: "
        + ", ".join(
            f"{language}={count}"
            for language, count in sorted(graph["language_counts"].items())
        ),
        "safety: "
        "storage_written=false "
        "source_tree_mutated=false "
        "server_memory_mutated=false "
        "source_acquisition=false "
        "destructive_db_actions=false",
    ]
    return "\n".join(lines)

def refresh_result_to_jsonable(
    config: OpsConfig,
    results: Sequence[OpsRefreshGraphResult],
    *,
    command: str,
) -> dict[str, Any]:
    result_rows = [result.to_jsonable() for result in results]
    failed = sum(1 for result in results if result.result != "success")
    refreshed = sum(1 for result in results if result.result == "success")
    overall = "success"
    if failed and refreshed:
        overall = "partial"
    elif failed:
        overall = "failed"
    return {
        "command": command,
        "config_path": config.config_path,
        "schema_version": config.schema_version,
        "result": overall,
        "graph_count": len(results),
        "refreshed_graph_count": refreshed,
        "failed_graph_count": failed,
        "graphs": result_rows,
        "watch": {
            "implemented": False,
            "status": "deferred",
        },
        "include_exclude": {
            "implemented": True,
            "status": "implemented",
            "default_exclude_paths_count": len(DEFAULT_DISCOVERY_EXCLUDE_PATHS),
        },
        "safety": _refresh_safety_markers(),
    }

def format_refresh_result_table(
    config: OpsConfig,
    results: Sequence[OpsRefreshGraphResult],
    *,
    command: str,
) -> str:
    payload = refresh_result_to_jsonable(config, results, command=command)
    lines = [
        "RepoMap ops refresh result",
        (
            "summary: "
            f"command={command} "
            f"result={payload['result']} "
            f"graphs={payload['graph_count']} "
            f"refreshed={payload['refreshed_graph_count']} "
            f"failed={payload['failed_graph_count']}"
        ),
        "id | repository | database | privacy | result | run | files | observations | warnings",
    ]
    for graph in payload["graphs"]:
        lines.append(
            " | ".join(
                (
                    str(graph["graph_id"]),
                    str(graph["repository_name"]),
                    str(graph["database"]),
                    str(graph["privacy"]),
                    str(graph["result"]),
                    str(graph["run_id"] or "-"),
                    str(graph["files"] if graph["files"] is not None else "-"),
                    str(
                        graph["observations"]
                        if graph["observations"] is not None
                        else "-"
                    ),
                    str(len(graph["warnings"])),
                )
            )
        )
    lines.append(
        "safety: "
        "source_trees_mutated=false "
        "destructive_db_actions=false "
        "server_memory_read=false "
        "source_acquisition=false "
        "expanded_mcp_tools=false"
    )
    return "\n".join(lines)


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


def _private_safe_root_path_display(graph: OpsGraphConfig, value: str) -> str:
    if graph.privacy in PRIVATE_PRIVACY:
        return "[private-root]"
    return value


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
        exclude_paths_enforced=True,
        configured_exclude_paths_count=len(graph.exclude_paths),
        default_exclude_paths_count=len(DEFAULT_DISCOVERY_EXCLUDE_PATHS),
        exclude_paths=graph.exclude_paths,
        warnings=tuple(warnings),
        diagnostics=tuple(diagnostics),
        error=error,
    )


def refresh_status_to_jsonable(
    config: OpsConfig,
    statuses: Mapping[str, OpsRefreshGraphStatus],
    *,
    graph_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    selected_graphs = _selected_status_graphs(config, graph_ids)
    graph_rows = [
        statuses.get(
            graph.id,
            _status_from_graph(graph, database=graph_database(config, graph)),
        ).to_jsonable()
        for graph in selected_graphs
    ]
    return {
        "command": "refresh-status",
        "config_path": config.config_path,
        "schema_version": config.schema_version,
        "graph_count": len(selected_graphs),
        "enabled_graph_count": sum(1 for graph in selected_graphs if graph.enabled),
        "filtered": graph_ids is not None,
        "db_checked": any(row["db_checked"] for row in graph_rows),
        "graphs": graph_rows,
        "watch": {
            "implemented": False,
            "status": "deferred",
        },
        "include_exclude": {
            "implemented": True,
            "status": "implemented",
            "default_exclude_paths_count": len(DEFAULT_DISCOVERY_EXCLUDE_PATHS),
        },
        "safety": _refresh_safety_markers(),
    }

def format_refresh_status_table(
    config: OpsConfig,
    statuses: Mapping[str, OpsRefreshGraphStatus],
    *,
    graph_ids: Sequence[str] | None = None,
) -> str:
    payload = refresh_status_to_jsonable(config, statuses, graph_ids=graph_ids)
    lines = [
        "RepoMap ops refresh status",
        (
            "graphs: "
            f"total={payload['graph_count']} "
            f"enabled={payload['enabled_graph_count']} "
            f"db_checked={bool_text(payload['db_checked'])}"
        ),
        (
            "id | repository | database | privacy | latest_status | latest_run | "
            "raw_total | raw_latest | nodes | edges"
        ),
    ]
    for graph in payload["graphs"]:
        lines.append(
            " | ".join(
                (
                    str(graph["graph_id"]),
                    str(graph["repository_name"]),
                    str(graph["database"]),
                    str(graph["privacy"]),
                    str(graph["latest_run_status"] or "none"),
                    str(graph["latest_run_id"] or "-"),
                    str(graph["raw_observations_total"] or 0),
                    str(graph["latest_run_raw_observations"] or 0),
                    str(graph["canonical_nodes"] or 0),
                    str(graph["canonical_edges"] or 0),
                )
            )
        )
    lines.append(
        "safety: "
        "source_trees_mutated=false "
        "destructive_db_actions=false "
        "server_memory_read=false "
        "source_acquisition=false "
        "expanded_mcp_tools=false"
    )
    return "\n".join(lines)

def graph_summary_to_jsonable(
    config: OpsConfig,
    summary: OpsGraphSummary,
) -> dict[str, Any]:
    return {
        "command": "graph-summary",
        "config_path": config.config_path,
        "schema_version": config.schema_version,
        "result": summary.result,
        "graph": summary.to_jsonable(),
        "readback": {
            "mode": "stored-graph-summary",
            "bounded": True,
            "raw_payloads_included": False,
            "path_examples_included": False,
        },
        "safety": _graph_readback_safety_markers(),
    }

_BASELINE_SCALAR_FIELDS = (
    "files",
    "raw_observations",
    "canonical_nodes",
    "canonical_edges",
)

_BASELINE_MAP_FIELDS = (
    "language_counts",
    "observation_kind_counts",
    "canonical_node_kind_counts",
    "canonical_edge_kind_counts",
)

_PREFLIGHT_BASELINE_SCALAR_FIELDS = (
    "files_considered",
    "files_included",
    "files_skipped",
    "directories_skipped",
    "symlink_count",
    "symlinks_skipped_outside_root",
    "symlinks_skipped_nix_store",
    "generated_output_skips",
    "secret_like_path_count",
    "configured_exclude_paths_count",
    "default_exclude_paths_count",
    "diagnostic_count",
    "warning_count",
    "unknown_role_count",
)

_PREFLIGHT_BASELINE_BOOLEAN_FIELDS = (
    "path_examples_included",
)

_PREFLIGHT_BASELINE_MAP_FIELDS = (
    "configured_exclude_hit_counts",
    "default_exclude_hit_counts",
    "language_counts",
    "role_counts",
    "extractor_categories",
)

_PREFLIGHT_FALSE_SAFETY_FIELDS = (
    "storage_written",
    "source_tree_mutated",
    "server_memory_read",
    "server_memory_mutated",
    "source_acquisition",
    "destructive_db_actions",
    "remote_exposure",
    "watch_daemon_started",
)

def graph_baseline_to_jsonable(
    config: OpsConfig,
    summary: OpsGraphSummary,
) -> dict[str, Any]:
    baseline = summary.to_jsonable()
    return {
        "command": "graph-baseline",
        "config_path": config.config_path,
        "schema_version": config.schema_version,
        "result": summary.result,
        "baseline": baseline,
        "readback": {
            "mode": "stored-graph-baseline",
            "bounded": True,
            "raw_payloads_included": False,
            "path_examples_included": False,
        },
        "safety": _graph_readback_safety_markers(),
    }

def baseline_save_to_jsonable(
    config: OpsConfig,
    result: OpsBaselineSaveResult,
) -> dict[str, Any]:
    return {
        "command": "baseline-save",
        "schema_version": config.schema_version,
        "result": result.result,
        "graph_id": result.graph_id,
        "database": result.database,
        "privacy": result.privacy,
        "timestamp": result.timestamp,
        "kinds": list(result.kinds),
        "baseline_root_display": result.baseline_root_display,
        "saved": [entry.to_jsonable() for entry in result.saved],
        "readback": {
            "mode": "baseline-save",
            "bounded": True,
            "raw_payloads_included": False,
            "path_examples_included": False,
            "automatic_refresh": False,
        },
        "safety": {
            "baseline_files_written": True,
            "graph_root_read": result.graph_root_read,
            "storage_written": False,
            "db_storage_mutated": False,
            "source_tree_mutated": False,
            "server_memory_mutated": False,
            "server_memory_read": False,
            "source_acquisition": False,
            "destructive_db_actions": False,
            "remote_exposure": False,
            "watch_daemon_started": False,
        },
        "warnings": [dict(warning) for warning in result.warnings],
        "diagnostics": [
            _redact_mapping(diagnostic) for diagnostic in result.diagnostics
        ],
    }

def format_baseline_save_table(
    config: OpsConfig,
    result: OpsBaselineSaveResult,
) -> str:
    payload = baseline_save_to_jsonable(config, result)
    lines = [
        "RepoMap ops baseline save",
        (
            "summary: "
            f"result={payload['result']} "
            f"graph={payload['graph_id']} "
            f"database={payload['database']} "
            f"kinds={','.join(payload['kinds'])}"
        ),
        f"root: {payload['baseline_root_display']}",
    ]
    for entry in payload["saved"]:
        lines.append(
            "saved: "
            f"kind={entry['kind']} "
            f"timestamped={entry['timestamped_path_display']} "
            f"latest={entry['latest_path_display']} "
            f"bytes={entry['bytes_written']}"
        )
    return "\n".join(lines)

def baseline_prune_to_jsonable(
    config: OpsConfig,
    result: OpsBaselinePruneResult,
) -> dict[str, Any]:
    deleted_count = sum(entry.deleted_count for entry in result.processed)
    return {
        "command": "baseline-prune",
        "schema_version": config.schema_version,
        "result": result.result,
        "graph_id": result.graph_id,
        "database": result.database,
        "privacy": result.privacy,
        "kinds": list(result.kinds),
        "keep": result.keep,
        "dry_run": result.dry_run,
        "baseline_root_display": result.baseline_root_display,
        "processed": [entry.to_jsonable() for entry in result.processed],
        "readback": {
            "mode": "baseline-prune",
            "bounded": True,
            "raw_payloads_included": False,
            "path_examples_included": False,
            "automatic_refresh": False,
        },
        "safety": {
            "baseline_files_deleted": deleted_count,
            "latest_deleted": False,
            "outside_baseline_root_deleted": False,
            "storage_written": False,
            "db_storage_mutated": False,
            "source_tree_mutated": False,
            "server_memory_mutated": False,
            "server_memory_read": False,
            "source_acquisition": False,
            "destructive_db_actions": False,
            "remote_exposure": False,
            "watch_daemon_started": False,
        },
        "warnings": [dict(warning) for warning in result.warnings],
        "diagnostics": [
            _redact_mapping(diagnostic) for diagnostic in result.diagnostics
        ],
    }

def format_baseline_prune_table(
    config: OpsConfig,
    result: OpsBaselinePruneResult,
) -> str:
    payload = baseline_prune_to_jsonable(config, result)
    lines = [
        "RepoMap ops baseline prune",
        (
            "summary: "
            f"result={payload['result']} "
            f"graph={payload['graph_id']} "
            f"database={payload['database']} "
            f"kinds={','.join(payload['kinds'])} "
            f"keep={payload['keep']} "
            f"dry_run={str(payload['dry_run']).lower()}"
        ),
        f"root: {payload['baseline_root_display']}",
    ]
    for entry in payload["processed"]:
        lines.append(
            "processed: "
            f"kind={entry['kind']} "
            f"found={entry['timestamped_files_found']} "
            f"kept={entry['kept_count']} "
            f"candidates={entry['candidate_count']} "
            f"deleted={entry['deleted_count']} "
            f"ignored={entry['ignored_count']} "
            f"latest_preserved={str(entry['latest_preserved']).lower()}"
        )
    return "\n".join(lines)

def drift_check_to_jsonable(
    config: OpsConfig,
    drift_check: OpsGraphDriftCheck,
) -> dict[str, Any]:
    return {
        "command": "drift-check",
        "config_path": config.config_path,
        "schema_version": config.schema_version,
        "result": drift_check.result,
        "drift_detected": drift_check.drift_detected,
        "stored_drift_detected": bool(drift_check.stored_drift_detected),
        "preflight_drift_detected": drift_check.preflight_drift_detected,
        "graph_id": drift_check.graph_id,
        "database": drift_check.database,
        "privacy": drift_check.privacy,
        "current": drift_check.current.to_jsonable(),
        "baseline": _redact_mapping(drift_check.baseline),
        "drift": _redact_mapping(drift_check.drift),
        "current_preflight": _redact_mapping(drift_check.current_preflight or {}),
        "preflight_baseline": _redact_mapping(drift_check.preflight_baseline or {}),
        "preflight_drift": _redact_mapping(drift_check.preflight_drift or {}),
        "preflight_safety_drift": dict(drift_check.preflight_safety_drift or {}),
        "warnings": [dict(warning) for warning in drift_check.warnings],
        "diagnostics": [
            _redact_mapping(diagnostic) for diagnostic in drift_check.diagnostics
        ],
        "readback": {
            "mode": (
                "stored-and-preflight-drift-check"
                if drift_check.current_preflight
                else "stored-graph-drift-check"
            ),
            "bounded": True,
            "raw_payloads_included": False,
            "path_examples_included": False,
            "automatic_refresh": False,
        },
        "safety": _graph_readback_safety_markers(),
    }

def format_drift_check_table(config: OpsConfig, drift_check: OpsGraphDriftCheck) -> str:
    payload = drift_check_to_jsonable(config, drift_check)
    lines = [
        "RepoMap ops drift check",
        (
            "summary: "
            f"result={payload['result']} "
            f"graph={payload['graph_id']} "
            f"database={payload['database']} "
            f"drift_detected={str(payload['drift_detected']).lower()} "
            f"stored_drift_detected={str(payload['stored_drift_detected']).lower()} "
            f"preflight_drift_detected="
            f"{str(payload['preflight_drift_detected']).lower()}"
        ),
    ]
    for field in _BASELINE_SCALAR_FIELDS:
        drift = payload["drift"].get(field, {})
        if drift:
            lines.append(
                f"{field}: baseline={drift.get('baseline')} "
                f"current={drift.get('current')} delta={drift.get('delta')}"
            )
    for field in _BASELINE_MAP_FIELDS:
        drift = payload["drift"].get(field, {})
        changed = drift.get("changed", {})
        if changed:
            lines.append(f"{field}: changed={len(changed)}")
    for field in _PREFLIGHT_BASELINE_SCALAR_FIELDS:
        drift = payload["preflight_drift"].get(field, {})
        if drift:
            lines.append(
                f"preflight.{field}: baseline={drift.get('baseline')} "
                f"current={drift.get('current')} delta={drift.get('delta')}"
            )
    for field in _PREFLIGHT_BASELINE_BOOLEAN_FIELDS:
        drift = payload["preflight_drift"].get(field, {})
        if drift:
            lines.append(
                f"preflight.{field}: baseline={drift.get('baseline')} "
                f"current={drift.get('current')}"
            )
    for field in _PREFLIGHT_BASELINE_MAP_FIELDS:
        drift = payload["preflight_drift"].get(field, {})
        changed = drift.get("changed", {})
        if changed:
            lines.append(f"preflight.{field}: changed={len(changed)}")
    safety_drift = payload.get("preflight_safety_drift", {})
    if any(safety_drift.values()):
        lines.append(
            "preflight_safety_drift: "
            + ", ".join(key for key, value in safety_drift.items() if value)
        )
    lines.append(
        "safety: "
        "graph_root_read=false "
        "storage_written=false "
        "source_tree_mutated=false "
        "server_memory_mutated=false "
        "source_acquisition=false "
        "destructive_db_actions=false"
    )
    return "\n".join(lines)

def format_graph_summary_table(config: OpsConfig, summary: OpsGraphSummary) -> str:
    payload = graph_summary_to_jsonable(config, summary)
    graph = payload["graph"]
    lines = [
        "RepoMap ops graph summary",
        (
            "summary: "
            f"result={payload['result']} "
            f"graph={graph['graph_id']} "
            f"database={graph['database']} "
            f"privacy={graph['privacy']}"
        ),
        (
            "counts: "
            f"files={graph['files']} "
            f"raw_total={graph['raw_observations_total']} "
            f"raw_latest={graph['latest_run_raw_observations'] or 0} "
            f"nodes={graph['canonical_nodes']} "
            f"edges={graph['canonical_edges']}"
        ),
        (
            "latest: "
            f"run={graph['latest_run_id'] or '-'} "
            f"status={graph['latest_run_status'] or 'none'}"
        ),
        "languages: "
        + ", ".join(
            f"{language}={count}"
            for language, count in sorted(graph["language_counts"].items())
        ),
        "observation kinds: "
        + ", ".join(
            f"{kind}={count}"
            for kind, count in sorted(graph["observation_kind_counts"].items())
        ),
        "canonical node kinds: "
        + ", ".join(
            f"{kind}={count}"
            for kind, count in sorted(graph["canonical_node_kind_counts"].items())
        ),
        "canonical edge kinds: "
        + ", ".join(
            f"{kind}={count}"
            for kind, count in sorted(graph["canonical_edge_kind_counts"].items())
        ),
        "safety: "
        "graph_root_read=false "
        "storage_written=false "
        "source_tree_mutated=false "
        "server_memory_mutated=false "
        "source_acquisition=false "
        "destructive_db_actions=false",
    ]
    return "\n".join(lines)
