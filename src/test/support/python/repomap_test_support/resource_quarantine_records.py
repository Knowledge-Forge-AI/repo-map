"""Quarantine record integrity, reversible restore, and interruption recovery."""

from __future__ import annotations

from pathlib import Path

from repomap_test_support.resource_atomic_rename import (
    AtomicRenameCollision,
    AtomicRenameError,
    atomic_rename_no_replace,
)
from repomap_test_support.resource_gc_ledger import GcLedger
from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_lifecycle_claim import (
    ClaimError,
    ClaimHandle,
    ClaimPurpose,
    ClaimRegistry,
    MaintenanceHandle,
)
from repomap_test_support.resource_retention import RetentionClass
from repomap_test_support.resource_scratch_history import HistoricalGcCandidate
from repomap_test_support.resource_validation import HygieneValidationError


QUARANTINE_SCHEMA_V1 = "repomap-test-quarantine-record-v1"
QUARANTINE_SCHEMA = "repomap-test-quarantine-record-v2"
QUARANTINE_TTL_SECONDS = 7 * 86_400


class QuarantineError(RuntimeError):
    """A historical candidate cannot be quarantined or restored exactly."""


def write_quarantine_record(
    ledger: GcLedger,
    candidate: HistoricalGcCandidate,
    *,
    claim_record_id: str,
    pass_id: str,
    quarantined_at_seconds: int,
    quarantine_device: int,
    quarantine_inode: int,
    completion_record_id: str,
    intent_record_id: str | None = None,
    finalization_mode: str = "ordinary",
    append_ledger_event: bool = True,
) -> dict[str, object]:
    intent_id = intent_record_id or _intent_for_completion(
        ledger.records(), completion_record_id
    )
    seed = {
        "schema": QUARANTINE_SCHEMA,
        "project": "repo-map_dev",
        "run_id": candidate.run_id,
        "phase": candidate.phase,
        "retention_class": RetentionClass.QUARANTINED_OR_REVALIDATION_PENDING.value,
        "quarantined_at_seconds": quarantined_at_seconds,
        "quarantine_ttl_seconds": QUARANTINE_TTL_SECONDS,
        "original_device": candidate.device,
        "original_inode": candidate.inode,
        "quarantine_device": quarantine_device,
        "quarantine_inode": quarantine_inode,
        "original_location_token": "managed-run-root",
        "gc_pass_id": pass_id,
        "claim_record_id": claim_record_id,
        "rename_intent_record_id": intent_id,
        "rename_completion_or_recovery_record_id": completion_record_id,
        "finalization_mode": finalization_mode,
    }
    record_id = _record_id(seed)
    payload = {**seed, "quarantine_record_id": record_id}
    write_private_json_exclusive(
        ledger.quarantine_record_path(candidate.run_id), payload
    )
    if append_ledger_event:
        ledger.append(
            "quarantine_record",
            {"run_id": candidate.run_id, "quarantine_record_id": record_id},
            now_seconds=quarantined_at_seconds,
        )
    return payload


