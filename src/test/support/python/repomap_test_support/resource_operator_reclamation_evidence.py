"""Evidence records, payloads, and public projections for operator reclamation."""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import Callable

from repomap_test_support.resource_interruption import (
    MARKER_SCHEMA,
    operator_marker_path,
)
from repomap_test_support.resource_ledger_io import (
    read_private_json,
    write_private_json_exclusive,
)
from repomap_test_support.resource_operator_records import (
    OPERATION_SCHEMA,
    PUBLIC_LOG_SCHEMA,
    SCOPE_CLASS,
    append_public_log,
    create_operation_record,
    replace_operation_record,
)
from repomap_test_support.resource_operator_scope import (
    ScopeEntry,
    category_counts,
    ensure_private_directory,
    fsync_directory,
    inventory_digest,
)
from repomap_test_support.resource_safe_tree_delete import SafeTreeDeleteFailure
from repomap_test_support.resource_validation import nonnegative_int
from repomap_test_support.resource_operator_reclamation_values import (
    CONFIRMATION_LITERAL,
    PROJECT,
    OperatorReclamationInterrupted,
    OperatorReclamationRequest,
    OperatorReclamationResult,
    replace_dict,
)


def public_operator_projection(
    result: OperatorReclamationResult,
) -> dict[str, int | str | bool | None]:
    return {
        "outcome": result.outcome,
        "scope_class": result.scope_class,
        "force_live": result.force_live,
        "override_pins": result.override_pins,
        "entry_count": result.entry_count,
        "allocated_bytes": result.allocated_bytes,
        "inode_count": result.inode_count,
        "live_count": result.live_count,
        "unknown_count": result.unknown_count,
        "pin_count": result.pin_count,
        "marker_count": result.markers_written,
        "removed_entry_count": result.removed_entry_count,
        "removed_allocated_bytes": result.removed_allocated_bytes,
        "removed_inode_count": result.removed_inode_count,
        "point_of_no_return": result.point_of_no_return,
        "barrier_released": result.barrier_released,
        "partial_failure_category": result.partial_failure_category,
        "partial_reason": result.partial_reason,
    }


def write_markers(root: Path, entries: tuple[ScopeEntry, ...], now: int) -> int:
    count = 0
    for entry in entries:
        if entry.category != "valid" or entry.manifest is None:
            continue
        path = operator_marker_path(root, project=PROJECT, run_id=entry.name)
        ensure_private_directory(path.parent)
        payload = {
            "schema": MARKER_SCHEMA,
            "project": PROJECT,
            "phase": entry.manifest["phase"],
            "run_id": entry.name,
            "operator_attributed": True,
            "observed_at_seconds": now,
        }
        if path.exists():
            existing = read_private_json(path)
            identity = {key: payload[key] for key in payload if key != "observed_at_seconds"}
            existing_identity = {
                key: existing.get(key) for key in identity
            } if isinstance(existing, dict) else None
            if existing_identity != identity:
                raise ValueError("operator marker identity is unsafe")
        else:
            write_private_json_exclusive(path, payload)
            fsync_directory(path.parent)
        count += 1
    return count


def refusal(
    request: OperatorReclamationRequest,
    live_count: int,
    unknown_count: int,
    pin_count: int,
) -> str | None:
    if type(request.confirmation) is not str or request.confirmation != CONFIRMATION_LITERAL:
        return "confirmation_refused"
    if unknown_count:
        return "unknown_liveness_refused"
    if live_count and not request.force_live:
        return "live_run_refused"
    if pin_count and not request.override_pins:
        return "operator_pin_refused"
    return None


