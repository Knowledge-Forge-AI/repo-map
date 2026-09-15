"""Recovery authority queries for the deletion-record store."""

from __future__ import annotations

import os
from pathlib import Path

from repomap_test_support.resource_deletion_record_persistence import read_private_json
from repomap_test_support.resource_deletion_record_types import (
    DeletionRecordError,
    DeletionRecoveryState,
    MAX_TOMBSTONE_RECOVERY_RECORDS,
    _DeletionRecordStoreProtocol,
)
from repomap_test_support.resource_deletion_record_validation import (
    _classify_evidence,
    _validate_tombstone,
)
from repomap_test_support.resource_index_records import safe_text
from repomap_test_support.resource_ledger_io import PrivateJsonError
from repomap_test_support.resource_validation import HygieneValidationError, sha256_hex

class _DeletionRecordAuthorityMixin(_DeletionRecordStoreProtocol):
    def validated_tombstones(
        self,
        *,
        limit: int = MAX_TOMBSTONE_RECOVERY_RECORDS,
    ) -> tuple[dict[str, object], ...]:
        """Return a bounded, validated snapshot of deleted-run authority."""
        if (
            type(limit) is not int
            or limit < 1
            or limit > MAX_TOMBSTONE_RECOVERY_RECORDS
        ):
            raise DeletionRecordError("tombstone recovery limit is invalid")
        records: list[dict[str, object]] = []
        try:
            with os.scandir(self.tombstone_root) as entries:
                for entry in entries:
                    if len(records) >= limit:
                        raise DeletionRecordError(
                            "tombstone recovery record limit exceeded"
                        )
                    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                        raise DeletionRecordError(
                            "tombstone record identity is unsafe"
                        )
                    payload = _validate_tombstone(
                        read_private_json(Path(entry.path)),
                        self.project,
                    )
                    expected = (
                        f"{self._key(str(payload['run_id']), str(payload['quarantine_record_id']))}.json"
                    )
                    if entry.name != expected:
                        raise DeletionRecordError(
                            "tombstone record filename is inconsistent"
                        )
                    records.append(payload)
        except DeletionRecordError:
            raise
        except (OSError, PrivateJsonError, HygieneValidationError) as error:
            raise DeletionRecordError(
                "tombstone recovery authority is invalid"
            ) from error
        return tuple(
            sorted(
                records,
                key=lambda item: (item["run_id"], item["quarantine_record_id"]),
            )
        )

    def validate_deleted_authority(
        self,
        *,
        run_id: str,
        phase: str,
        quarantine_record_id: str,
        deletion_completion_record_id: str,
        tombstone_record_id: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Validate completion and tombstone authority for reconciliation."""
        evidence = self.evidence(run_id, quarantine_record_id)
        if (
            evidence.completion is None
            or evidence.tombstone is None
            or _classify_evidence(evidence, quarantine_root_present=False)
            is not DeletionRecoveryState.DELETED_COMPLETE
        ):
            raise DeletionRecordError(
                "deleted reconciliation authority is incomplete"
            )
        completion = evidence.completion
        tombstone = evidence.tombstone
        if (
            completion["phase"] != safe_text(phase, "phase")
            or completion["completion_record_id"]
            != sha256_hex(
                deletion_completion_record_id,
                "deletion completion record id",
            )
            or tombstone["tombstone_record_id"]
            != sha256_hex(tombstone_record_id, "tombstone record id")
            or tombstone["deletion_completion_record_id"]
            != completion["completion_record_id"]
        ):
            raise DeletionRecordError("deleted reconciliation authority changed")
        return completion, tombstone

    def classify(
        self,
        run_id: str,
        quarantine_record_id: str,
        *,
        quarantine_root_present: bool,
    ) -> DeletionRecoveryState:
        evidence = self.evidence(run_id, quarantine_record_id)
        return _classify_evidence(
            evidence, quarantine_root_present=quarantine_root_present
        )


__all__ = ["_DeletionRecordAuthorityMixin"]
