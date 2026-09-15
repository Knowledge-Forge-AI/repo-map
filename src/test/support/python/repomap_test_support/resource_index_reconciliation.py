"""Advisory-index reconciliation for deleted runs and stale admission lock recovery."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from repomap_test_support.resource_deletion_records import (
    DeletionRecordError,
    DeletionRecordStore,
)
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_index_layout import ALLOWED_PROJECT_INDEX_ENTRIES
from repomap_test_support.resource_index_records import (
    LOCK_SCHEMA,
    safe_run_id,
    safe_text,
    validate_admission,
    validate_close,
)
from repomap_test_support.resource_index_recovery_records import IndexRecoveryError
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
)
from repomap_test_support.resource_lifecycle_claim import (
    CLAIM_LEASE_SECONDS,
    ClaimRegistry,
    MaintenanceHandle,
    ProcessLiveness,
    coerce_process_liveness,
    process_owner_matches,
)
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    exact_object,
    nonnegative_int,
    sha256_hex,
)

if TYPE_CHECKING:
    from repomap_test_support.resource_index import AdvisoryIndex
    from repomap_test_support.resource_index_maintenance import InventoryResult


class IndexMaintenanceError(RuntimeError):
    """Maintenance index authority is absent, stale, or unsafe."""


@dataclass(frozen=True)
class DeletedIndexRecoveryResult:
    reconciled_runs: int
    inventory: InventoryResult | None


@dataclass(frozen=True)
class _DeletedIndexPlan:
    run_id: str
    admitted: tuple[Path, tuple[int, int]] | None
    closed: tuple[Path, tuple[int, int]] | None


def recover_stale_admission_lock(
    index: AdvisoryIndex,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    ledger: GcLedger,
    *,
    now_seconds: int,
    owner_is_live=process_owner_matches,
) -> Path:
    registry.require_maintenance(maintenance)
    try:
        payload = exact_object(
            read_private_json(index.lock_path),
            {
                "schema", "owner_token", "process_id",
                "process_start_evidence", "created_at_seconds",
            },
            "admission lock",
        )
        if payload["schema"] != LOCK_SCHEMA:
            raise HygieneValidationError("unsupported admission lock schema")
        sha256_hex(payload["process_start_evidence"], "process start evidence")
        created = nonnegative_int(payload["created_at_seconds"], "lock timestamp")
    except (OSError, PrivateJsonError, HygieneValidationError) as error:
        raise IndexMaintenanceError("admission lock is invalid") from error
    now = nonnegative_int(now_seconds, "recovery timestamp")
    if now - created < CLAIM_LEASE_SECONDS:
        raise IndexMaintenanceError("admission lock lease has not expired")
    liveness = coerce_process_liveness(
        owner_is_live(payload["process_id"], payload["process_start_evidence"])
    )
    if liveness is ProcessLiveness.LIVE:
        raise IndexMaintenanceError("admission lock owner is still live")
    if liveness is ProcessLiveness.UNKNOWN:
        raise IndexMaintenanceError("admission lock owner is not provably dead")
    tombstone = ledger.tombstone_path("admission-lock", "global")
    ledger.append("stale_lock_intent", {"kind": "admission_lock"}, now_seconds=now)
    if tombstone.exists() or tombstone.is_symlink():
        raise IndexMaintenanceError("admission lock tombstone already exists")
    try:
        os.rename(index.lock_path, tombstone)
    except OSError as error:
        raise IndexMaintenanceError("admission lock tombstone rename failed") from error
    ledger.append("stale_lock_completion", {"kind": "admission_lock"}, now_seconds=now)
    return tombstone


def reconcile_deleted_run(
    index: AdvisoryIndex,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    store: DeletionRecordStore,
    *,
    run_id: str,
    phase: str,
    quarantine_record_id: str,
    deletion_completion_record_id: str,
    tombstone_record_id: str,
    now_seconds: int,
) -> InventoryResult:
    """Reconcile one exact tombstone-authorized deleted run."""
    from repomap_test_support.resource_index_maintenance import rebuild_inventory

    registry.require_maintenance(maintenance)
    plan = _deleted_index_plan(
        index,
        registry,
        store,
        run_id=run_id,
        phase=phase,
        quarantine_record_id=quarantine_record_id,
        deletion_completion_record_id=deletion_completion_record_id,
        tombstone_record_id=tombstone_record_id,
    )
    _apply_deleted_index_plan(index, plan)
    return rebuild_inventory(
        index,
        registry,
        maintenance,
        now_seconds=now_seconds,
        operator_requested=True,
    )


def recover_deleted_index_reconciliations(
    index: AdvisoryIndex,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    store: DeletionRecordStore,
    *,
    now_seconds: int,
) -> DeletedIndexRecoveryResult:
    """Resume every bounded tombstone-authorized index reconciliation."""
    from repomap_test_support.resource_index_maintenance import rebuild_inventory

    registry.require_maintenance(maintenance)
    try:
        tombstones = store.validated_tombstones()
    except DeletionRecordError as error:
        raise IndexMaintenanceError(
            "deleted index recovery authority is invalid"
        ) from error
    if not tombstones:
        return DeletedIndexRecoveryResult(0, None)
    run_ids = [item["run_id"] for item in tombstones]
    if len(run_ids) != len(set(run_ids)):
        raise IndexMaintenanceError("deleted index recovery run identity is ambiguous")
    plans = []
    for tombstone in tombstones:
        plans.append(
            _deleted_index_plan(
                index,
                registry,
                store,
                run_id=str(tombstone["run_id"]),
                phase=str(tombstone["phase"]),
                quarantine_record_id=str(tombstone["quarantine_record_id"]),
                deletion_completion_record_id=str(
                    tombstone["deletion_completion_record_id"]
                ),
                tombstone_record_id=str(tombstone["tombstone_record_id"]),
            )
        )
    for plan in plans:
        _apply_deleted_index_plan(index, plan)
    inventory = rebuild_inventory(
        index,
        registry,
        maintenance,
        now_seconds=now_seconds,
        operator_requested=True,
    )
    return DeletedIndexRecoveryResult(len(plans), inventory)


def _deleted_index_plan(
    index: AdvisoryIndex,
    registry: ClaimRegistry,
    store: DeletionRecordStore,
    *,
    run_id: str,
    phase: str,
    quarantine_record_id: str,
    deletion_completion_record_id: str,
    tombstone_record_id: str,
) -> _DeletedIndexPlan:
    run_id = safe_run_id(run_id)
    phase = safe_text(phase, "phase")
    try:
        store.validate_deleted_authority(
            run_id=run_id,
            phase=phase,
            quarantine_record_id=quarantine_record_id,
            deletion_completion_record_id=deletion_completion_record_id,
            tombstone_record_id=tombstone_record_id,
        )
    except DeletionRecordError as error:
        raise IndexMaintenanceError(
            "deleted run tombstone authority is invalid"
        ) from error
    for root in (
        index.scratch_root / "r" / run_id,
        index.scratch_root / ".quarantine" / registry.project / run_id,
    ):
        if not _path_absent(root):
            raise IndexMaintenanceError("deleted run remains physically present")
    admitted = _validated_index_record(
        index.records_path / f"{run_id}.admitted.json",
        run_id=run_id,
        phase=phase,
        validator=validate_admission,
    )
    closed = _validated_index_record(
        index.records_path / f"{run_id}.closed.json",
        run_id=run_id,
        phase=phase,
        validator=validate_close,
    )
    return _DeletedIndexPlan(run_id, admitted, closed)


def _validated_index_record(path, *, run_id, phase, validator):
    if _path_absent(path):
        return None
    try:
        metadata = path.stat(follow_symlinks=False)
        payload = validator(read_private_json(path))
    except (OSError, PrivateJsonError, HygieneValidationError) as error:
        raise IndexMaintenanceError("deleted run index record is invalid") from error
    if (
        path.is_symlink()
        or not path.is_file()
        or metadata.st_nlink != 1
        or payload["run_id"] != run_id
        or payload["phase"] != phase
    ):
        raise IndexMaintenanceError("deleted run index identity changed")
    return path, (metadata.st_dev, metadata.st_ino)


def _apply_deleted_index_plan(
    index: AdvisoryIndex, plan: _DeletedIndexPlan
) -> None:
    for record, label in ((plan.closed, "close"), (plan.admitted, "admission")):
        if record is None:
            continue
        path, identity = record
        if not _same_file(path, identity):
            raise IndexMaintenanceError(
                f"deleted {label} record identity changed"
            )
        try:
            path.unlink()
            _fsync_directory(index.records_path)
        except OSError as error:
            raise IndexMaintenanceError(
                f"deleted {label} record removal failed"
            ) from error


def _path_absent(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError as error:
        raise IndexMaintenanceError("deleted run physical state is unobservable") from error
    return False


def _same_file(path: Path, identity: tuple[int, int]) -> bool:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return not path.is_symlink() and (metadata.st_dev, metadata.st_ino) == identity


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _private_directory(path: Path, label: str):
    try:
        metadata = path.lstat()
    except OSError as error:
        raise IndexRecoveryError(f"{label} is unavailable") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise IndexRecoveryError(f"{label} is unsafe")
    return metadata


def _ensure_private_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        _private_directory(path, "recovery evidence directory")
        return
    path.mkdir(mode=0o700)
    _private_directory(path, "recovery evidence directory")
    _fsync_directory(path.parent)


def _validate_index_entries(root: Path) -> None:
    try:
        names = {path.name for path in root.iterdir()}
    except OSError as error:
        raise IndexRecoveryError("index directory is unreadable") from error
    if names - ALLOWED_PROJECT_INDEX_ENTRIES:
        raise IndexRecoveryError("index directory contains unknown entries")


def _record_count(path: Path) -> int:
    try:
        return len(tuple(path.iterdir()))
    except OSError as error:
        raise IndexRecoveryError("index record count is unavailable") from error


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "DeletedIndexRecoveryResult",
    "IndexMaintenanceError",
    "reconcile_deleted_run",
    "recover_deleted_index_reconciliations",
    "recover_stale_admission_lock",
]
