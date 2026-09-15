"""Strict per-entry quarantine deletion catalog and bounded selection."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from repomap_test_support.resource_deletion_records import (
    DeletionRecordError,
    DeletionRecordStore,
    DeletionRecoveryState,
    quarantine_ttl_elapsed,
)
from repomap_test_support.resource_gc_ledger import GcLedger, GcLedgerError
from repomap_test_support.resource_index_records import safe_run_id
from repomap_test_support.resource_ledger import (
    ResourceLedger,
    ResourceLedgerError,
    RunIdentity,
)
from repomap_test_support.resource_lifecycle_claim import ClaimRegistry
from repomap_test_support.resource_quarantine_records import (
    QUARANTINE_SCHEMA,
    QuarantineError,
    read_quarantine_record,
)
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteError,
    inspect_quarantine_tree,
)
from repomap_test_support.resource_validation import nonnegative_int
from repomap_test_support.test_scratch import MANIFEST_SCHEMA


GIB = 1_073_741_824
DELETION_MAX_RUNS = 25
DELETION_MAX_BYTES = 10 * GIB
QUARANTINE_MAX_WITHOUT_PIN_SECONDS = 30 * 86_400


class DeletionGcError(RuntimeError):
    """Global or candidate deletion authority cannot be established."""


class DeletionAuthorityMode(str, Enum):
    ORDINARY_QUARANTINE = "ordinary_quarantine"
    COMMITTED_RECOVERY = "committed_recovery"


@dataclass(frozen=True)
class DeletionCandidate:
    run_id: str
    phase: str
    root: Path
    record: dict[str, object]
    ledger: GcLedger
    allocated_bytes: int
    inode_count: int
    manifest_process_id: int | None
    over_retention: bool
    recovery_state: DeletionRecoveryState
    authority_mode: DeletionAuthorityMode


@dataclass(frozen=True)
class DeletionDiscovery:
    candidates: tuple[DeletionCandidate, ...]
    ttl_held: int
    ambiguous: int
    operator_attention_required: int
    deleted_complete: int


@dataclass(frozen=True)
class DeletionBatchSelection:
    candidates: tuple[DeletionCandidate, ...]
    allocated_bytes: int
    limit_reason: str | None


def discover_quarantine_deletions(
    scratch_root: Path,
    *,
    registry: ClaimRegistry,
    store: DeletionRecordStore,
    now_seconds: int,
) -> DeletionDiscovery:
    """Classify immediate quarantine entries independently; mutate nothing."""
    root = Path(scratch_root)
    now = nonnegative_int(now_seconds, "deletion discovery timestamp")
    record_owners = _quarantine_record_owners(root, registry.project)
    physical, invalid_physical_names = _physical_entries(root, registry.project)
    candidates = []
    ttl_held = deleted_complete = 0
    ambiguous = attention = invalid_physical_names
    for run_id in sorted(set(record_owners).union(physical)):
        owner = record_owners.get(run_id)
        target = physical.get(run_id)
        if owner is None:
            ambiguous += 1
            attention += 1
            continue
        ledger, record_path = owner
        try:
            record = read_quarantine_record(record_path)
        except QuarantineError:
            ambiguous += 1
            attention += 1
            continue
        if record["run_id"] != run_id or record["project"] != registry.project:
            ambiguous += 1
            attention += 1
            continue
        if record["schema"] != QUARANTINE_SCHEMA:
            attention += 1
            continue
        if not _ledger_finalized(ledger, run_id, str(record["quarantine_record_id"])):
            ambiguous += 1
            attention += 1
            continue
        root_present = target is not None
        try:
            state = store.classify(
                run_id,
                str(record["quarantine_record_id"]),
                quarantine_root_present=root_present,
            )
        except DeletionRecordError:
            ambiguous += 1
            attention += 1
            continue
        if state is DeletionRecoveryState.AMBIGUOUS_EVIDENCE_CONFLICT:
            ambiguous += 1
            attention += 1
            continue
        if state is DeletionRecoveryState.PROTECTED_RESTORED:
            continue
        if state is DeletionRecoveryState.DELETED_COMPLETE:
            deleted_complete += 1
            continue
        if root_present and target is not None:
            try:
                _require_physical_identity(target, record)
                if committed_state(state):
                    state, evidence = store.committed_authority(
                        record, quarantine_root_present=True
                    )
                    intent = evidence.intent
                    if intent is None:
                        raise DeletionRecordError(
                            "committed deletion lacks its intent"
                        )
                    allocated = nonnegative_int(intent["measured_target_allocated_bytes"], "allocated")
                    inodes = nonnegative_int(intent["measured_target_inode_count"], "inodes")
                    process_id = None
                    authority_mode = DeletionAuthorityMode.COMMITTED_RECOVERY
                else:
                    eligible = quarantine_ttl_elapsed(record, now_seconds=now)
                    manifest = read_quarantined_manifest(root, target, record)
                    inspection = inspect_quarantine_tree(
                        root,
                        project=registry.project,
                        run_id=run_id,
                        expected_device=nonnegative_int(record["quarantine_device"], "device"),
                        expected_inode=nonnegative_int(record["quarantine_inode"], "inode"),
                    )
                    if not eligible:
                        ttl_held += 1
                        continue
                    allocated = inspection.allocated_bytes
                    inodes = inspection.inode_count
                    process_id = nonnegative_int(manifest["pid"], "pid")
                    authority_mode = DeletionAuthorityMode.ORDINARY_QUARANTINE
            except (
                OSError,
                ValueError,
                DeletionRecordError,
                ResourceLedgerError,
                SafeTreeDeleteError,
            ):
                ambiguous += 1
                attention += 1
                continue
        else:
            if state not in {
                DeletionRecoveryState.COMMITTED_ROOT_ABSENT_COMPLETION_REQUIRED,
                DeletionRecoveryState.COMPLETED_TOMBSTONE_REQUIRED,
            }:
                ambiguous += 1
                attention += 1
                continue
            try:
                state, evidence = store.committed_authority(
                    record, quarantine_root_present=False
                )
            except DeletionRecordError:
                ambiguous += 1
                attention += 1
                continue
            if evidence.intent is None:
                raise DeletionGcError("committed deletion lacks its intent")
            allocated = nonnegative_int(evidence.intent["measured_target_allocated_bytes"], "allocated")
            inodes = nonnegative_int(evidence.intent["measured_target_inode_count"], "inodes")
            process_id = None
            authority_mode = DeletionAuthorityMode.COMMITTED_RECOVERY
        candidates.append(
            DeletionCandidate(
                run_id,
                str(record["phase"]),
                root / ".quarantine" / registry.project / run_id,
                record,
                ledger,
                allocated,
                inodes,
                process_id,
                now >= nonnegative_int(record["quarantined_at_seconds"], "quarantined_at") + QUARANTINE_MAX_WITHOUT_PIN_SECONDS,
                state,
                authority_mode,
            )
        )
    return DeletionDiscovery(
        tuple(candidates), ttl_held, ambiguous, attention, deleted_complete
    )


def select_deletion_batch(
    candidates: tuple[DeletionCandidate, ...]
) -> DeletionBatchSelection:
    ordered = sorted(
        candidates,
        key=lambda item: (
            0 if committed_state(item.recovery_state) else 1,
            0 if item.over_retention else 1,
            item.record["quarantined_at_seconds"],
            item.run_id,
        ),
    )
    selected: list[DeletionCandidate] = []
    allocated = 0
    limit = None
    for candidate in ordered:
        if len(selected) >= DELETION_MAX_RUNS:
            limit = "run_limit"
            break
        if not selected and candidate.allocated_bytes > DELETION_MAX_BYTES:
            selected.append(candidate)
            allocated = candidate.allocated_bytes
            break
        if allocated + candidate.allocated_bytes > DELETION_MAX_BYTES:
            limit = "byte_limit"
            break
        selected.append(candidate)
        allocated += candidate.allocated_bytes
    return DeletionBatchSelection(tuple(selected), allocated, limit)


def read_quarantined_manifest(
    scratch_root: Path,
    run_root: Path,
    record: dict[str, object],
) -> dict[str, object]:
    manifest_path = run_root / "manifest.json"
    ledger_path = run_root / "resource-ledger.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("quarantined manifest identity is unsafe")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "schema", "project", "phase", "run_kind", "run_id", "pid",
        "physical_run_root", "monitoring_index_path", "state",
        "retention_policy", "exit_status", "live_runtime_residue",
    }
    if type(manifest) is not dict or set(manifest) != required:
        raise ValueError("quarantined manifest fields are not exact")
    if (
        manifest["schema"] != MANIFEST_SCHEMA
        or manifest["project"] != record["project"]
        or manifest["phase"] != record["phase"]
        or manifest["run_kind"] != "test"
        or manifest["run_id"] != record["run_id"]
        or type(manifest["pid"]) is not int
        or manifest["state"] not in {"passed", "failed", "stopped"}
        or Path(manifest["physical_run_root"])
        != scratch_root / "r" / str(record["run_id"])
        or run_root.name != record["run_id"]
        or ledger_path.is_symlink()
        or not ledger_path.is_file()
    ):
        raise ValueError("quarantined manifest identity is invalid")
    ResourceLedger.open(
        ledger_path,
        RunIdentity(str(record["project"]), str(record["phase"]), str(record["run_id"])),
    )
    return manifest


def committed_state(state: DeletionRecoveryState) -> bool:
    return state in {
        DeletionRecoveryState.COMMITTED_DELETE_REQUIRED,
        DeletionRecoveryState.COMMITTED_ROOT_ABSENT_COMPLETION_REQUIRED,
        DeletionRecoveryState.COMPLETED_TOMBSTONE_REQUIRED,
    }


def _quarantine_record_owners(
    scratch_root: Path, project: str
) -> dict[str, tuple[GcLedger, Path]]:
    gc_root = scratch_root / ".gc" / project
    if not gc_root.exists():
        return {}
    _require_private_directory(gc_root, "GC root")
    result = {}
    for pass_root in sorted(gc_root.iterdir(), key=lambda item: item.name):
        if pass_root.is_symlink() or not pass_root.is_dir():
            raise DeletionGcError("GC pass framing is invalid")
        try:
            ledger = GcLedger.open(pass_root)
            ledger.records()
        except GcLedgerError as error:
            raise DeletionGcError("global GC ledger authority is invalid") from error
        for path in sorted(ledger.quarantine_root.iterdir(), key=lambda item: item.name):
            if not path.name.endswith(".json"):
                raise DeletionGcError("quarantine record framing is invalid")
            try:
                run_id = safe_run_id(path.name.removesuffix(".json"))
            except ValueError as error:
                raise DeletionGcError("quarantine record identity is ambiguous") from error
            if run_id in result:
                raise DeletionGcError("duplicate quarantine record identity")
            result[run_id] = (ledger, path)
    return result


def _physical_entries(
    scratch_root: Path, project: str
) -> tuple[dict[str, Path], int]:
    root = scratch_root / ".quarantine" / project
    if not root.exists():
        return {}, 0
    _require_private_directory(root, "quarantine root")
    result = {}
    invalid = 0
    for path in root.iterdir():
        try:
            run_id = safe_run_id(path.name)
        except ValueError:
            invalid += 1
            continue
        if run_id in result:
            raise DeletionGcError("duplicate quarantine entry identity")
        result[run_id] = path
    return result, invalid


def _ledger_finalized(ledger: GcLedger, run_id: str, record_id: str) -> bool:
    return any(
        record.event in {"quarantine_record", "recovered_record_finalization"}
        and record.payload.get("run_id") == run_id
        and record.payload.get("quarantine_record_id") == record_id
        for record in ledger.records()
    )


def _require_physical_identity(
    target: Path, record: dict[str, object]
) -> None:
    metadata = target.stat(follow_symlinks=False)
    if (
        target.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_dev, metadata.st_ino)
        != (record["quarantine_device"], record["quarantine_inode"])
    ):
        raise ValueError("quarantine identity mismatch")


def _require_private_directory(path: Path, label: str) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError as error:
        raise DeletionGcError(f"{label} is unavailable") from error
    if (
        path.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise DeletionGcError(f"{label} identity is unsafe")


__all__ = [
    "DELETION_MAX_BYTES", "DELETION_MAX_RUNS", "DeletionBatchSelection",
    "DeletionAuthorityMode", "DeletionCandidate", "DeletionDiscovery", "DeletionGcError",
    "committed_state", "discover_quarantine_deletions",
    "read_quarantined_manifest", "select_deletion_batch",
]
