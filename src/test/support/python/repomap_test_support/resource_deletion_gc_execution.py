"""Durable commit, physical delete, and recovery execution for deletion GC."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from repomap_test_support.resource_deletion_candidates import (
    DeletionAuthorityMode,
    DeletionCandidate,
    DeletionGcError,
)
from repomap_test_support.resource_deletion_gc_types import (
    DeletionOutcome,
    PhysicalMutationState,
)
from repomap_test_support.resource_deletion_record_store import DeletionRecordStore
from repomap_test_support.resource_deletion_record_types import DeletionRecoveryState
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
    MaintenanceHandle,
)
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteError,
    SafeTreeDeleteFailure,
    SafeTreeDeleteResult,
    inspect_quarantine_tree,
    quarantine_root_absent,
)
from repomap_test_support.resource_validation import nonnegative_int


def _commit_and_delete(
    scratch_root: Path,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    ledger: GcLedger,
    store: DeletionRecordStore,
    candidate: DeletionCandidate,
    *,
    claim_record_id: str,
    now_seconds: int,
    deadline: float,
    monotonic: Callable[[], float],
    safe_delete: Callable[..., SafeTreeDeleteResult],
    after_prepare: Callable[[DeletionCandidate], None] | None,
    after_barrier: Callable[[DeletionCandidate], None] | None,
    before_delete: Callable[[DeletionCandidate], None] | None,
) -> DeletionOutcome:
    registry.require_maintenance(maintenance)
    evidence = store.evidence(
        candidate.run_id, str(candidate.record["quarantine_record_id"])
    )
    state = store.classify(
        candidate.run_id,
        str(candidate.record["quarantine_record_id"]),
        quarantine_root_present=candidate.root.exists() and not candidate.root.is_symlink(),
    )
    intent = evidence.intent
    barrier = evidence.barrier
    if state is DeletionRecoveryState.NO_DELETION:
        inspection = inspect_quarantine_tree(
            scratch_root,
            project=registry.project,
            run_id=candidate.run_id,
            expected_device=nonnegative_int(
                candidate.record["quarantine_device"], "quarantine_device"
            ),
            expected_inode=nonnegative_int(
                candidate.record["quarantine_inode"], "quarantine_inode"
            ),
        )
        intent = store.prepare(
            run_id=candidate.run_id,
            phase=candidate.phase,
            quarantine_record_id=str(candidate.record["quarantine_record_id"]),
            quarantine_device=nonnegative_int(
                candidate.record["quarantine_device"], "quarantine_device"
            ),
            quarantine_inode=nonnegative_int(
                candidate.record["quarantine_inode"], "quarantine_inode"
            ),
            prepared_at_seconds=now_seconds,
            maintenance_owner_token=maintenance.owner_token,
            lifecycle_claim_record_id=claim_record_id,
            measured_target_allocated_bytes=inspection.allocated_bytes,
            measured_target_inode_count=inspection.inode_count,
        )
        ledger.append(
            "deletion_intent",
            {"intent_record_id": intent["intent_record_id"]},
            now_seconds=now_seconds,
        )
        if after_prepare is not None:
            after_prepare(candidate)
        state = DeletionRecoveryState.PREPARED_REVALIDATION_REQUIRED
    if state is DeletionRecoveryState.PREPARED_REVALIDATION_REQUIRED:
        if intent is None:
            raise DeletionGcError("deletion intent is unavailable")
        barrier = store.commit(
            intent,
            committed_at_seconds=now_seconds,
            maintenance_owner_token=maintenance.owner_token,
            lifecycle_claim_record_id=claim_record_id,
        )
        ledger.append(
            "deletion_barrier",
            {"barrier_record_id": barrier["barrier_record_id"]},
            now_seconds=now_seconds,
        )
        if after_barrier is not None:
            after_barrier(candidate)
        state = DeletionRecoveryState.COMMITTED_DELETE_REQUIRED
    if state is DeletionRecoveryState.COMMITTED_DELETE_REQUIRED:
        if barrier is None:
            raise DeletionGcError("deletion barrier is unavailable")
        if before_delete is not None:
            before_delete(candidate)
        try:
            result = safe_delete(
                scratch_root,
                project=registry.project,
                run_id=candidate.run_id,
                expected_device=candidate.record["quarantine_device"],
                expected_inode=candidate.record["quarantine_inode"],
                deadline=deadline,
                monotonic=monotonic,
            )
        except SafeTreeDeleteFailure as error:
            store.record_progress(
                barrier,
                recorded_at_seconds=now_seconds,
                removed_allocated_bytes=error.removed_allocated_bytes,
                removed_inode_count=error.removed_inode_count,
                root_absent=False,
                outcome="deletion_in_progress",
            )
            ledger.append(
                "deletion_progress",
                {"category": "deletion_in_progress"},
                now_seconds=now_seconds,
            )
            if error.failure_category == "interrupted":
                cause = error.__cause__
                if cause is not None and not isinstance(cause, Exception):
                    raise cause
                raise
            mutation = (
                PhysicalMutationState.PARTIAL
                if error.removed_inode_count > 0
                else PhysicalMutationState.NONE
            )
            return DeletionOutcome(
                candidate.run_id,
                "deletion_in_progress",
                mutation,
                error.removed_allocated_bytes,
                error.removed_inode_count,
                False,
                False,
            )
        except SafeTreeDeleteError:
            ledger.append(
                "deletion_progress",
                {"category": "mutation_unobserved"},
                now_seconds=now_seconds,
            )
            return DeletionOutcome(
                candidate.run_id,
                "deletion_in_progress",
                PhysicalMutationState.UNOBSERVED,
                None,
                None,
                None,
                False,
            )
        store.record_progress(
            barrier,
            recorded_at_seconds=now_seconds,
            removed_allocated_bytes=result.removed_allocated_bytes,
            removed_inode_count=result.removed_inode_count,
            root_absent=result.completed,
            outcome="root_absent" if result.completed else "deletion_in_progress",
        )
        ledger.append(
            "deletion_progress",
            {"category": "root_absent" if result.completed else "deletion_in_progress"},
            now_seconds=now_seconds,
        )
        if not result.completed:
            mutation = (
                PhysicalMutationState.PARTIAL
                if result.removed_inode_count > 0
                else PhysicalMutationState.NONE
            )
            return DeletionOutcome(
                candidate.run_id,
                "deletion_in_progress",
                mutation,
                result.removed_allocated_bytes,
                result.removed_inode_count,
                False,
                True,
            )
        state = DeletionRecoveryState.COMMITTED_ROOT_ABSENT_COMPLETION_REQUIRED
    if state is DeletionRecoveryState.COMMITTED_ROOT_ABSENT_COMPLETION_REQUIRED:
        if not quarantine_root_absent(
            scratch_root, project=registry.project, run_id=candidate.run_id
        ):
            raise DeletionGcError("deletion completion requires exact root absence")
        if intent is None or barrier is None:
            raise DeletionGcError("deletion intent or barrier is unavailable")
        completion = store.complete(
            intent,
            barrier,
            deleted_at_seconds=now_seconds,
            completion_mode=(
                "root_absent_recovery"
                if candidate.recovery_state
                is DeletionRecoveryState.COMMITTED_ROOT_ABSENT_COMPLETION_REQUIRED
                else (
                    "resumed"
                    if candidate.authority_mode
                    is DeletionAuthorityMode.COMMITTED_RECOVERY
                    else "ordinary"
                )
            ),
        )
        ledger.append(
            "deletion_completion",
            {"completion_record_id": completion["completion_record_id"]},
            now_seconds=now_seconds,
        )
        state = DeletionRecoveryState.COMPLETED_TOMBSTONE_REQUIRED
    if state is DeletionRecoveryState.COMPLETED_TOMBSTONE_REQUIRED:
        completion_candidate = store.evidence(
            candidate.run_id, str(candidate.record["quarantine_record_id"])
        ).completion
        if completion_candidate is None:
            raise DeletionGcError("completion authority is unavailable")
        tombstone = store.finalize_tombstone(
            completion_candidate,
            original_quarantined_at_seconds=nonnegative_int(
                candidate.record["quarantined_at_seconds"], "quarantined_at_seconds"
            ),
        )
        ledger.append(
            "deleted_tombstone",
            {"tombstone_record_id": tombstone["tombstone_record_id"]},
            now_seconds=now_seconds,
        )
        return _completed_outcome(candidate.run_id, completion_candidate)
    if state is DeletionRecoveryState.DELETED_COMPLETE:
        evidence_completion = store.evidence(
            candidate.run_id, str(candidate.record["quarantine_record_id"])
        ).completion
        if evidence_completion is None:
            raise DeletionGcError("deleted completion authority is unavailable")
        return _completed_outcome(
            candidate.run_id, evidence_completion, "deleted_complete"
        )
    raise DeletionGcError("deletion recovery state is not actionable")


def _no_mutation(run_id: str, category: str) -> DeletionOutcome:
    return DeletionOutcome(
        run_id,
        category,
        PhysicalMutationState.NONE,
        0,
        0,
        False,
        True,
    )


def _completed_outcome(
    run_id: str,
    completion: dict[str, object],
    category: str = "deleted",
) -> DeletionOutcome:
    raw_bytes = completion.get("measured_deleted_allocated_bytes")
    raw_inodes = completion.get("measured_deleted_inode_count")
    bytes_val = (
        nonnegative_int(raw_bytes, "measured_deleted_allocated_bytes")
        if raw_bytes is not None
        else None
    )
    inodes_val = (
        nonnegative_int(raw_inodes, "measured_deleted_inode_count")
        if raw_inodes is not None
        else None
    )
    return DeletionOutcome(
        run_id,
        category,
        PhysicalMutationState.COMPLETED,
        bytes_val,
        inodes_val,
        True,
        True,
    )


__all__ = ["_commit_and_delete", "_completed_outcome", "_no_mutation"]
