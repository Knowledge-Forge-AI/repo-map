"""Validation and state classification for deletion-record authority."""

from __future__ import annotations

from repomap_test_support.resource_deletion_record_persistence import (
    _record_id,
    _timestamp,
)
from repomap_test_support.resource_deletion_record_types import (
    BARRIER_SCHEMA,
    COMPLETION_SCHEMA,
    DeletionEvidence,
    DeletionRecordError,
    DeletionRecoveryState,
    INTENT_SCHEMA,
    MAX_TIMESTAMP_SECONDS,
    PROGRESS_SCHEMA,
    RESTORATION_SCHEMA,
    TOMBSTONE_SCHEMA,
)
from repomap_test_support.resource_index_records import owner_token, safe_run_id, safe_text
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    exact_object,
    nonnegative_int,
    sha256_hex,
)


def quarantine_ttl_elapsed(record: dict[str, object], *, now_seconds: int) -> bool:
    """Return v2 TTL eligibility without consulting filesystem timestamps."""
    from repomap_test_support.resource_quarantine_records import QUARANTINE_SCHEMA

    if record.get("schema") != QUARANTINE_SCHEMA:
        return False
    now = _timestamp(now_seconds, "current timestamp")
    quarantined = _timestamp(
        record.get("quarantined_at_seconds"), "quarantine timestamp"
    )
    ttl = nonnegative_int(record.get("quarantine_ttl_seconds"), "quarantine TTL")
    if ttl == 0 or quarantined > now or quarantined > MAX_TIMESTAMP_SECONDS - ttl:
        raise DeletionRecordError("quarantine TTL authority is invalid")
    return now >= quarantined + ttl


def _validate_intent(value: object, project: str) -> dict[str, object]:
    fields = {
        "schema", "project", "run_id", "phase", "quarantine_record_id",
        "quarantine_device", "quarantine_inode", "prepared_at_seconds",
        "maintenance_owner_token", "lifecycle_claim_record_id",
        "measured_target_allocated_bytes", "measured_target_inode_count",
        "intent_record_id",
    }
    return _validate_record(value, fields, INTENT_SCHEMA, "intent_record_id", project)


def _validate_barrier(value: object, project: str) -> dict[str, object]:
    fields = {
        "schema", "project", "run_id", "phase", "quarantine_record_id",
        "quarantine_device", "quarantine_inode", "deletion_intent_record_id",
        "maintenance_owner_token", "lifecycle_claim_record_id",
        "committed_at_seconds", "barrier_digest", "barrier_record_id",
    }
    payload = exact_object(value, fields, "deletion barrier")
    _validate_common(payload, BARRIER_SCHEMA, project)
    for field in ("quarantine_device", "quarantine_inode", "committed_at_seconds"):
        _timestamp(payload[field], field)
    for field in (
        "deletion_intent_record_id", "lifecycle_claim_record_id",
        "barrier_digest", "barrier_record_id",
    ):
        sha256_hex(payload[field], field)
    owner_token(payload["maintenance_owner_token"])
    seed = dict(payload)
    record_id = seed.pop("barrier_record_id")
    if _record_id(seed) != record_id:
        raise HygieneValidationError("deletion barrier integrity mismatch")
    digest_seed = dict(seed)
    digest = digest_seed.pop("barrier_digest")
    if _record_id(digest_seed) != digest:
        raise HygieneValidationError("deletion barrier digest mismatch")
    return payload


def _validate_progress(value: object, project: str) -> dict[str, object]:
    fields = {
        "schema", "project", "run_id", "quarantine_record_id",
        "deletion_barrier_record_id", "sequence", "recorded_at_seconds",
        "removed_allocated_bytes", "removed_inode_count", "root_absent",
        "outcome", "progress_record_id",
    }
    payload = _validate_record(
        value, fields, PROGRESS_SCHEMA, "progress_record_id", project
    )
    if type(payload["root_absent"]) is not bool:
        raise HygieneValidationError("deletion progress root absence is invalid")
    if payload["outcome"] not in {"deletion_in_progress", "root_absent"}:
        raise HygieneValidationError("deletion progress outcome is invalid")
    return payload


