"""Durable deletion-record store and committed recovery authority."""

from __future__ import annotations

from pathlib import Path

from repomap_test_support.resource_deletion_record_authority import (
    _DeletionRecordAuthorityMixin,
)
from repomap_test_support.resource_deletion_record_io import (
    _DeletionRecordStoreIoMixin,
)
from repomap_test_support.resource_deletion_record_persistence import (
    _matching_records,
    _owned_directory,
    _private_directory,
    _record_id,
    _timestamp,
    read_private_json,
    _write_checked,
)
from repomap_test_support.resource_deletion_record_types import (
    BARRIER_SCHEMA,
    COMPLETION_SCHEMA,
    DeletionEvidence,
    DeletionRecordError,
    DeletionRecoveryState,
    INTENT_SCHEMA,
    PROGRESS_SCHEMA,
    RESTORATION_SCHEMA,
    TOMBSTONE_SCHEMA,
)
from repomap_test_support.resource_deletion_record_validation import (
    _classify_evidence,
    _require_attempt_match,
    _require_quarantine_match,
    _validate_barrier,
    _validate_completion,
    _validate_intent,
    _validate_progress,
    _validate_tombstone,
)
from repomap_test_support.resource_index_records import owner_token, safe_run_id, safe_text
from repomap_test_support.resource_ledger_io import PrivateJsonError
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    nonnegative_int,
    sha256_hex,
)


