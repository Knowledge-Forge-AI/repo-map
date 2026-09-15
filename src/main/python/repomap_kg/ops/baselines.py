"""Ops baseline path, write, prune, and drift helpers."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from repomap_kg.ops.config import PRIVATE_PRIVACY, OpsConfig
from repomap_kg.ops.reports import (
    OpsBaselinePruneKindResult,
    OpsBaselineSaveEntry,
    OpsGraphSummary,
    OpsRefreshError,
    _BASELINE_MAP_FIELDS,
    _BASELINE_SCALAR_FIELDS,
    _PREFLIGHT_BASELINE_BOOLEAN_FIELDS,
    _PREFLIGHT_BASELINE_MAP_FIELDS,
    _PREFLIGHT_BASELINE_SCALAR_FIELDS,
    _PREFLIGHT_FALSE_SAFETY_FIELDS,
    _count_map,
)

def _normalize_baseline_payload(baseline: Mapping[str, Any]) -> dict[str, Any]:
    raw_b = baseline.get("baseline")
    raw_g = baseline.get("graph")
    source: Mapping[str, Any] = (
        raw_b if isinstance(raw_b, Mapping) else (raw_g if isinstance(raw_g, Mapping) else baseline)
    )
    return {str(key): value for key, value in source.items()}

def _normalize_preflight_baseline_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw_g = payload.get("graph")
    graph_payload = raw_g if isinstance(raw_g, Mapping) else payload
    safety_payload = payload.get("safety")
    if not isinstance(graph_payload, Mapping):
        raise OpsRefreshError("preflight baseline file must contain a graph object")
    normalized = {str(key): value for key, value in graph_payload.items()}
    graph_safety = normalized.get("safety")
    if isinstance(safety_payload, Mapping):
        normalized["safety"] = {str(key): value for key, value in safety_payload.items()}
    elif isinstance(graph_safety, Mapping):
        normalized["safety"] = {str(key): value for key, value in graph_safety.items()}
    else:
        normalized["safety"] = {}
    return normalized

def _int_or_zero(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

def _bool_or_false(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return False

def _build_drift_payload(
    current: OpsGraphSummary,
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    current_payload = current.to_jsonable()
    drift: dict[str, Any] = {}

    for field in _BASELINE_SCALAR_FIELDS:
        baseline_value = _int_or_zero(baseline.get(field))
        current_value = _int_or_zero(current_payload.get(field))
        drift[field] = {
            "baseline": baseline_value,
            "current": current_value,
            "delta": current_value - baseline_value,
            "changed": current_value != baseline_value,
        }

    for field in _BASELINE_MAP_FIELDS:
        baseline_counts = _count_map(baseline.get(field))
        current_counts = _count_map(current_payload.get(field))
        changed: dict[str, dict[str, int]] = {}
        for key in sorted(set(baseline_counts) | set(current_counts)):
            baseline_value = baseline_counts.get(key, 0)
            current_value = current_counts.get(key, 0)
            if baseline_value != current_value:
                changed[key] = {
                    "baseline": baseline_value,
                    "current": current_value,
                    "delta": current_value - baseline_value,
                }
        drift[field] = {
            "baseline_total": sum(baseline_counts.values()),
            "current_total": sum(current_counts.values()),
            "delta_total": sum(current_counts.values()) - sum(baseline_counts.values()),
            "changed": changed,
        }

    return drift

def _preflight_scalar_value(payload: Mapping[str, Any], field: str) -> int:
    if field == "diagnostic_count":
        diagnostics = payload.get("diagnostics")
        return len(diagnostics) if isinstance(diagnostics, list) else 0
    if field == "warning_count":
        warnings = payload.get("warnings")
        return len(warnings) if isinstance(warnings, list) else 0
    if field == "unknown_role_count":
        return _count_map(payload.get("role_counts")).get("unknown", 0)
    return _int_or_zero(payload.get(field))

def _build_preflight_drift_payload(
    current: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    drift: dict[str, Any] = {}

    for field in _PREFLIGHT_BASELINE_SCALAR_FIELDS:
        baseline_value = _preflight_scalar_value(baseline, field)
        current_value = _preflight_scalar_value(current, field)
        drift[field] = {
            "baseline": baseline_value,
            "current": current_value,
            "delta": current_value - baseline_value,
            "changed": current_value != baseline_value,
        }

    for field in _PREFLIGHT_BASELINE_BOOLEAN_FIELDS:
        baseline_value = _bool_or_false(baseline.get(field))
        current_value = _bool_or_false(current.get(field))
        drift[field] = {
            "baseline": baseline_value,
            "current": current_value,
            "changed": current_value != baseline_value,
        }

    for field in _PREFLIGHT_BASELINE_MAP_FIELDS:
        baseline_counts = _count_map(baseline.get(field))
        current_counts = _count_map(current.get(field))
        changed: dict[str, dict[str, int]] = {}
        for key in sorted(set(baseline_counts) | set(current_counts)):
            baseline_value = baseline_counts.get(key, 0)
            current_value = current_counts.get(key, 0)
            if baseline_value != current_value:
                changed[key] = {
                    "baseline": baseline_value,
                    "current": current_value,
                    "delta": current_value - baseline_value,
                }
        drift[field] = {
            "baseline_total": sum(baseline_counts.values()),
            "current_total": sum(current_counts.values()),
            "delta_total": sum(current_counts.values()) - sum(baseline_counts.values()),
            "changed": changed,
        }

    return drift

def _build_preflight_safety_drift(
    current: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    privacy: str,
) -> dict[str, bool]:
    current_safety = current.get("safety")
    baseline_safety = baseline.get("safety")
    current_markers = current_safety if isinstance(current_safety, Mapping) else {}
    baseline_markers = baseline_safety if isinstance(baseline_safety, Mapping) else {}

    drift: dict[str, bool] = {}
    for field in _PREFLIGHT_FALSE_SAFETY_FIELDS:
        current_value = _bool_or_false(current_markers.get(field))
        baseline_value = _bool_or_false(baseline_markers.get(field))
        drift[field] = current_value or current_value != baseline_value

    private_root_must_be_redacted = privacy in PRIVATE_PRIVACY
    current_root_display = str(current.get("root_path_display") or "")
    current_root_expanded = str(current.get("root_path_expanded") or "")
    drift["private_root_redacted"] = private_root_must_be_redacted and (
        current_root_display != "[private-root]"
        or current_root_expanded != "[private-root]"
    )
    return drift

def _drift_payload_detected(drift: Mapping[str, Any]) -> bool:
    for field in _BASELINE_SCALAR_FIELDS:
        if drift.get(field, {}).get("changed"):
            return True
    for field in _BASELINE_MAP_FIELDS:
        if drift.get(field, {}).get("changed"):
            return True
    return False

def _preflight_drift_detected(
    drift: Mapping[str, Any],
    safety_drift: Mapping[str, bool],
) -> bool:
    for field in _PREFLIGHT_BASELINE_SCALAR_FIELDS:
        if drift.get(field, {}).get("changed"):
            return True
    for field in _PREFLIGHT_BASELINE_BOOLEAN_FIELDS:
        if drift.get(field, {}).get("changed"):
            return True
    for field in _PREFLIGHT_BASELINE_MAP_FIELDS:
        if drift.get(field, {}).get("changed"):
            return True
    return any(safety_drift.values())

_BASELINE_PATH_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_BASELINE_TIMESTAMP_FILE_PATTERN = re.compile(r"^\d{8}T\d{6}Z\.json$")

_BASELINE_DISPLAY_LIMIT = 25

def _baseline_path_segment(value: str, label: str) -> str:
    if not value or value in (".", ".."):
        raise OpsRefreshError(f"unsafe {label} for baseline path: {value!r}")
    if "/" in value or "\\" in value:
        raise OpsRefreshError(f"unsafe {label} for baseline path: {value!r}")
    if not _BASELINE_PATH_SEGMENT_PATTERN.fullmatch(value):
        raise OpsRefreshError(f"unsafe {label} for baseline path: {value!r}")
    return value

def _baseline_kinds(kind: str) -> tuple[str, ...]:
    if kind == "stored":
        return ("stored",)
    if kind == "preflight":
        return ("preflight",)
    if kind == "both":
        return ("stored", "preflight")
    raise OpsRefreshError(f"unsupported baseline kind {kind!r}")

def _baseline_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

def _baseline_storage_root(config: OpsConfig) -> Path:
    if not config.config_home:
        raise OpsRefreshError("baseline-save requires --repo-map-home or REPOMAP_HOME")
    repo_map_home = Path(config.config_home).expanduser().resolve()
    return repo_map_home / "status" / "baselines"

def _baseline_display_path(
    graph_segment: str,
    kind: str | None = None,
    file_name: str | None = None,
) -> str:
    parts = ["status", "baselines", graph_segment]
    if kind is not None:
        parts.append(kind)
    if file_name is not None:
        parts.append(file_name)
    return "/".join(parts)

def _write_baseline_payload(
    baseline_graph_root: Path,
    *,
    graph_segment: str,
    kind: str,
    timestamp: str,
    payload: Mapping[str, Any],
) -> OpsBaselineSaveEntry:
    kind_segment = _baseline_path_segment(kind, "baseline kind")
    file_name = f"{timestamp}.json"
    _baseline_path_segment(timestamp, "baseline timestamp")
    baseline_dir = baseline_graph_root / kind_segment
    baseline_dir.mkdir(parents=True, exist_ok=True)
    timestamped_path = baseline_dir / file_name
    latest_path = baseline_dir / "latest.json"
    json_text = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    bytes_written = len(json_text.encode("utf-8"))
    _atomic_write_text(timestamped_path, json_text, replace_existing=False)
    _atomic_write_text(latest_path, json_text, replace_existing=True)
    return OpsBaselineSaveEntry(
        kind=kind_segment,
        timestamped_path_display=_baseline_display_path(graph_segment, kind_segment, file_name),
        latest_path_display=_baseline_display_path(graph_segment, kind_segment, "latest.json"),
        bytes_written=bytes_written,
        payload_command=str(payload.get("command", "")),
    )

def _prune_baseline_kind(
    baseline_graph_root: Path,
    *,
    graph_segment: str,
    kind: str,
    keep: int,
    dry_run: bool,
    baseline_root: Path,
) -> OpsBaselinePruneKindResult:
    kind_segment = _baseline_path_segment(kind, "baseline kind")
    baseline_dir = baseline_graph_root / kind_segment
    _ensure_path_under_baseline_root(baseline_dir, baseline_root)

    timestamped_files: list[Path] = []
    ignored_files: list[Path] = []
    latest_path = baseline_dir / "latest.json"
    latest_exists = latest_path.exists()

    if baseline_dir.exists():
        if not baseline_dir.is_dir():
            raise OpsRefreshError(
                f"baseline path is not a directory: "
                f"{_baseline_display_path(graph_segment, kind_segment)}"
            )
        for path in baseline_dir.iterdir():
            _ensure_path_under_baseline_root(path, baseline_root)
            if path.name == "latest.json":
                continue
            if path.is_file() and _BASELINE_TIMESTAMP_FILE_PATTERN.fullmatch(path.name):
                timestamped_files.append(path)
            else:
                ignored_files.append(path)

    timestamped_files.sort(key=lambda path: path.name, reverse=True)
    kept_files = timestamped_files[:keep]
    candidate_files = timestamped_files[keep:]
    deleted_files: list[Path] = []

    if not dry_run:
        for path in candidate_files:
            _ensure_path_under_baseline_root(path, baseline_root)
            if path.name == "latest.json":
                raise OpsRefreshError("refusing to delete latest.json")
            if not _BASELINE_TIMESTAMP_FILE_PATTERN.fullmatch(path.name):
                raise OpsRefreshError(f"refusing to delete non-baseline file: {path.name}")
            if path.is_file():
                path.unlink()
                deleted_files.append(path)
            else:
                ignored_files.append(path)

    return OpsBaselinePruneKindResult(
        kind=kind_segment,
        directory_display=_baseline_display_path(graph_segment, kind_segment),
        timestamped_files_found=len(timestamped_files),
        kept_count=len(kept_files),
        candidate_count=len(candidate_files),
        deleted_count=len(deleted_files),
        ignored_count=len(ignored_files),
        latest_preserved=latest_exists == latest_path.exists(),
        latest_exists=latest_path.exists(),
        kept_path_displays=_baseline_path_displays(graph_segment, kind_segment, kept_files),
        candidate_path_displays=_baseline_path_displays(graph_segment, kind_segment, candidate_files),
        deleted_path_displays=_baseline_path_displays(graph_segment, kind_segment, deleted_files),
        ignored_path_displays=_baseline_path_displays(graph_segment, kind_segment, ignored_files),
    )

def _baseline_path_displays(
    graph_segment: str,
    kind_segment: str,
    paths: Sequence[Path],
) -> tuple[str, ...]:
    return tuple(
        _baseline_display_path(graph_segment, kind_segment, path.name)
        for path in paths[:_BASELINE_DISPLAY_LIMIT]
    )

def _ensure_path_under_baseline_root(path: Path, baseline_root: Path) -> None:
    resolved_root = baseline_root.resolve()
    resolved_path = path.resolve()
    if resolved_path == resolved_root:
        return
    if resolved_root not in resolved_path.parents:
        raise OpsRefreshError("refusing baseline path outside REPOMAP_HOME/status/baselines")

def _atomic_write_text(path: Path, text: str, *, replace_existing: bool) -> None:
    if path.exists() and not replace_existing:
        raise OpsRefreshError(f"baseline file already exists: {path.name}")
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass

def _utc_now_text() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