def operation_payload(
    operation_id: str,
    request: OperatorReclamationRequest,
    entries: tuple[ScopeEntry, ...],
    categories: dict[str, int],
    *,
    live_count: int,
    unknown_count: int,
    pin_count: int,
    cotenant_activity: dict[str, int],
    inventory_digest: str,
    now_seconds: int,
) -> dict[str, object]:
    return {
        "schema": OPERATION_SCHEMA,
        "project": PROJECT,
        "operation_id": operation_id,
        "started_at_seconds": now_seconds,
        "scope_class": SCOPE_CLASS,
        "force_live": request.force_live,
        "override_pins": request.override_pins,
        "confirmation_digest": hashlib.sha256(
            (request.confirmation or "").encode()
        ).hexdigest(),
        "inventory_digest": inventory_digest,
        "entry_count": len(entries),
        "allocated_bytes": sum(e.inspection.allocated_bytes for e in entries),
        "inode_count": sum(e.inspection.inode_count for e in entries),
        "live_count": live_count,
        "unknown_count": unknown_count,
        "pin_count": pin_count,
        "marker_count": 0,
        "entries": [
            {
                "name": e.name,
                "device": e.inspection.device,
                "inode": e.inspection.inode,
                "mode": e.inspection.mode,
            }
            for e in entries
        ],
        "categories": categories,
        "state": "intent",
        "point_of_no_return": False,
        "removed_entry_count": 0,
        "removed_allocated_bytes": 0,
        "removed_inode_count": 0,
        "completed_at_seconds": None,
        "outcome": None,
        "barrier_released": False,
        "partial_failure_category": None,
        "partial_reason": None,
        **cotenant_activity,
    }


def create_preflight_operation(
    root: Path,
    request: OperatorReclamationRequest,
    entries: tuple[ScopeEntry, ...],
    *,
    live_count: int,
    unknown_count: int,
    pin_count: int,
    cotenant_activity: dict[str, int],
    now_seconds: int,
    create_record: Callable[[Path, dict[str, object]], Path] = create_operation_record,
) -> tuple[Path, dict[str, object], dict[str, int]]:
    operation_id = secrets.token_hex(16)
    scope_digest = inventory_digest(entries)
    categories = category_counts(entries)
    payload = operation_payload(
        operation_id,
        request,
        entries,
        categories,
        live_count=live_count,
        unknown_count=unknown_count,
        pin_count=pin_count,
        cotenant_activity=cotenant_activity,
        inventory_digest=scope_digest,
        now_seconds=now_seconds,
    )
    return create_record(root, payload), payload, categories


def finish(
    root: Path,
    operation_path: Path,
    payload: dict[str, object],
    outcome: str,
    categories: dict[str, int],
    *,
    now_seconds: int,
    identity_replacement_refused: bool = False,
    barrier_released: bool = False,
    replace_record: Callable[[Path, dict[str, object]], None] = replace_operation_record,
    append_log: Callable[[Path, dict[str, object]], Path] = append_public_log,
) -> OperatorReclamationResult:
    state = (
        "completed" if outcome == "completed"
        else "partial" if outcome == "partial"
        else "aborted"
    )
    if outcome == "partial":
        reason = payload.get("partial_reason") or "unexpected_post_pnr_failure"
        category = payload.get("partial_failure_category") or (
            reason if reason != "exceptional_safe_tree_failure"
            else "unexpected_safe_tree_error"
        )
        payload = replace_dict(
            payload,
            partial_reason=reason,
            partial_failure_category=category,
        )
    payload = replace_dict(
        payload,
        state=state,
        completed_at_seconds=now_seconds,
        outcome=outcome,
        barrier_released=barrier_released,
    )
    replace_record(operation_path, payload)
    public = {
        "schema": PUBLIC_LOG_SCHEMA,
        "timestamp_seconds": now_seconds,
        "scope_class": SCOPE_CLASS,
        "outcome": outcome,
        "force_live": payload["force_live"],
        "override_pins": payload["override_pins"],
        "entry_count": payload["entry_count"],
        "allocated_bytes": payload["allocated_bytes"],
        "inode_count": payload["inode_count"],
        "live_count": payload["live_count"],
        "unknown_count": payload["unknown_count"],
        "pin_count": payload["pin_count"],
        "marker_count": payload["marker_count"],
        "removed_entry_count": payload["removed_entry_count"],
        "removed_allocated_bytes": payload["removed_allocated_bytes"],
        "removed_inode_count": payload["removed_inode_count"],
        "point_of_no_return": payload["point_of_no_return"],
        "barrier_released": payload["barrier_released"],
        "partial_failure_category": payload["partial_failure_category"],
        "partial_reason": payload["partial_reason"],
    }
    log = append_log(root, public)
    return OperatorReclamationResult(
        outcome,
        SCOPE_CLASS,
        bool(payload["force_live"]),
        bool(payload["override_pins"]),
        nonnegative_int(payload["entry_count"], "entry_count"),
        nonnegative_int(payload["allocated_bytes"], "allocated_bytes"),
        nonnegative_int(payload["inode_count"], "inode_count"),
        nonnegative_int(payload["live_count"], "live_count"),
        nonnegative_int(payload["unknown_count"], "unknown_count"),
        nonnegative_int(payload["pin_count"], "pin_count"),
        nonnegative_int(payload["marker_count"], "marker_count"),
        nonnegative_int(payload["removed_entry_count"], "removed_entry_count"),
        nonnegative_int(payload["removed_allocated_bytes"], "removed_allocated_bytes"),
        nonnegative_int(payload["removed_inode_count"], "removed_inode_count"),
        bool(payload["point_of_no_return"]),
        any(
            nonnegative_int(payload[field], field) > 0
            for field in (
                "removed_entry_count",
                "removed_allocated_bytes",
                "removed_inode_count",
            )
        ),
        identity_replacement_refused,
        categories,
        str(payload["operation_id"]),
        str(payload["inventory_digest"]),
        operation_path,
        log,
        bool(payload["barrier_released"]),
        str(payload["partial_reason"]) if payload["partial_reason"] is not None else None,
        str(payload["partial_failure_category"]) if payload["partial_failure_category"] is not None else None,
    )


