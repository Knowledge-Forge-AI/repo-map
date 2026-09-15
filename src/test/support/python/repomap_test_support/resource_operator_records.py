"""Strict private evidence and public-safe logs for operator reclamation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from repomap_test_support.resource_ledger_io import (
    PrivateJsonError,
    read_private_json,
    write_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_safe_tree_failure import (
    SAFE_TREE_FAILURE_CATEGORIES,
)
from repomap_test_support.resource_validation import (
    HygieneValidationError,
    bounded_string,
    exact_bool,
    exact_object,
    nonnegative_int,
    sha256_hex,
)


OPERATION_SCHEMA = "repomap-test-operator-reclamation-v1"
PUBLIC_LOG_SCHEMA = "repomap-test-operator-reclamation-log-v1"
SCOPE_CLASS = "selected_run_directory_contents"
_STATES = {"intent", "point_of_no_return", "aborted", "partial", "completed"}
_OPERATION_REQUIRED_FIELDS = {
    "schema", "project", "operation_id", "started_at_seconds", "scope_class",
    "force_live", "override_pins", "confirmation_digest", "inventory_digest",
    "entry_count", "allocated_bytes", "inode_count", "live_count",
    "unknown_count", "pin_count", "marker_count", "entries", "categories", "state",
    "point_of_no_return", "removed_entry_count", "removed_allocated_bytes",
    "removed_inode_count", "completed_at_seconds", "outcome",
    "barrier_released",
}
_COTENANT_FIELDS = {
    f"{category}_{suffix}"
    for category in ("foreign", "ambiguous")
    for suffix in (
        "running_manifest_count", "positive_pid_manifest_count",
        "live_observed_count", "dead_observed_count",
        "unknown_observed_count", "invalid_or_missing_pid_count",
    )
}
_OPERATION_OPTIONAL_FIELDS = _COTENANT_FIELDS | {
    "partial_failure_category",
    "partial_reason",
}
_OPERATION_FIELDS = _OPERATION_REQUIRED_FIELDS | _OPERATION_OPTIONAL_FIELDS
_PUBLIC_FIELDS = {
    "schema", "timestamp_seconds", "scope_class", "outcome", "force_live",
    "override_pins", "entry_count", "allocated_bytes", "inode_count",
    "live_count", "unknown_count", "pin_count", "marker_count",
    "removed_entry_count", "removed_allocated_bytes", "removed_inode_count",
    "point_of_no_return",
    "barrier_released",
    "partial_failure_category",
    "partial_reason",
}
PARTIAL_REASONS = frozenset(
    {
        "exceptional_safe_tree_failure",
        "interrupted",
        "reconciliation_failure",
        "unexpected_post_pnr_failure",
        "wall_time_limit",
    }
)
PARTIAL_FAILURE_CATEGORIES = SAFE_TREE_FAILURE_CATEGORIES | frozenset(
    {
        "reconciliation_failure",
        "unexpected_post_pnr_failure",
        "wall_time_limit",
    }
)
_DIRECT_PARTIAL_CAUSES = frozenset(
    {
        "interrupted",
        "reconciliation_failure",
        "unexpected_post_pnr_failure",
        "wall_time_limit",
    }
)


def operation_root(scratch_root: Path) -> Path:
    return Path(scratch_root) / ".operator-reclamation"


def create_operation_record(
    scratch_root: Path,
    payload: dict[str, Any],
) -> Path:
    values = validate_operation_record(payload, writing=True)
    directory = operation_root(scratch_root) / "operations"
    _private_directory(directory)
    path = directory / f"{values['operation_id']}.json"
    write_private_json_exclusive(path, values)
    _fsync_directory(directory)
    return path


def replace_operation_record(path: Path, payload: dict[str, Any]) -> None:
    values = validate_operation_record(payload, writing=True)
    existing = read_operation_record(path)
    if (
        values["operation_id"] != existing["operation_id"]
        or values["started_at_seconds"] != existing["started_at_seconds"]
        or values["inventory_digest"] != existing["inventory_digest"]
        or values["entries"] != existing["entries"]
    ):
        raise ValueError("operator operation immutable identity changed")
    write_private_json(path, values)
    _fsync_directory(Path(path).parent)


def read_operation_record(path: Path) -> dict[str, Any]:
    try:
        return validate_operation_record(read_private_json(path))
    except (PrivateJsonError, HygieneValidationError) as error:
        raise ValueError("operator operation evidence is invalid") from error


def validate_operation_record(
    payload: Any, *, writing: bool = False
) -> dict[str, Any]:
    if type(payload) is not dict:
        raise HygieneValidationError("operator operation must be an object")
    fields = set(payload)
    if (
        not _OPERATION_REQUIRED_FIELDS <= fields
        or not fields <= _OPERATION_FIELDS
        or (writing and fields != _OPERATION_FIELDS)
    ):
        raise HygieneValidationError("operator operation fields are invalid")
    values = dict(payload)
    for field in _COTENANT_FIELDS:
        values.setdefault(field, 0)
    values.setdefault("partial_failure_category", None)
    values.setdefault("partial_reason", None)
    if values["schema"] != OPERATION_SCHEMA:
        raise HygieneValidationError("unsupported operator operation schema")
    if values["project"] != "repo-map_dev":
        raise HygieneValidationError("operator operation project is invalid")
    operation_id = bounded_string(values["operation_id"], "operation id")
    if len(operation_id) != 32 or any(c not in "0123456789abcdef" for c in operation_id):
        raise HygieneValidationError("operation id is invalid")
    nonnegative_int(values["started_at_seconds"], "operation timestamp")
    if values["scope_class"] != SCOPE_CLASS:
        raise HygieneValidationError("operator scope class is invalid")
    exact_bool(values["force_live"], "force_live")
    exact_bool(values["override_pins"], "override_pins")
    sha256_hex(values["confirmation_digest"], "confirmation digest")
    sha256_hex(values["inventory_digest"], "inventory digest")
    for field in (
        "entry_count", "allocated_bytes", "inode_count", "live_count",
        "unknown_count", "pin_count", "marker_count", "removed_entry_count",
        "removed_allocated_bytes", "removed_inode_count",
    ):
        nonnegative_int(values[field], field)
    for field in _COTENANT_FIELDS:
        nonnegative_int(values[field], field)
    if values["partial_reason"] not in {None, *PARTIAL_REASONS}:
        raise HygieneValidationError("operator partial reason is invalid")
    if values["partial_failure_category"] not in {
        None,
        *PARTIAL_FAILURE_CATEGORIES,
    }:
        raise HygieneValidationError("operator partial failure category is invalid")
    entries = values["entries"]
    if type(entries) is not list or len(entries) != values["entry_count"]:
        raise HygieneValidationError("operator inventory entries are invalid")
    for entry in entries:
        item = exact_object(
            entry,
            {"name", "device", "inode", "mode"},
            "operator inventory entry",
        )
        bounded_string(item["name"], "operator inventory name")
        nonnegative_int(item["device"], "operator inventory device")
        nonnegative_int(item["inode"], "operator inventory inode")
        nonnegative_int(item["mode"], "operator inventory mode")
    categories = exact_object(
        values["categories"],
        {"valid", "ambiguous", "foreign", "opaque"},
        "operator inventory categories",
    )
    for key in categories:
        nonnegative_int(categories[key], f"operator category {key}")
    if sum(categories.values()) != values["entry_count"]:
        raise HygieneValidationError("operator category counts do not reconcile")
    if values["state"] not in _STATES:
        raise HygieneValidationError("operator operation state is invalid")
    if writing:
        _validate_partial_cause_relation(
            partial=values["state"] == "partial",
            reason=values["partial_reason"],
            category=values["partial_failure_category"],
        )
    exact_bool(values["point_of_no_return"], "point_of_no_return")
    exact_bool(values["barrier_released"], "barrier_released")
    completed = values["completed_at_seconds"]
    if completed is not None:
        nonnegative_int(completed, "operation completion timestamp")
    outcome = values["outcome"]
    if outcome is not None:
        bounded_string(outcome, "operator outcome")
    return values


def append_public_log(scratch_root: Path, payload: dict[str, Any]) -> Path:
    values = exact_object(payload, _PUBLIC_FIELDS, "public operator log")
    if values["schema"] != PUBLIC_LOG_SCHEMA or values["scope_class"] != SCOPE_CLASS:
        raise HygieneValidationError("public operator log identity is invalid")
    bounded_string(values["outcome"], "public operator outcome")
    nonnegative_int(values["timestamp_seconds"], "public operator timestamp")
    exact_bool(values["force_live"], "force_live")
    exact_bool(values["override_pins"], "override_pins")
    exact_bool(values["point_of_no_return"], "point_of_no_return")
    exact_bool(values["barrier_released"], "barrier_released")
    if values["partial_reason"] not in {None, *PARTIAL_REASONS}:
        raise HygieneValidationError("public partial reason is invalid")
    if values["partial_failure_category"] not in {
        None,
        *PARTIAL_FAILURE_CATEGORIES,
    }:
        raise HygieneValidationError("public partial failure category is invalid")
    _validate_partial_cause_relation(
        partial=values["outcome"] == "partial",
        reason=values["partial_reason"],
        category=values["partial_failure_category"],
    )
    for field in _PUBLIC_FIELDS - {
        "schema", "scope_class", "outcome", "force_live", "override_pins",
        "point_of_no_return", "barrier_released", "partial_failure_category",
        "partial_reason",
    }:
        nonnegative_int(values[field], field)
    directory = operation_root(scratch_root) / "log"
    _private_directory(directory)
    path = directory / "operator-reclamation.jsonl"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        data = (json.dumps(values, sort_keys=True) + "\n").encode()
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(directory)
    return path


def _validate_partial_cause_relation(
    *,
    partial: bool,
    reason: object,
    category: object,
) -> None:
    if not partial:
        if reason is not None or category is not None:
            raise HygieneValidationError("non-partial cause relation is invalid")
        return
    if reason is None or category is None:
        raise HygieneValidationError("partial cause relation is incomplete")
    if reason == "exceptional_safe_tree_failure":
        valid = category in SAFE_TREE_FAILURE_CATEGORIES and category != "interrupted"
    else:
        valid = reason in _DIRECT_PARTIAL_CAUSES and category == reason
    if not valid:
        raise HygieneValidationError("partial cause relation is invalid")


def _private_directory(path: Path) -> None:
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
    current = path
    while True:
        metadata = current.stat(follow_symlinks=False)
        if current.is_symlink() or not current.is_dir():
            raise PrivateJsonError("operator evidence directory is unsafe")
        if (
            current == path or ".operator-reclamation" in current.parts
        ) and metadata.st_mode & 0o077:
            raise PrivateJsonError("operator evidence directory is not private")
        if current.name == ".operator-reclamation":
            break
        current = current.parent


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "OPERATION_SCHEMA", "PARTIAL_FAILURE_CATEGORIES", "PARTIAL_REASONS",
    "PUBLIC_LOG_SCHEMA", "SCOPE_CLASS",
    "append_public_log", "create_operation_record", "operation_root",
    "read_operation_record", "replace_operation_record",
    "validate_operation_record",
]
