"""Immutable advisory-index records and serialized prospective admission."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repomap_test_support.resource_hygiene_policy import GIB, HygieneProfile
from repomap_test_support.resource_index_bootstrap import (
    IndexBootstrapError,
    directional_filesystem_check as directional_filesystem_check,
    infer_scratch_root,
    initialize_empty_paths,
    read_summary_authority,
    validate_existing_index_directories,
    validate_index_binding,
)
from repomap_test_support.resource_index_records import (
    ADMISSION_SCHEMA,
    CLOSE_SCHEMA,
    LOCK_SCHEMA,
    owner_token as validate_owner_token,
    safe_run_id as safe_run_id,
    safe_text as safe_text,
    validate_admission,
    validate_close,
)
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimPurpose as ClaimPurpose,
    lifecycle_claim as lifecycle_claim,
)
from repomap_test_support.resource_retention import RetentionClass as RetentionClass, TerminalOutcome
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    exact_object,
    nonnegative_int,
)


RECORD_CAP = 512
DEFAULT_SOFT_BYTES = 40 * GIB
DEFAULT_SOFT_INODES = 1_500_000


class IndexError(RuntimeError):
    """The private advisory index is unsafe, malformed, or conflicting."""


class HostAdmissionRefused(IndexError):
    """The conservative admission bound cannot be established safely."""

    def __init__(self, message: str, *, maintenance_required: bool = False) -> None:
        self.maintenance_required = maintenance_required
        suffix = "; maintenance_required" if maintenance_required else ""
        super().__init__(f"{message}{suffix}")


class AdmissionRecordedError(IndexError):
    """Admission exists but the serialization lock could not be released."""


@dataclass(frozen=True)
class ReconciledBound:
    allocated_bytes: int
    inode_count: int
    record_count: int
    generation: int
    active_runs: int


@dataclass(frozen=True)
class LifecycleRecordCapacity:
    record_count: int
    active_runs: int
    reserved_future_close_records: int
    lifecycle_committed_records: int
    new_lifecycle_required_records: int
    lifecycle_record_headroom: int
    existing_lifecycle_safe: bool
    new_run_lifecycle_admissible: bool


def lifecycle_record_capacity(
    *, record_count: int, active_runs: int
) -> LifecycleRecordCapacity:
    """Project physical records plus every mandatory future close record."""
    records = nonnegative_int(record_count, "record count")
    active = nonnegative_int(active_runs, "active run count")
    committed = records + active
    required = 2
    return LifecycleRecordCapacity(
        record_count=records,
        active_runs=active,
        reserved_future_close_records=active,
        lifecycle_committed_records=committed,
        new_lifecycle_required_records=required,
        lifecycle_record_headroom=RECORD_CAP - committed,
        existing_lifecycle_safe=committed <= RECORD_CAP,
        new_run_lifecycle_admissible=committed + required <= RECORD_CAP,
    )


@dataclass(frozen=True)
class IndexRecord:
    path: Path
    run_id: str
    phase: str


@dataclass(frozen=True)
class AdmissionLockHandle:
    owner_token: str
    device: int
    inode: int


class AdvisoryIndex:
    def __init__(self, root: Path, scratch_root: Path) -> None:
        self.root = Path(root)
        self.scratch_root = Path(scratch_root)
        self.records_path = self.root / "runs"
        self.summary_path = self.root / "summary.json"
        self.bootstrap_path = self.root / "bootstrap.json"
        self.inventory_path = self.root / "inventory.json"
        self.lock_path = self.root / "admission.lock"

    @classmethod
    def open(cls, root: Path, *, scratch_root: Path | None = None) -> "AdvisoryIndex":
        if Path(root).is_symlink():
            raise IndexError("advisory index directory is unsafe")
        try:
            scratch = (
                Path(scratch_root)
                if scratch_root is not None
                else infer_scratch_root(root)
            )
        except IndexBootstrapError as error:
            raise HostAdmissionRefused(
                str(error), maintenance_required=error.maintenance_required
            ) from error
        index = cls(root, scratch)
        try:
            validate_index_binding(Path(root), scratch)
        except IndexBootstrapError as error:
            raise HostAdmissionRefused(
                str(error), maintenance_required=error.maintenance_required
            ) from error
        try:
            validate_existing_index_directories(index.root, index.records_path)
        except IndexBootstrapError as error:
            raise HostAdmissionRefused(
                str(error), maintenance_required=error.maintenance_required
            ) from error
        index._read_summary()
        return index

    @classmethod
    def initialize_empty(
        cls,
        root: Path,
        *,
        scratch_root: Path,
        requesting_run_id: str | None,
        initialized_at_seconds: int,
    ) -> "AdvisoryIndex":
        try:
            initialize_empty_paths(
                root,
                scratch_root=scratch_root,
                requesting_run_id=requesting_run_id,
                initialized_at_seconds=initialized_at_seconds,
            )
        except IndexBootstrapError as error:
            raise HostAdmissionRefused(
                str(error), maintenance_required=error.maintenance_required
            ) from error
        return cls.open(root, scratch_root=scratch_root)

    def reconcile(self) -> ReconciledBound:
        from repomap_test_support.resource_index_operations import (
            reconcile_index_bound,
        )

        return reconcile_index_bound(self)

    def admit(
        self,
        *,
        run_id: str,
        phase: str,
        profile: HygieneProfile,
        hard_watermark_bytes: int,
        hard_watermark_inodes: int,
        admitted_at_seconds: int,
        process_id: int,
        process_start_evidence: str,
        owner_token: str,
        configuration_sha256: str,
        soft_watermark_bytes: int = DEFAULT_SOFT_BYTES,
        soft_watermark_inodes: int = DEFAULT_SOFT_INODES,
        max_active_runs: int | None = None,
    ) -> IndexRecord:
        from repomap_test_support.resource_index_operations import admit_run

        return admit_run(
            self,
            run_id=run_id,
            phase=phase,
            profile=profile,
            hard_watermark_bytes=hard_watermark_bytes,
            hard_watermark_inodes=hard_watermark_inodes,
            admitted_at_seconds=admitted_at_seconds,
            process_id=process_id,
            process_start_evidence=process_start_evidence,
            owner_token=owner_token,
            configuration_sha256=configuration_sha256,
            soft_watermark_bytes=soft_watermark_bytes,
            soft_watermark_inodes=soft_watermark_inodes,
            max_active_runs=max_active_runs,
            write_exclusive_fn=write_private_json_exclusive,
        )

    def close(
        self,
        *,
        run_id: str,
        phase: str,
        terminal_outcome: TerminalOutcome | str,
        retention_class: str,
        allocated_bytes: int,
        inode_count: int,
        retained_evidence_bytes: int,
        closed_at_seconds: int,
        owner_token: str,
    ) -> IndexRecord:
        from repomap_test_support.resource_index_operations import close_run

        return close_run(
            self,
            run_id=run_id,
            phase=phase,
            terminal_outcome=terminal_outcome,
            retention_class=retention_class,
            allocated_bytes=allocated_bytes,
            inode_count=inode_count,
            retained_evidence_bytes=retained_evidence_bytes,
            closed_at_seconds=closed_at_seconds,
            owner_token=owner_token,
            write_exclusive_fn=write_private_json_exclusive,
        )


    def _read_summary(self) -> dict[str, Any]:
        try:
            return read_summary_authority(
                self.summary_path,
                self.bootstrap_path,
                self.scratch_root,
                self.inventory_path,
            )
        except (PrivateJsonError, HygieneValidationError, OSError) as error:
            raise HostAdmissionRefused(
                "index summary is invalid", maintenance_required=True
            ) from error

    def _read_record(self, path: Path) -> tuple[str, str, dict[str, Any]]:
        try:
            payload = read_private_json(path)
            schema = payload.get("schema")
            if schema == ADMISSION_SCHEMA:
                payload = validate_admission(payload)
                return "admitted", payload["run_id"], payload
            if schema == CLOSE_SCHEMA:
                payload = validate_close(payload)
                return "closed", payload["run_id"], payload
            raise HygieneValidationError("unsupported or lower-authority index record schema")
        except (PrivateJsonError, HygieneValidationError, OSError, IndexError) as error:
            raise HostAdmissionRefused("index record is invalid") from error

    def _acquire_lock(
        self, now_seconds: int, *, owner_token: str | None = None
    ) -> AdmissionLockHandle:
        token = secrets.token_hex(16) if owner_token is None else validate_owner_token(owner_token)
        payload = {
            "schema": LOCK_SCHEMA,
            "owner_token": token,
            "process_id": os.getpid(),
            "process_start_evidence": _current_process_start_evidence(),
            "created_at_seconds": now_seconds,
        }
        try:
            write_private_json_exclusive(self.lock_path, payload)
        except FileExistsError as error:
            raise HostAdmissionRefused("admission lock is already held") from error
        except (PrivateJsonError, OSError) as error:
            raise HostAdmissionRefused("admission lock creation failed") from error
        metadata = self.lock_path.stat(follow_symlinks=False)
        return AdmissionLockHandle(token, metadata.st_dev, metadata.st_ino)

    def _release_lock(self, handle: AdmissionLockHandle) -> None:
        tombstone = self.lock_path.with_name(
            f".admission-release-{getattr(handle, 'owner_token', 'invalid')}.tmp"
        )
        try:
            if tombstone.exists() or tombstone.is_symlink():
                raise IndexError("admission lock release tombstone exists")
            os.rename(self.lock_path, tombstone)
            payload = exact_object(
                read_private_json(tombstone),
                {
                    "schema", "owner_token", "process_id",
                    "process_start_evidence", "created_at_seconds",
                },
                "admission lock",
            )
            if payload["schema"] != LOCK_SCHEMA:
                raise HygieneValidationError("unsupported admission lock schema")
            metadata = tombstone.stat(follow_symlinks=False)
            if (
                not isinstance(handle, AdmissionLockHandle)
                or payload["owner_token"] != handle.owner_token
                or metadata.st_dev != handle.device
                or metadata.st_ino != handle.inode
            ):
                raise IndexError("admission lock ownership changed")
            tombstone.unlink()
        except (OSError, PrivateJsonError, HygieneValidationError) as error:
            if tombstone.exists() and not self.lock_path.exists():
                os.rename(tombstone, self.lock_path)
            raise IndexError("admission lock release failed") from error

def _sha256(value: Any, name: str) -> str:
    if type(value) is not str or len(value) != 64:
        raise HygieneValidationError(f"{name} is invalid")
    try:
        int(value, 16)
    except ValueError as error:
        raise HygieneValidationError(f"{name} is invalid") from error
    return value


def _current_process_start_evidence() -> str:
    from repomap_test_support.resource_run_cleanup import process_start_evidence

    return process_start_evidence()


__all__ = [
    "AdvisoryIndex",
    "AdmissionLockHandle",
    "AdmissionRecordedError",
    "HostAdmissionRefused",
    "IndexError",
    "LifecycleRecordCapacity",
    "ReconciledBound",
    "lifecycle_record_capacity",
]
