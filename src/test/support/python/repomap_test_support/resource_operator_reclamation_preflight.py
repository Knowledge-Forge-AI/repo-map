"""Preflight stages, authority validation, and cleanup reconciliation."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from repomap_test_support.resource_index_recovery import (
    AdmissionBarrier,
    MaintenanceIndexBinding,
    release_admission_barrier,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
    MaintenanceHandle,
    ProcessLiveness,
)
from repomap_test_support.resource_operator_scope import (
    OperatorScopeIdentityError,
    OwnedPath,
    ScopeEntry,
    classify_cotenant_activity,
    classify_liveness,
    close_scope_pins,
    inventory_operator_scope,
    unlink_owned,
)
from repomap_test_support.resource_operator_reclamation_values import (
    PROJECT,
    T,
    OperatorReclamationPreflightError,
)


def preflight(category: str, action: Callable[[], T]) -> T:
    try:
        return action()
    except Exception as error:
        raise OperatorReclamationPreflightError(category) from error


def acquire_maintenance(
    root: Path,
    now_seconds: int,
    registry_cls: type[ClaimRegistry] = ClaimRegistry,
) -> tuple[ClaimRegistry, MaintenanceHandle]:
    registry = registry_cls(root, PROJECT)
    maintenance = registry.acquire_maintenance(
        "operator-reclaim", now_seconds=now_seconds
    )
    return registry, maintenance


def inventory_preflight(
    root: Path,
    inventory_fn: Callable[[Path], tuple[ScopeEntry, ...]] = inventory_operator_scope,
) -> tuple[ScopeEntry, ...]:
    try:
        return inventory_fn(root)
    except OperatorScopeIdentityError as error:
        raise OperatorReclamationPreflightError(
            "inventory_identity_changed"
        ) from error
    except Exception as error:
        raise OperatorReclamationPreflightError(
            "inventory_authority_unavailable"
        ) from error


def classify_activity(
    entries: tuple[ScopeEntry, ...],
    process_is_live: Callable[[int], ProcessLiveness | bool],
    classify_live_fn: Callable[
        [tuple[ScopeEntry, ...], Callable[[int], ProcessLiveness | bool]],
        tuple[int, int],
    ] = classify_liveness,
    classify_cotenant_fn: Callable[
        [tuple[ScopeEntry, ...], Callable[[int], ProcessLiveness | bool]],
        dict[str, int],
    ] = classify_cotenant_activity,
) -> tuple[int, int, dict[str, int]]:
    live_count, unknown_count = classify_live_fn(entries, process_is_live)
    return (
        live_count,
        unknown_count,
        classify_cotenant_fn(entries, process_is_live),
    )


def reconcile_completed_entry_records(
    completed_names: set[str],
    protections: list[OwnedPath],
    monitoring: list[OwnedPath],
    index_records: list[OwnedPath],
    unlink_fn: Callable[[OwnedPath], None] = unlink_owned,
) -> None:
    for records in (protections, monitoring):
        for owned in tuple(records):
            if not owned.owner_names or not set(owned.owner_names).issubset(
                completed_names
            ):
                continue
            unlink_fn(owned)
            records.remove(owned)
    ready_index = [
        owned
        for owned in index_records
        if owned.owner_names and set(owned.owner_names).issubset(completed_names)
    ]
    order = {"closed": 0, "admitted": 1}
    for owned in sorted(
        ready_index,
        key=lambda item: (order.get(item.record_kind or "", 2), item.path.name),
    ):
        unlink_fn(owned)
        index_records.remove(owned)


def safe_release_admission_barrier(
    binding: MaintenanceIndexBinding,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    barrier: AdmissionBarrier,
    release_fn: Callable[
        [MaintenanceIndexBinding, ClaimRegistry, MaintenanceHandle, AdmissionBarrier],
        None,
    ] = release_admission_barrier,
) -> tuple[AdmissionBarrier | None, bool, BaseException | None]:
    try:
        release_fn(binding, registry, maintenance, barrier)
        return None, True, None
    except BaseException as barrier_error:
        return barrier, False, barrier_error


def cleanup_reclamation_resources(
    entries: tuple[ScopeEntry, ...],
    binding: MaintenanceIndexBinding | None,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    barrier: AdmissionBarrier | None,
    *,
    barrier_release_attempted: bool,
    can_release_barrier: bool,
    release_barrier_fn: Callable[
        [MaintenanceIndexBinding, ClaimRegistry, MaintenanceHandle, AdmissionBarrier],
        None,
    ] = release_admission_barrier,
    existing_error: BaseException | None = None,
) -> BaseException | None:
    close_scope_pins(entries)
    release_error = existing_error
    if (
        barrier is not None
        and not barrier_release_attempted
        and can_release_barrier
        and binding is not None
    ):
        try:
            release_barrier_fn(binding, registry, maintenance, barrier)
        except BaseException as error:
            if release_error is None:
                release_error = error
    try:
        registry.release_maintenance(maintenance)
    except BaseException as error:
        if release_error is None:
            release_error = error
    return release_error


__all__ = [
    "acquire_maintenance",
    "classify_activity",
    "cleanup_reclamation_resources",
    "inventory_preflight",
    "preflight",
    "reconcile_completed_entry_records",
    "safe_release_admission_barrier",
]
