"""Immutable reclaim inventory records and pure liveness summaries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from repomap_test_support.resource_lifecycle_claim import (
    ProcessLiveness, coerce_process_liveness,
)
from repomap_test_support.resource_safe_tree_delete import RunEntryInspection
from repomap_test_support.resource_safe_tree_pin import EntryPin


@dataclass(frozen=True)
class ScopeEntry:
    name: str
    inspection: RunEntryInspection
    category: str
    manifest: dict[str, object] | None
    pin: EntryPin | None = None


@dataclass(frozen=True)
class OwnedPath:
    path: Path
    device: int
    inode: int
    mode: int
    link_target: Path | None = None
    owner_names: tuple[str, ...] = ()
    record_kind: str | None = None


def classify_liveness(
    entries: tuple[ScopeEntry, ...],
    probe: Callable[[int], ProcessLiveness | bool],
) -> tuple[int, int]:
    live = unknown = 0
    for entry in entries:
        if entry.category != "valid":
            continue
        manifest = entry.manifest
        if not isinstance(manifest, dict) or manifest.get("state") != "running":
            continue
        pid = manifest.get("pid")
        if type(pid) is not int or pid <= 0:
            unknown += 1
            continue
        state = coerce_process_liveness(probe(pid))
        if state is ProcessLiveness.LIVE:
            live += 1
        elif state is ProcessLiveness.UNKNOWN:
            unknown += 1
    return live, unknown


COTENANT_ACTIVITY_FIELDS = tuple(
    f"{category}_{suffix}"
    for category in ("foreign", "ambiguous")
    for suffix in (
        "running_manifest_count",
        "positive_pid_manifest_count",
        "live_observed_count",
        "dead_observed_count",
        "unknown_observed_count",
        "invalid_or_missing_pid_count",
    )
)


_MAX_AUDIT_PID = 2**31 - 1


def classify_cotenant_activity(
    entries: tuple[ScopeEntry, ...],
    probe: Callable[[int], ProcessLiveness | bool],
) -> dict[str, int]:
    """Observe foreign/ambiguous running manifests without granting authority."""
    result = {field: 0 for field in COTENANT_ACTIVITY_FIELDS}
    for entry in entries:
        if entry.category not in {"foreign", "ambiguous"}:
            continue
        manifest = entry.manifest
        if not isinstance(manifest, dict) or manifest.get("state") != "running":
            continue
        prefix = entry.category
        result[f"{prefix}_running_manifest_count"] += 1
        pid = manifest.get("pid")
        if type(pid) is not int or pid <= 0 or pid > _MAX_AUDIT_PID:
            result[f"{prefix}_invalid_or_missing_pid_count"] += 1
            continue
        result[f"{prefix}_positive_pid_manifest_count"] += 1
        try:
            state = coerce_process_liveness(probe(pid))
        except Exception:
            state = ProcessLiveness.UNKNOWN
        suffix = {
            ProcessLiveness.LIVE: "live_observed_count",
            ProcessLiveness.DEAD: "dead_observed_count",
            ProcessLiveness.UNKNOWN: "unknown_observed_count",
        }[state]
        result[f"{prefix}_{suffix}"] += 1
    return result


def category_counts(entries: tuple[ScopeEntry, ...]) -> dict[str, int]:
    result = {key: 0 for key in ("valid", "ambiguous", "foreign", "opaque")}
    for entry in entries:
        result[entry.category] += 1
    return result


def inventory_digest(entries: tuple[ScopeEntry, ...]) -> str:
    values = [
        {
            "name": entry.name,
            "device": entry.inspection.device,
            "inode": entry.inspection.inode,
            "mode": entry.inspection.mode,
        }
        for entry in entries
    ]
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
