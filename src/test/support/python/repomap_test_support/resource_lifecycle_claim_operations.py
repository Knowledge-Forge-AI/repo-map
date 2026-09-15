"""Lifecycle-claim operations and process-liveness helpers."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from repomap_test_support.resource_index_records import (
    owner_token as validate_owner_token,
    safe_run_id,
    safe_text,
)
from repomap_test_support.resource_ledger_io import (
    write_private_json_exclusive,
)
from repomap_test_support.resource_validation import (
    exact_object,
    nonnegative_int,
    sha256_hex,
)

if TYPE_CHECKING:
    from repomap_test_support.resource_lifecycle_claim import (
        ClaimHandle,
        ClaimPurpose,
        ProcessLiveness,
    )


def _owner():
    from repomap_test_support import resource_lifecycle_claim

    return resource_lifecycle_claim


@contextmanager
def lifecycle_claim(
    scratch_root: Path,
    project: str,
    run_id: str,
    purpose: ClaimPurpose,
) -> Iterator[ClaimHandle]:
    owner = _owner()
    registry = owner.ClaimRegistry(scratch_root, project)
    handle = registry.acquire(run_id, purpose)
    try:
        yield handle
    except BaseException as error:
        try:
            registry.release(handle)
        except owner.ClaimError as release_error:
            error.add_note(f"lifecycle claim release also failed: {release_error}")
        raise
    registry.release(handle)


def register_protection(
    scratch_root: Path,
    project: str,
    run_id: str,
    purpose: ClaimPurpose,
    *,
    now_seconds: int,
) -> Path:
    owner = _owner()
    if purpose not in {
        owner.ClaimPurpose.OPERATOR_PIN_REGISTRATION,
        owner.ClaimPurpose.REPORT_SOURCE_REGISTRATION,
        owner.ClaimPurpose.MONITORING_REGISTRATION,
    }:
        raise owner.ClaimError("claim purpose cannot grant protection")
    registry = owner.ClaimRegistry(scratch_root, project)
    kind = {
        owner.ClaimPurpose.OPERATOR_PIN_REGISTRATION: "pins",
        owner.ClaimPurpose.REPORT_SOURCE_REGISTRATION: "reports",
        owner.ClaimPurpose.MONITORING_REGISTRATION: "monitoring",
    }[purpose]
    target_dir = registry.protection_root / kind
    owner._private_directory(target_dir, create=True)
    with owner.lifecycle_claim(scratch_root, project, run_id, purpose) as handle:
        from repomap_test_support import resource_deletion_records

        try:
            deletion_state = resource_deletion_records.deletion_registration_state(
                scratch_root, project, run_id
            )
        except resource_deletion_records.DeletionRecordError as error:
            raise owner.ClaimError(
                "protection registration deletion authority is unavailable"
            ) from error
        if deletion_state is not None:
            raise owner.ClaimError(deletion_state)
        payload = {
            "schema": owner.PROTECTION_SCHEMA,
            "project": project,
            "run_id": safe_run_id(run_id),
            "purpose": purpose.value,
            "claim_record_id": handle.record_id,
            "registered_at_seconds": nonnegative_int(now_seconds, "registration timestamp"),
        }
        path = target_dir / f"{run_id}.json"
        try:
            write_private_json_exclusive(path, payload)
        except FileExistsError as error:
            raise owner.ClaimError("run protection already exists") from error
        return path


def process_owner_matches(process_id: int, expected_start: str) -> ProcessLiveness:
    owner = _owner()
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return owner.ProcessLiveness.DEAD
    except (PermissionError, OSError, ValueError):
        return owner.ProcessLiveness.UNKNOWN
    try:
        import psutil
    except ImportError:
        return owner.ProcessLiveness.UNKNOWN
    try:
        started = psutil.Process(process_id).create_time()
    except psutil.NoSuchProcess:
        return owner.ProcessLiveness.DEAD
    except (PermissionError, OSError, psutil.AccessDenied, psutil.Error):
        return owner.ProcessLiveness.UNKNOWN
    seed = f"repomap-process-start-v1\0{process_id}\0{started:.6f}".encode()
    return (
        owner.ProcessLiveness.LIVE
        if hashlib.sha256(seed).hexdigest() == expected_start
        else owner.ProcessLiveness.DEAD
    )


def coerce_process_liveness(value: object) -> ProcessLiveness:
    owner = _owner()
    if isinstance(value, owner.ProcessLiveness):
        return value
    if value is True:
        return owner.ProcessLiveness.LIVE
    if value is False:
        return owner.ProcessLiveness.DEAD
    return owner.ProcessLiveness.UNKNOWN


def _current_process_start_evidence() -> str:
    owner = _owner()
    try:
        import psutil
    except ImportError as error:
        raise owner.ClaimError("process start evidence is unavailable") from error
    try:
        started = psutil.Process(os.getpid()).create_time()
    except (OSError, psutil.Error) as error:
        raise owner.ClaimError("process start evidence is unavailable") from error
    seed = f"repomap-process-start-v1\0{os.getpid()}\0{started:.6f}".encode()
    return hashlib.sha256(seed).hexdigest()


def _validate_maintenance(payload: object) -> dict[str, object]:
    owner = _owner()
    values = exact_object(
        payload,
        {
            "schema", "project", "purpose", "process_id", "process_start_evidence",
            "owner_token", "created_at_seconds", "maintenance_record_id",
        },
        "global maintenance lock",
    )
    if values["schema"] != owner.MAINTENANCE_SCHEMA:
        raise owner.ClaimError("global maintenance lock schema is unsupported")
    safe_text(values["project"], "project")
    safe_text(values["purpose"], "maintenance purpose")
    nonnegative_int(values["process_id"], "process id")
    sha256_hex(values["process_start_evidence"], "process start evidence")
    validate_owner_token(values["owner_token"])
    nonnegative_int(values["created_at_seconds"], "maintenance timestamp")
    record_id = sha256_hex(values["maintenance_record_id"], "maintenance record id")
    seed = dict(values)
    seed.pop("maintenance_record_id")
    if _record_id(seed) != record_id:
        raise owner.ClaimError("global maintenance lock integrity mismatch")
    return values


def _private_directory(path: Path, *, create: bool) -> None:
    owner = _owner()
    path = Path(path)
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as error:
        raise owner.ClaimError("private lifecycle directory is unavailable") from error
    if path.is_symlink() or not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise owner.ClaimError("private lifecycle directory identity is unsafe")
    if metadata.st_mode & 0o077:
        raise owner.ClaimError("private lifecycle directory mode is not restrictive")


def _owned_directory(path: Path) -> None:
    owner = _owner()
    try:
        metadata = Path(path).stat(follow_symlinks=False)
    except OSError as error:
        raise owner.ClaimError("managed scratch root is unavailable") from error
    if (
        Path(path).is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
    ):
        raise owner.ClaimError("managed scratch root identity is unsafe")


def _record_id(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
