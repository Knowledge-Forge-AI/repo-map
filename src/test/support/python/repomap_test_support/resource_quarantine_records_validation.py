"""Schema validation helpers for quarantine records."""

from __future__ import annotations

import hashlib
import json

from repomap_test_support.resource_retention import RetentionClass
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    exact_object,
    nonnegative_int,
    sha256_hex,
)


def _owner():
    from repomap_test_support import resource_quarantine_records

    return resource_quarantine_records


def _read_v1(raw: dict[str, object]) -> dict[str, object]:
    return exact_object(
        raw,
        {
            "schema", "project", "run_id", "phase", "retention_class",
            "quarantined_at_seconds", "quarantine_ttl_seconds", "original_device",
            "original_inode", "quarantine_device", "quarantine_inode",
            "original_location_token", "gc_pass_id", "claim_record_id",
            "completion_record_id", "quarantine_record_id",
        },
        "quarantine record v1",
    )


def _read_v2(raw: dict[str, object]) -> dict[str, object]:
    payload = exact_object(
        raw,
        {
            "schema", "project", "run_id", "phase", "retention_class",
            "quarantined_at_seconds", "quarantine_ttl_seconds", "original_device",
            "original_inode", "quarantine_device", "quarantine_inode",
            "original_location_token", "gc_pass_id", "claim_record_id",
            "rename_intent_record_id", "rename_completion_or_recovery_record_id",
            "finalization_mode", "quarantine_record_id",
        },
        "quarantine record v2",
    )
    sha256_hex(payload["rename_intent_record_id"], "intent record id")
    sha256_hex(
        payload["rename_completion_or_recovery_record_id"],
        "completion or recovery record id",
    )
    if payload["finalization_mode"] not in {
        "ordinary",
        "recovered_before_rename_completion",
        "recovered_after_rename_completion",
    }:
        raise HygieneValidationError("quarantine finalization mode is invalid")
    return payload


def _validate_common_record(payload: dict[str, object]) -> None:
    owner = _owner()
    if payload["retention_class"] != RetentionClass.QUARANTINED_OR_REVALIDATION_PENDING.value:
        raise HygieneValidationError("quarantine retention class is invalid")
    if payload["quarantine_ttl_seconds"] != owner.QUARANTINE_TTL_SECONDS:
        raise HygieneValidationError("quarantine TTL is invalid")
    for field in (
        "quarantined_at_seconds", "original_device", "original_inode",
        "quarantine_device", "quarantine_inode",
    ):
        nonnegative_int(payload[field], field)
    for field in ("claim_record_id", "quarantine_record_id"):
        sha256_hex(payload[field], field)
    if payload["schema"] == owner.QUARANTINE_SCHEMA_V1:
        sha256_hex(payload["completion_record_id"], "completion record id")


def _record_id(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
