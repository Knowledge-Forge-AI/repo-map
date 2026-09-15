"""Strict private schemas for physical inventory membership."""

from __future__ import annotations

import hashlib
import os
from typing import Any

from repomap_test_support.resource_index_records import safe_run_id
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    exact_object,
    nonnegative_int,
    sha256_hex,
)


PHYSICAL_INVENTORY_SCHEMA = "repomap-test-hygiene-index-inventory-v3"
RECOVERY_PHYSICAL_INVENTORY_SCHEMA = (
    "repomap-test-hygiene-index-recovery-inventory-v4"
)
_ENTRY_KEY_DOMAIN = b"repomap-physical-entry-v1\0"


def physical_entry_key(name: str) -> str:
    """Return the host-local key for one exact immediate basename."""
    if type(name) is not str:
        raise HygieneValidationError("physical entry name is invalid")
    return hashlib.sha256(_ENTRY_KEY_DOMAIN + os.fsencode(name)).hexdigest()


def validate_physical_inventory(payload: Any) -> dict[str, Any]:
    payload = exact_object(
        payload,
        {
            "schema", "scratch_filesystem_id", "initialization_mode",
            "inventory_at_seconds", "allocated_bytes", "inode_count",
            "measured_physical_entries", "provenance_record_id",
        },
        "physical membership inventory record",
    )
    if payload["schema"] != PHYSICAL_INVENTORY_SCHEMA:
        raise HygieneValidationError("unsupported physical inventory schema")
    _validate_common(payload)
    _validate_physical_entries(payload["measured_physical_entries"])
    sha256_hex(payload["provenance_record_id"], "provenance record id")
    return payload


def validate_recovery_physical_inventory(payload: Any) -> dict[str, Any]:
    payload = exact_object(
        payload,
        {
            "schema", "scratch_filesystem_id", "initialization_mode",
            "inventory_at_seconds", "allocated_bytes", "inode_count",
            "population_entry_count", "valid_run_count", "ambiguous_run_count",
            "internal_unsafe_link_count", "recovery_record_id",
            "generation_basis", "prior_generation", "measured_physical_entries",
            "provenance_record_id",
        },
        "recovery physical membership inventory record",
    )
    if payload["schema"] != RECOVERY_PHYSICAL_INVENTORY_SCHEMA:
        raise HygieneValidationError(
            "unsupported recovery physical inventory schema"
        )
    _validate_common(payload)
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
    entries = _validate_physical_entries(payload["measured_physical_entries"])
    if len(entries) != population:
        raise HygieneValidationError("recovery membership count does not reconcile")
    sha256_hex(payload["provenance_record_id"], "provenance record id")
    return payload


def _validate_common(payload: dict[str, Any]) -> None:
    sha256_hex(payload["scratch_filesystem_id"], "scratch filesystem identity")
    if payload["initialization_mode"] != "maintenance_inventory":
        raise HygieneValidationError("unsupported maintenance inventory mode")
    nonnegative_int(payload["inventory_at_seconds"], "inventory timestamp")
    nonnegative_int(payload["allocated_bytes"], "allocated_bytes")
    nonnegative_int(payload["inode_count"], "inode_count")


def _validate_physical_entries(payload: Any) -> tuple[dict[str, Any], ...]:
    if type(payload) is not list:
        raise HygieneValidationError("measured physical entries must be a list")
    entries = []
    keys = []
    run_ids = set()
    folded = set()
    for value in payload:
        entry = exact_object(
            value,
            {"entry_key", "valid_run_id", "device", "inode"},
            "measured physical entry",
        )
        key = sha256_hex(entry["entry_key"], "physical entry key")
        run_id = entry["valid_run_id"]
        if run_id is not None:
            run_id = safe_run_id(run_id)
            if physical_entry_key(run_id) != key:
                raise HygieneValidationError("physical entry key does not match run id")
            if run_id in run_ids or run_id.casefold() in folded:
                raise HygieneValidationError("measured run identity is ambiguous")
            run_ids.add(run_id)
            folded.add(run_id.casefold())
        nonnegative_int(entry["device"], "measured physical device")
        nonnegative_int(entry["inode"], "measured physical inode")
        keys.append(key)
        entries.append(entry)
    if len(keys) != len(set(keys)):
        raise HygieneValidationError("physical entry key is duplicated")
    if keys != sorted(keys):
        raise HygieneValidationError("measured physical entries are not sorted")
    return tuple(entries)


__all__ = [
    "PHYSICAL_INVENTORY_SCHEMA",
    "RECOVERY_PHYSICAL_INVENTORY_SCHEMA",
    "physical_entry_key",
    "validate_physical_inventory",
    "validate_recovery_physical_inventory",
]
