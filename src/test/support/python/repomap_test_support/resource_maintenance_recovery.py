"""Explicit cooperative recovery of an exact, provably dead maintenance owner."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import stat
import time
from typing import Callable

from repomap_test_support.resource_index_records import LOCK_SCHEMA
from repomap_test_support.resource_ledger_io import read_private_json, write_private_json_exclusive
from repomap_test_support.resource_lifecycle_claim import (
    CLAIM_LEASE_SECONDS, ClaimError, ProcessLiveness,
    coerce_process_liveness, process_owner_matches,
)
from repomap_test_support.resource_lifecycle_claim_operations import (
    _owned_directory, _private_directory, _validate_maintenance,
)
from repomap_test_support.resource_validation import exact_object, nonnegative_int, sha256_hex


CONFIRM_RECOVERY = "RECOVER EXACT PROVABLY DEAD MAINTENANCE OWNER"


@dataclass(frozen=True)
class _Record:
    path: Path
    device: int
    inode: int
    payload: dict[str, object]


def _read(path: Path) -> _Record:
    metadata = path.lstat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1 or metadata.st_mode & 0o077):
        raise ClaimError("recovery record identity is unsafe")
    payload = read_private_json(path)
    after = path.lstat()
    if (metadata.st_dev, metadata.st_ino) != (after.st_dev, after.st_ino):
        raise ClaimError("recovery record identity changed")
    return _Record(path, metadata.st_dev, metadata.st_ino, payload)


def _require_exact(record: _Record) -> None:
    if _read(record.path) != record:
        raise ClaimError("recovery record identity changed")


def _require_dead(record: _Record, now: int, probe: Callable[[int, str], object]) -> None:
    payload = record.payload
    pid = nonnegative_int(payload["process_id"], "process id")
    if pid == 0:
        raise ClaimError("recovery process id must be positive")
    start = sha256_hex(payload["process_start_evidence"], "process start evidence")
    created = nonnegative_int(payload["created_at_seconds"], "creation timestamp")
    if now - created < CLAIM_LEASE_SECONDS:
        raise ClaimError("recovery owner lease has not expired")
    if coerce_process_liveness(probe(pid, start)) is not ProcessLiveness.DEAD:
        raise ClaimError("recovery owner is not provably dead")


def _paired_barrier(scratch_root: Path, owner: _Record) -> _Record | None:
    path = scratch_root / ".index" / "repo-map_dev" / "admission.lock"
    if not path.exists() and not path.is_symlink():
        return None
    _owned_directory(scratch_root / ".index")
    _private_directory(path.parent, create=False)
    barrier = _read(path)
    values = exact_object(barrier.payload, {
        "schema", "owner_token", "process_id", "process_start_evidence", "created_at_seconds",
    }, "admission barrier")
    if values["schema"] != LOCK_SCHEMA or owner.payload["purpose"] != "recover-index":
        raise ClaimError("admission barrier is not a paired recovery owner")
    if any(values[key] != owner.payload[key] for key in (
        "owner_token", "process_id", "process_start_evidence",
    )):
        raise ClaimError("admission barrier owner differs")
    return barrier


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def recover_maintenance_owner(
    scratch_root: Path, *, expected_record_id: str, confirmation: str,
    now_seconds: int | None = None,
    owner_is_live: Callable[[int, str], object] = process_owner_matches,
) -> dict[str, object]:
    """Retire only the selected dead record; never rebuild the index or delete runs.

    An OS lock on the existing owner inode serializes recovery attempts. It
    vanishes on process death, so recovery creates no second persistent lock.
    This is cooperative local maintenance, not protection against hostile writes.
    """
    if confirmation != CONFIRM_RECOVERY:
        raise ClaimError("explicit maintenance recovery confirmation required")
    sha256_hex(expected_record_id, "expected maintenance record id")
    if os.name != "posix":
        raise ClaimError("maintenance recovery requires POSIX file locking")
    import fcntl

    scratch_root = Path(scratch_root)
    if not scratch_root.is_absolute() or any(p.is_symlink() for p in (scratch_root, *scratch_root.parents)):
        raise ClaimError("scratch root is not an absolute link-safe authority")
    maintenance_root = scratch_root / ".maintenance" / "repo-map_dev"
    _owned_directory(scratch_root / ".maintenance")
    for directory in (scratch_root, maintenance_root):
        _private_directory(directory, create=False)
    path = maintenance_root / "maintenance.lock"
    owner = _read(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        metadata = os.fstat(fd)
        if (metadata.st_dev, metadata.st_ino) != (owner.device, owner.inode):
            raise ClaimError("recovery owner changed before locking")
        _require_exact(owner)
        values = _validate_maintenance(owner.payload)
        if values["project"] != "repo-map_dev" or values["maintenance_record_id"] != expected_record_id:
            raise ClaimError("expected maintenance record does not match")
        now = nonnegative_int(int(time.time()) if now_seconds is None else now_seconds, "recovery timestamp")
        _require_dead(owner, now, owner_is_live)
        barrier = _paired_barrier(scratch_root, owner)
        if barrier is not None:
            _require_dead(barrier, now, owner_is_live)
        evidence = maintenance_root / "recovery-records"
        _private_directory(evidence, create=True)
        attempt = secrets.token_hex(16)
        write_private_json_exclusive(evidence / f"{attempt}.intent.json", {
            "schema": "repomap-maintenance-owner-recovery-v1", "state": "intent",
            "maintenance": owner.payload, "barrier": barrier.payload if barrier else None,
            "maintenance_identity": [owner.device, owner.inode],
            "barrier_identity": [barrier.device, barrier.inode] if barrier else None,
            "observed_at_seconds": now, "liveness": "dead",
        })
        _sync_directory(evidence)
        removed = 0
        try:
            _require_dead(owner, now, owner_is_live)
            _require_exact(owner)
            if barrier is not None:
                _require_exact(barrier)
                barrier.path.unlink()
                removed += 1
                _sync_directory(barrier.path.parent)
            _require_exact(owner)
            owner.path.unlink()
            removed += 1
            _sync_directory(owner.path.parent)
        except BaseException as error:
            try:
                write_private_json_exclusive(evidence / f"{attempt}.interrupted.json", {
                    "schema": "repomap-maintenance-owner-recovery-v1", "state": "interrupted",
                    "removed_records": removed,
                })
            except Exception:
                error.add_note("maintenance recovery interruption evidence unavailable")
            raise
        write_private_json_exclusive(evidence / f"{attempt}.completed.json", {
            "schema": "repomap-maintenance-owner-recovery-v1", "state": "completed",
            "removed_records": removed,
        })
        return {"outcome": "recovered", "maintenance_records": 1, "paired_barriers": int(barrier is not None)}
    finally:
        os.close(fd)