class DeletionRecordStore(
    _DeletionRecordAuthorityMixin,
    _DeletionRecordStoreIoMixin,
):
    """Own immutable per-quarantine-attempt evidence outside deleted roots."""

    def __init__(
        self,
        scratch_root: Path,
        project: str = "repo-map_dev",
        *,
        create: bool = True,
    ) -> None:
        self.scratch_root = Path(scratch_root)
        self.project = safe_run_id(project)
        authority_root = self.scratch_root / ".deletions"
        self.root = authority_root / self.project
        _owned_directory(self.scratch_root)
        _private_directory(authority_root, create=create)
        _private_directory(self.root, create=create)
        self.intent_root = self.root / "intents"
        self.barrier_root = self.root / "barriers"
        self.progress_root = self.root / "progress"
        self.completion_root = self.root / "completions"
        self.tombstone_root = self.root / "tombstones"
        self.restoration_root = self.root / "restorations"
        for path in (
            self.intent_root,
            self.barrier_root,
            self.progress_root,
            self.completion_root,
            self.tombstone_root,
            self.restoration_root,
        ):
            _private_directory(path, create=create)

    def prepare(
        self,
        *,
        run_id: str,
        phase: str,
        quarantine_record_id: str,
        quarantine_device: int,
        quarantine_inode: int,
        prepared_at_seconds: int,
        maintenance_owner_token: str,
        lifecycle_claim_record_id: str,
        measured_target_allocated_bytes: int,
        measured_target_inode_count: int,
    ) -> dict[str, object]:
        seed = {
            "schema": INTENT_SCHEMA,
            "project": self.project,
            "run_id": safe_run_id(run_id),
            "phase": safe_text(phase, "phase"),
            "quarantine_record_id": sha256_hex(
                quarantine_record_id, "quarantine record id"
            ),
            "quarantine_device": nonnegative_int(
                quarantine_device, "quarantine device"
            ),
            "quarantine_inode": nonnegative_int(
                quarantine_inode, "quarantine inode"
            ),
            "prepared_at_seconds": _timestamp(
                prepared_at_seconds, "prepared timestamp"
            ),
            "maintenance_owner_token": owner_token(maintenance_owner_token),
            "lifecycle_claim_record_id": sha256_hex(
                lifecycle_claim_record_id, "lifecycle claim record id"
            ),
            "measured_target_allocated_bytes": nonnegative_int(
                measured_target_allocated_bytes, "measured target allocated bytes"
            ),
            "measured_target_inode_count": nonnegative_int(
                measured_target_inode_count, "measured target inode count"
            ),
        }
        payload = {**seed, "intent_record_id": _record_id(seed)}
        return self._write("intent", payload)

    def commit(
        self,
        intent: dict[str, object],
        *,
        committed_at_seconds: int,
        maintenance_owner_token: str,
        lifecycle_claim_record_id: str,
    ) -> dict[str, object]:
        intent = _validate_intent(intent, self.project)
        seed = {
            "schema": BARRIER_SCHEMA,
            "project": self.project,
            "run_id": intent["run_id"],
            "phase": intent["phase"],
            "quarantine_record_id": intent["quarantine_record_id"],
            "quarantine_device": intent["quarantine_device"],
            "quarantine_inode": intent["quarantine_inode"],
            "deletion_intent_record_id": intent["intent_record_id"],
            "maintenance_owner_token": owner_token(maintenance_owner_token),
            "lifecycle_claim_record_id": sha256_hex(
                lifecycle_claim_record_id, "lifecycle claim record id"
            ),
            "committed_at_seconds": _timestamp(
                committed_at_seconds, "committed timestamp"
            ),
        }
        digest = _record_id(seed)
        identified = {**seed, "barrier_digest": digest}
        payload = {**identified, "barrier_record_id": _record_id(identified)}
        return self._write("barrier", payload)

    def record_progress(
        self,
        barrier: dict[str, object],
        *,
        recorded_at_seconds: int,
        removed_allocated_bytes: int,
        removed_inode_count: int,
        root_absent: bool,
        outcome: str,
    ) -> dict[str, object]:
        barrier = _validate_barrier(barrier, self.project)
        if type(root_absent) is not bool:
            raise DeletionRecordError("deletion progress root absence is invalid")
        if outcome not in {"deletion_in_progress", "root_absent"}:
            raise DeletionRecordError("deletion progress outcome is unsupported")
        attempt = self._key(
            str(barrier["run_id"]), str(barrier["quarantine_record_id"])
        )
        directory = self.progress_root / attempt
        _private_directory(directory, create=True)
        sequence = len(tuple(directory.iterdir()))
        seed = {
            "schema": PROGRESS_SCHEMA,
            "project": self.project,
            "run_id": barrier["run_id"],
            "quarantine_record_id": barrier["quarantine_record_id"],
            "deletion_barrier_record_id": barrier["barrier_record_id"],
            "sequence": sequence,
            "recorded_at_seconds": _timestamp(
                recorded_at_seconds, "progress timestamp"
            ),
            "removed_allocated_bytes": nonnegative_int(
                removed_allocated_bytes, "removed allocated bytes"
            ),
            "removed_inode_count": nonnegative_int(
                removed_inode_count, "removed inode count"
            ),
            "root_absent": root_absent,
            "outcome": outcome,
        }
        payload = {**seed, "progress_record_id": _record_id(seed)}
        path = directory / f"{sequence:06d}.json"
        return _write_checked(
            path,
            payload,
            lambda item: _validate_progress(item, self.project),
        )

    def complete(
        self,
        intent: dict[str, object],
        barrier: dict[str, object],
        *,
        deleted_at_seconds: int,
        completion_mode: str,
    ) -> dict[str, object]:
        intent = _validate_intent(intent, self.project)
        barrier = _validate_barrier(barrier, self.project)
        _require_attempt_match(intent, barrier)
        if completion_mode not in {"ordinary", "resumed", "root_absent_recovery"}:
            raise DeletionRecordError("deletion completion mode is unsupported")
        seed = {
            "schema": COMPLETION_SCHEMA,
            "project": self.project,
            "run_id": intent["run_id"],
            "phase": intent["phase"],
            "quarantine_record_id": intent["quarantine_record_id"],
            "deletion_intent_record_id": intent["intent_record_id"],
            "deletion_barrier_record_id": barrier["barrier_record_id"],
            "deleted_at_seconds": _timestamp(deleted_at_seconds, "deleted timestamp"),
            "measured_deleted_allocated_bytes": intent[
                "measured_target_allocated_bytes"
            ],
            "measured_deleted_inode_count": intent["measured_target_inode_count"],
            "completion_mode": completion_mode,
        }
        payload = {**seed, "completion_record_id": _record_id(seed)}
        return self._write("completion", payload)

    def finalize_tombstone(
        self,
        completion: dict[str, object],
        *,
        original_quarantined_at_seconds: int,
    ) -> dict[str, object]:
        completion = _validate_completion(completion, self.project)
        seed = {
            "schema": TOMBSTONE_SCHEMA,
            "project": self.project,
            "run_id": completion["run_id"],
            "phase": completion["phase"],
            "quarantine_record_id": completion["quarantine_record_id"],
            "deletion_completion_record_id": completion["completion_record_id"],
            "original_quarantined_at_seconds": _timestamp(
                original_quarantined_at_seconds, "original quarantine timestamp"
            ),
            "deleted_at_seconds": completion["deleted_at_seconds"],
            "retention_class": "deleted",
        }
        payload = {**seed, "tombstone_record_id": _record_id(seed)}
        return self._write("tombstone", payload)

    def record_restoration(
        self,
        intent: dict[str, object],
        *,
        restored_at_seconds: int,
        reason: str,
    ) -> dict[str, object]:
        intent = _validate_intent(intent, self.project)
        if reason not in {"report", "monitoring", "pin"}:
            raise DeletionRecordError("protected restoration reason is unsupported")
        seed = {
            "schema": RESTORATION_SCHEMA,
            "project": self.project,
            "run_id": intent["run_id"],
            "phase": intent["phase"],
            "quarantine_record_id": intent["quarantine_record_id"],
            "deletion_intent_record_id": intent["intent_record_id"],
            "restored_at_seconds": _timestamp(
                restored_at_seconds, "restored timestamp"
            ),
            "reason": reason,
        }
        payload = {**seed, "restoration_record_id": _record_id(seed)}
        return self._write("restoration", payload)

    def evidence(
        self, run_id: str, quarantine_record_id: str
    ) -> DeletionEvidence:
        return DeletionEvidence(
            self._read_optional("intent", run_id, quarantine_record_id),
            self._read_optional("barrier", run_id, quarantine_record_id),
            self._read_optional("completion", run_id, quarantine_record_id),
            self._read_optional("tombstone", run_id, quarantine_record_id),
            self._read_optional("restoration", run_id, quarantine_record_id),
        )

    def committed_authority(
        self,
        quarantine_record: dict[str, object],
        *,
        quarantine_root_present: bool,
    ) -> tuple[DeletionRecoveryState, DeletionEvidence]:
        """Return exact durable authority for an irreversible recovery state."""
        evidence = self.evidence(
            str(quarantine_record["run_id"]),
            str(quarantine_record["quarantine_record_id"]),
        )
        state = _classify_evidence(
            evidence, quarantine_root_present=quarantine_root_present
        )
        if state not in {
            DeletionRecoveryState.COMMITTED_DELETE_REQUIRED,
            DeletionRecoveryState.COMMITTED_ROOT_ABSENT_COMPLETION_REQUIRED,
            DeletionRecoveryState.COMPLETED_TOMBSTONE_REQUIRED,
            DeletionRecoveryState.DELETED_COMPLETE,
        }:
            raise DeletionRecordError(
                "durable committed deletion authority is unavailable"
            )
        if evidence.intent is None or evidence.barrier is None:
            raise DeletionRecordError("committed deletion records are incomplete")
        _require_quarantine_match(
            quarantine_record, evidence.intent, evidence.barrier
        )
        return state, evidence

    def registration_state(self, run_id: str) -> str | None:
        run_id = safe_run_id(run_id)
        try:
            for path in _matching_records(self.tombstone_root, run_id):
                tombstone = _validate_tombstone(
                    read_private_json(path), self.project
                )
                if tombstone["run_id"] == run_id:
                    return "deleted"
            for path in _matching_records(self.barrier_root, run_id):
                barrier = _validate_barrier(read_private_json(path), self.project)
                if barrier["run_id"] == run_id:
                    return "deletion_in_progress"
        except (OSError, PrivateJsonError, HygieneValidationError) as error:
            raise DeletionRecordError(
                "deletion registration authority is invalid"
            ) from error
        return None


def deletion_registration_state(
    scratch_root: Path, project: str, run_id: str
) -> str | None:
    """Read barrier/tombstone authority without creating deletion state."""
    root = Path(scratch_root) / ".deletions" / safe_run_id(project)
    if not root.exists() and not root.is_symlink():
        return None
    return DeletionRecordStore(
        scratch_root, project, create=False
    ).registration_state(run_id)


__all__ = ["DeletionRecordStore", "deletion_registration_state"]
