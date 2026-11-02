"""Strict byte-budget accounting, UTF-8 field caps, skeleton compaction, and fixpoint (W4 §4.1-4.2)."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any

from common_lore_index.retrieval.context_contracts import (
    BUDGET_ERROR_HARD_CAP_BYTES,
    COMPACT_CONTEXT_SCHEMA_VERSION,
    MAX_BUDGET_BYTES,
    MIN_BUDGET_BYTES,
)

DISPLAY_NAME_CAP_BYTES = 512
SOURCE_RELATIVE_PATH_CAP_BYTES = 1024
CANONICAL_KEY_CAP_BYTES = 4096

PROACTIVE_COMPACTION_BUDGET_THRESHOLD = 6144
TARGET_ECHO_PROACTIVE_CAP_BYTES = 128
SCOPE_ECHO_PROACTIVE_CAP_BYTES = 256
ECHO_BUDGET_INT_ABS_LIMIT = 999_999_999

def serialize_compact_json(payload: Mapping[str, Any]) -> bytes:
    """Serialize packet to compact UTF-8 JSON with trailing newline and no NaN."""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    return text.encode("utf-8")


def sha256_prefixed(text: str) -> str:
    """Return 'sha256:<64-hex>' over UTF-8 bytes (replacing lone surrogates only for digest)."""
    raw = text.encode("utf-8", errors="surrogatepass")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def sanitize_stored_string(
    value: Any, *, field_cap_bytes: int
) -> tuple[str | None, str | None]:
    """Validate stored string for strict UTF-8 and byte cap without mid-character slicing."""
    if value is None:
        return None, None
    if not isinstance(value, str):
        value = str(value)
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return None, "unencodable_field_withheld"
    if len(encoded) > field_cap_bytes:
        return None, "oversize_field_withheld"
    return value, None


def build_budget_error_envelope(
    *,
    reason: str,
    budget_bytes: int | None,
    required_min_bytes: int | None = None,
) -> dict[str, Any]:
    """Build the fixed-vocabulary <= 512-byte budget_error envelope."""
    envelope: dict[str, Any] = {
        "schema": COMPACT_CONTEXT_SCHEMA_VERSION,
        "status": "budget_error",
        "reason": reason,
        "budget_bytes": budget_bytes,
        "min_budget_bytes": MIN_BUDGET_BYTES,
        "max_budget_bytes": MAX_BUDGET_BYTES,
        "required_min_bytes": required_min_bytes,
    }
    raw = serialize_compact_json(envelope)
    if len(raw) > BUDGET_ERROR_HARD_CAP_BYTES:
        raise AssertionError(f"budget_error envelope exceeded {BUDGET_ERROR_HARD_CAP_BYTES} bytes")
    return envelope


def validate_budget_bytes(raw_budget: Any) -> dict[str, Any] | None:
    """Validate budget_bytes before any config, selection, DB, or source I/O."""
    if type(raw_budget) is not int:
        return build_budget_error_envelope(
            reason="invalid_budget_type",
            budget_bytes=None,
            required_min_bytes=None,
        )
    if raw_budget < MIN_BUDGET_BYTES or raw_budget > MAX_BUDGET_BYTES:
        echoed = (
            raw_budget
            if -ECHO_BUDGET_INT_ABS_LIMIT <= raw_budget <= ECHO_BUDGET_INT_ABS_LIMIT
            else None
        )
        return build_budget_error_envelope(
            reason="budget_out_of_range",
            budget_bytes=echoed,
            required_min_bytes=None,
        )
    return None


def compute_actual_bytes_fixpoint(packet: dict[str, Any]) -> tuple[bytes, int]:
    """Converge work_ledger['actual_bytes'] to exact UTF-8 byte length including newline."""
    ledger = packet["work_ledger"]
    ledger["actual_bytes"] = 0
    raw = serialize_compact_json(packet)
    length = len(raw)
    for _ in range(3):
        ledger["actual_bytes"] = length
        raw_next = serialize_compact_json(packet)
        length_next = len(raw_next)
        if length_next == length:
            return raw_next, length_next
        raw = raw_next
        length = length_next
    ledger["actual_bytes"] = length
    raw = serialize_compact_json(packet)
    return raw, len(raw)


def _withhold_target_echo(packet: dict[str, Any]) -> None:
    req = packet.get("request")
    if isinstance(req, dict) and req.get("target_echo") is not None:
        req["target_echo"] = None
        req["target_echo_withheld"] = True


def _withhold_scope_echo(packet: dict[str, Any]) -> None:
    scope = packet.get("scope")
    if isinstance(scope, dict) and scope.get("scope_echo_complete") is not False:
        scope["selected_binding_ids"] = None
        scope["path_prefixes"] = None
        scope["scope_echo_complete"] = False


def apply_skeleton_compaction(packet: dict[str, Any], budget_bytes: int) -> int:
    """Apply skeleton_compaction_v1 rules and return converged skeleton byte length."""
    req = packet.get("request", {})
    scope = packet.get("scope", {})

    if budget_bytes < PROACTIVE_COMPACTION_BUDGET_THRESHOLD:
        target_echo = req.get("target_echo")
        if isinstance(target_echo, str) and len(target_echo.encode("utf-8")) > TARGET_ECHO_PROACTIVE_CAP_BYTES:
            _withhold_target_echo(packet)
        b_ids = scope.get("selected_binding_ids")
        p_pfxs = scope.get("path_prefixes")
        if b_ids is not None or p_pfxs is not None:
            combined = json.dumps(
                {"b": b_ids, "p": p_pfxs}, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            if len(combined) > SCOPE_ECHO_PROACTIVE_CAP_BYTES:
                _withhold_scope_echo(packet)

    _, size = compute_actual_bytes_fixpoint(packet)
    if size > budget_bytes and req.get("target_echo") is not None:
        _withhold_target_echo(packet)
        _, size = compute_actual_bytes_fixpoint(packet)
    if size > budget_bytes and scope.get("scope_echo_complete") is not False:
        _withhold_scope_echo(packet)
        _, size = compute_actual_bytes_fixpoint(packet)
    return size


def maximally_compacted_skeleton_bytes(packet: dict[str, Any]) -> int:
    """Compute the minimum packet envelope while retaining current diagnostics."""
    saved_req = dict(packet["request"])
    saved_scope = dict(packet["scope"])
    saved_items = packet["items"]
    saved_neighbors = packet["neighbors"]
    saved_relations = packet["relations"]
    saved_omissions = packet["omissions"]
    saved_work = packet["work_ledger"]
    saved_absence_basis = packet["absence_basis"]
    try:
        packet["items"] = []
        packet["neighbors"] = []
        packet["relations"] = []
        packet["omissions"] = []
        if packet["absence_basis"] is None:
            is_scoped = (
                int(packet["scope"].get("selected_binding_count") or 0) > 0
                or int(packet["scope"].get("path_prefix_count") or 0) > 0
            )
            packet["absence_basis"] = (
                "stored_direct_locatable_metadata_fields_in_selected_scope"
                if is_scoped else "stored_metadata_fields_in_selected_scope"
            )
        packet["work_ledger"] = {**saved_work, "actual_bytes": 0}
        _withhold_target_echo(packet)
        _withhold_scope_echo(packet)
        _, min_bytes = compute_actual_bytes_fixpoint(packet)
        return min_bytes
    finally:
        packet["request"] = saved_req
        packet["scope"] = saved_scope
        packet["items"] = saved_items
        packet["neighbors"] = saved_neighbors
        packet["relations"] = saved_relations
        packet["omissions"] = saved_omissions
        packet["work_ledger"] = saved_work
        packet["absence_basis"] = saved_absence_basis


def finalize_packet_within_budget(
    packet: dict[str, Any],
    budget_bytes: int,
    *,
    top_tied_keys: frozenset[str] = frozenset(),
    required_min_bytes: int | None = None,
) -> dict[str, Any]:
    """Compact and converge a fully reserved packet without removing records."""
    _ = top_tied_keys  # retained for the established helper API
    apply_skeleton_compaction(packet, budget_bytes)
    _, size = compute_actual_bytes_fixpoint(packet)
    if size <= budget_bytes:
        return packet
    min_b = (
        required_min_bytes
        if required_min_bytes is not None
        else maximally_compacted_skeleton_bytes(packet)
    )
    if min_b > budget_bytes:
        return build_budget_error_envelope(
            reason="required_envelope_does_not_fit",
            budget_bytes=budget_bytes,
            required_min_bytes=min_b,
        )
    raise AssertionError(
        "packet exceeded budget after the pre-admission reservation invariant"
    )
