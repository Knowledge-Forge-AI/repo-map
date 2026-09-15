"""Exact legacy/current record planning for advisory-index recovery."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repomap_test_support.resource_hygiene_policy import HygieneProfile
from repomap_test_support.resource_index_records import (
    safe_run_id,
    safe_text,
    validate_admission,
    validate_close,
)
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
)
from repomap_test_support.resource_retention import RetentionClass
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    exact_object,
    nonnegative_int,
)


LEGACY_ADMISSION_SCHEMA = "repomap-test-hygiene-admission-v1"
LEGACY_CLOSE_SCHEMA = "repomap-test-hygiene-close-v1"


class IndexRecoveryError(RuntimeError):
    """Untrusted authority could not be recovered without weakening safety."""

    def __init__(self, message: str, *, category: str = "recovery_refused") -> None:
        self.category = category
        super().__init__(message)


@dataclass(frozen=True)
class RecoveryRecord:
    path: Path
    run_id: str
    phase: str
    kind: str
    version: int
    payload: dict[str, Any]
    device: int
    inode: int


@dataclass(frozen=True)
class RecoveryRecordPlan:
    redundant_pairs: tuple[tuple[RecoveryRecord, RecoveryRecord], ...]
    remaining_count: int
    active_count: int


def plan_recovery_records(
    records_path: Path,
    measured: frozenset[str],
    *,
    preserved_terminal_names: frozenset[str] = frozenset(),
) -> RecoveryRecordPlan:
    groups: dict[str, dict[str, RecoveryRecord]] = {}
    folded: dict[str, str] = {}
    for path in sorted(records_path.iterdir(), key=lambda item: item.name):
        record = _read_record(path)
        previous = folded.setdefault(record.run_id.casefold(), record.run_id)
        if previous != record.run_id:
            raise IndexRecoveryError("record run identity is ambiguous")
        run_records = groups.setdefault(record.run_id, {})
        if record.kind in run_records:
            raise IndexRecoveryError("duplicate record identity")
        run_records[record.kind] = record
    redundant = []
    remaining = 0
    active = 0
    for run_id, records in groups.items():
        admitted = records.get("admitted")
        closed = records.get("closed")
        if admitted is None:
            raise IndexRecoveryError("close record lacks admission authority")
        if closed is None:
            if admitted.version != 2:
                raise IndexRecoveryError("legacy active admission is unsupported")
            remaining += 1
            active += 1
            continue
        if admitted.phase != closed.phase or admitted.version != closed.version:
            raise IndexRecoveryError("terminal record pair is not redundant")
        if run_id in measured:
            redundant.append((admitted, closed))
        elif run_id in preserved_terminal_names:
            remaining += 2
        else:
            raise IndexRecoveryError("terminal record pair is not redundant")
    return RecoveryRecordPlan(tuple(redundant), remaining, active)


def cleanup_recovery_records(
    records_path: Path, plan: RecoveryRecordPlan
) -> int:
    completed = 0
    for admitted, closed in plan.redundant_pairs:
        try:
            _unlink_exact(closed)
            _fsync_directory(records_path)
            _unlink_exact(admitted)
            _fsync_directory(records_path)
        except OSError as error:
            raise IndexRecoveryError("redundant record cleanup failed") from error
        completed += 1
    return completed


def _read_record(path: Path) -> RecoveryRecord:
    try:
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
        ):
            raise HygieneValidationError("unsafe record identity")
        payload = read_private_json(path)
        schema = payload.get("schema")
        if schema == LEGACY_ADMISSION_SCHEMA:
            payload = _validate_legacy_admission(payload)
            kind, version = "admitted", 1
        elif schema == LEGACY_CLOSE_SCHEMA:
            payload = _validate_legacy_close(payload)
            kind, version = "closed", 1
        elif path.name.endswith(".admitted.json"):
            payload = validate_admission(payload)
            kind, version = "admitted", 2
        elif path.name.endswith(".closed.json"):
            payload = validate_close(payload)
            kind, version = "closed", 2
        else:
            raise HygieneValidationError("unsupported record schema")
        run_id = payload["run_id"]
        if path.name != f"{run_id}.{kind}.json":
            raise HygieneValidationError("record filename mismatch")
    except (OSError, PrivateJsonError, HygieneValidationError) as error:
        raise IndexRecoveryError("index record is invalid") from error
    return RecoveryRecord(
        path,
        run_id,
        payload["phase"],
        kind,
        version,
        payload,
        metadata.st_dev,
        metadata.st_ino,
    )


def _validate_legacy_admission(payload: Any) -> dict[str, Any]:
    payload = exact_object(
        payload,
        {
            "schema", "run_id", "phase", "profile", "byte_quota",
            "inode_quota", "admitted_at_seconds",
        },
        "legacy admission",
    )
    if payload["schema"] != LEGACY_ADMISSION_SCHEMA:
        raise HygieneValidationError("unsupported legacy admission schema")
    safe_run_id(payload["run_id"])
    safe_text(payload["phase"], "phase")
    try:
        HygieneProfile(payload["profile"])
    except (TypeError, ValueError) as error:
        raise HygieneValidationError("unsupported legacy profile") from error
    nonnegative_int(payload["byte_quota"], "byte quota")
    nonnegative_int(payload["inode_quota"], "inode quota")
    nonnegative_int(payload["admitted_at_seconds"], "admission timestamp")
    return payload


def _validate_legacy_close(payload: Any) -> dict[str, Any]:
    payload = exact_object(
        payload,
        {
            "schema", "run_id", "phase", "retention_class",
            "allocated_bytes", "inode_count", "closed_at_seconds",
        },
        "legacy close",
    )
    if payload["schema"] != LEGACY_CLOSE_SCHEMA:
        raise HygieneValidationError("unsupported legacy close schema")
    safe_run_id(payload["run_id"])
    safe_text(payload["phase"], "phase")
    try:
        RetentionClass(payload["retention_class"])
    except (TypeError, ValueError) as error:
        raise HygieneValidationError("unsupported legacy retention") from error
    nonnegative_int(payload["allocated_bytes"], "allocated bytes")
    nonnegative_int(payload["inode_count"], "inode count")
    nonnegative_int(payload["closed_at_seconds"], "close timestamp")
    return payload


def _unlink_exact(record: RecoveryRecord) -> None:
    metadata = record.path.stat(follow_symlinks=False)
    if (
        record.path.is_symlink()
        or (metadata.st_dev, metadata.st_ino) != (record.device, record.inode)
    ):
        raise OSError("record identity changed")
    record.path.unlink()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "IndexRecoveryError",
    "RecoveryRecordPlan",
    "cleanup_recovery_records",
    "plan_recovery_records",
]
