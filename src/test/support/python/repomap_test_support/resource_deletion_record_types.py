"""Shared immutable types for deletion-record authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


INTENT_SCHEMA = "repomap-test-deletion-intent-v1"
BARRIER_SCHEMA = "repomap-test-deletion-barrier-v1"
PROGRESS_SCHEMA = "repomap-test-deletion-progress-v1"
COMPLETION_SCHEMA = "repomap-test-deletion-completion-v1"
TOMBSTONE_SCHEMA = "repomap-test-deleted-tombstone-v1"
RESTORATION_SCHEMA = "repomap-test-deletion-restoration-v1"
MAX_TIMESTAMP_SECONDS = (1 << 63) - 1
MAX_TOMBSTONE_RECOVERY_RECORDS = 512


class DeletionRecordError(RuntimeError):
    """Deletion evidence is absent, malformed, conflicting, or unsafe."""


class DeletionRecoveryState(str, Enum):
    NO_DELETION = "no_deletion"
    PREPARED_REVALIDATION_REQUIRED = "prepared_revalidation_required"
    COMMITTED_DELETE_REQUIRED = "committed_delete_required"
    COMMITTED_ROOT_ABSENT_COMPLETION_REQUIRED = (
        "committed_root_absent_completion_required"
    )
    COMPLETED_TOMBSTONE_REQUIRED = "completed_tombstone_required"
    DELETED_COMPLETE = "deleted_complete"
    PROTECTED_RESTORED = "protected_restored"
    AMBIGUOUS_EVIDENCE_CONFLICT = "ambiguous_evidence_conflict"


@dataclass(frozen=True)
class DeletionEvidence:
    intent: dict[str, object] | None
    barrier: dict[str, object] | None
    completion: dict[str, object] | None
    tombstone: dict[str, object] | None
    restoration: dict[str, object] | None


class _DeletionRecordStoreProtocol(Protocol):
    project: str
    tombstone_root: Path

    def _key(self, run_id: str, quarantine_record_id: str) -> str:
        ...

    def evidence(
        self, run_id: str, quarantine_record_id: str
    ) -> DeletionEvidence:
        ...


__all__ = [
    "BARRIER_SCHEMA",
    "COMPLETION_SCHEMA",
    "DeletionEvidence",
    "DeletionRecordError",
    "DeletionRecoveryState",
    "INTENT_SCHEMA",
    "MAX_TIMESTAMP_SECONDS",
    "MAX_TOMBSTONE_RECOVERY_RECORDS",
    "PROGRESS_SCHEMA",
    "RESTORATION_SCHEMA",
    "TOMBSTONE_SCHEMA",
    "_DeletionRecordStoreProtocol",
]
