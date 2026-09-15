"""Closed schemas and validation for immutable advisory-index evidence."""

from __future__ import annotations

import re
from typing import Any

from repomap_test_support.resource_hygiene_policy import HygieneProfile
from repomap_test_support.resource_retention import RetentionClass, TerminalOutcome
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    bounded_string,
    exact_object,
    nonnegative_int,
    sha256_hex,
)


SUMMARY_SCHEMA = "repomap-test-hygiene-index-summary-v2"
BOOTSTRAP_SCHEMA = "repomap-test-hygiene-index-bootstrap-v1"
INVENTORY_SCHEMA = "repomap-test-hygiene-index-inventory-v1"
RECOVERY_INVENTORY_SCHEMA = "repomap-test-hygiene-index-recovery-inventory-v2"
INVENTORY_MEMBERSHIP_SCHEMA = "repomap-test-hygiene-index-inventory-v2"
RECOVERY_INVENTORY_MEMBERSHIP_SCHEMA = (
    "repomap-test-hygiene-index-recovery-inventory-v3"
)
ADMISSION_SCHEMA = "repomap-test-hygiene-admission-v2"
CLOSE_SCHEMA = "repomap-test-hygiene-close-v2"
LOCK_SCHEMA = "repomap-test-hygiene-admission-lock-v1"
INITIALIZATION_MODES = frozenset({"safe_empty_bootstrap", "maintenance_inventory"})
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OWNER_TOKEN = re.compile(r"^[0-9a-f]{32,64}$")


def validate_summary(payload: Any) -> dict[str, Any]:
    payload = exact_object(
        payload,
        {
            "schema",
            "scratch_filesystem_id",
            "generation",
            "initialization_mode",
            "inventory_at_seconds",
            "provenance_record_id",
            "allocated_bytes",
            "inode_count",
        },
        "index summary",
    )
    if payload["schema"] != SUMMARY_SCHEMA:
        raise HygieneValidationError("unsupported index summary schema")
    sha256_hex(payload["scratch_filesystem_id"], "scratch filesystem identity")
    nonnegative_int(payload["generation"], "generation")
    if payload["initialization_mode"] not in INITIALIZATION_MODES:
        raise HygieneValidationError("unsupported index initialization mode")
    nonnegative_int(payload["inventory_at_seconds"], "inventory timestamp")
    sha256_hex(payload["provenance_record_id"], "provenance record id")
    nonnegative_int(payload["allocated_bytes"], "allocated_bytes")
    nonnegative_int(payload["inode_count"], "inode_count")
    return payload


def validate_bootstrap(payload: Any) -> dict[str, Any]:
    payload = exact_object(
        payload,
        {
            "schema",
            "scratch_filesystem_id",
            "initialization_mode",
            "inventory_at_seconds",
            "population_entry_count",
            "requesting_run_id",
            "provenance_record_id",
        },
        "index bootstrap record",
    )
    if payload["schema"] != BOOTSTRAP_SCHEMA:
        raise HygieneValidationError("unsupported bootstrap schema")
    sha256_hex(payload["scratch_filesystem_id"], "scratch filesystem identity")
    if payload["initialization_mode"] != "safe_empty_bootstrap":
        raise HygieneValidationError("unsupported bootstrap mode")
    nonnegative_int(payload["inventory_at_seconds"], "inventory timestamp")
    count = nonnegative_int(payload["population_entry_count"], "population count")
    requesting = payload["requesting_run_id"]
    if requesting is not None:
        safe_run_id(requesting)
    if count not in {0, 1} or (count == 1 and requesting is None):
        raise HygieneValidationError("bootstrap population proof is invalid")
    sha256_hex(payload["provenance_record_id"], "provenance record id")
    return payload


def validate_inventory(payload: Any) -> dict[str, Any]:
    payload = exact_object(
        payload,
        {
            "schema", "scratch_filesystem_id", "initialization_mode",
            "inventory_at_seconds", "allocated_bytes", "inode_count",
            "provenance_record_id",
        },
        "maintenance inventory record",
    )
    if payload["schema"] != INVENTORY_SCHEMA:
        raise HygieneValidationError("unsupported maintenance inventory schema")
    sha256_hex(payload["scratch_filesystem_id"], "scratch filesystem identity")
    if payload["initialization_mode"] != "maintenance_inventory":
        raise HygieneValidationError("unsupported maintenance inventory mode")
    nonnegative_int(payload["inventory_at_seconds"], "inventory timestamp")
    nonnegative_int(payload["allocated_bytes"], "allocated_bytes")
    nonnegative_int(payload["inode_count"], "inode_count")
    sha256_hex(payload["provenance_record_id"], "provenance record id")
    return payload