def restore_quarantined(
    scratch_root: Path,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    ledger: GcLedger,
    run_id: str,
    *,
    now_seconds: int,
    before_rename=None,
    claim_handle: ClaimHandle | None = None,
    after_rename=None,
) -> Path:
    registry.require_maintenance(maintenance)
    record = read_quarantine_record(ledger.quarantine_record_path(run_id))
    if record["run_id"] != run_id or record["project"] != registry.project:
        raise QuarantineError("quarantine record owner is invalid")
    if not _ledger_finalized(ledger.records(), run_id, str(record["quarantine_record_id"])):
        raise QuarantineError("quarantine ledger finalization is missing")
    source = Path(scratch_root) / ".quarantine" / registry.project / run_id
    destination = Path(scratch_root) / "r" / run_id
    owns_claim = claim_handle is None
    claim = claim_handle or registry.acquire(
        run_id, ClaimPurpose.MAINTENANCE_RECOVERY, now_seconds=now_seconds
    )
    if claim.run_id != run_id:
        raise QuarantineError("restore lifecycle claim identity is invalid")
    registry.require_claim(claim)
    try:
        metadata = source.stat(follow_symlinks=False)
        if source.is_symlink() or (metadata.st_dev, metadata.st_ino) != (
            record["quarantine_device"], record["quarantine_inode"]
        ):
            raise QuarantineError("quarantine identity is invalid")
        intent = ledger.append(
            "restore_intent",
            {"run_id": run_id, "quarantine_record_id": record["quarantine_record_id"]},
            now_seconds=now_seconds,
        )
        if before_rename is not None:
            before_rename()
        try:
            result = atomic_rename_no_replace(
                source,
                destination,
                require_private_destination_parent=False,
            )
        except AtomicRenameCollision as error:
            _append_once(
                ledger,
                "restore_collision",
                {"run_id": run_id, "intent_record_id": intent.record_id},
                now_seconds,
            )
            raise QuarantineError("restore destination collision") from error
        except AtomicRenameError as error:
            raise QuarantineError("restore atomic no-replace rename failed") from error
        if (result.destination_device, result.destination_inode) != (
            record["original_device"], record["original_inode"]
        ):
            raise QuarantineError("restore identity readback failed")
        completion = ledger.append(
            "restore_completion",
            {"run_id": run_id, "intent_record_id": intent.record_id},
            now_seconds=now_seconds,
        )
        if after_rename is not None:
            after_rename()
        _remove_completed_restore_record(
            ledger.quarantine_record_path(run_id),
            record,
            completion,
            intent,
        )
    except BaseException as error:
        if owns_claim:
            try:
                registry.release(claim)
            except ClaimError as release_error:
                error.add_note(f"lifecycle claim release also failed: {release_error}")
        raise
    if owns_claim:
        registry.release(claim)
    return destination


def recover_interrupted_renames(
    scratch_root: Path,
    registry: ClaimRegistry,
    maintenance: MaintenanceHandle,
    ledger: GcLedger,
    *,
    now_seconds: int,
) -> dict[str, int]:
    registry.require_maintenance(maintenance)
    records = ledger.records()
    counts = _empty_recovery_counts()
    intents = [record for record in records if record.event == "rename_intent"]
    for intent in intents:
        _recover_intent(
            Path(scratch_root), registry, ledger, intent, records, counts, now_seconds
        )
        records = ledger.records()
    _classify_unrecorded_quarantine(
        Path(scratch_root), registry, ledger, intents, records, counts, now_seconds
    )
    counts["source_only"] = counts["no_mutation"]
    counts["quarantine_only"] = (
        counts["quarantined_complete"]
        + counts["quarantined_needs_record_finalization"]
        + counts["quarantined_needs_ledger_finalization"]
    )
    counts["ambiguous"] = (
        counts["ambiguous_both_present"]
        + counts["ambiguous_neither_present"]
        + counts["ambiguous_evidence_conflict"]
    )
    return counts


def read_quarantine_record(path: Path) -> dict[str, object]:
    try:
        raw = read_private_json(path)
        schema = raw.get("schema")
        if schema == QUARANTINE_SCHEMA_V1:
            payload = _read_v1(raw)
        elif schema == QUARANTINE_SCHEMA:
            payload = _read_v2(raw)
        else:
            raise HygieneValidationError("unsupported quarantine record schema")
        _validate_common_record(payload)
        seed = dict(payload)
        record_id = seed.pop("quarantine_record_id")
        if _record_id(seed) != record_id:
            raise HygieneValidationError("quarantine record integrity mismatch")
        return payload
    except (OSError, PrivateJsonError, HygieneValidationError) as error:
        raise QuarantineError("quarantine record is invalid") from error


from repomap_test_support.resource_quarantine_records_recovery import (
    _append_once,
    _ambiguous as _ambiguous,
    _classify_unrecorded_quarantine,
    _completion_for_intent as _completion_for_intent,
    _empty_recovery_counts,
    _finalization_record as _finalization_record,
    _intent_for_completion,
    _ledger_finalized,
    _record_matches_intent as _record_matches_intent,
    _recover_intent,
    _recovery_candidate as _recovery_candidate,
    _remove_completed_restore_record,
    _restore_completion_for_intent as _restore_completion_for_intent,
    _restore_intent_for_record as _restore_intent_for_record,
)
from repomap_test_support.resource_quarantine_records_validation import (
    _read_v1,
    _read_v2,
    _record_id,
    _validate_common_record,
)


__all__ = [
    "QUARANTINE_SCHEMA",
    "QUARANTINE_SCHEMA_V1",
    "QUARANTINE_TTL_SECONDS",
    "QuarantineError",
    "read_quarantine_record",
    "recover_interrupted_renames",
    "restore_quarantined",
    "write_quarantine_record",
]
