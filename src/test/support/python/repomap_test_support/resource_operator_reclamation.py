"""Explicit operator-only reclamation of one selected scratch run directory.

Preflight ``physical_mutation_performed`` describes deletion from ``r/*``
only; maintenance, barrier, and evidence-record lifecycle facts are separate.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_index_recovery import (
    MaintenanceIndexBinding,
    acquire_admission_barrier,
    recover_index,
    release_admission_barrier,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
    MaintenanceHandle,
    ProcessLiveness,
)
from repomap_test_support.resource_operator_records import (
    create_operation_record,
    replace_operation_record,
)
from repomap_test_support.resource_operator_scope import (
    OwnedPath,
    ScopeEntry,
    bind_operator_root,
    capture_index_records,
    capture_monitoring,
    capture_protections,
    classify_cotenant_activity,
    classify_liveness,
    inventory_operator_scope,
    quarantined_run_names,
    unlink_owned,
)
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteFailure,
    delete_run_entry,
)
from repomap_test_support.resource_operator_reclamation_evidence import (
    create_preflight_operation,
    finish as _finish,
    interruption_boundary as _interruption_boundary,
    partial_on_delete_failure,
    partial_on_exception,
    partial_on_wall_time_limit,
    public_operator_projection as public_operator_projection,
    refusal as _refusal,
    write_markers as _write_markers,
)
from repomap_test_support.resource_operator_reclamation_preflight import (
    acquire_maintenance,
    classify_activity,
    cleanup_reclamation_resources,
    inventory_preflight,
    preflight as _preflight,
    reconcile_completed_entry_records,
    safe_release_admission_barrier,
)
from repomap_test_support.resource_operator_reclamation_values import (
    CONFIRMATION_LITERAL as CONFIRMATION_LITERAL,
    OPERATOR_DELETION_MAX_SECONDS as OPERATOR_DELETION_MAX_SECONDS,
    PREFLIGHT_CATEGORIES as PREFLIGHT_CATEGORIES,
    PROJECT as PROJECT,
    T as T,
    OperatorReclamationInterrupted as OperatorReclamationInterrupted,
    OperatorReclamationPreflightError as OperatorReclamationPreflightError,
    OperatorReclamationRequest as OperatorReclamationRequest,
    OperatorReclamationResult as OperatorReclamationResult,
    categories_from_payload as _categories_from_payload,
    replace_dict as replace_dict,
)


def _acquire_maintenance(
    root: Path, now_seconds: int
) -> tuple[ClaimRegistry, MaintenanceHandle]:
    return acquire_maintenance(root, now_seconds, registry_cls=ClaimRegistry)


def _inventory_preflight(root: Path) -> tuple[ScopeEntry, ...]:
    return inventory_preflight(root, inventory_fn=inventory_operator_scope)


def _classify_activity(
    entries: tuple[ScopeEntry, ...],
    process_is_live: Callable[[int], ProcessLiveness | bool],
) -> tuple[int, int, dict[str, int]]:
    return classify_activity(
        entries,
        process_is_live,
        classify_live_fn=classify_liveness,
        classify_cotenant_fn=classify_cotenant_activity,
    )


def _create_preflight_operation(
    root: Path,
    request: OperatorReclamationRequest,
    entries: tuple[ScopeEntry, ...],
    *,
    live_count: int,
    unknown_count: int,
    pin_count: int,
    cotenant_activity: dict[str, int],
    now_seconds: int,
) -> tuple[Path, dict[str, object], dict[str, int]]:
    return create_preflight_operation(
        root,
        request,
        entries,
        live_count=live_count,
        unknown_count=unknown_count,
        pin_count=pin_count,
        cotenant_activity=cotenant_activity,
        now_seconds=now_seconds,
        create_record=create_operation_record,
    )


def _reconcile_completed_entry_records(
    completed_names: set[str],
    protections: list[OwnedPath],
    monitoring: list[OwnedPath],
    index_records: list[OwnedPath],
) -> None:
    reconcile_completed_entry_records(
        completed_names,
        protections,
        monitoring,
        index_records,
        unlink_fn=unlink_owned,
    )


def reclaim_run_population(
    scratch_root: Path,
    request: OperatorReclamationRequest,
    *,
    now_seconds: int,
    process_is_live: Callable[[int], ProcessLiveness | bool],
    checkpoint: Callable[[str], None] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> OperatorReclamationResult:
    """Reclaim ``r/*`` under explicit operator authority, never by inference."""
    if not isinstance(request, OperatorReclamationRequest):
        raise ValueError("operator reclamation request is invalid")
    if type(request.force_live) is not bool or type(request.override_pins) is not bool:
        raise ValueError("operator reclamation flags are invalid")
    root = _preflight(
        "scratch_root_authority_unavailable",
        lambda: bind_operator_root(scratch_root),
    )
    checkpoint = checkpoint or (lambda _stage: None)
    registry, maintenance = _preflight(
        "maintenance_authority_unavailable",
        lambda: _acquire_maintenance(root, now_seconds),
    )
    barrier = None
    operation_path = None
    payload = None
    result = None
    pnr = False
    recovery_completed = False
    barrier_released = False
    barrier_release_attempted = False
    release_error = None
    interruption_boundary = None
    reconciling = False
    entries: tuple[ScopeEntry, ...] = ()
    binding = None
    try:
        binding = _preflight(
            "index_authority_unavailable",
            lambda: MaintenanceIndexBinding.bind(root, registry, maintenance),
        )
        barrier = _preflight(
            "admission_barrier_unavailable",
            lambda: acquire_admission_barrier(
                binding, registry, maintenance, now_seconds=now_seconds
            ),
        )
        checkpoint("barrier_acquired")
        entries = _inventory_preflight(root)
        live_count, unknown_count, cotenant_activity = _preflight(
            "liveness_authority_unavailable",
            lambda: _classify_activity(entries, process_is_live),
        )
        protections, pin_count = _preflight(
            "protection_authority_unavailable",
            lambda: capture_protections(root, entries),
        )
        monitoring = _preflight(
            "monitoring_authority_unavailable",
            lambda: capture_monitoring(root, entries),
        )
        index_records = _preflight(
            "index_record_authority_unavailable",
            lambda: capture_index_records(binding, entries),
        )
        operation_path, payload, categories = _preflight(
            "operator_evidence_authority_unavailable",
            lambda: _create_preflight_operation(
                root, request, entries,
                live_count=live_count, unknown_count=unknown_count,
                pin_count=pin_count, cotenant_activity=cotenant_activity,
                now_seconds=now_seconds,
            ),
        )
        refusal = _refusal(request, live_count, unknown_count, pin_count)
        if refusal is not None:
            barrier_release_attempted = True
            release_admission_barrier(binding, registry, maintenance, barrier)
            barrier = None
            barrier_released = True
            return _finish(
                root, operation_path, payload, refusal, categories,
                now_seconds=now_seconds, barrier_released=True,
            )
        marker_count = _write_markers(root, entries, now_seconds)
        payload = replace_dict(payload, marker_count=marker_count)
        replace_operation_record(operation_path, payload)
        checkpoint("before_point_of_no_return")
        payload = replace_dict(
            payload, state="point_of_no_return", point_of_no_return=True
        )
        replace_operation_record(operation_path, payload)
        pnr = True
        deletion_deadline = monotonic() + OPERATOR_DELETION_MAX_SECONDS
        checkpoint("after_point_of_no_return")
        removed_entries = removed_bytes = removed_inodes = 0
        completed_names: set[str] = set()
        pending_protections = list(protections)
        pending_monitoring = list(monitoring)
        pending_index_records = list(index_records)
        first = True
        for entry in entries:
            if first:
                checkpoint("before_first_delete")
                first = False
            try:
                deleted = delete_run_entry(
                    root, name=entry.name,
                    expected_device=entry.inspection.device,
                    expected_inode=entry.inspection.inode,
                    expected_mode=entry.inspection.mode,
                    deadline=deletion_deadline, monotonic=monotonic,
                    pin=entry.pin,
                )
            except SafeTreeDeleteFailure as error:
                payload, removed_bytes, removed_inodes, interrupted = (
                    partial_on_delete_failure(
                        payload, error, removed_bytes, removed_inodes
                    )
                )
                replace_operation_record(operation_path, payload)
                result = _finish(
                    root, operation_path, payload, "partial", categories,
                    now_seconds=now_seconds,
                    identity_replacement_refused=(
                        error.failure_category == "identity_changed"
                    ),
                    barrier_released=False,
                )
                if interrupted:
                    interruption_boundary = _interruption_boundary(
                        result, error.__cause__
                    )
                    raise interruption_boundary from error.__cause__
                return result
            removed_bytes += deleted.removed_allocated_bytes
            removed_inodes += deleted.removed_inode_count
            if not deleted.completed:
                if deleted.stop_reason != "wall_time_limit":
                    raise ValueError("operator deletion stop reason is invalid")
                payload = partial_on_wall_time_limit(
                    payload, removed_bytes, removed_inodes
                )
                replace_operation_record(operation_path, payload)
                return _finish(
                    root, operation_path, payload, "partial", categories,
                    now_seconds=now_seconds, barrier_released=False,
                )
            removed_entries += 1
            payload = replace_dict(
                payload,
                removed_entry_count=removed_entries,
                removed_allocated_bytes=removed_bytes,
                removed_inode_count=removed_inodes,
            )
            replace_operation_record(operation_path, payload)
            completed_names.add(entry.name)
            reconciling = True
            _reconcile_completed_entry_records(
                completed_names, pending_protections,
                pending_monitoring, pending_index_records,
            )
            reconciling = False
        reconciling = True
        recover_index(
            binding, registry, maintenance, now_seconds=now_seconds,
            admission_barrier=barrier,
            preserved_terminal_names=quarantined_run_names(root),
        )
        index = AdvisoryIndex.open(binding.root, scratch_root=root)
        index.reconcile()
        reconciling = False
        recovery_completed = True
        barrier_release_attempted = True
        release_admission_barrier(binding, registry, maintenance, barrier)
        barrier = None
        barrier_released = True
        return _finish(
            root, operation_path, payload, "completed", categories,
            now_seconds=now_seconds, barrier_released=True,
        )
    except BaseException as error:
        if error is interruption_boundary or operation_path is None or payload is None:
            raise
        outcome = "partial" if pnr else "aborted"
        interrupted = False
        identity_changed = False
        if pnr:
            payload, interrupted, identity_changed = partial_on_exception(
                payload, error, reconciling=reconciling
            )
        if (
            barrier is not None
            and not pnr
            and not barrier_release_attempted
            and binding is not None
        ):
            barrier_release_attempted = True
            barrier, barrier_released, release_error = (
                safe_release_admission_barrier(
                    binding, registry, maintenance, barrier,
                    release_fn=release_admission_barrier,
                )
            )
        result = _finish(
            root, operation_path, payload, outcome,
            _categories_from_payload(payload), now_seconds=now_seconds,
            identity_replacement_refused=identity_changed,
            barrier_released=barrier_released,
        )
        if interrupted:
            interruption_boundary = _interruption_boundary(result, error)
            raise interruption_boundary from error
        return result
    finally:
        cleanup_err = cleanup_reclamation_resources(
            entries, binding, registry, maintenance, barrier,
            barrier_release_attempted=barrier_release_attempted,
            can_release_barrier=(not pnr or recovery_completed),
            release_barrier_fn=release_admission_barrier,
            existing_error=release_error,
        )
        if cleanup_err is not None:
            if interruption_boundary is not None:
                interruption_boundary.cleanup_error = cleanup_err
            else:
                raise cleanup_err


__all__ = [
    "CONFIRMATION_LITERAL",
    "OPERATOR_DELETION_MAX_SECONDS",
    "PREFLIGHT_CATEGORIES",
    "OperatorReclamationInterrupted",
    "OperatorReclamationPreflightError",
    "OperatorReclamationRequest",
    "OperatorReclamationResult",
    "public_operator_projection",
    "reclaim_run_population",
]
