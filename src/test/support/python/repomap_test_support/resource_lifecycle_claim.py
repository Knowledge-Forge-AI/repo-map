"""Exclusive lifecycle claims shared by protection writers and maintenance."""

from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from repomap_test_support.resource_index_records import (
    owner_token as validate_owner_token,
    safe_run_id,
    safe_text,
)
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    exact_object,
    nonnegative_int,
    sha256_hex,
)


CLAIM_SCHEMA = "repomap-test-lifecycle-claim-v1"
MAINTENANCE_SCHEMA = "repomap-test-maintenance-lock-v1"
PROTECTION_SCHEMA = "repomap-test-run-protection-v1"
CLAIM_LEASE_SECONDS = 3_600


class ClaimError(RuntimeError):
    """A lifecycle claim is held, malformed, stale, or not exactly owned."""


class ClaimPurpose(str, Enum):
    GC_QUARANTINE = "gc_quarantine"
    PHYSICAL_DELETE = "physical_delete"
    OPERATOR_PIN_REGISTRATION = "operator_pin_registration"
    REPORT_SOURCE_REGISTRATION = "report_source_registration"
    MONITORING_REGISTRATION = "monitoring_registration"
    INDEX_CLOSE = "index_close"
    MAINTENANCE_RECOVERY = "maintenance_recovery"


class ProcessLiveness(str, Enum):
    LIVE = "live"
    DEAD = "dead"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClaimHandle:
    path: Path
    project: str
    run_id: str
    purpose: ClaimPurpose
    owner_token: str
    record_id: str
    device: int
    inode: int


@dataclass(frozen=True)
class MaintenanceHandle:
    path: Path
    project: str
    owner_token: str
    record_id: str
    device: int
    inode: int


