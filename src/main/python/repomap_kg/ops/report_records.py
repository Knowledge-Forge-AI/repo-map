"""Ops refresh report records and shared projection helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from repomap_kg.storage.authority import RefreshResult
from repomap_kg.graph.discovery import DEFAULT_DISCOVERY_EXCLUDE_PATHS
from repomap_kg.ops.config_helpers import OpsConfigDiagnostic, redact_text
from repomap_kg.ops.report_safety import (
    _graph_readback_safety_markers as _graph_readback_safety_markers,
    _preflight_safety_markers as _preflight_safety_markers,
    _refresh_safety_markers as _refresh_safety_markers,
)

SafetyMarkerBuilder = Callable[[], dict[str, bool]]


def recorded_run_consistency_payload(
    *,
    latest_run_status: str | None,
    latest_run_finished_at: str | None,
) -> dict[str, Any]:
    complete_without_finished_at = latest_run_status == "complete" and latest_run_finished_at is None
    if complete_without_finished_at:
        return {
            "complete_without_finished_at": True,
            "diagnostic": "complete run has no finished timestamp in storage",
        }
    return {"complete_without_finished_at": False}


# Public payloads retain the established key name through this compatibility
# alias. Internal callers use the explicit recorded-run term.
latest_run_consistency_payload = recorded_run_consistency_payload


class OpsRefreshError(ValueError):
    """Raised when an operations graph refresh cannot start safely."""


@dataclass(frozen=True)
class OpsPsqlExecution:
    command: str
    args_prefix: tuple[str, ...] = ()
    strategy: str = "host"

    def full_command(
        self, psql_args: Sequence[str], tail_args: Sequence[str],
    ) -> list[str]:
        return [self.command, *self.args_prefix, *psql_args, *tail_args]


@dataclass(frozen=True)
class OpsRefreshGraphResult:
    graph_id: str
    repository_name: str
    privacy: str
    enabled: bool
    mcp_visible: bool
    root_path_display: str
    root_path_expanded: str
    result: RefreshResult
    database: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    repository_id: int | None = None
    run_id: int | None = None
    files: int | None = None
    observations: int | None = None
    exclude_paths_enforced: bool = True
    configured_exclude_paths_count: int = 0
    default_exclude_paths_count: int = len(DEFAULT_DISCOVERY_EXCLUDE_PATHS)
    exclude_paths: tuple[str, ...] = ()
    warnings: tuple[Mapping[str, Any], ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()
    error: str | None = None
    publication_state: str = "not_started"
    error_category: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "repository_name": self.repository_name,
            "database": self.database,
            "privacy": self.privacy,
            "enabled": self.enabled,
            "mcp_visible": self.mcp_visible,
            "root_path_display": self.root_path_display,
            "root_path_expanded": self.root_path_expanded,
            "result": self.result,
            "publication_state": self.publication_state,
            "error_category": self.error_category,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "repository_id": self.repository_id,
            "run_id": self.run_id,
            "files": self.files,
            "observations": self.observations,
            "exclude_paths_enforced": self.exclude_paths_enforced,
            "configured_exclude_paths_count": self.configured_exclude_paths_count,
            "default_exclude_paths_count": self.default_exclude_paths_count,
            "exclude_paths": [_redact_text(path) for path in self.exclude_paths],
            "warnings": [dict(warning) for warning in self.warnings],
            "diagnostics": [_redact_mapping(item) for item in self.diagnostics],
            "error": _redact_text(self.error) if self.error else None,
        }


@dataclass(frozen=True)
class OpsRefreshGraphStatus:
    graph_id: str
    repository_name: str
    privacy: str
    enabled: bool
    mcp_visible: bool
    refresh_policy: str
    root_path_display: str
    root_path_expanded: str
    database: str = ""
    db_checked: bool = False
    repository_exists: bool | None = None
    latest_run_id: int | None = None
    latest_run_status: str | None = None
    latest_run_started_at: str | None = None
    latest_run_finished_at: str | None = None
    raw_observations: int | None = None
    raw_observations_total: int | None = None
    latest_run_raw_observations: int | None = None
    canonical_nodes: int | None = None
    canonical_edges: int | None = None
    publication: Mapping[str, object] | None = None
    exclude_paths_enforced: bool = True
    configured_exclude_paths_count: int = 0
    default_exclude_paths_count: int = len(DEFAULT_DISCOVERY_EXCLUDE_PATHS)
    exclude_paths: tuple[str, ...] = ()
    root_path_checked: bool = False
    warnings: tuple[Mapping[str, Any], ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()
    error: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "repository_name": self.repository_name,
            "database": self.database,
            "privacy": self.privacy,
            "enabled": self.enabled,
            "mcp_visible": self.mcp_visible,
            "refresh_policy": self.refresh_policy,
            "root_path_display": self.root_path_display,
            "root_path_expanded": self.root_path_expanded,
            "root_path_checked": self.root_path_checked,
            "db_checked": self.db_checked,
            "repository_exists": self.repository_exists,
            "latest_run_id": self.latest_run_id,
            "latest_run_status": self.latest_run_status,
            "latest_run_started_at": self.latest_run_started_at,
            "latest_run_finished_at": self.latest_run_finished_at,
            "latest_run_consistency": recorded_run_consistency_payload(
                latest_run_status=self.latest_run_status,
                latest_run_finished_at=self.latest_run_finished_at,
            ),
            "raw_observations": self.raw_observations,
            "raw_observations_total": (
                self.raw_observations_total
                if self.raw_observations_total is not None
                else self.raw_observations
            ),
            "latest_run_raw_observations": self.latest_run_raw_observations,
            "canonical_nodes": self.canonical_nodes,
            "canonical_edges": self.canonical_edges,
            "publication": dict(self.publication) if self.publication else None,
            "exclude_paths_enforced": self.exclude_paths_enforced,
            "configured_exclude_paths_count": self.configured_exclude_paths_count,
            "default_exclude_paths_count": self.default_exclude_paths_count,
            "exclude_paths": [_redact_text(path) for path in self.exclude_paths],
            "warnings": [dict(warning) for warning in self.warnings],
            "diagnostics": [
                _redact_mapping(diagnostic) for diagnostic in self.diagnostics
            ],
            "error": _redact_text(self.error) if self.error else None,
        }


@dataclass(frozen=True)
class OpsGraphSummary:
    graph_id: str
    repository_name: str
    database: str
    privacy: str
    enabled: bool
    mcp_visible: bool
    root_path_display: str
    root_path_expanded: str
    result: RefreshResult
    db_checked: bool = False
    repository_exists: bool | None = None
    latest_run_id: int | None = None
    latest_run_status: str | None = None
    latest_run_started_at: str | None = None
    latest_run_finished_at: str | None = None
    files: int = 0
    raw_observations: int = 0
    raw_observations_total: int | None = None
    latest_run_raw_observations: int | None = None
    canonical_nodes: int = 0
    canonical_edges: int = 0
    language_counts: Mapping[str, int] | None = None
    observation_kind_counts: Mapping[str, int] | None = None
    latest_run_observation_kind_counts: Mapping[str, int] | None = None
    canonical_node_kind_counts: Mapping[str, int] | None = None
    canonical_edge_kind_counts: Mapping[str, int] | None = None
    warnings: tuple[Mapping[str, Any], ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()
    error: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "repository_name": self.repository_name,
            "database": self.database,
            "privacy": self.privacy,
            "enabled": self.enabled,
            "mcp_visible": self.mcp_visible,
            "root_path_display": self.root_path_display,
            "root_path_expanded": self.root_path_expanded,
            "result": self.result,
            "db_checked": self.db_checked,
            "repository_exists": self.repository_exists,
            "latest_run_id": self.latest_run_id,
            "latest_run_status": self.latest_run_status,
            "latest_run_started_at": self.latest_run_started_at,
            "latest_run_finished_at": self.latest_run_finished_at,
            "latest_run_consistency": recorded_run_consistency_payload(
                latest_run_status=self.latest_run_status,
                latest_run_finished_at=self.latest_run_finished_at,
            ),
            "files": self.files,
            "raw_observations": self.raw_observations,
            "raw_observations_total": (
                self.raw_observations_total
                if self.raw_observations_total is not None
                else self.raw_observations
            ),
            "latest_run_raw_observations": self.latest_run_raw_observations,
            "canonical_nodes": self.canonical_nodes,
            "canonical_edges": self.canonical_edges,
            "language_counts": dict(self.language_counts or {}),
            "observation_kind_counts": dict(self.observation_kind_counts or {}),
            "latest_run_observation_kind_counts": dict(
                self.latest_run_observation_kind_counts or {}
            ),
            "canonical_node_kind_counts": dict(self.canonical_node_kind_counts or {}),
            "canonical_edge_kind_counts": dict(self.canonical_edge_kind_counts or {}),
            "warnings": [dict(warning) for warning in self.warnings],
            "diagnostics": [
                _redact_mapping(diagnostic) for diagnostic in self.diagnostics
            ],
            "error": _redact_text(self.error) if self.error else None,
        }


@dataclass(frozen=True)
class OpsGraphDriftCheck:
    graph_id: str
    database: str
    privacy: str
    current: OpsGraphSummary
    baseline: Mapping[str, Any]
    drift: Mapping[str, Any]
    drift_detected: bool
    result: str
    stored_drift_detected: bool | None = None
    current_preflight: Mapping[str, Any] | None = None
    preflight_baseline: Mapping[str, Any] | None = None
    preflight_drift: Mapping[str, Any] | None = None
    preflight_drift_detected: bool = False
    preflight_safety_drift: Mapping[str, bool] | None = None
    warnings: tuple[Mapping[str, Any], ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class OpsBaselineSaveEntry:
    kind: str
    timestamped_path_display: str
    latest_path_display: str
    bytes_written: int
    payload_command: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "timestamped_path_display": self.timestamped_path_display,
            "latest_path_display": self.latest_path_display,
            "bytes_written": self.bytes_written,
            "payload_command": self.payload_command,
        }


@dataclass(frozen=True)
class OpsBaselineSaveResult:
    graph_id: str
    database: str
    privacy: str
    result: str
    timestamp: str
    kinds: tuple[str, ...]
    baseline_root_display: str
    saved: tuple[OpsBaselineSaveEntry, ...]
    graph_root_read: bool
    warnings: tuple[Mapping[str, Any], ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class OpsBaselinePruneKindResult:
    kind: str
    directory_display: str
    timestamped_files_found: int
    kept_count: int
    candidate_count: int
    deleted_count: int
    ignored_count: int
    latest_preserved: bool
    latest_exists: bool
    kept_path_displays: tuple[str, ...] = ()
    candidate_path_displays: tuple[str, ...] = ()
    deleted_path_displays: tuple[str, ...] = ()
    ignored_path_displays: tuple[str, ...] = ()

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "directory_display": self.directory_display,
            "timestamped_files_found": self.timestamped_files_found,
            "kept_count": self.kept_count,
            "candidate_count": self.candidate_count,
            "deleted_count": self.deleted_count,
            "ignored_count": self.ignored_count,
            "latest_preserved": self.latest_preserved,
            "latest_exists": self.latest_exists,
            "kept_path_displays": list(self.kept_path_displays),
            "candidate_path_displays": list(self.candidate_path_displays),
            "deleted_path_displays": list(self.deleted_path_displays),
            "ignored_path_displays": list(self.ignored_path_displays),
        }


@dataclass(frozen=True)
class OpsBaselinePruneResult:
    graph_id: str
    database: str
    privacy: str
    result: str
    kinds: tuple[str, ...]
    keep: int
    dry_run: bool
    baseline_root_display: str
    processed: tuple[OpsBaselinePruneKindResult, ...]
    warnings: tuple[Mapping[str, Any], ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class OpsRefreshPreflightResult:
    graph_id: str
    repository_name: str
    database: str
    privacy: str
    enabled: bool
    mcp_visible: bool
    root_path_display: str
    root_path_expanded: str
    result: str
    root_exists: bool
    root_is_dir: bool
    root_path_checked: bool = True
    exclude_paths_enforced: bool = True
    configured_exclude_paths_count: int = 0
    default_exclude_paths_count: int = len(DEFAULT_DISCOVERY_EXCLUDE_PATHS)
    configured_exclude_hit_counts: Mapping[str, int] | None = None
    default_exclude_hit_counts: Mapping[str, int] | None = None
    files_considered: int = 0
    files_included: int = 0
    files_skipped: int = 0
    directories_skipped: int = 0
    symlink_count: int = 0
    symlinks_skipped_outside_root: int = 0
    symlinks_skipped_nix_store: int = 0
    generated_output_skips: int = 0
    secret_like_path_count: int = 0
    path_examples_included: bool = False
    top_level_directory_count: int = 0
    top_level_file_count: int = 0
    language_counts: Mapping[str, int] | None = None
    role_counts: Mapping[str, int] | None = None
    extractor_categories: Mapping[str, int] | None = None
    warnings: tuple[Mapping[str, Any], ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()
    error: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "repository_name": self.repository_name,
            "database": self.database,
            "privacy": self.privacy,
            "enabled": self.enabled,
            "mcp_visible": self.mcp_visible,
            "root_path_display": self.root_path_display,
            "root_path_expanded": self.root_path_expanded,
            "root_path_checked": self.root_path_checked,
            "root_exists": self.root_exists,
            "root_is_dir": self.root_is_dir,
            "result": self.result,
            "exclude_paths_enforced": self.exclude_paths_enforced,
            "configured_exclude_paths_count": self.configured_exclude_paths_count,
            "default_exclude_paths_count": self.default_exclude_paths_count,
            "configured_exclude_hit_counts": {
                _redact_text(path): count
                for path, count in (self.configured_exclude_hit_counts or {}).items()
            },
            "default_exclude_hit_counts": {
                _redact_text(path): count
                for path, count in (self.default_exclude_hit_counts or {}).items()
            },
            "files_considered": self.files_considered,
            "files_included": self.files_included,
            "files_skipped": self.files_skipped,
            "directories_skipped": self.directories_skipped,
            "symlink_count": self.symlink_count,
            "symlinks_skipped_outside_root": self.symlinks_skipped_outside_root,
            "symlinks_skipped_nix_store": self.symlinks_skipped_nix_store,
            "generated_output_skips": self.generated_output_skips,
            "secret_like_path_count": self.secret_like_path_count,
            "path_examples_included": self.path_examples_included,
            "top_level_directory_count": self.top_level_directory_count,
            "top_level_file_count": self.top_level_file_count,
            "language_counts": dict(self.language_counts or {}),
            "role_counts": dict(self.role_counts or {}),
            "extractor_categories": dict(self.extractor_categories or {}),
            "warnings": [dict(warning) for warning in self.warnings],
            "diagnostics": [
                _redact_mapping(diagnostic) for diagnostic in self.diagnostics
            ],
            "safety": _preflight_safety_markers(),
            "error": _redact_text(self.error) if self.error else None,
        }


def _count_map(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    counts: dict[str, int] = {}
    for key, count in value.items():
        if (
            isinstance(key, str)
            and isinstance(count, int)
            and not isinstance(count, bool)
        ):
            counts[key] = count
    return dict(sorted(counts.items()))


def _diagnostic(severity: str, code: str, path: str, message: str) -> Mapping[str, str]:
    return OpsConfigDiagnostic(severity, code, path, message).to_jsonable()


def _redact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _redact_text(value) if isinstance(value, str) else value
        for key, value in payload.items()
    }


def _redact_text(value: str | None) -> str:
    if not value:
        return ""
    redacted = redact_text(value)
    assignment = re.compile(
        r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)"
        r"\s*[:=]\s*[^\s,;]+"
    )
    return assignment.sub(lambda match: match.group(1) + "=" + "[REDACTED]", redacted)
