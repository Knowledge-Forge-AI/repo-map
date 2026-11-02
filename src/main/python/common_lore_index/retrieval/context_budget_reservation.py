"""Pre-freshness packet reservation helpers for W4 admission."""

from __future__ import annotations

from collections.abc import Mapping
import copy
from typing import Any

_FRESHNESS_REASON = "structural_span_only_no_lexical_anchor"
_FRESHNESS_LIMITS = ["structural_span_only", "no_lexical_anchor", "no_body_text"]

# These are the closed W4 ceilings, expressed as packet-field maxima rather
# than a generic digit cushion.  They bound the largest diagnostics that can
# be produced before the freshness pass runs.
_MAX_SCAN_UNITS = 8
_MAX_SCAN_NODES = 2_000
_MAX_NEIGHBORS = 128
_MAX_RELATIONS = 256
_MAX_CANDIDATE_ROWS = _MAX_SCAN_UNITS * _MAX_SCAN_NODES
_MAX_LOCATIONS = (_MAX_SCAN_UNITS + 1) * 10_000
_MAX_OUTPUT_OMISSIONS = _MAX_CANDIDATE_ROWS + _MAX_NEIGHBORS + _MAX_RELATIONS
_MAX_FIELD_OMISSIONS = _MAX_LOCATIONS + _MAX_CANDIDATE_ROWS + _MAX_NEIGHBORS + 1
_MAX_EXPANSION_EDGES = 5 * 64
_MAX_SQL_STATEMENTS = 36
_MAX_PROGRESS_CALLBACKS = _MAX_SQL_STATEMENTS * 250
_MAX_VM_STEPS = _MAX_PROGRESS_CALLBACKS * 1_000
_MAX_EVIDENCE_ROWS = (_MAX_SCAN_UNITS + 1) * 10_000

_OMISSION_COUNT_LIMITS = {
    "output_budget": _MAX_OUTPUT_OMISSIONS,
    "item_limit": _MAX_CANDIDATE_ROWS,
    "location_limit": _MAX_LOCATIONS,
    "ambiguous_alternative_omitted_by_budget": _MAX_CANDIDATE_ROWS,
    "expansion_node_limit": _MAX_EXPANSION_EDGES,
    "expansion_edge_limit": 5,
    "expansion_backend_unsupported": 1,
    "candidate_scan_incomplete": _MAX_SCAN_UNITS + 1,
    "unlocatable_kind_pattern_excluded": 32,
    "oversize_field_withheld": _MAX_FIELD_OMISSIONS,
    "unencodable_field_withheld": _MAX_FIELD_OMISSIONS,
}


def _locations(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for group_key in ("items", "neighbors"):
        for item in packet.get(group_key, ()) or ():
            result.extend(
                loc for loc in item.get("locations", ())
                if isinstance(loc, dict)
            )
    return result


def _reserve_variable_fields(packet: dict[str, Any]) -> None:
    if packet.get("status") in {"complete", "partial"}:
        packet["status"] = "complete"

    counts = packet.get("omission_counts")
    if isinstance(counts, dict):
        for key, value in tuple(counts.items()):
            counts[key] = max(_OMISSION_COUNT_LIMITS.get(key, 0), int(value or 0))

    records = packet.get("omissions")
    if isinstance(records, list):
        reserved: list[dict[str, Any]] = []
        for record in records:
            copy_record = dict(record)
            reason = str(copy_record.get("reason", ""))
            copy_record["count"] = max(
                _OMISSION_COUNT_LIMITS.get(reason, 0),
                int(copy_record.get("count") or 0),
            )
            reserved.append(copy_record)
        if not any(record.get("reason") == "output_budget" for record in reserved):
            reserved.append({"reason": "output_budget", "count": _MAX_OUTPUT_OMISSIONS})
        packet["omissions"] = reserved

    work = packet.get("work_ledger")
    if isinstance(work, dict):
        maxima = {
            "config_revalidations_executed": 1,
            "logical_read_units": 16,
            "sql_statements_executed": _MAX_SQL_STATEMENTS,
            "scan_units_executed": _MAX_SCAN_UNITS,
            "seed_expansions_executed": 5,
            "candidate_rows_scanned": _MAX_CANDIDATE_ROWS,
            "evidence_rows_scanned": _MAX_EVIDENCE_ROWS,
            "sqlite_vm_steps_estimate": _MAX_VM_STEPS,
            "elapsed_ms": 10_001,
            "sqlite_progress_callbacks": _MAX_PROGRESS_CALLBACKS,
        }
        for key, maximum in maxima.items():
            if type(work.get(key)) is int:
                work[key] = max(work[key], maximum)

    locations = _locations(packet)
    fresh_locations = [loc for loc in locations if loc.get("freshness") is not None]
    if packet.get("absence_basis") is None and not packet.get("items"):
        scope = packet.get("scope") or {}
        scoped = (
            int(scope.get("selected_binding_count") or 0) > 0
            or int(scope.get("path_prefix_count") or 0) > 0
        )
        packet["absence_basis"] = (
            "stored_direct_locatable_metadata_fields_in_selected_scope"
            if scoped else "stored_metadata_fields_in_selected_scope"
        )
    if not fresh_locations:
        return
    for loc in fresh_locations:
        observation = loc["freshness"]
        if isinstance(observation, dict):
            observation["state"] = "no_change_observed_with_limits"
            observation["reason"] = _FRESHNESS_REASON
            observation["limits"] = list(_FRESHNESS_LIMITS)
    freshness = packet.get("freshness")
    if isinstance(freshness, dict):
        count = len(fresh_locations)
        freshness.update(
            state="checked",
            files_checked=16,
            bytes_read=262_144,
            counts={
                "changed_observed": count,
                "no_change_observed_with_limits": count,
                "not_checked": count,
                "unavailable": count,
            },
        )


def packet_size_with_reservation(packet: dict[str, Any]) -> int:
    """Measure a packet after reserving all bounded post-admission fields."""
    from common_lore_index.retrieval.context_budget import compute_actual_bytes_fixpoint

    reserved = copy.deepcopy(packet)
    _reserve_variable_fields(reserved)
    _, size = compute_actual_bytes_fixpoint(reserved)
    return size


def empty_packet_size_with_reservation(packet: dict[str, Any]) -> int:
    """Measure the final empty envelope with current immutable diagnostics."""
    empty = copy.deepcopy(packet)
    empty["items"] = []
    empty["neighbors"] = []
    empty["relations"] = []
    empty["omissions"] = []
    return packet_size_with_reservation(empty)
