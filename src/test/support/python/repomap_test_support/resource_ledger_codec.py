"""Payload serialization, deserialization, and structural validation for resource ledgers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from repomap_test_support.resource_ledger_records import (
    CHECKPOINT_FIELDS,
    CHECKPOINT_INTEGER_FIELDS,
    FACTS,
    CleanupResult,
    FinalPresence,
    LEDGER_SCHEMA,
    LedgerLifecycle,
    ResourceKind,
    ResourceLedgerError,
    ResourceRecord,
    RetainedReason,
    RunIdentity,
    validate_record,
)
from repomap_test_support.resource_retention import (
    RetentionClass,
    TerminalOutcome,
    create_terminal_stamp,
)
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    bounded_string,
    closed_enum,
    exact_array,
    exact_bool,
    exact_object,
    nonnegative_int,
)


@dataclass(frozen=True)
class DecodedLedgerPayload:
    identity: RunIdentity
    created_at_seconds: int
    records: tuple[ResourceRecord, ...]
    checkpoints: tuple[dict[str, Any], ...]
    facts: dict[str, bool]
    lifecycle: LedgerLifecycle


def record_to_payload(record: ResourceRecord) -> dict[str, Any]:
    payload = asdict(record)
    for field in ("kind", "cleanup_result", "retained_reason", "final_presence"):
        payload[field] = getattr(record, field).value
    return payload


def record_from_payload(
    payload: Any,
    *,
    validate: bool = True,
) -> ResourceRecord:
    keys = set(ResourceRecord.__dataclass_fields__)
    values = exact_object(payload, keys, "resource record")
    record = ResourceRecord(
        kind=closed_enum(ResourceKind, values["kind"], "resource kind"),
        identity=bounded_string(values["identity"], "resource identity", 4096),
        creation_owner=bounded_string(values["creation_owner"], "creation owner"),
        created_before_run=exact_bool(values["created_before_run"], "created_before_run"),
        creation_observed=exact_bool(values["creation_observed"], "creation_observed"),
        cleanup_required=exact_bool(values["cleanup_required"], "cleanup_required"),
        cleanup_attempted=exact_bool(values["cleanup_attempted"], "cleanup_attempted"),
        cleanup_result=closed_enum(CleanupResult, values["cleanup_result"], "cleanup result"),
        retained=exact_bool(values["retained"], "retained"),
        retained_reason=closed_enum(RetainedReason, values["retained_reason"], "retained reason"),
        final_presence=closed_enum(FinalPresence, values["final_presence"], "final presence"),
        size_bytes=nonnegative_int(values["size_bytes"], "size_bytes"),
        inode_count=nonnegative_int(values["inode_count"], "inode_count"),
    )
    if validate:
        validate_record(record)
    return record


def checkpoint_from_payload(payload: Any) -> dict[str, Any]:
    values = exact_object(payload, set(CHECKPOINT_FIELDS) | {"label"}, "checkpoint")
    bounded_string(values["label"], "checkpoint label", 64)
    for key in CHECKPOINT_INTEGER_FIELDS:
        nonnegative_int(values[key], key)
    bounded_string(values["largest_owned_subtree_category"], "largest subtree category", 64)
    return dict(values)


def facts_from_payload(payload: Any) -> dict[str, bool]:
    if type(payload) is not dict or not set(payload) <= set(FACTS):
        raise HygieneValidationError("invalid ledger facts")
    return {name: exact_bool(value, name) for name, value in payload.items()}


def identity_to_payload(identity: RunIdentity) -> dict[str, Any]:
    return asdict(identity)


def identity_from_payload(payload: Any) -> RunIdentity:
    values = exact_object(payload, {"project", "phase", "run_id"}, "run identity")
    return RunIdentity(values["project"], values["phase"], values["run_id"])


def lifecycle_to_payload(lifecycle: LedgerLifecycle) -> dict[str, Any]:
    return {
        "retention_class": lifecycle.retention_class.value,
        "terminal_outcome": (
            lifecycle.terminal_outcome.value if lifecycle.terminal_outcome else None
        ),
        "terminal_at_seconds": lifecycle.terminal_at_seconds,
    }


def lifecycle_from_payload(payload: Any) -> LedgerLifecycle:
    values = exact_object(
        payload,
        {"retention_class", "terminal_outcome", "terminal_at_seconds"},
        "ledger lifecycle",
    )
    retention = closed_enum(RetentionClass, values["retention_class"], "retention class")
    outcome = values["terminal_outcome"]
    terminal = values["terminal_at_seconds"]
    if outcome is None and terminal is None and retention is RetentionClass.ACTIVE:
        return LedgerLifecycle()
    if outcome is None or terminal is None:
        raise HygieneValidationError("invalid terminal lifecycle")
    return LedgerLifecycle(
        retention,
        closed_enum(TerminalOutcome, outcome, "terminal outcome"),
        nonnegative_int(terminal, "terminal timestamp"),
    )


def validate_lifecycle(
    records: Sequence[ResourceRecord],
    lifecycle: LedgerLifecycle,
) -> None:
    if lifecycle.terminal_outcome is None:
        return
    if lifecycle.terminal_at_seconds is None:
        raise HygieneValidationError("terminal lifecycle lacks a timestamp")
    report_source_pending = any(
        record.retained and record.retained_reason is RetainedReason.REPORT_SOURCE
        for record in records
    )
    expected = create_terminal_stamp(
        lifecycle.terminal_outcome,
        lifecycle.terminal_at_seconds,
        report_source_pending=report_source_pending,
    )
    if lifecycle.retention_class is not expected.retention_class:
        raise HygieneValidationError("terminal lifecycle retention is inconsistent")


def encode_ledger_payload(
    *,
    identity: RunIdentity,
    created_at_seconds: int,
    records: Sequence[ResourceRecord],
    checkpoints: Sequence[dict[str, Any]],
    facts: dict[str, bool],
    lifecycle: LedgerLifecycle,
    record_encoder: Callable[[ResourceRecord], dict[str, Any]] = record_to_payload,
    lifecycle_encoder: Callable[[LedgerLifecycle], dict[str, Any]] = lifecycle_to_payload,
) -> dict[str, Any]:
    return {
        "schema": LEDGER_SCHEMA,
        "identity": asdict(identity),
        "created_at_seconds": created_at_seconds,
        "resources": [record_encoder(item) for item in records],
        "checkpoints": list(checkpoints),
        "facts": dict(facts),
        "lifecycle": lifecycle_encoder(lifecycle),
    }


def decode_ledger_payload(
    payload: Any,
    expected_identity: RunIdentity,
    *,
    record_decoder: Callable[[Any], ResourceRecord] = record_from_payload,
    checkpoint_decoder: Callable[[Any], dict[str, Any]] = checkpoint_from_payload,
    facts_decoder: Callable[[Any], dict[str, bool]] = facts_from_payload,
    identity_decoder: Callable[[Any], RunIdentity] = identity_from_payload,
    lifecycle_decoder: Callable[[Any], LedgerLifecycle] = lifecycle_from_payload,
    lifecycle_validator: Callable[[tuple[ResourceRecord, ...], LedgerLifecycle], None] = validate_lifecycle,
) -> DecodedLedgerPayload:
    if not isinstance(payload, dict) or payload.get("schema") != LEDGER_SCHEMA:
        raise ResourceLedgerError(
            "resource ledger schema is unsupported; legacy evidence is ambiguous"
        )
    payload = exact_object(
        payload,
        {
            "schema",
            "identity",
            "created_at_seconds",
            "resources",
            "checkpoints",
            "facts",
            "lifecycle",
        },
        "resource ledger",
    )
    loaded_identity = identity_decoder(payload["identity"])
    if loaded_identity != expected_identity:
        raise ResourceLedgerError("resource ledger belongs to another run")
    created = nonnegative_int(payload["created_at_seconds"], "ledger creation timestamp")
    records = tuple(
        record_decoder(item)
        for item in exact_array(payload["resources"], "resources")
    )
    if len({(record.kind, record.identity) for record in records}) != len(records):
        raise HygieneValidationError("duplicate resource identities")
    checkpoints = tuple(
        checkpoint_decoder(item)
        for item in exact_array(payload["checkpoints"], "checkpoints")
    )
    facts = facts_decoder(payload["facts"])
    lifecycle = lifecycle_decoder(payload["lifecycle"])
    lifecycle_validator(records, lifecycle)
    return DecodedLedgerPayload(
        identity=loaded_identity,
        created_at_seconds=created,
        records=records,
        checkpoints=checkpoints,
        facts=facts,
        lifecycle=lifecycle,
    )


__all__ = [
    "DecodedLedgerPayload",
    "checkpoint_from_payload",
    "decode_ledger_payload",
    "encode_ledger_payload",
    "facts_from_payload",
    "identity_from_payload",
    "identity_to_payload",
    "lifecycle_from_payload",
    "lifecycle_to_payload",
    "record_from_payload",
    "record_to_payload",
    "validate_lifecycle",
]