def validate_recovery_inventory(payload: Any) -> dict[str, Any]:
    payload = exact_object(
        payload,
        {
            "schema", "scratch_filesystem_id", "initialization_mode",
            "inventory_at_seconds", "allocated_bytes", "inode_count",
            "population_entry_count", "valid_run_count", "ambiguous_run_count",
            "internal_unsafe_link_count", "recovery_record_id",
            "generation_basis", "prior_generation", "provenance_record_id",
        },
        "recovery inventory record",
    )
    if payload["schema"] != RECOVERY_INVENTORY_SCHEMA:
        raise HygieneValidationError("unsupported recovery inventory schema")
    sha256_hex(payload["scratch_filesystem_id"], "scratch filesystem identity")
    if payload["initialization_mode"] != "maintenance_inventory":
        raise HygieneValidationError("unsupported recovery inventory mode")
    nonnegative_int(payload["inventory_at_seconds"], "inventory timestamp")
    nonnegative_int(payload["allocated_bytes"], "allocated_bytes")
    nonnegative_int(payload["inode_count"], "inode_count")
    population = nonnegative_int(
        payload["population_entry_count"], "population count"
    )
    valid = nonnegative_int(payload["valid_run_count"], "valid run count")
    ambiguous = nonnegative_int(
        payload["ambiguous_run_count"], "ambiguous run count"
    )
    if valid + ambiguous != population:
        raise HygieneValidationError("recovery population counts do not reconcile")
    nonnegative_int(
        payload["internal_unsafe_link_count"], "internal unsafe link count"
    )
    sha256_hex(payload["recovery_record_id"], "recovery record id")
    if payload["generation_basis"] not in {
        "preserved_increment", "recovery_epoch"
    }:
        raise HygieneValidationError("unsupported recovery generation basis")
    prior = payload["prior_generation"]
    if payload["generation_basis"] == "preserved_increment":
        nonnegative_int(prior, "prior generation")
    elif prior is not None:
        raise HygieneValidationError("recovery epoch cannot claim prior generation")
    sha256_hex(payload["provenance_record_id"], "provenance record id")
    return payload


def validate_inventory_membership(payload: Any) -> dict[str, Any]:
    payload = exact_object(
        payload,
        {
            "schema", "scratch_filesystem_id", "initialization_mode",
            "inventory_at_seconds", "allocated_bytes", "inode_count",
            "measured_run_entries", "provenance_record_id",
        },
        "maintenance membership inventory record",
    )
    if payload["schema"] != INVENTORY_MEMBERSHIP_SCHEMA:
        raise HygieneValidationError("unsupported maintenance inventory schema")
    _validate_inventory_common(payload)
    _validate_measured_run_entries(payload["measured_run_entries"])
    sha256_hex(payload["provenance_record_id"], "provenance record id")
    return payload


def validate_recovery_inventory_membership(payload: Any) -> dict[str, Any]:
    payload = exact_object(
        payload,
        {
            "schema", "scratch_filesystem_id", "initialization_mode",
            "inventory_at_seconds", "allocated_bytes", "inode_count",
            "population_entry_count", "valid_run_count", "ambiguous_run_count",
            "internal_unsafe_link_count", "recovery_record_id",
            "generation_basis", "prior_generation", "measured_run_entries",
            "provenance_record_id",
        },
        "recovery membership inventory record",
    )
    if payload["schema"] != RECOVERY_INVENTORY_MEMBERSHIP_SCHEMA:
        raise HygieneValidationError("unsupported recovery inventory schema")
    _validate_inventory_common(payload)
    population = nonnegative_int(
        payload["population_entry_count"], "population count"
    )
    valid = nonnegative_int(payload["valid_run_count"], "valid run count")
    ambiguous = nonnegative_int(
        payload["ambiguous_run_count"], "ambiguous run count"
    )
    if valid + ambiguous != population:
        raise HygieneValidationError("recovery population counts do not reconcile")
    nonnegative_int(
        payload["internal_unsafe_link_count"], "internal unsafe link count"
    )
    sha256_hex(payload["recovery_record_id"], "recovery record id")
    if payload["generation_basis"] not in {
        "preserved_increment", "recovery_epoch"
    }:
        raise HygieneValidationError("unsupported recovery generation basis")
    prior = payload["prior_generation"]
    if payload["generation_basis"] == "preserved_increment":
        nonnegative_int(prior, "prior generation")
    elif prior is not None:
        raise HygieneValidationError("recovery epoch cannot claim prior generation")
    entries = _validate_measured_run_entries(payload["measured_run_entries"])
    if len(entries) != population:
        raise HygieneValidationError("recovery membership count does not reconcile")
    sha256_hex(payload["provenance_record_id"], "provenance record id")
    return payload


def _validate_inventory_common(payload: dict[str, Any]) -> None:
    sha256_hex(payload["scratch_filesystem_id"], "scratch filesystem identity")
    if payload["initialization_mode"] != "maintenance_inventory":
        raise HygieneValidationError("unsupported maintenance inventory mode")
    nonnegative_int(payload["inventory_at_seconds"], "inventory timestamp")
    nonnegative_int(payload["allocated_bytes"], "allocated_bytes")
    nonnegative_int(payload["inode_count"], "inode_count")