def _validate_completion(value: object, project: str) -> dict[str, object]:
    fields = {
        "schema", "project", "run_id", "phase", "quarantine_record_id",
        "deletion_intent_record_id", "deletion_barrier_record_id",
        "deleted_at_seconds", "measured_deleted_allocated_bytes",
        "measured_deleted_inode_count", "completion_mode",
        "completion_record_id",
    }
    payload = _validate_record(
        value, fields, COMPLETION_SCHEMA, "completion_record_id", project
    )
    if payload["completion_mode"] not in {
        "ordinary", "resumed", "root_absent_recovery"
    }:
        raise HygieneValidationError("deletion completion mode is invalid")
    return payload


def _validate_tombstone(value: object, project: str) -> dict[str, object]:
    fields = {
        "schema", "project", "run_id", "phase", "quarantine_record_id",
        "deletion_completion_record_id", "original_quarantined_at_seconds",
        "deleted_at_seconds", "retention_class", "tombstone_record_id",
    }
    payload = _validate_record(
        value, fields, TOMBSTONE_SCHEMA, "tombstone_record_id", project
    )
    if payload["retention_class"] != "deleted":
        raise HygieneValidationError("deleted tombstone retention class is invalid")
    return payload


def _validate_restoration(value: object, project: str) -> dict[str, object]:
    fields = {
        "schema", "project", "run_id", "phase", "quarantine_record_id",
        "deletion_intent_record_id", "restored_at_seconds", "reason",
        "restoration_record_id",
    }
    payload = _validate_record(
        value, fields, RESTORATION_SCHEMA, "restoration_record_id", project
    )
    if payload["reason"] not in {"report", "monitoring", "pin"}:
        raise HygieneValidationError("protected restoration reason is invalid")
    return payload


def _validate_record(
    value: object,
    fields: set[str],
    schema: str,
    id_field: str,
    project: str,
) -> dict[str, object]:
    payload = exact_object(value, fields, schema)
    _validate_common(payload, schema, project)
    for field, item in payload.items():
        if field.endswith("_seconds") or field in {
            "quarantine_device", "quarantine_inode", "sequence",
            "measured_target_allocated_bytes", "measured_target_inode_count",
            "removed_allocated_bytes", "removed_inode_count",
            "measured_deleted_allocated_bytes", "measured_deleted_inode_count",
        }:
            _timestamp(item, field)
        elif field.endswith("_record_id"):
            sha256_hex(item, field)
    if "maintenance_owner_token" in payload:
        owner_token(payload["maintenance_owner_token"])
    seed = dict(payload)
    record_id = seed.pop(id_field)
    if _record_id(seed) != record_id:
        raise HygieneValidationError("deletion record integrity mismatch")
    return payload


def _validate_common(payload: dict[str, object], schema: str, project: str) -> None:
    if payload["schema"] != schema or payload["project"] != project:
        raise HygieneValidationError("deletion record identity is unsupported")
    safe_run_id(payload["run_id"])
    if "phase" in payload:
        safe_text(payload["phase"], "phase")
    sha256_hex(payload["quarantine_record_id"], "quarantine record id")


def _require_attempt_match(
    intent: dict[str, object], barrier: dict[str, object]
) -> None:
    if any(
        barrier[field] != intent[field]
        for field in (
            "project", "run_id", "phase", "quarantine_record_id",
            "quarantine_device", "quarantine_inode",
        )
    ) or barrier["deletion_intent_record_id"] != intent["intent_record_id"]:
        raise DeletionRecordError("deletion attempt records conflict")


def _require_quarantine_match(
    quarantine_record: dict[str, object],
    intent: dict[str, object],
    barrier: dict[str, object],
) -> None:
    _require_attempt_match(intent, barrier)
    if any(
        quarantine_record.get(field) != intent[field]
        for field in (
            "project", "run_id", "phase", "quarantine_record_id",
            "quarantine_device", "quarantine_inode",
        )
    ):
        raise DeletionRecordError(
            "committed deletion does not match its quarantine record"
        )


