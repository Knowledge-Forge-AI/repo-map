"""Candidate revalidation and protection classification for deletion GC."""

from __future__ import annotations

import stat
from dataclasses import replace
from pathlib import Path
from typing import Callable

from repomap_test_support.resource_deletion_candidates import (
    DeletionAuthorityMode,
    DeletionCandidate,
    DeletionGcError,
    read_quarantined_manifest,
)
from repomap_test_support.resource_deletion_record_types import (
    DeletionRecordError,
    DeletionRecoveryState,
)
from repomap_test_support.resource_deletion_record_store import DeletionRecordStore
from repomap_test_support.resource_deletion_record_validation import (
    quarantine_ttl_elapsed,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
    ProcessLiveness,
    coerce_process_liveness,
)
from repomap_test_support.resource_protection_authority import ProtectionObservation
from repomap_test_support.resource_quarantine_records import read_quarantine_record
from repomap_test_support.resource_safe_tree_delete import inspect_quarantine_tree
from repomap_test_support.resource_validation import nonnegative_int


def _fresh_state(
    store: DeletionRecordStore, candidate: DeletionCandidate
) -> DeletionRecoveryState:
    return store.classify(
        candidate.run_id,
        str(candidate.record["quarantine_record_id"]),
        quarantine_root_present=candidate.root.exists() and not candidate.root.is_symlink(),
    )


def _revalidate_candidate(
    scratch_root: Path,
    registry: ClaimRegistry,
    candidate: DeletionCandidate,
    *,
    now_seconds: int,
    process_is_live: Callable[[int], ProcessLiveness | bool],
) -> DeletionCandidate:
    record = read_quarantine_record(
        candidate.ledger.quarantine_record_path(candidate.run_id)
    )
    if record != candidate.record or not quarantine_ttl_elapsed(
        record, now_seconds=now_seconds
    ):
        raise DeletionGcError("quarantine deletion eligibility changed")
    metadata = candidate.root.stat(follow_symlinks=False)
    if (
        candidate.root.is_symlink()
        or (metadata.st_dev, metadata.st_ino)
        != (record["quarantine_device"], record["quarantine_inode"])
    ):
        raise DeletionGcError("quarantine physical identity changed")
    manifest = read_quarantined_manifest(Path(scratch_root), candidate.root, record)
    liveness = coerce_process_liveness(
        process_is_live(nonnegative_int(manifest["pid"], "pid"))
    )
    if liveness is not ProcessLiveness.DEAD:
        raise DeletionGcError("quarantined run owner is not provably dead")
    inspection = inspect_quarantine_tree(
        scratch_root,
        project=registry.project,
        run_id=candidate.run_id,
        expected_device=nonnegative_int(
            record["quarantine_device"], "quarantine_device"
        ),
        expected_inode=nonnegative_int(
            record["quarantine_inode"], "quarantine_inode"
        ),
    )
    if (
        inspection.allocated_bytes != candidate.allocated_bytes
        or inspection.inode_count != candidate.inode_count
    ):
        raise DeletionGcError("quarantine contents changed before deletion")
    return candidate


def _revalidate_committed_candidate(
    scratch_root: Path,
    registry: ClaimRegistry,
    store: DeletionRecordStore,
    candidate: DeletionCandidate,
) -> DeletionCandidate:
    expected_root = (
        Path(scratch_root)
        / ".quarantine"
        / registry.project
        / candidate.run_id
    )
    if candidate.root != expected_root:
        raise DeletionGcError("committed quarantine ancestry changed")
    record = read_quarantine_record(
        candidate.ledger.quarantine_record_path(candidate.run_id)
    )
    if record != candidate.record:
        raise DeletionGcError("committed quarantine record changed")
    try:
        metadata = candidate.root.stat(follow_symlinks=False)
    except FileNotFoundError:
        root_present = False
        metadata = None
    except OSError as error:
        raise DeletionGcError("committed quarantine root is unavailable") from error
    else:
        root_present = True
    try:
        state, evidence = store.committed_authority(
            record, quarantine_root_present=root_present
        )
    except DeletionRecordError as error:
        raise DeletionGcError(
            "committed deletion authority changed"
        ) from error
    if evidence.intent is None or evidence.barrier is None:
        raise DeletionGcError("committed deletion records are incomplete")
    if root_present:
        if (
            candidate.root.is_symlink()
            or metadata is None
            or not stat.S_ISDIR(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino)
            != (record["quarantine_device"], record["quarantine_inode"])
        ):
            raise DeletionGcError("committed quarantine identity changed")
    registration_state = store.registration_state(candidate.run_id)
    expected_registration = (
        "deleted" if state is DeletionRecoveryState.DELETED_COMPLETE
        else "deletion_in_progress"
    )
    if registration_state != expected_registration:
        raise DeletionGcError("committed deletion registration state changed")
    intent = evidence.intent
    if intent is None:
        raise DeletionGcError("committed deletion intent is unavailable")
    return replace(
        candidate,
        record=record,
        allocated_bytes=nonnegative_int(
            intent["measured_target_allocated_bytes"],
            "measured_target_allocated_bytes",
        ),
        inode_count=nonnegative_int(
            intent["measured_target_inode_count"],
            "measured_target_inode_count",
        ),
        manifest_process_id=None,
        recovery_state=state,
        authority_mode=DeletionAuthorityMode.COMMITTED_RECOVERY,
    )


def _protection_reason(
    observation: ProtectionObservation, run_id: str
) -> str | None:
    if run_id in observation.pin_run_ids:
        return "pin"
    if run_id in observation.report_run_ids:
        return "report"
    if run_id in observation.monitoring_run_ids:
        return "monitoring"
    return None


__all__ = [
    "_fresh_state",
    "_protection_reason",
    "_revalidate_candidate",
    "_revalidate_committed_candidate",
]