def _validate_measured_run_entries(payload: Any) -> tuple[dict[str, Any], ...]:
    if type(payload) is not list:
        raise HygieneValidationError("measured run entries must be a list")
    entries = []
    names = []
    folded = set()
    for value in payload:
        entry = exact_object(
            value,
            {"run_id", "device", "inode"},
            "measured run entry",
        )
        name = safe_run_id(entry["run_id"])
        nonnegative_int(entry["device"], "measured run device")
        nonnegative_int(entry["inode"], "measured run inode")
        if name.casefold() in folded:
            raise HygieneValidationError("measured run identity is ambiguous")
        folded.add(name.casefold())
        names.append(name)
        entries.append(entry)
    if names != sorted(names):
        raise HygieneValidationError("measured run entries are not sorted")
    return tuple(entries)


def validate_admission(payload: Any) -> dict[str, Any]:
    payload = exact_object(
        payload,
        {
            "schema",
            "run_id",
            "phase",
            "profile",
            "byte_quota",
            "inode_quota",
            "process_id",
            "process_start_evidence",
            "owner_token",
            "configuration_sha256",
            "admitted_at_seconds",
        },
        "admission record",
    )
    if payload["schema"] != ADMISSION_SCHEMA:
        raise HygieneValidationError("unsupported admission schema")
    safe_run_id(payload["run_id"])
    safe_text(payload["phase"], "phase")
    try:
        HygieneProfile(payload["profile"])
    except (TypeError, ValueError) as error:
        raise HygieneValidationError("unsupported hygiene profile") from error
    nonnegative_int(payload["byte_quota"], "byte_quota")
    nonnegative_int(payload["inode_quota"], "inode_quota")
    process_id = nonnegative_int(payload["process_id"], "process id")
    if process_id == 0:
        raise HygieneValidationError("process id must be positive")
    sha256_hex(payload["process_start_evidence"], "process start evidence")
    owner_token(payload["owner_token"])
    sha256_hex(payload["configuration_sha256"], "configuration SHA-256")
    nonnegative_int(payload["admitted_at_seconds"], "admission timestamp")
    return payload


def validate_close(payload: Any) -> dict[str, Any]:
    payload = exact_object(
        payload,
        {
            "schema",
            "run_id",
            "phase",
            "terminal_outcome",
            "retention_class",
            "allocated_bytes",
            "inode_count",
            "retained_evidence_bytes",
            "closed_at_seconds",
        },
        "close record",
    )
    if payload["schema"] != CLOSE_SCHEMA:
        raise HygieneValidationError("unsupported close schema")
    safe_run_id(payload["run_id"])
    safe_text(payload["phase"], "phase")
    try:
        terminal = TerminalOutcome(payload["terminal_outcome"])
        retention = RetentionClass(payload["retention_class"])
    except (TypeError, ValueError) as error:
        raise HygieneValidationError("unsupported terminal close state") from error
    allocated = nonnegative_int(payload["allocated_bytes"], "allocated_bytes")
    nonnegative_int(payload["inode_count"], "inode_count")
    retained = nonnegative_int(
        payload["retained_evidence_bytes"], "retained_evidence_bytes"
    )
    if retained > allocated:
        raise HygieneValidationError("retained evidence exceeds allocated bytes")
    if not terminal_retention_consistent(terminal, retention):
        raise HygieneValidationError("terminal outcome and retention class conflict")
    nonnegative_int(payload["closed_at_seconds"], "close timestamp")
    return payload


def terminal_retention_consistent(
    terminal: TerminalOutcome, retention: RetentionClass
) -> bool:
    if retention is RetentionClass.REPORT_SOURCE_PENDING_APPEND:
        return True
    if terminal is TerminalOutcome.PASSED:
        return retention is RetentionClass.SUCCESSFUL_EVIDENCE
    if terminal is TerminalOutcome.CORRECTION_REQUIRED:
        return retention is RetentionClass.CORRECTION_REQUIRED_EVIDENCE
    return retention is RetentionClass.FAILED_EVIDENCE


def safe_run_id(value: Any) -> str:
    if type(value) is not str or not _RUN_ID.fullmatch(value):
        raise HygieneValidationError("run id is invalid")
    return value


def safe_text(value: Any, name: str) -> str:
    return bounded_string(value, name, 256)


def owner_token(value: Any) -> str:
    if type(value) is not str or not _OWNER_TOKEN.fullmatch(value):
        raise HygieneValidationError("owner token is invalid")
    return value


__all__ = [
    "ADMISSION_SCHEMA",
    "BOOTSTRAP_SCHEMA",
    "CLOSE_SCHEMA",
    "INITIALIZATION_MODES",
    "INVENTORY_SCHEMA",
    "INVENTORY_MEMBERSHIP_SCHEMA",
    "RECOVERY_INVENTORY_SCHEMA",
    "RECOVERY_INVENTORY_MEMBERSHIP_SCHEMA",
    "LOCK_SCHEMA",
    "SUMMARY_SCHEMA",
    "owner_token",
    "safe_run_id",
    "safe_text",
    "validate_admission",
    "validate_bootstrap",
    "validate_close",
    "validate_inventory",
    "validate_inventory_membership",
    "validate_recovery_inventory",
    "validate_recovery_inventory_membership",
    "validate_summary",
]
