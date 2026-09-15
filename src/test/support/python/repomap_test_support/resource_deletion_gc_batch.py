"""Batch orchestration and public projection for quarantine deletion."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from repomap_test_support.resource_deletion_candidates import (
    DELETION_MAX_BYTES,
    DELETION_MAX_RUNS,
    DeletionAuthorityMode,
    DeletionBatchSelection,
    DeletionCandidate,
    DeletionDiscovery,
    DeletionGcError,
    committed_state,
)
from repomap_test_support.resource_deletion_gc_execution import (
    _commit_and_delete,
    _no_mutation,
)
from repomap_test_support.resource_deletion_gc_revalidation import (
    _fresh_state,
    _protection_reason,
    _revalidate_candidate,
    _revalidate_committed_candidate,
)
from repomap_test_support.resource_deletion_gc_types import (
    DeletionOutcome,
    DeletionResult,
    PhysicalMutationState,
    _require_dict,
)
from repomap_test_support.resource_deletion_record_store import DeletionRecordStore
from repomap_test_support.resource_deletion_record_types import DeletionRecoveryState
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_lifecycle_claim import (
    ClaimError,
    ClaimPurpose,
    ClaimRegistry,
    MaintenanceHandle,
    ProcessLiveness,
)
from repomap_test_support.resource_protection_authority import (
    ProtectionAuthorityError,
    ProtectionObservation,
)
from repomap_test_support.resource_quarantine_records import (
    QuarantineError,
    restore_quarantined,
)
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteResult,
    delete_quarantine_tree,
)
from repomap_test_support.resource_validation import nonnegative_int


# Patch resource_deletion_gc.DELETION_MAX_SECONDS; execution reads the facade.
DELETION_MAX_SECONDS = 60


def delete_quarantine_batch(
    scratch_root: Path,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    ledger: GcLedger,
    *,
    now_seconds: int,
    protection_provider: Callable[[int], ProtectionObservation],
    process_is_live: Callable[[int], ProcessLiveness | bool],
    aggregate_below_soft: Callable[[], bool],
    monotonic: Callable[[], float] = time.monotonic,
    safe_delete: Callable[..., SafeTreeDeleteResult] = delete_quarantine_tree,
    after_prepare: Callable[[DeletionCandidate], None] | None = None,
    after_barrier: Callable[[DeletionCandidate], None] | None = None,
    before_delete: Callable[[DeletionCandidate], None] | None = None,
    before_protected_restore: Callable[[DeletionCandidate], None] | None = None,
    on_completion: Callable[[DeletionCandidate], None] | None = None,
) -> DeletionResult:
    from repomap_test_support import resource_deletion_gc as owner

    registry.require_maintenance(maintenance)
    now = nonnegative_int(now_seconds, "deletion pass timestamp")
    store = DeletionRecordStore(scratch_root, registry.project)
    discovery = owner.discover_quarantine_deletions(
        scratch_root, registry=registry, store=store, now_seconds=now
    )
    selection = owner.select_deletion_batch(discovery.candidates)
    started = monotonic()
    deadline = started + owner.DELETION_MAX_SECONDS
    outcomes: list[DeletionOutcome] = []
    deleted = restored = collisions = claims = partial = 0
    attention = discovery.operator_attention_required
    stop_reason = selection.limit_reason or "candidate_exhausted"
    for candidate in selection.candidates:
        if monotonic() >= deadline:
            stop_reason = "wall_time_limit"
            break
        if not committed_state(candidate.recovery_state):
            try:
                if aggregate_below_soft():
                    stop_reason = "below_soft"
                    break
            except Exception as error:
                raise DeletionGcError(
                    "aggregate authority is unavailable"
                ) from error
        try:
            claim = registry.acquire(
                candidate.run_id,
                ClaimPurpose.PHYSICAL_DELETE,
                now_seconds=now,
            )
        except ClaimError:
            claims += 1
            attention += 1
            outcomes.append(_no_mutation(candidate.run_id, "claim_unavailable"))
            continue
        try:
            registry.require_claim(claim, purpose=ClaimPurpose.PHYSICAL_DELETE)
            if candidate.authority_mode is DeletionAuthorityMode.COMMITTED_RECOVERY:
                candidate = _revalidate_committed_candidate(
                    scratch_root, registry, store, candidate
                )
                state = candidate.recovery_state
            else:
                state = _fresh_state(store, candidate)
                if state not in {
                    DeletionRecoveryState.NO_DELETION,
                    DeletionRecoveryState.PREPARED_REVALIDATION_REQUIRED,
                }:
                    raise DeletionGcError(
                        "ordinary quarantine authority changed before deletion"
                    )
            if state in {
                DeletionRecoveryState.NO_DELETION,
                DeletionRecoveryState.PREPARED_REVALIDATION_REQUIRED,
            }:
                candidate = _revalidate_candidate(
                    scratch_root,
                    registry,
                    candidate,
                    now_seconds=now,
                    process_is_live=process_is_live,
                )
                try:
                    observation = protection_provider(now)
                except ProtectionAuthorityError as error:
                    raise DeletionGcError(
                        "protection authority is unavailable"
                    ) from error
                ledger.append(
                    "deletion_protection_observation",
                    {
                        "provider_record_id": observation.provider_record_id,
                        "report_count": len(observation.report_run_ids),
                        "monitoring_count": len(observation.monitoring_run_ids),
                        "pin_count": len(observation.pin_run_ids),
                    },
                    now_seconds=now,
                )
                reason = _protection_reason(observation, candidate.run_id)
                if reason is not None:
                    try:
                        restore_quarantined(
                            scratch_root,
                            registry,
                            maintenance,
                            candidate.ledger,
                            candidate.run_id,
                            now_seconds=now,
                            claim_handle=claim,
                            before_rename=(
                                (lambda: before_protected_restore(candidate))
                                if before_protected_restore is not None
                                else None
                            ),
                            after_rename=(
                                (
                                    lambda: store.record_restoration(
                                        _require_dict(
                                            store.evidence(
                                                candidate.run_id,
                                                str(
                                                    candidate.record[
                                                        "quarantine_record_id"
                                                    ]
                                                ),
                                            ).intent
                                        ),
                                        restored_at_seconds=now,
                                        reason=reason,
                                    )
                                )
                                if state
                                is DeletionRecoveryState.PREPARED_REVALIDATION_REQUIRED
                                else None
                            ),
                        )
                    except QuarantineError:
                        collisions += 1
                        attention += 1
                        outcomes.append(
                            _no_mutation(
                                candidate.run_id, "protected_restore_collision"
                            )
                        )
                        continue
                    ledger.append(
                        "protected_restored",
                        {"category": reason},
                        now_seconds=now,
                    )
                    restored += 1
                    outcomes.append(
                        _no_mutation(candidate.run_id, "protected_restored")
                    )
                    continue
            outcome = _commit_and_delete(
                scratch_root,
                registry,
                maintenance,
                ledger,
                store,
                candidate,
                claim_record_id=claim.record_id,
                now_seconds=now,
                deadline=deadline,
                monotonic=monotonic,
                safe_delete=safe_delete,
                after_prepare=after_prepare,
                after_barrier=after_barrier,
                before_delete=before_delete,
            )
            outcomes.append(outcome)
            if outcome.category == "deleted":
                deleted += 1
                if on_completion is not None:
                    try:
                        on_completion(candidate)
                    except Exception:
                        attention += 1
                        stop_reason = "index_reconciliation_pending"
                        ledger.append(
                            "deleted_index_reconciliation_pending",
                            {"category": "callback_failed"},
                            now_seconds=now,
                        )
                        break
            elif outcome.category == "deletion_in_progress":
                partial += 1
                attention += 1
                stop_reason = "partial_deletion_in_progress"
                break
        finally:
            registry.release(claim)
    mutation_state, removed_bytes, removed_inodes = _aggregate_mutation(outcomes)
    result = DeletionResult(
        tuple(outcomes),
        deleted,
        restored,
        collisions,
        discovery.ttl_held,
        discovery.ambiguous,
        attention,
        claims,
        partial,
        stop_reason,
        mutation_state,
        removed_bytes,
        removed_inodes,
    )
    ledger.append(
        "delete_batch_summary",
        {
            "selected": len(selection.candidates),
            "deleted": result.deleted,
            "protected_restored": result.protected_restored,
            "protected_restore_collision": result.protected_restore_collision,
            "ttl_held": result.ttl_held,
            "ambiguous": result.ambiguous,
            "operator_attention_required": result.operator_attention_required,
            "claim_unavailable": result.claim_unavailable,
            "partial_in_progress": result.partial_in_progress,
            "stop_reason": result.stop_reason,
            "physical_mutation_state": result.physical_mutation_state.value,
            "removed_allocated_bytes": (
                result.removed_allocated_bytes
                if result.removed_allocated_bytes is not None
                else "unobserved"
            ),
            "removed_inode_count": (
                result.removed_inode_count
                if result.removed_inode_count is not None
                else "unobserved"
            ),
        },
        now_seconds=now,
    )
    return result


def public_deletion_projection(result: DeletionResult) -> dict[str, int | str | bool]:
    state = result.physical_mutation_state
    return {
        "deleted_runs": result.deleted,
        "protected_restored_runs": result.protected_restored,
        "protected_restore_collisions": result.protected_restore_collision,
        "ttl_held_runs": result.ttl_held,
        "ambiguous_runs": result.ambiguous,
        "operator_attention_required": result.operator_attention_required,
        "claim_unavailable_runs": result.claim_unavailable,
        "deletion_in_progress_runs": result.partial_in_progress,
        "stop_reason": result.stop_reason,
        "physical_mutation_state": state.value,
        "removed_allocated_bytes": (
            result.removed_allocated_bytes
            if result.removed_allocated_bytes is not None
            else "unobserved"
        ),
        "removed_inode_count": (
            result.removed_inode_count
            if result.removed_inode_count is not None
            else "unobserved"
        ),
        "physical_deletion_performed": (
            "unobserved"
            if state is PhysicalMutationState.UNOBSERVED
            else state is not PhysicalMutationState.NONE
        ),
        "host_restored": False,
    }


def _aggregate_mutation(
    outcomes: list[DeletionOutcome],
) -> tuple[PhysicalMutationState, int | None, int | None]:
    if any(
        outcome.physical_mutation_state is PhysicalMutationState.UNOBSERVED
        for outcome in outcomes
    ):
        return PhysicalMutationState.UNOBSERVED, None, None
    removed_bytes = sum(outcome.removed_allocated_bytes or 0 for outcome in outcomes)
    removed_inodes = sum(outcome.removed_inode_count or 0 for outcome in outcomes)
    states = {outcome.physical_mutation_state for outcome in outcomes}
    if PhysicalMutationState.PARTIAL in states:
        state = PhysicalMutationState.PARTIAL
    elif PhysicalMutationState.COMPLETED in states:
        state = PhysicalMutationState.COMPLETED
    else:
        state = PhysicalMutationState.NONE
    return state, removed_bytes, removed_inodes


__all__ = [
    "DELETION_MAX_BYTES",
    "DELETION_MAX_RUNS",
    "DELETION_MAX_SECONDS",
    "DeletionAuthorityMode",
    "DeletionBatchSelection",
    "DeletionCandidate",
    "DeletionDiscovery",
    "DeletionGcError",
    "delete_quarantine_batch",
    "public_deletion_projection",
    "_aggregate_mutation",
]
