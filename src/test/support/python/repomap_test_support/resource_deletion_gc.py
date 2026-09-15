"""Compatibility surface for TTL-gated physical quarantine deletion."""

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
    discover_quarantine_deletions,
    select_deletion_batch,
)
from repomap_test_support.resource_deletion_gc_batch import (
    DELETION_MAX_SECONDS,
    public_deletion_projection,
)
from repomap_test_support.resource_deletion_gc_types import (
    DeletionOutcome,
    DeletionResult,
    PhysicalMutationState,
)
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_lifecycle_claim import (
    ClaimRegistry,
    MaintenanceHandle,
    ProcessLiveness,
)
from repomap_test_support.resource_protection_authority import ProtectionObservation
from repomap_test_support.resource_safe_tree_delete import (
    SafeTreeDeleteResult,
    delete_quarantine_tree,
)


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
    """Delegate while retaining the original facade-level patch seams."""
    from repomap_test_support import resource_deletion_gc_batch as batch

    return batch.delete_quarantine_batch(
        scratch_root,
        registry,
        maintenance,
        ledger,
        now_seconds=now_seconds,
        protection_provider=protection_provider,
        process_is_live=process_is_live,
        aggregate_below_soft=aggregate_below_soft,
        monotonic=monotonic,
        safe_delete=safe_delete,
        after_prepare=after_prepare,
        after_barrier=after_barrier,
        before_delete=before_delete,
        before_protected_restore=before_protected_restore,
        on_completion=on_completion,
    )


__all__ = [
    "DELETION_MAX_BYTES",
    "DELETION_MAX_RUNS",
    "DELETION_MAX_SECONDS",
    "DeletionAuthorityMode",
    "DeletionBatchSelection",
    "DeletionCandidate",
    "DeletionDiscovery",
    "DeletionGcError",
    "DeletionOutcome",
    "DeletionResult",
    "PhysicalMutationState",
    "delete_quarantine_batch",
    "discover_quarantine_deletions",
    "public_deletion_projection",
    "select_deletion_batch",
]
