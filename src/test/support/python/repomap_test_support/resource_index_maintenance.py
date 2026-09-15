"""Maintenance-only advisory-index compaction, inventory, and stale recovery."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from repomap_test_support.resource_index import AdvisoryIndex, HostAdmissionRefused
from repomap_test_support.resource_index_bootstrap import canonical_json, filesystem_identity
from repomap_test_support.resource_index_physical_membership import (
    PHYSICAL_INVENTORY_SCHEMA,
    RECOVERY_PHYSICAL_INVENTORY_SCHEMA,
    validate_physical_inventory,
    validate_recovery_physical_inventory,
)
from repomap_test_support.resource_index_reconciliation import (
    DeletedIndexRecoveryResult,
    IndexMaintenanceError,
    _fsync_directory,
    _same_file,
    reconcile_deleted_run,
    recover_deleted_index_reconciliations,
    recover_stale_admission_lock,
)
from repomap_test_support.resource_index_records import (
    INVENTORY_MEMBERSHIP_SCHEMA,
    RECOVERY_INVENTORY_MEMBERSHIP_SCHEMA,
    SUMMARY_SCHEMA,
    safe_run_id,
    validate_admission,
    validate_close,
    validate_inventory_membership,
    validate_recovery_inventory_membership,
)
from repomap_test_support.resource_index_recovery import (
    IndexRecoveryError,
    scan_run_population,
)
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
    write_private_json,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
    MaintenanceHandle,
)
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    nonnegative_int,
)


INVENTORY_MIN_INTERVAL_SECONDS = 86_400


@dataclass(frozen=True)
class CompactionResult:
    generation: int
    folded_runs: int
    records_remaining: int
    allocated_bytes: int
    inode_count: int
    accounting_folded_runs: int
    folded_allocated_bytes: int
    folded_inode_count: int
    snapshot_preserved_runs: int


@dataclass(frozen=True)
class InventoryResult:
    generation: int
    run_count: int
    ambiguous_count: int
    allocated_bytes: int
    inode_count: int


def compact_index(
    index: AdvisoryIndex,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
) -> CompactionResult:
    registry.require_maintenance(maintenance)
    summary = index._read_summary()
    try:
        paths = sorted(index.records_path.iterdir(), key=lambda item: item.name)
    except OSError as error:
        raise IndexMaintenanceError("index records are unreadable") from error
    groups: dict[str, dict[str, tuple[Path, dict[str, object], tuple[int, int]]]] = {}
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise IndexMaintenanceError("index record identity is unsafe")
        metadata = path.stat(follow_symlinks=False)
        try:
            payload = read_private_json(path)
            if path.name.endswith(".admitted.json"):
                kind = "admitted"
                payload = validate_admission(payload)
            elif path.name.endswith(".closed.json"):
                kind = "closed"
                payload = validate_close(payload)
            else:
                raise HygieneValidationError("unsupported index record filename")
        except (PrivateJsonError, HygieneValidationError) as error:
            raise IndexMaintenanceError("index record is invalid") from error
        run_id = payload["run_id"]
        if path.name != f"{run_id}.{kind}.json" or kind in groups.setdefault(run_id, {}):
            raise IndexMaintenanceError("index record identity is ambiguous")
        groups[run_id][kind] = (path, payload, (metadata.st_dev, metadata.st_ino))
    allocated = nonnegative_int(summary["allocated_bytes"], "allocated_bytes")
    inodes = nonnegative_int(summary["inode_count"], "inode_count")
    folded = []
    accounting_folded_runs = 0
    folded_allocated_bytes = 0
    folded_inode_count = 0
    snapshot_preserved_runs = 0
    snapshot_entries: dict[str, tuple[int, int]] = {}
    physical_entries: dict[str, tuple[int, int]] = {}
    if summary["initialization_mode"] == "maintenance_inventory":
        snapshot_entries = _snapshot_entries(index, summary)
        if snapshot_entries:
            physical_entries = _current_run_entries(index)
    for run_id, records in groups.items():
        admitted = records.get("admitted")
        closed = records.get("closed")
        if admitted is None:
            raise IndexMaintenanceError("close record lacks admission authority")
        if closed is None:
            continue
        if admitted[1]["phase"] != closed[1]["phase"]:
            raise IndexMaintenanceError("index record owner is inconsistent")
        snapshot_identity = snapshot_entries.get(run_id)
        no_fold = (
            snapshot_identity is not None
            and physical_entries.get(run_id) == snapshot_identity
            and closed[1]["closed_at_seconds"] < summary["inventory_at_seconds"]
        )
        if not no_fold:
            delta_bytes = nonnegative_int(closed[1]["allocated_bytes"], "allocated_bytes")
            delta_inodes = nonnegative_int(closed[1]["inode_count"], "inode_count")
            allocated += delta_bytes
            inodes += delta_inodes
            accounting_folded_runs += 1
            folded_allocated_bytes += delta_bytes
            folded_inode_count += delta_inodes
        else:
            snapshot_preserved_runs += 1
        folded.append((run_id, admitted, closed))
    replacement = {
        **summary,
        "generation": nonnegative_int(summary["generation"], "generation") + 1,
        "allocated_bytes": allocated,
        "inode_count": inodes,
    }
    try:
        write_private_json(index.summary_path, replacement)
        _fsync_directory(index.root)
        installed = index._read_summary()
    except (OSError, PrivateJsonError, HostAdmissionRefused) as error:
        raise IndexMaintenanceError("replacement summary installation failed") from error
    if installed != replacement:
        raise IndexMaintenanceError("replacement summary readback failed")
    cleanup_incomplete = False
    for _, admitted, closed in folded:
        if not _same_file(closed[0], closed[2]):
            cleanup_incomplete = True
            continue
        try:
            closed[0].unlink()
        except OSError:
            cleanup_incomplete = True
            continue
        if not _same_file(admitted[0], admitted[2]):
            cleanup_incomplete = True
            continue
        try:
            admitted[0].unlink()
        except OSError:
            cleanup_incomplete = True
    remaining = len(tuple(index.records_path.iterdir()))
    if cleanup_incomplete:
        raise IndexMaintenanceError("compaction cleanup is incomplete")
    return CompactionResult(
        installed["generation"],
        len(folded),
        remaining,
        allocated,
        inodes,
        accounting_folded_runs,
        folded_allocated_bytes,
        folded_inode_count,
        snapshot_preserved_runs,
    )


def rebuild_inventory(
    index: AdvisoryIndex,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    *,
    now_seconds: int,
    operator_requested: bool,
) -> InventoryResult:
    registry.require_maintenance(maintenance)
    now = nonnegative_int(now_seconds, "inventory timestamp")
    if index.inventory_path.exists() and not operator_requested:
        try:
            previous = read_private_json(index.inventory_path)
            previous_at = nonnegative_int(
                previous["inventory_at_seconds"], "previous inventory timestamp"
            )
        except (KeyError, PrivateJsonError, HygieneValidationError) as error:
            raise IndexMaintenanceError("previous inventory authority is invalid") from error
        if now - previous_at < INVENTORY_MIN_INTERVAL_SECONDS:
            raise IndexMaintenanceError("maintenance inventory cadence has not elapsed")
    try:
        scan = scan_run_population(index.scratch_root, registry.project)
    except IndexRecoveryError as error:
        raise IndexMaintenanceError("run metadata inventory is unsafe") from error
    allocated = scan.allocated_bytes
    inodes = scan.inode_count
    filesystem_id = filesystem_identity(index.scratch_root)
    seed = {
        "schema": PHYSICAL_INVENTORY_SCHEMA,
        "scratch_filesystem_id": filesystem_id,
        "initialization_mode": "maintenance_inventory",
        "inventory_at_seconds": now,
        "allocated_bytes": allocated,
        "inode_count": inodes,
        "measured_physical_entries": _measured_physical_entries(
            scan.identities
        ),
    }
    provenance_id = hashlib.sha256(canonical_json(seed)).hexdigest()
    inventory = {**seed, "provenance_record_id": provenance_id}
    current = index._read_summary()
    summary = {
        "schema": SUMMARY_SCHEMA,
        "scratch_filesystem_id": filesystem_id,
        "generation": current["generation"] + 1,
        "initialization_mode": "maintenance_inventory",
        "inventory_at_seconds": now,
        "provenance_record_id": provenance_id,
        "allocated_bytes": allocated,
        "inode_count": inodes,
    }
    try:
        write_private_json(index.inventory_path, inventory)
        _fsync_directory(index.root)
        write_private_json(index.summary_path, summary)
        _fsync_directory(index.root)
        installed = index._read_summary()
    except (OSError, PrivateJsonError, HostAdmissionRefused) as error:
        raise IndexMaintenanceError("maintenance inventory installation failed") from error
    if installed != summary:
        raise IndexMaintenanceError("maintenance inventory readback failed")
    return InventoryResult(
        summary["generation"],
        scan.valid_run_count,
        scan.ambiguous_run_count,
        allocated,
        inodes,
    )


def _snapshot_entries(
    index: AdvisoryIndex,
    summary: dict[str, object],
) -> dict[str, tuple[int, int]]:
    try:
        raw = read_private_json(index.inventory_path)
        schema = raw.get("schema")
        if schema == INVENTORY_MEMBERSHIP_SCHEMA:
            payload = validate_inventory_membership(raw)
        elif schema == RECOVERY_INVENTORY_MEMBERSHIP_SCHEMA:
            payload = validate_recovery_inventory_membership(raw)
        elif schema == PHYSICAL_INVENTORY_SCHEMA:
            payload = validate_physical_inventory(raw)
        elif schema == RECOVERY_PHYSICAL_INVENTORY_SCHEMA:
            payload = validate_recovery_physical_inventory(raw)
        else:
            return {}
    except (PrivateJsonError, HygieneValidationError) as error:
        raise IndexMaintenanceError("inventory membership is invalid") from error
    if payload["inventory_at_seconds"] != summary["inventory_at_seconds"]:
        raise IndexMaintenanceError("inventory membership cutoff is inconsistent")
    if schema in {PHYSICAL_INVENTORY_SCHEMA, RECOVERY_PHYSICAL_INVENTORY_SCHEMA}:
        return {
            entry["valid_run_id"]: (entry["device"], entry["inode"])
            for entry in payload["measured_physical_entries"]
            if entry["valid_run_id"] is not None
        }
    return {
        entry["run_id"]: (entry["device"], entry["inode"])
        for entry in payload["measured_run_entries"]
    }


def _current_run_entries(index: AdvisoryIndex) -> dict[str, tuple[int, int]]:
    runs_root = index.scratch_root / "r"
    if runs_root.is_symlink():
        raise IndexMaintenanceError("run population is unsafe")
    if not runs_root.exists():
        return {}
    try:
        scratch_device = index.scratch_root.stat().st_dev
        entries = {}
        folded = set()
        for path in runs_root.iterdir():
            metadata = path.lstat()
            if path.name.casefold() in folded:
                raise IndexMaintenanceError("run population identity is ambiguous")
            folded.add(path.name.casefold())
            try:
                run_id = safe_run_id(path.name)
            except HygieneValidationError:
                continue
            if (
                stat.S_ISDIR(metadata.st_mode)
                and not stat.S_ISLNK(metadata.st_mode)
                and metadata.st_uid == os.getuid()
                and metadata.st_dev == scratch_device
            ):
                entries[run_id] = (metadata.st_dev, metadata.st_ino)
        return entries
    except OSError as error:
        raise IndexMaintenanceError("run population is unreadable") from error


def _measured_physical_entries(
    identities: tuple[tuple[str, str | None, int, int], ...],
) -> list[dict[str, int | str | None]]:
    return [
        {
            "entry_key": entry_key,
            "valid_run_id": run_id,
            "device": device,
            "inode": inode,
        }
        for entry_key, run_id, device, inode in identities
    ]




__all__ = [
    "CompactionResult", "DeletedIndexRecoveryResult",
    "INVENTORY_MIN_INTERVAL_SECONDS", "IndexMaintenanceError",
    "InventoryResult", "compact_index", "rebuild_inventory",
    "reconcile_deleted_run", "recover_deleted_index_reconciliations",
    "recover_stale_admission_lock",
]