class ClaimRegistry:
    def __init__(self, scratch_root: Path, project: str = "repo-map_dev") -> None:
        self.scratch_root = Path(scratch_root)
        self.project = safe_run_id(project)
        self.root = self.scratch_root / ".claims" / self.project
        self.maintenance_root = self.scratch_root / ".maintenance" / self.project
        self.protection_root = self.scratch_root / ".protections" / self.project
        _owned_directory(self.scratch_root)
        _private_directory(self.root, create=True)
        _private_directory(self.maintenance_root, create=True)
        _private_directory(self.protection_root, create=True)

    def acquire(
        self,
        run_id: str,
        purpose: ClaimPurpose | str,
        *,
        now_seconds: int | None = None,
        process_id: int | None = None,
        process_start: str | None = None,
        owner_token: str | None = None,
    ) -> ClaimHandle:
        run_id = safe_run_id(run_id)
        try:
            purpose = ClaimPurpose(purpose)
        except (TypeError, ValueError) as error:
            raise ClaimError("claim purpose is not in the closed vocabulary") from error
        now = nonnegative_int(
            int(time.time()) if now_seconds is None else now_seconds,
            "claim creation timestamp",
        )
        pid = os.getpid() if process_id is None else nonnegative_int(process_id, "process id")
        if pid == 0:
            raise ClaimError("process id must be positive")
        start = _current_process_start_evidence() if process_start is None else process_start
        sha256_hex(start, "process start evidence")
        token = secrets.token_hex(16) if owner_token is None else validate_owner_token(owner_token)
        seed: dict[str, object] = {
            "schema": CLAIM_SCHEMA,
            "project": self.project,
            "run_id": run_id,
            "purpose": purpose.value,
            "process_id": pid,
            "process_start_evidence": start,
            "owner_token": token,
            "created_at_seconds": now,
            "claim_lease_seconds": CLAIM_LEASE_SECONDS,
        }
        record_id = _record_id(seed)
        payload = {**seed, "claim_record_id": record_id}
        path = self.root / f"{run_id}.claim.json"
        try:
            write_private_json_exclusive(path, payload)
        except FileExistsError as error:
            raise ClaimError("lifecycle claim is already held") from error
        except (OSError, PrivateJsonError) as error:
            raise ClaimError("lifecycle claim creation failed") from error
        metadata = path.stat(follow_symlinks=False)
        return ClaimHandle(
            path,
            self.project,
            run_id,
            purpose,
            token,
            record_id,
            metadata.st_dev,
            metadata.st_ino,
        )

    def release(self, handle: ClaimHandle) -> None:
        if not isinstance(handle, ClaimHandle) or handle.path.parent != self.root:
            raise ClaimError("claim handle does not belong to this registry")
        tombstone = self.root / f".release-{handle.owner_token}.tmp"
        if tombstone.exists() or tombstone.is_symlink():
            raise ClaimError("claim release tombstone already exists")
        try:
            os.rename(handle.path, tombstone)
        except OSError as error:
            raise ClaimError("lifecycle claim release failed") from error
        try:
            payload = self._validate_claim(tombstone)
            metadata = tombstone.stat(follow_symlinks=False)
            exact = (
                metadata.st_dev == handle.device
                and metadata.st_ino == handle.inode
                and payload["claim_record_id"] == handle.record_id
                and payload["owner_token"] == handle.owner_token
                and payload["project"] == handle.project
                and payload["run_id"] == handle.run_id
                and payload["purpose"] == handle.purpose.value
            )
            if not exact:
                raise ClaimError("lifecycle claim ownership changed")
        except BaseException:
            if not handle.path.exists() and not handle.path.is_symlink():
                os.rename(tombstone, handle.path)
            raise
        tombstone.unlink()

    def require_claim(
        self,
        handle: ClaimHandle,
        *,
        purpose: ClaimPurpose | None = None,
    ) -> dict[str, object]:
        if not isinstance(handle, ClaimHandle) or handle.path.parent != self.root:
            raise ClaimError("claim handle does not belong to this registry")
        payload = self._validate_claim(handle.path)
        metadata = handle.path.stat(follow_symlinks=False)
        if (
            metadata.st_dev != handle.device
            or metadata.st_ino != handle.inode
            or payload["claim_record_id"] != handle.record_id
            or payload["owner_token"] != handle.owner_token
            or payload["project"] != handle.project
            or payload["run_id"] != handle.run_id
            or payload["purpose"] != handle.purpose.value
            or (purpose is not None and handle.purpose is not purpose)
        ):
            raise ClaimError("lifecycle claim ownership changed")
        return payload

    def acquire_maintenance(
        self,
        purpose: str,
        *,
        now_seconds: int | None = None,
    ) -> MaintenanceHandle:
        purpose = safe_text(purpose, "maintenance purpose")
        now = nonnegative_int(
            int(time.time()) if now_seconds is None else now_seconds,
            "maintenance timestamp",
        )
        token = secrets.token_hex(16)
        seed: dict[str, object] = {
            "schema": MAINTENANCE_SCHEMA,
            "project": self.project,
            "purpose": purpose,
            "process_id": os.getpid(),
            "process_start_evidence": _current_process_start_evidence(),
            "owner_token": token,
            "created_at_seconds": now,
        }
        record_id = _record_id(seed)
        payload = {**seed, "maintenance_record_id": record_id}
        path = self.maintenance_root / "maintenance.lock"
        try:
            write_private_json_exclusive(path, payload)
        except FileExistsError as error:
            raise ClaimError("global maintenance lock is already held") from error
        except (OSError, PrivateJsonError) as error:
            raise ClaimError("global maintenance lock creation failed") from error
        metadata = path.stat(follow_symlinks=False)
        return MaintenanceHandle(
            path,
            self.project,
            token,
            record_id,
            metadata.st_dev,
            metadata.st_ino,
        )

    def release_maintenance(self, handle: MaintenanceHandle) -> None:
        self.require_maintenance(handle)
        tombstone = handle.path.with_name(f".release-{handle.owner_token}.tmp")
        if tombstone.exists() or tombstone.is_symlink():
            raise ClaimError("maintenance release tombstone already exists")
        try:
            os.rename(handle.path, tombstone)
        except OSError as error:
            raise ClaimError("global maintenance lock release failed") from error
        metadata = tombstone.stat(follow_symlinks=False)
        payload = _validate_maintenance(read_private_json(tombstone))
        if (
            metadata.st_dev != handle.device
            or metadata.st_ino != handle.inode
            or payload["owner_token"] != handle.owner_token
            or payload["maintenance_record_id"] != handle.record_id
        ):
            if not handle.path.exists() and not handle.path.is_symlink():
                os.rename(tombstone, handle.path)
            raise ClaimError("global maintenance lock ownership changed")
        tombstone.unlink()

    def require_maintenance(self, handle: MaintenanceHandle) -> dict[str, object]:
        if not isinstance(handle, MaintenanceHandle) or handle.path.parent != self.maintenance_root:
            raise ClaimError("maintenance handle does not belong to this registry")
        payload = _validate_maintenance(read_private_json(handle.path))
        metadata = handle.path.stat(follow_symlinks=False)
        if (
            metadata.st_dev != handle.device
            or metadata.st_ino != handle.inode
            or payload["owner_token"] != handle.owner_token
            or payload["maintenance_record_id"] != handle.record_id
            or payload["project"] != handle.project
        ):
            raise ClaimError("global maintenance lock ownership changed")
        return payload

    def recover_stale_claim(
        self,
        handle: MaintenanceHandle,
        run_id: str,
        *,
        now_seconds: int,
        tombstone_path: Path,
        owner_is_live: Callable[[int, str], ProcessLiveness | bool] | None = None,
    ) -> Path:
        self.require_maintenance(handle)
        run_id = safe_run_id(run_id)
        path = self.root / f"{run_id}.claim.json"
        payload = self._validate_claim(path)
        created_at = nonnegative_int(payload["created_at_seconds"], "claim timestamp")
        now = nonnegative_int(now_seconds, "recovery timestamp")
        if now - created_at < CLAIM_LEASE_SECONDS:
            raise ClaimError("lifecycle claim lease has not expired")
        process_id = nonnegative_int(payload["process_id"], "process id")
        process_start = sha256_hex(payload["process_start_evidence"], "process start evidence")
        probe = owner_is_live or process_owner_matches
        liveness = coerce_process_liveness(
            probe(process_id, process_start)
        )
        if liveness is ProcessLiveness.LIVE:
            raise ClaimError("lifecycle claim owner is still live")
        if liveness is ProcessLiveness.UNKNOWN:
            raise ClaimError("lifecycle claim owner is not provably dead")
        tombstone = Path(tombstone_path)
        _private_directory(tombstone.parent, create=True)
        if tombstone.exists() or tombstone.is_symlink():
            raise ClaimError("stale-claim tombstone already exists")
        try:
            os.rename(path, tombstone)
        except OSError as error:
            raise ClaimError("stale claim tombstone rename failed") from error
        return tombstone

    def _validate_claim(self, path: Path) -> dict[str, object]:
        try:
            payload = exact_object(
                read_private_json(path),
                {
                    "schema", "project", "run_id", "purpose", "process_id",
                    "process_start_evidence", "owner_token", "created_at_seconds",
                    "claim_lease_seconds", "claim_record_id",
                },
                "lifecycle claim",
            )
            if payload["schema"] != CLAIM_SCHEMA or payload["project"] != self.project:
                raise HygieneValidationError("unsupported lifecycle claim identity")
            safe_run_id(payload["run_id"])
            ClaimPurpose(payload["purpose"])
            if nonnegative_int(payload["process_id"], "process id") == 0:
                raise HygieneValidationError("process id must be positive")
            sha256_hex(payload["process_start_evidence"], "process start evidence")
            validate_owner_token(payload["owner_token"])
            nonnegative_int(payload["created_at_seconds"], "claim timestamp")
            if payload["claim_lease_seconds"] != CLAIM_LEASE_SECONDS:
                raise HygieneValidationError("claim lease is unsupported")
            record_id = payload["claim_record_id"]
            sha256_hex(record_id, "claim record id")
            seed = dict(payload)
            seed.pop("claim_record_id")
            if _record_id(seed) != record_id:
                raise HygieneValidationError("claim record integrity mismatch")
            return payload
        except (OSError, PrivateJsonError, HygieneValidationError, ValueError) as error:
            raise ClaimError("lifecycle claim is invalid") from error


from repomap_test_support.resource_lifecycle_claim_operations import (
    _current_process_start_evidence,
    _owned_directory,
    _private_directory,
    _record_id,
    _validate_maintenance,
    coerce_process_liveness,
    lifecycle_claim,
    process_owner_matches,
    register_protection,
)


__all__ = [
    "CLAIM_LEASE_SECONDS", "ClaimError", "ClaimHandle", "ClaimPurpose",
    "ClaimRegistry", "MaintenanceHandle", "ProcessLiveness",
    "coerce_process_liveness", "lifecycle_claim", "process_owner_matches",
    "register_protection",
]
