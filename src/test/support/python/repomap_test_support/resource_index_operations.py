"""Advisory-index reconciliation, admission, closure, and profile headroom operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from repomap_test_support.resource_hygiene_policy import HygieneProfile
from repomap_test_support.resource_index import (
    DEFAULT_SOFT_BYTES,
    DEFAULT_SOFT_INODES,
    RECORD_CAP,
    AdmissionRecordedError,
    AdvisoryIndex,
    HostAdmissionRefused,
    IndexError,
    IndexRecord,
    ReconciledBound,
    lifecycle_record_capacity,
)
from repomap_test_support.resource_index_bootstrap import (
    IndexBootstrapError,
    directional_filesystem_check,
)
from repomap_test_support.resource_index_records import (
    ADMISSION_SCHEMA,
    CLOSE_SCHEMA,
    owner_token as validate_owner_token,
    safe_run_id,
    safe_text,
    validate_admission,
    validate_close,
)
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    write_private_json_exclusive,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimPurpose,
    lifecycle_claim,
)
from repomap_test_support.resource_retention import RetentionClass, TerminalOutcome
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    nonnegative_int,
)


def reconcile_index_bound(index: AdvisoryIndex) -> ReconciledBound:
    """Establish conservative bound from records and summary."""
    for attempt in range(2):
        summary = index._read_summary()
        try:
            directional_filesystem_check(summary, index.scratch_root)
        except IndexBootstrapError as error:
            raise HostAdmissionRefused(
                str(error), maintenance_required=error.maintenance_required
            ) from error
        try:
            files = tuple(sorted(index.records_path.iterdir(), key=lambda item: item.name))
        except OSError as error:
            raise HostAdmissionRefused("index record directory is unreadable") from error
        if len(files) > RECORD_CAP:
            raise HostAdmissionRefused("index record cap exceeded", maintenance_required=True)
        allocated = summary["allocated_bytes"]
        inodes = summary["inode_count"]
        records: dict[str, dict[str, dict[str, Any]]] = {}
        for path in files:
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise HostAdmissionRefused("index record directory is malformed")
            kind, run_id, payload = index._read_record(path)
            if path.name != f"{run_id}.{kind}.json":
                raise HostAdmissionRefused("index record identity is malformed")
            run_records = records.setdefault(run_id, {})
            if kind in run_records:
                raise HostAdmissionRefused("duplicate index record identity")
            run_records[kind] = payload
        active_runs = 0
        for run_records in records.values():
            admitted = run_records.get("admitted")
            closed = run_records.get("closed")
            if admitted is None:
                raise HostAdmissionRefused("close record lacks its admission")
            if closed is None:
                active_runs += 1
                allocated += admitted["byte_quota"]
                inodes += admitted["inode_quota"]
            else:
                if closed["phase"] != admitted["phase"]:
                    raise HostAdmissionRefused("index record owner is inconsistent")
                allocated += closed["allocated_bytes"]
                inodes += closed["inode_count"]
        after = index._read_summary()
        if after["generation"] == summary["generation"]:
            return ReconciledBound(
                allocated, inodes, len(files), summary["generation"], active_runs
            )
        if attempt:
            break
    raise HostAdmissionRefused("index generation changed during reconciliation")


def admit_run(
    index: AdvisoryIndex,
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
    write_exclusive_fn: Callable[[Path, dict[str, Any]], None] = write_private_json_exclusive,
) -> IndexRecord:
    """Execute run admission against conservative bound."""
    run_id = safe_run_id(run_id)
    phase = safe_text(phase, "phase")
    profile = HygieneProfile(profile)
    process_id = nonnegative_int(process_id, "process id")
    process_start_evidence = _sha256(process_start_evidence, "process start evidence")
    owner_token = validate_owner_token(owner_token)
    configuration_sha256 = _sha256(configuration_sha256, "configuration SHA-256")
    hard_watermark_bytes = nonnegative_int(hard_watermark_bytes, "hard byte watermark")
    hard_watermark_inodes = nonnegative_int(hard_watermark_inodes, "hard inode watermark")
    soft_watermark_bytes = nonnegative_int(soft_watermark_bytes, "soft byte watermark")
    soft_watermark_inodes = nonnegative_int(soft_watermark_inodes, "soft inode watermark")
    admitted_at_seconds = nonnegative_int(admitted_at_seconds, "admission timestamp")
    if max_active_runs is not None:
        max_active_runs = nonnegative_int(max_active_runs, "active run limit")
    token = index._acquire_lock(admitted_at_seconds, owner_token=owner_token)
    try:
        target = index.records_path / f"{run_id}.admitted.json"
        if target.exists() or target.is_symlink():
            raise IndexError("admission record already exists")
        bound = index.reconcile()
        capacity = lifecycle_record_capacity(
            record_count=bound.record_count,
            active_runs=bound.active_runs,
        )
        if not capacity.new_run_lifecycle_admissible:
            raise HostAdmissionRefused(
                "lifecycle record capacity would be exceeded",
                maintenance_required=True,
            )
        if max_active_runs is not None and bound.active_runs >= max_active_runs:
            raise HostAdmissionRefused("active run limit would be exceeded")
        if profile is HygieneProfile.QUALIFICATION:
            if bound.allocated_bytes >= soft_watermark_bytes:
                raise HostAdmissionRefused("soft_byte_watermark")
            if bound.inode_count >= soft_watermark_inodes:
                raise HostAdmissionRefused("soft_inode_watermark")
        byte_quota, inode_quota = profile.quota
        if bound.allocated_bytes + byte_quota > hard_watermark_bytes:
            raise HostAdmissionRefused("hard_byte_watermark")
        if bound.inode_count + inode_quota > hard_watermark_inodes:
            raise HostAdmissionRefused("hard_inode_watermark")
        payload = {
            "schema": ADMISSION_SCHEMA,
            "run_id": run_id,
            "phase": phase,
            "profile": profile.value,
            "byte_quota": byte_quota,
            "inode_quota": inode_quota,
            "process_id": process_id,
            "process_start_evidence": process_start_evidence,
            "owner_token": owner_token,
            "configuration_sha256": configuration_sha256,
            "admitted_at_seconds": admitted_at_seconds,
        }
        validate_admission(payload)
        write_exclusive_fn(target, payload)
        record = IndexRecord(target, run_id, phase)
    except BaseException as error:
        try:
            index._release_lock(token)
        except IndexError as release_error:
            error.add_note(f"admission lock release also failed: {release_error}")
        if isinstance(error, FileExistsError):
            raise IndexError("admission record already exists") from error
        if isinstance(error, PrivateJsonError):
            raise IndexError("admission record creation failed") from error
        raise
    try:
        index._release_lock(token)
    except IndexError as error:
        if record is None:
            raise
        raise AdmissionRecordedError(
            "admission record exists after lock release failure"
        ) from error
    if record is None:
        raise IndexError("admission record was not created")
    return record


def close_run(
    index: AdvisoryIndex,
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
    write_exclusive_fn: Callable[[Path, dict[str, Any]], None] = write_private_json_exclusive,
) -> IndexRecord:
    """Execute run closure within index lifecycle claim."""
    run_id = safe_run_id(run_id)
    phase = safe_text(phase, "phase")
    owner_token = validate_owner_token(owner_token)
    closed_at_seconds = nonnegative_int(closed_at_seconds, "close timestamp")
    with lifecycle_claim(
        index.scratch_root,
        index.root.name,
        run_id,
        ClaimPurpose.INDEX_CLOSE,
    ):
        lock = index._acquire_lock(closed_at_seconds, owner_token=owner_token)
        try:
            admission = index.records_path / f"{run_id}.admitted.json"
            kind, admitted_run, payload = index._read_record(admission)
            if (
                kind != "admitted"
                or admitted_run != run_id
                or payload["phase"] != phase
                or payload["owner_token"] != owner_token
            ):
                raise IndexError("close record does not match admission owner")
            try:
                terminal = TerminalOutcome(terminal_outcome)
                retention = RetentionClass(retention_class)
            except (TypeError, ValueError) as error:
                raise IndexError("unsupported terminal close state") from error
            target = index.records_path / f"{run_id}.closed.json"
            if target.exists() or target.is_symlink():
                raise IndexError("close record already exists")
            try:
                record_count = len(tuple(index.records_path.iterdir()))
            except OSError as error:
                raise HostAdmissionRefused(
                    "index record count is unavailable",
                    maintenance_required=True,
                ) from error
            if record_count >= RECORD_CAP:
                raise HostAdmissionRefused(
                    "close record capacity is unavailable",
                    maintenance_required=True,
                )
            close_payload = {
                "schema": CLOSE_SCHEMA,
                "run_id": run_id,
                "phase": phase,
                "terminal_outcome": terminal.value,
                "retention_class": retention.value,
                "allocated_bytes": nonnegative_int(allocated_bytes, "allocated_bytes"),
                "inode_count": nonnegative_int(inode_count, "inode_count"),
                "retained_evidence_bytes": nonnegative_int(
                    retained_evidence_bytes, "retained_evidence_bytes"
                ),
                "closed_at_seconds": closed_at_seconds,
            }
            validate_close(close_payload)
            write_exclusive_fn(target, close_payload)
            record = IndexRecord(target, run_id, phase)
        except BaseException as error:
            try:
                index._release_lock(lock)
            except IndexError as release_error:
                error.add_note(f"admission lock release also failed: {release_error}")
            if isinstance(error, FileExistsError):
                raise IndexError("close record already exists") from error
            if isinstance(
                error, (OSError, PrivateJsonError, HygieneValidationError)
            ):
                raise IndexError("close record creation failed") from error
            raise
        index._release_lock(lock)
    return record


def profile_headroom(
    bound: ReconciledBound,
    *,
    soft_watermark_bytes: int,
    soft_watermark_inodes: int,
    hard_watermark_bytes: int,
    hard_watermark_inodes: int,
) -> dict[str, dict[str, int | bool]]:
    """Compute admission headroom per hygiene profile under reconciled bound."""
    values: dict[str, dict[str, int | bool]] = {}
    active_limits = {
        HygieneProfile.ORDINARY: None,
        HygieneProfile.INTEGRATION: 2,
        HygieneProfile.BUILD: 1,
        HygieneProfile.EXHAUSTIVE: 1,
        HygieneProfile.HEAVY: 1,
        HygieneProfile.QUALIFICATION: 1,
    }
    for profile in HygieneProfile:
        byte_quota, inode_quota = profile.quota
        soft = profile is not HygieneProfile.QUALIFICATION or (
            bound.allocated_bytes < soft_watermark_bytes
            and bound.inode_count < soft_watermark_inodes
        )
        hard = (
            bound.allocated_bytes + byte_quota <= hard_watermark_bytes
            and bound.inode_count + inode_quota <= hard_watermark_inodes
        )
        active_limit = active_limits[profile]
        active = active_limit is None or bound.active_runs < active_limit
        record_cap = bound.record_count < RECORD_CAP
        lifecycle = lifecycle_record_capacity(
            record_count=bound.record_count,
            active_runs=bound.active_runs,
        )
        values[profile.value] = {
            "byte_quota": byte_quota,
            "inode_quota": inode_quota,
            "soft_admissible": soft,
            "hard_admissible": hard,
            "active_run_admissible": active,
            "record_cap_admissible": record_cap,
            "lifecycle_record_admissible": (
                lifecycle.new_run_lifecycle_admissible
            ),
            "reserved_future_close_records": (
                lifecycle.reserved_future_close_records
            ),
            "lifecycle_committed_records": (
                lifecycle.lifecycle_committed_records
            ),
            "lifecycle_record_headroom": lifecycle.lifecycle_record_headroom,
            "structurally_admissible": (
                soft
                and hard
                and active
                and lifecycle.new_run_lifecycle_admissible
            ),
            "hard_byte_headroom": hard_watermark_bytes - bound.allocated_bytes,
            "hard_inode_headroom": hard_watermark_inodes - bound.inode_count,
        }
    return values


def _sha256(value: Any, name: str) -> str:
    if type(value) is not str or len(value) != 64:
        raise HygieneValidationError(f"{name} is invalid")
    try:
        int(value, 16)
    except ValueError as error:
        raise HygieneValidationError(f"{name} is invalid") from error
    return value


__all__ = [
    "admit_run",
    "close_run",
    "profile_headroom",
    "reconcile_index_bound",
]