def partial_on_delete_failure(
    payload: dict[str, object],
    error: SafeTreeDeleteFailure,
    removed_bytes: int,
    removed_inodes: int,
) -> tuple[dict[str, object], int, int, bool]:
    new_bytes = removed_bytes + error.removed_allocated_bytes
    new_inodes = removed_inodes + error.removed_inode_count
    interrupted = error.failure_category == "interrupted"
    new_payload = replace_dict(
        payload,
        state="partial",
        removed_allocated_bytes=new_bytes,
        removed_inode_count=new_inodes,
        partial_reason="interrupted" if interrupted else "exceptional_safe_tree_failure",
        partial_failure_category=error.failure_category,
    )
    return new_payload, new_bytes, new_inodes, interrupted


def partial_on_wall_time_limit(
    payload: dict[str, object],
    removed_bytes: int,
    removed_inodes: int,
) -> dict[str, object]:
    return replace_dict(
        payload,
        state="partial",
        removed_allocated_bytes=removed_bytes,
        removed_inode_count=removed_inodes,
        partial_reason="wall_time_limit",
        partial_failure_category="wall_time_limit",
    )


def partial_on_exception(
    payload: dict[str, object],
    error: BaseException,
    *,
    reconciling: bool,
) -> tuple[dict[str, object], bool, bool]:
    interrupted = not isinstance(error, Exception)
    identity_changed = reconciling and "identity changed" in str(error)
    reason = (
        "interrupted" if interrupted
        else "reconciliation_failure" if reconciling
        else "unexpected_post_pnr_failure"
    )
    new_payload = replace_dict(
        payload,
        partial_reason=reason,
        partial_failure_category=reason,
    )
    return new_payload, interrupted, identity_changed


def interruption_boundary(
    result: OperatorReclamationResult,
    error: BaseException | None,
) -> OperatorReclamationInterrupted:
    if isinstance(error, KeyboardInterrupt):
        return OperatorReclamationInterrupted(
            result, interruption_kind="keyboard_interrupt", exit_code=130
        )
    if isinstance(error, SystemExit):
        code = error.code
        exit_code = code if type(code) is int and 1 <= code <= 255 else 2
        return OperatorReclamationInterrupted(
            result, interruption_kind="system_exit", exit_code=exit_code
        )
    return OperatorReclamationInterrupted(
        result, interruption_kind="base_exception", exit_code=2
    )


__all__ = [
    "create_preflight_operation",
    "finish",
    "interruption_boundary",
    "operation_payload",
    "partial_on_delete_failure",
    "partial_on_exception",
    "partial_on_wall_time_limit",
    "public_operator_projection",
    "refusal",
    "write_markers",
]
