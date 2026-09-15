"""Maintenance-only recovery for untrusted advisory-index authority."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from repomap_test_support.resource_index import (
    lifecycle_record_capacity,
)
from repomap_test_support.resource_index_operations import profile_headroom
from repomap_test_support.resource_index_physical_membership import (
    physical_entry_key,
)
from repomap_test_support.resource_index_records import (
    LOCK_SCHEMA,
    owner_token as validate_owner_token,
    safe_run_id,
)
from repomap_test_support.resource_index_recovery_records import (
    IndexRecoveryError,
)
from repomap_test_support.resource_index_recovery_execution import (
    LEGACY_SUMMARY_SCHEMA as LEGACY_SUMMARY_SCHEMA,
    MAX_PRESERVED_GENERATION as MAX_PRESERVED_GENERATION,
    MaintenanceIndexBinding,
    PostRecoveryLifecycleUnresolved,
    RecordCapUnresolved,
    RecoveryResult,
    SharedStateChanged,
    _authority_snapshot as _authority_snapshot,
    _ensure_private_directory,
    _fsync_directory,
    _generation_rule as _generation_rule,
    execute_recover_index,
)
from repomap_test_support.resource_ledger import (
    ResourceLedger,
    ResourceLedgerError,
    RunIdentity,
)
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
    MaintenanceHandle,
)
from repomap_test_support.resource_run_cleanup import process_start_evidence
from repomap_test_support.resource_scratch import (
    ScratchAccountingError,
    measure_scratch,
)
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    nonnegative_int,
)
from repomap_test_support.test_scratch import (
    MANIFEST_SCHEMA,
    TestScratchError,
    read_run_manifest,
)


@dataclass(frozen=True)
class PopulationScan:
    entry_count: int
    valid_run_count: int
    ambiguous_run_count: int
    allocated_bytes: int
    inode_count: int
    internal_unsafe_link_count: int
    measured_names: frozenset[str]
    identities: tuple[tuple[str, str | None, int, int], ...]


@dataclass(frozen=True)
class AdmissionBarrier:
    owner_token: str
    device: int
    inode: int


def scan_run_population(scratch_root: Path, project: str) -> PopulationScan:
    """Measure every immediate entry before classifying its authority."""
    project = safe_run_id(project)
    runs_root = Path(scratch_root) / "r"
    if runs_root.is_symlink():
        raise IndexRecoveryError("run population is unsafe")
    if not runs_root.exists():
        return PopulationScan(0, 0, 0, 0, 0, 0, frozenset(), ())
    runs_metadata = _owned_directory(runs_root, "run population")
    before = _population_snapshot(runs_root)
    allocated = inodes = unsafe_links = valid = ambiguous = 0
    names: set[str] = set()
    identities: list[tuple[str, str | None, int, int]] = []
    folded_names: set[str] = set()
    for name, device, inode in before:
        if name.casefold() in folded_names:
            raise IndexRecoveryError("run population identity is ambiguous")
        folded_names.add(name.casefold())
        run_root = runs_root / name
        metadata = _measurable_immediate(
            run_root, device, inode, expected_device=runs_metadata.st_dev
        )
        try:
            measurement = measure_scratch(run_root, reject_unsafe_links=False)
        except ScratchAccountingError as error:
            raise IndexRecoveryError(
                "run population is unmeasurable",
                category="physical_entry_unmeasurable",
            ) from error
        current = _measurable_immediate(
            run_root, device, inode, expected_device=runs_metadata.st_dev
        )
        if (current.st_dev, current.st_ino) != (
            metadata.st_dev,
            metadata.st_ino,
        ):
            raise SharedStateChanged()
        allocated += measurement.allocated_bytes
        inodes += measurement.inode_count
        unsafe_links += measurement.unsafe_link_count
        try:
            valid_run_id = safe_run_id(name)
        except HygieneValidationError:
            valid_run_id = None
        else:
            if stat.S_ISDIR(metadata.st_mode) and valid_run_id is not None:
                names.add(valid_run_id)
        identities.append(
            (physical_entry_key(name), valid_run_id, device, inode)
        )
        if valid_run_id is not None and _is_valid_run(run_root, project):
            valid += 1
        else:
            ambiguous += 1
    after = _population_snapshot(runs_root)
    if after != before:
        raise SharedStateChanged()
    return PopulationScan(
        len(before),
        valid,
        ambiguous,
        allocated,
        inodes,
        unsafe_links,
        frozenset(names),
        tuple(sorted(identities, key=lambda item: item[0])),
    )


def recover_index(
    binding: MaintenanceIndexBinding,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    *,
    now_seconds: int,
    checkpoint: Callable[[str], None] | None = None,
    admission_barrier: AdmissionBarrier | None = None,
    preserved_terminal_names: frozenset[str] = frozenset(),
) -> RecoveryResult:
    """Install conservative authority without trusting the current summary."""
    return execute_recover_index(
        binding,
        registry,
        maintenance,
        now_seconds=now_seconds,
        checkpoint=checkpoint,
        admission_barrier=admission_barrier,
        preserved_terminal_names=preserved_terminal_names,
        lifecycle_capacity_fn=lifecycle_record_capacity,
    )


def acquire_admission_barrier(
    binding: MaintenanceIndexBinding,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    *,
    now_seconds: int,
) -> AdmissionBarrier:
    registry.require_maintenance(maintenance)
    binding.revalidate()
    now = nonnegative_int(now_seconds, "admission barrier timestamp")
    _ensure_private_directory(binding.recovery_path)
    token = validate_owner_token(maintenance.owner_token)
    payload = {
        "schema": LOCK_SCHEMA,
        "owner_token": token,
        "process_id": os.getpid(),
        "process_start_evidence": process_start_evidence(),
        "created_at_seconds": now,
    }
    try:
        write_private_json_exclusive(binding.lock_path, payload)
    except FileExistsError as error:
        raise IndexRecoveryError("admission barrier is already held") from error
    metadata = binding.lock_path.stat(follow_symlinks=False)
    return AdmissionBarrier(token, metadata.st_dev, metadata.st_ino)


def require_admission_barrier(
    binding: MaintenanceIndexBinding,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    barrier: AdmissionBarrier,
) -> None:
    registry.require_maintenance(maintenance)
    binding.revalidate()
    if not isinstance(barrier, AdmissionBarrier):
        raise IndexRecoveryError("admission barrier handle is invalid")
    try:
        payload = read_private_json(binding.lock_path)
        metadata = binding.lock_path.stat(follow_symlinks=False)
    except (OSError, PrivateJsonError) as error:
        raise IndexRecoveryError("admission barrier is unavailable") from error
    if (
        payload.get("schema") != LOCK_SCHEMA
        or payload.get("owner_token") != barrier.owner_token
        or barrier.owner_token != maintenance.owner_token
        or (metadata.st_dev, metadata.st_ino) != (barrier.device, barrier.inode)
    ):
        raise IndexRecoveryError("admission barrier ownership changed")


def release_admission_barrier(
    binding: MaintenanceIndexBinding,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    barrier: AdmissionBarrier,
) -> None:
    require_admission_barrier(binding, registry, maintenance, barrier)
    tombstone = binding.recovery_path / (
        f"admission-release-{barrier.owner_token}.tmp"
    )
    if tombstone.exists() or tombstone.is_symlink():
        raise IndexRecoveryError("admission barrier release tombstone exists")
    try:
        os.rename(binding.lock_path, tombstone)
        payload = read_private_json(tombstone)
        metadata = tombstone.stat(follow_symlinks=False)
        if (
            payload.get("schema") != LOCK_SCHEMA
            or payload.get("owner_token") != barrier.owner_token
            or (metadata.st_dev, metadata.st_ino) != (barrier.device, barrier.inode)
        ):
            raise IndexRecoveryError("admission barrier ownership changed")
        tombstone.unlink()
        _fsync_directory(binding.root)
    except (OSError, PrivateJsonError) as error:
        if tombstone.exists() and not binding.lock_path.exists():
            os.rename(tombstone, binding.lock_path)
        raise IndexRecoveryError("admission barrier release failed") from error


def _population_snapshot(root: Path) -> tuple[tuple[str, int, int], ...]:
    try:
        values = []
        for path in root.iterdir():
            metadata = path.lstat()
            values.append((path.name, metadata.st_dev, metadata.st_ino))
        return tuple(sorted(values))
    except OSError as error:
        raise IndexRecoveryError("run population is unreadable") from error


def _measurable_immediate(
    path: Path,
    device: int,
    inode: int,
    *,
    expected_device: int,
):
    try:
        metadata = path.lstat()
    except OSError as error:
        raise SharedStateChanged() from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode))
        or metadata.st_uid != os.getuid()
        or metadata.st_dev != expected_device
        or (stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1)
    ):
        raise IndexRecoveryError(
            "immediate run entry is unsafe", category="physical_entry_unsafe"
        )
    if (metadata.st_dev, metadata.st_ino) != (device, inode):
        raise SharedStateChanged()
    return metadata


def _is_valid_run(run_root: Path, project: str) -> bool:
    if not run_root.is_dir():
        return False
    try:
        manifest = read_run_manifest(run_root)
        if (
            manifest.get("schema") != MANIFEST_SCHEMA
            or manifest.get("project") != project
            or manifest.get("run_kind") != "test"
            or manifest.get("run_id") != run_root.name
            or Path(manifest.get("physical_run_root", "")).resolve()
            != run_root.resolve()
        ):
            return False
        identity = RunIdentity(project, manifest["phase"], run_root.name)
        ResourceLedger.open(run_root / "resource-ledger.json", identity)
    except (
        KeyError,
        OSError,
        ResourceLedgerError,
        TestScratchError,
        TypeError,
        ValueError,
    ):
        return False
    return True


def _owned_directory(path: Path, label: str):
    try:
        metadata = path.lstat()
    except OSError as error:
        raise IndexRecoveryError(f"{label} is unavailable") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
    ):
        raise IndexRecoveryError(f"{label} is unsafe")
    return metadata




__all__ = [
    "AdmissionBarrier",
    "IndexRecoveryError",
    "MaintenanceIndexBinding",
    "PopulationScan",
    "PostRecoveryLifecycleUnresolved",
    "RecordCapUnresolved",
    "RecoveryResult",
    "SharedStateChanged",
    "acquire_admission_barrier",
    "profile_headroom",
    "release_admission_barrier",
    "recover_index",
    "require_admission_barrier",
    "scan_run_population",
]
