"""Safe-empty advisory-index bootstrap and provenance readback."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

from repomap_test_support.resource_index_records import (
    BOOTSTRAP_SCHEMA,
    INVENTORY_SCHEMA,
    INVENTORY_MEMBERSHIP_SCHEMA,
    RECOVERY_INVENTORY_SCHEMA,
    RECOVERY_INVENTORY_MEMBERSHIP_SCHEMA,
    SUMMARY_SCHEMA,
    safe_run_id,
    validate_bootstrap,
    validate_inventory,
    validate_inventory_membership,
    validate_recovery_inventory,
    validate_recovery_inventory_membership,
    validate_summary,
)
from repomap_test_support.resource_index_physical_membership import (
    PHYSICAL_INVENTORY_SCHEMA,
    RECOVERY_PHYSICAL_INVENTORY_SCHEMA,
    validate_physical_inventory,
    validate_recovery_physical_inventory,
)
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_validation import HygieneValidationError, nonnegative_int


class IndexBootstrapError(RuntimeError):
    def __init__(self, message: str, *, maintenance_required: bool = False) -> None:
        self.maintenance_required = maintenance_required
        super().__init__(message)


def initialize_empty_paths(
    root: Path,
    *,
    scratch_root: Path,
    requesting_run_id: str | None,
    initialized_at_seconds: int,
) -> None:
    root = Path(root)
    scratch_root = Path(scratch_root)
    records_path = root / "runs"
    summary_path = root / "summary.json"
    bootstrap_path = root / "bootstrap.json"
    lock_path = root / "bootstrap.lock"
    if requesting_run_id is not None:
        requesting_run_id = safe_run_id(requesting_run_id)
    initialized_at_seconds = nonnegative_int(
        initialized_at_seconds, "initialization timestamp"
    )
    _validate_scratch_root(scratch_root)
    validate_index_binding(root, scratch_root)
    _prepare_index_directories(root, records_path, scratch_root)
    token = secrets.token_hex(16)
    try:
        write_private_json_exclusive(
            lock_path,
            {
                "schema": "repomap-test-hygiene-bootstrap-lock-v1",
                "owner_token": token,
                "process_id": os.getpid(),
                "created_at_seconds": initialized_at_seconds,
            },
        )
    except FileExistsError as error:
        raise IndexBootstrapError("index bootstrap lock is held") from error
    except (PrivateJsonError, OSError) as error:
        raise IndexBootstrapError("index bootstrap lock creation failed") from error
    try:
        if not summary_path.exists() and not summary_path.is_symlink():
            entries = _bounded_run_population(scratch_root)
            allowed = {requesting_run_id} if requesting_run_id is not None else set()
            if any(entry.name not in allowed for entry in entries) or len(
                entries
            ) > len(allowed):
                raise IndexBootstrapError(
                    "missing index over an unproved run population",
                    maintenance_required=True,
                )
            if entries and (
                len(entries) != 1
                or requesting_run_id is None
                or entries[0].name != requesting_run_id
                or entries[0].is_symlink()
                or not entries[0].is_dir()
            ):
                raise IndexBootstrapError(
                    "safe-empty bootstrap population is invalid",
                    maintenance_required=True,
                )
            filesystem_id = filesystem_identity(scratch_root)
            provenance = {
                "schema": BOOTSTRAP_SCHEMA,
                "scratch_filesystem_id": filesystem_id,
                "initialization_mode": "safe_empty_bootstrap",
                "inventory_at_seconds": initialized_at_seconds,
                "population_entry_count": len(entries),
                "requesting_run_id": requesting_run_id,
            }
            provenance_id = hashlib.sha256(canonical_json(provenance)).hexdigest()
            provenance["provenance_record_id"] = provenance_id
            write_private_json_exclusive(bootstrap_path, provenance)
            write_private_json_exclusive(
                summary_path,
                {
                    "schema": SUMMARY_SCHEMA,
                    "scratch_filesystem_id": filesystem_id,
                    "generation": 0,
                    "initialization_mode": "safe_empty_bootstrap",
                    "inventory_at_seconds": initialized_at_seconds,
                    "provenance_record_id": provenance_id,
                    "allocated_bytes": 0,
                    "inode_count": 0,
                },
            )
    except (PrivateJsonError, OSError) as error:
        failure = IndexBootstrapError("safe-empty index bootstrap failed")
        try:
            _release_lock(lock_path, token)
        except IndexBootstrapError as release_error:
            failure.add_note(f"bootstrap lock release also failed: {release_error}")
        raise failure from error
    except BaseException as error:
        try:
            _release_lock(lock_path, token)
        except IndexBootstrapError as release_error:
            error.add_note(f"bootstrap lock release also failed: {release_error}")
        raise
    else:
        _release_lock(lock_path, token)


def read_summary_authority(
    summary_path: Path,
    bootstrap_path: Path,
    scratch_root: Path,
    inventory_path: Path | None = None,
) -> dict[str, Any]:
    summary = validate_summary(read_private_json(summary_path))
    if summary["scratch_filesystem_id"] != filesystem_identity(scratch_root):
        raise HygieneValidationError("scratch filesystem identity mismatch")
    if summary["initialization_mode"] == "safe_empty_bootstrap":
        provenance = validate_bootstrap(read_private_json(bootstrap_path))
        description = "bootstrap"
    elif summary["initialization_mode"] == "maintenance_inventory" and inventory_path:
        raw_inventory = read_private_json(inventory_path)
        if raw_inventory.get("schema") == INVENTORY_SCHEMA:
            provenance = validate_inventory(raw_inventory)
        elif raw_inventory.get("schema") == INVENTORY_MEMBERSHIP_SCHEMA:
            provenance = validate_inventory_membership(raw_inventory)
        elif raw_inventory.get("schema") == RECOVERY_INVENTORY_SCHEMA:
            provenance = validate_recovery_inventory(raw_inventory)
        elif raw_inventory.get("schema") == RECOVERY_INVENTORY_MEMBERSHIP_SCHEMA:
            provenance = validate_recovery_inventory_membership(raw_inventory)
        elif raw_inventory.get("schema") == PHYSICAL_INVENTORY_SCHEMA:
            provenance = validate_physical_inventory(raw_inventory)
        elif raw_inventory.get("schema") == RECOVERY_PHYSICAL_INVENTORY_SCHEMA:
            provenance = validate_recovery_physical_inventory(raw_inventory)
        else:
            raise HygieneValidationError(
                "maintenance inventory authority is unsupported"
            )
        description = "maintenance inventory"
    else:
        raise HygieneValidationError("maintenance inventory authority is unavailable")
    seed = dict(provenance)
    record_id = seed.pop("provenance_record_id")
    if hashlib.sha256(canonical_json(seed)).hexdigest() != record_id:
        raise HygieneValidationError(f"{description} provenance integrity mismatch")
    if (
        provenance["scratch_filesystem_id"] != summary["scratch_filesystem_id"]
        or provenance["inventory_at_seconds"] != summary["inventory_at_seconds"]
        or record_id != summary["provenance_record_id"]
    ):
        raise HygieneValidationError("summary provenance mismatch")
    return summary


def infer_scratch_root(root: Path) -> Path:
    path = Path(root)
    if path.parent.name == ".index":
        return path.parent.parent
    raise IndexBootstrapError(
        "scratch filesystem identity is unproved", maintenance_required=True
    )


def filesystem_identity(path: Path) -> str:
    metadata = Path(path).stat()
    seed = f"repo-map-scratch-fs-v2\0{metadata.st_dev}\0{metadata.st_ino}"
    return hashlib.sha256(seed.encode()).hexdigest()


def directional_filesystem_check(
    summary: dict[str, Any], scratch_root: Path
) -> None:
    try:
        stats = os.statvfs(scratch_root)
    except OSError as error:
        raise IndexBootstrapError("scratch filesystem is unreadable") from error
    total_bytes = stats.f_blocks * stats.f_frsize
    if total_bytes and summary["allocated_bytes"] > total_bytes:
        raise IndexBootstrapError(
            "index byte aggregate is impossible", maintenance_required=True
        )
    if stats.f_files and summary["inode_count"] > stats.f_files:
        raise IndexBootstrapError(
            "index inode aggregate is impossible", maintenance_required=True
        )


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _validate_scratch_root(scratch_root: Path) -> None:
    if scratch_root.is_symlink() or not scratch_root.is_dir():
        raise IndexBootstrapError("scratch root is unsafe", maintenance_required=True)


def validate_index_binding(root: Path, scratch_root: Path) -> None:
    index_parent = root.parent
    if index_parent.name != ".index" or index_parent.is_symlink():
        raise IndexBootstrapError(
            "index root is not bound to the scratch root",
            maintenance_required=True,
        )
    try:
        inferred = index_parent.parent.stat()
        supplied = scratch_root.stat()
    except OSError as error:
        raise IndexBootstrapError(
            "scratch root binding is unreadable",
            maintenance_required=True,
        ) from error
    if (inferred.st_dev, inferred.st_ino) != (supplied.st_dev, supplied.st_ino):
        raise IndexBootstrapError(
            "index root and scratch root do not match",
            maintenance_required=True,
        )


def validate_existing_index_directories(root: Path, records_path: Path) -> None:
    if root.is_symlink() or records_path.is_symlink():
        raise IndexBootstrapError("advisory index directory is unsafe")
    if not root.is_dir() or not records_path.is_dir():
        raise IndexBootstrapError(
            "index authority is missing", maintenance_required=True
        )
    os.chmod(root, 0o700)
    os.chmod(records_path, 0o700)


def _prepare_index_directories(
    root: Path, records_path: Path, scratch_root: Path
) -> None:
    if root.is_symlink() or records_path.is_symlink():
        raise IndexBootstrapError("advisory index directory is unsafe")
    _prepare_index_parent(root.parent, scratch_root)
    root.mkdir(mode=0o700, exist_ok=True)
    records_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or records_path.is_symlink():
        raise IndexBootstrapError("advisory index directory is unsafe")
    os.chmod(root, 0o700)
    os.chmod(records_path, 0o700)


def _prepare_index_parent(index_parent: Path, scratch_root: Path) -> None:
    created = False
    try:
        index_parent.mkdir(mode=0o700)
        created = True
    except FileExistsError:
        pass
    try:
        metadata = index_parent.lstat()
        scratch = scratch_root.lstat()
    except OSError as error:
        raise IndexBootstrapError(
            "index parent is unavailable", maintenance_required=True
        ) from error
    safe_shape = (
        not stat.S_ISLNK(metadata.st_mode)
        and stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and metadata.st_dev == scratch.st_dev
    )
    if not safe_shape:
        raise IndexBootstrapError(
            "index parent is unsafe", maintenance_required=True
        )
    if created:
        _chmod_created_directory(index_parent, metadata)
        current = index_parent.lstat()
        if (
            stat.S_ISLNK(current.st_mode)
            or not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino, current.st_uid)
            != (metadata.st_dev, metadata.st_ino, metadata.st_uid)
        ):
            raise IndexBootstrapError("index parent identity changed")
        metadata = current
    mode = stat.S_IMODE(metadata.st_mode)
    if mode != 0o700:
        message = (
            "legacy index parent requires maintenance"
            if mode == 0o755
            else "index parent is unsafe"
        )
        raise IndexBootstrapError(message, maintenance_required=True)


def _chmod_created_directory(path: Path, expected) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_uid) != (
            expected.st_dev,
            expected.st_ino,
            expected.st_uid,
        ):
            raise IndexBootstrapError("index parent identity changed")
        os.fchmod(descriptor, 0o700)
        after = os.fstat(descriptor)
        if (
            (after.st_dev, after.st_ino, after.st_uid)
            != (before.st_dev, before.st_ino, before.st_uid)
            or stat.S_IMODE(after.st_mode) != 0o700
        ):
            raise IndexBootstrapError("index parent hardening failed")
        try:
            os.fsync(descriptor)
        except OSError:
            pass
    finally:
        os.close(descriptor)


def _bounded_run_population(scratch_root: Path) -> tuple[Path, ...]:
    run_parent = scratch_root / "r"
    if run_parent.is_symlink():
        raise IndexBootstrapError("run population is unsafe", maintenance_required=True)
    if not run_parent.exists():
        return ()
    try:
        return tuple(run_parent.iterdir())
    except OSError as error:
        raise IndexBootstrapError(
            "run population is unreadable", maintenance_required=True
        ) from error


def _release_lock(lock_path: Path, token: str) -> None:
    try:
        payload = read_private_json(lock_path)
        if payload.get("owner_token") != token:
            raise IndexBootstrapError("bootstrap lock ownership changed")
        lock_path.unlink()
    except (OSError, PrivateJsonError) as error:
        raise IndexBootstrapError("bootstrap lock release failed") from error


__all__ = [
    "IndexBootstrapError",
    "directional_filesystem_check",
    "filesystem_identity",
    "infer_scratch_root",
    "initialize_empty_paths",
    "read_summary_authority",
    "validate_existing_index_directories",
    "validate_index_binding",
]
