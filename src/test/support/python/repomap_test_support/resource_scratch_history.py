"""Dry-run historical scratch candidate classification."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from repomap_test_support.resource_lifecycle_claim import (
    ProcessLiveness,
    coerce_process_liveness,
)
from repomap_test_support.resource_retention import RetentionClass
from repomap_test_support.test_scratch import MANIFEST_SCHEMA


@dataclass(frozen=True)
class HistoricalScratchCandidate:
    opaque_run_token: str
    allocated_bytes: int
    apparent_bytes: int
    inode_count: int


@dataclass(frozen=True)
class HistoricalScratchInventory:
    candidates: tuple[HistoricalScratchCandidate, ...]
    ambiguous_count: int
    active_count: int


@dataclass(frozen=True)
class HistoricalGcCandidate:
    run_id: str
    phase: str
    run_root: Path
    device: int
    inode: int
    allocated_bytes: int
    inode_count: int
    terminal_at_seconds: int
    retention_class: RetentionClass
    over_retention: bool


@dataclass(frozen=True)
class HistoricalGcDiscovery:
    eligible: tuple[HistoricalGcCandidate, ...]
    active_count: int
    ambiguous_count: int
    unexpired_count: int
    pinned_count: int
    report_held_count: int
    monitoring_held_count: int


class HistoricalRevalidationError(ValueError):
    def __init__(self, message: str, *, category: str) -> None:
        self.category = category
        super().__init__(message)


def classify_historical_scratch(
    scratch_root: Path,
    *,
    current_run_id: str,
    process_is_live: Callable[[int], ProcessLiveness | bool],
    active_report_run_ids: set[str],
    active_monitoring_run_ids: set[str],
) -> HistoricalScratchInventory:
    """Return exact dry-run candidates; never remove or rewrite a run."""
    from repomap_test_support.resource_scratch import (
        ScratchAccountingError,
        measure_scratch,
    )

    runs = Path(scratch_root) / "r"
    candidate_measurements = []
    ambiguous = active = 0
    reports = active_report_run_ids
    monitored = active_monitoring_run_ids
    if not runs.is_dir() or runs.is_symlink():
        return HistoricalScratchInventory((), 0, 0)
    for run in sorted(runs.iterdir(), key=lambda item: item.name):
        if run.is_symlink() or not run.is_dir():
            ambiguous += 1
            continue
        manifest_path = run / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            ambiguous += 1
            continue
        try:
            if run.stat().st_uid != os.getuid() or manifest_path.stat().st_uid != os.getuid():
                ambiguous += 1
                continue
        except OSError:
            ambiguous += 1
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ambiguous += 1
            continue
        physical = manifest.get("physical_run_root")
        valid = (
            manifest.get("schema") == MANIFEST_SCHEMA
            and manifest.get("project") == "repo-map_dev"
            and manifest.get("run_kind") == "test"
            and manifest.get("run_id") == run.name
            and isinstance(physical, str)
            and Path(physical).resolve() == run.resolve()
        )
        if not valid:
            ambiguous += 1
            continue
        if run.name == current_run_id:
            continue
        pid = manifest.get("pid")
        owner_live = isinstance(pid, int) and _process_protects(
            process_is_live(pid)
        )
        if (
            manifest.get("state") == "running"
            or owner_live
            or run.name in reports
            or run.name in monitored
        ):
            active += 1
            continue
        if manifest.get("state") not in {"passed", "failed", "stopped"}:
            ambiguous += 1
            continue
        try:
            measurement = measure_scratch(run, reject_unsafe_links=True)
        except ScratchAccountingError:
            ambiguous += 1
            continue
        candidate_measurements.append((run.name, measurement))
    candidates = tuple(
        HistoricalScratchCandidate(
            run_id,
            measurement.allocated_bytes,
            measurement.apparent_bytes,
            measurement.inode_count,
        )
        for run_id, measurement in candidate_measurements
    )
    return HistoricalScratchInventory(candidates, ambiguous, active)


def _process_protects(value: ProcessLiveness | bool) -> bool:
    return coerce_process_liveness(value) is not ProcessLiveness.DEAD


from repomap_test_support import resource_scratch_history_gc as _gc

_report_source_released = _gc._report_source_released
_strict_manifest = _gc._strict_manifest
_valid_protection = _gc._valid_protection
discover_historical_gc = _gc.discover_historical_gc
revalidate_historical_candidate = _gc.revalidate_historical_candidate


__all__ = [
    "HistoricalScratchCandidate",
    "HistoricalScratchInventory",
    "HistoricalGcCandidate",
    "HistoricalGcDiscovery",
    "HistoricalRevalidationError",
    "classify_historical_scratch",
    "discover_historical_gc",
    "revalidate_historical_candidate",
]
