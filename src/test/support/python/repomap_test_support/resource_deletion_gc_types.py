"""Result types for bounded quarantine deletion."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from repomap_test_support.resource_deletion_candidates import (
    DeletionGcError,
)


def _require_dict(val: dict[str, object] | None) -> dict[str, object]:
    if val is None:
        raise DeletionGcError("expected record is unavailable")
    return val


class PhysicalMutationState(str, Enum):
    NONE = "none"
    PARTIAL = "partial"
    COMPLETED = "completed"
    UNOBSERVED = "unobserved"


@dataclass(frozen=True)
class DeletionOutcome:
    run_id: str
    category: str
    physical_mutation_state: PhysicalMutationState
    removed_allocated_bytes: int | None
    removed_inode_count: int | None
    root_absent: bool | None
    observation_complete: bool


@dataclass(frozen=True)
class DeletionResult:
    outcomes: tuple[DeletionOutcome, ...]
    deleted: int
    protected_restored: int
    protected_restore_collision: int
    ttl_held: int
    ambiguous: int
    operator_attention_required: int
    claim_unavailable: int
    partial_in_progress: int
    stop_reason: str
    physical_mutation_state: PhysicalMutationState
    removed_allocated_bytes: int | None
    removed_inode_count: int | None


__all__ = [
    "DeletionOutcome",
    "DeletionResult",
    "PhysicalMutationState",
    "_require_dict",
]