def _classify_evidence(
    evidence: DeletionEvidence, *, quarantine_root_present: bool
) -> DeletionRecoveryState:
    if _evidence_links_conflict(evidence):
        return DeletionRecoveryState.AMBIGUOUS_EVIDENCE_CONFLICT
    present = tuple(
        item is not None
        for item in (
            evidence.intent,
            evidence.barrier,
            evidence.completion,
            evidence.tombstone,
            evidence.restoration,
        )
    )
    intent, barrier, completion, tombstone, restoration = present
    if restoration:
        if barrier or completion or tombstone or quarantine_root_present:
            return DeletionRecoveryState.AMBIGUOUS_EVIDENCE_CONFLICT
        return DeletionRecoveryState.PROTECTED_RESTORED
    if tombstone:
        if quarantine_root_present or not (intent and barrier and completion):
            return DeletionRecoveryState.AMBIGUOUS_EVIDENCE_CONFLICT
        return DeletionRecoveryState.DELETED_COMPLETE
    if completion:
        if quarantine_root_present or not (intent and barrier):
            return DeletionRecoveryState.AMBIGUOUS_EVIDENCE_CONFLICT
        return DeletionRecoveryState.COMPLETED_TOMBSTONE_REQUIRED
    if barrier:
        if not intent:
            return DeletionRecoveryState.AMBIGUOUS_EVIDENCE_CONFLICT
        return (
            DeletionRecoveryState.COMMITTED_DELETE_REQUIRED
            if quarantine_root_present
            else DeletionRecoveryState.COMMITTED_ROOT_ABSENT_COMPLETION_REQUIRED
        )
    if intent:
        return (
            DeletionRecoveryState.PREPARED_REVALIDATION_REQUIRED
            if quarantine_root_present
            else DeletionRecoveryState.AMBIGUOUS_EVIDENCE_CONFLICT
        )
    return (
        DeletionRecoveryState.NO_DELETION
        if quarantine_root_present
        else DeletionRecoveryState.AMBIGUOUS_EVIDENCE_CONFLICT
    )


def _evidence_links_conflict(evidence: DeletionEvidence) -> bool:
    intent = evidence.intent
    barrier = evidence.barrier
    completion = evidence.completion
    tombstone = evidence.tombstone
    restoration = evidence.restoration
    if intent is not None and barrier is not None:
        try:
            _require_attempt_match(intent, barrier)
        except DeletionRecordError:
            return True
    if completion is not None:
        if intent is not None and any(
            completion[field] != intent[field]
            for field in ("project", "run_id", "phase", "quarantine_record_id")
        ):
            return True
        if intent is not None and (
            completion["deletion_intent_record_id"] != intent["intent_record_id"]
        ):
            return True
        if barrier is not None and (
            completion["deletion_barrier_record_id"] != barrier["barrier_record_id"]
        ):
            return True
    if tombstone is not None and completion is not None:
        if any(
            tombstone[field] != completion[field]
            for field in ("project", "run_id", "phase", "quarantine_record_id")
        ) or (
            tombstone["deletion_completion_record_id"]
            != completion["completion_record_id"]
        ):
            return True
    if restoration is not None and intent is not None:
        if any(
            restoration[field] != intent[field]
            for field in ("project", "run_id", "phase", "quarantine_record_id")
        ) or (
            restoration["deletion_intent_record_id"] != intent["intent_record_id"]
        ):
            return True
    return False


__all__ = [
    "_classify_evidence",
    "_evidence_links_conflict",
    "_require_attempt_match",
    "_require_quarantine_match",
    "_validate_barrier",
    "_validate_completion",
    "_validate_intent",
    "_validate_progress",
    "_validate_restoration",
    "_validate_tombstone",
    "quarantine_ttl_elapsed",
]
