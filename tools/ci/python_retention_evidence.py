"""Deterministic compact retention evidence generation and commitments."""

from __future__ import annotations

import hashlib
import copy
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ci.python_retention_evidence_schema import (
    CANONICAL_VERSION,
    COMPLETE_SCHEMA,
    INCOMPLETE_SCHEMA,
    validate_retention_evidence_schema,
)


class RetentionEvidenceError(ValueError):
    """Integrity or validation error during evidence compaction."""


def _normalize_canonical(obj: Any) -> Any:
    if isinstance(obj, (set, frozenset)):
        return sorted((_normalize_canonical(it) for it in obj), key=canonical_json_bytes)
    if isinstance(obj, Mapping):
        if any(not isinstance(k, str) for k in obj):
            raise RetentionEvidenceError("canonical mappings require string keys")
        return {k: _normalize_canonical(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize_canonical(item) for item in obj]
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise RetentionEvidenceError("non-finite float not allowed in canonical JSON")
        return obj
    if obj is not None and type(obj) not in (str, int, bool):
        raise RetentionEvidenceError("unsupported canonical value")
    return obj


def canonical_json_bytes(obj: Any) -> bytes:
    """Encode object into deterministic canonical UTF-8 JSON bytes."""
    return json.dumps(
        _normalize_canonical(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def make_collection_commitment(
    items: Any, element_type: str, count: int | None = None
) -> dict[str, Any]:
    """Calculate the canonical encoding version, element count, and SHA-256 commitment."""
    if count is None:
        if not hasattr(items, "__len__"):
            raise RetentionEvidenceError("collection count requires a sized value or explicit count")
        count = len(items)
    if type(count) is not int or count < 0:
        raise RetentionEvidenceError("collection count must be a non-negative integer")
    raw_bytes = canonical_json_bytes(items)
    return {
        "element_type": element_type,
        "count": count,
        "canonical_version": CANONICAL_VERSION,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
    }


def compact_retention_evidence(
    source_doc: dict[str, Any],
    *,
    max_examples: int = 3,
) -> dict[str, Any]:
    """Produce the deterministic compact retention artifact from a full sanitized document."""
    from ci.python_retention_evidence_source import validate_source_document
    try:
        validate_source_document(source_doc)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise RetentionEvidenceError(str(error)) from error
    source_doc = copy.deepcopy(source_doc)
    def sort_path_sets(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {
                    "paths", "members", "analyzed_paths", "unknown_paths",
                    "cohort_regressions", "cohort_ids", "external_dependencies",
                    "ungoverned_dependencies", "dependency_blockers",
                    "external_dependency_indices", "ungoverned_dependency_indices",
                    "dependency_blocker_indices",
                } and isinstance(item, list):
                    value[key] = sorted(item)
                else:
                    sort_path_sets(item)
        elif isinstance(value, list):
            for item in value:
                sort_path_sets(item)
    sort_path_sets(source_doc)
    for field in ("eligible", "assigned", "enforced", "eligible_minus_enforced", "unassigned"):
        source_doc[field] = {root: sorted(paths) for root, paths in source_doc[field].items()}
    source_doc["cohorts"] = sorted(source_doc["cohorts"], key=lambda c: c["id"])
    for record in [*source_doc["cohorts"], *source_doc["cohort_results"].values()]:
        record["members"] = sorted(record["members"])
    if "atomic_groups" in source_doc and isinstance(source_doc["atomic_groups"], dict):
        for g in source_doc["atomic_groups"].values():
            if isinstance(g, dict) and "cohort_ids" in g and isinstance(g["cohort_ids"], list):
                g["cohort_ids"] = sorted(g["cohort_ids"])

    if type(max_examples) is not int or not 0 <= max_examples <= 10:
        raise RetentionEvidenceError("example limit must be between zero and ten")
    status = source_doc["status"]
    classification = source_doc.get("classification", "passed" if status == "passed" else "policy-finding")
    enforcement_complete = bool(source_doc.get("enforcement_complete", status == "passed"))

    candidate = source_doc["candidate_sha256"]
    eligible, assigned = source_doc["eligible"], source_doc["assigned"]
    enforced = source_doc.get("enforced", {})
    residual = source_doc.get("eligible_minus_enforced", source_doc.get("unassigned", {}))

    census = source_doc["counts"]["total_files"]
    el_total = sum(len(p) for p in eligible.values())
    as_total = sum(len(p) for p in assigned.values())
    enf_total = sum(len(p) for p in enforced.values())
    res_total = sum(len(p) for p in residual.values())

    profile_progress = source_doc.get("profile_progress", {})
    check_results = source_doc.get("check_results", {})
    all_roots = sorted(set(eligible) | set(assigned) | set(enforced) | set(check_results))

    roots: dict[str, dict[str, Any]] = {}
    finding_counts: dict[str, dict[str, int]] = {}
    for root in all_roots:
        r_el, r_as, r_enf, r_res = len(eligible.get(root, [])), len(assigned.get(root, [])), len(enforced.get(root, [])), len(residual.get(root, []))
        closed = (
            profile_progress.get(root, {}).get("root_closure", {}).get("closed", r_res == 0)
            if profile_progress else (r_res == 0 and r_el > 0)
        )
        r_check = check_results.get(root, {})
        r_st = r_check.get("status")
        if r_st == "passed":
            state = "passed"
        elif r_check.get("classification") == "tool-failure" or r_check.get("tool_failure"):
            state = "tool-failure"
        elif r_st == "failed":
            state = "finding"
        elif r_res > 0:
            state = "unassigned"
        else:
            state = r_st or "not-checked"

        roots[root] = {
            "eligible": r_el, "assigned": r_as, "enforced": r_enf,
            "residual": r_res, "closed": closed, "state": state,
            "tool_failure": bool(r_check.get("tool_failure") or r_check.get("classification") == "tool-failure"),
            "unknown_count": profile_progress[root]["unknown"]["count"],
            "finding_or_failure_count": profile_progress[root]["findings_or_tool_failures"]["count"],
        }
        root_fc: dict[str, int] = {}
        nested_checks = r_check.get("checks", {}) if isinstance(r_check, dict) else {}
        def count_findings(value: Any, prefix: str = "") -> None:
            if not isinstance(value, dict):
                return
            for key, item in value.items():
                label = f"{prefix}.{key}" if prefix else key
                if key in {"findings", "blocking_inventory", "deferred_inventory", "architecture_violations"} and isinstance(item, list):
                    root_fc[label] = len(item)
                elif isinstance(item, dict):
                    count_findings(item, label)
        count_findings(nested_checks)
        finding_counts[root] = root_fc

    cohorts_list = source_doc.get("cohorts", [])
    cohort_results = source_doc.get("cohort_results", {})
    cohort_regressions = sorted(str(r) for r in source_doc.get("cohort_regressions", []))

    cohort_summary = {
        "total": len(cohorts_list),
        "admitted": sum(1 for c in cohorts_list if c.get("admission") == "admitted"),
        "pending": sum(1 for c in cohorts_list if c.get("admission") == "pending"),
        "passed": sum(1 for _, rec in cohort_results.items() if rec.get("status") == "passed"),
        "failed": sum(1 for _, rec in cohort_results.items() if rec.get("status") == "failed"),
        "regression_count": len(cohort_regressions),
        "regressions": cohort_regressions,
    }

    governing_inputs = source_doc.get("governing_inputs", {})
    bindings = {
        "candidate_scope": source_doc.get("candidate_scope", "existing-index-and-nonignored-untracked"),
        "inventory_path": source_doc.get("inventory_path", "tools/ci/python_retention_inventory.json"),
        "inventory_sha256": governing_inputs[source_doc["inventory_path"]]["sha256"],
        "ratchet_sha256": source_doc.get("ratchet_sha256"),
        "governing_inputs": governing_inputs,
        "environment": source_doc.get("environment"),
        "history": source_doc.get("history"),
    }

    timings = {
        "validation_duration_seconds": float(source_doc.get("validation_duration_seconds", 0.0)),
        "cohort_evaluation_duration_seconds": float(source_doc.get("cohort_evaluation_duration_seconds", 0.0)),
        "duration_seconds": float(source_doc.get("duration_seconds", 0.0)),
        "root_check_seconds": {root: check.get("duration_seconds") for root, check in check_results.items()},
    }

    bounded_examples = {
        "residual": {root: sorted(paths)[:max_examples] for root, paths in sorted(residual.items()) if paths},
        "blockers": {
            cid: [source_doc["cohort_dependency_blockers"][i]
                  for i in rec["dependency_blocker_indices"]][:max_examples]
            for cid, rec in list((cid, rec) for cid, rec in sorted(cohort_results.items())
                                 if rec["status"] == "failed")[:max_examples]
        },
    }

    omitted: dict[str, dict[str, Any]] = {
        "candidate_files": make_collection_commitment(candidate, "candidate_file_digest", len(candidate)),
        "eligible_paths": make_collection_commitment(eligible, "eligible_path", el_total),
        "assigned_paths": make_collection_commitment(assigned, "assigned_path", as_total),
        "enforced_paths": make_collection_commitment(enforced, "enforced_path", enf_total),
        "residual_paths": make_collection_commitment(residual, "residual_path", res_total),
    }
    if cohorts_list:
        omitted["cohort_definitions"] = make_collection_commitment(cohorts_list, "cohort_definition", len(cohorts_list))
    if cohort_results:
        omitted["cohort_results"] = make_collection_commitment(cohort_results, "cohort_result", len(cohort_results))
    if "path_transitions" in source_doc:
        omitted["path_transitions"] = make_collection_commitment(
            source_doc["path_transitions"], "path_transition", len(source_doc["path_transitions"])
        )
    if check_results:
        omitted["check_results"] = make_collection_commitment(check_results, "check_result", len(check_results))

    atomic_groups = source_doc.get("atomic_groups")
    atomic_summary: dict[str, Any] | None = None
    if atomic_groups is not None:
        g_total = len(atomic_groups)
        g_passed = sum(1 for g in atomic_groups.values() if g.get("status") == "passed")
        g_effective = sum(1 for g in atomic_groups.values() if g.get("effective_enforcement"))
        g_blocked = sum(1 for g in atomic_groups.values() if g.get("status") == "failed")
        blockers_table = source_doc.get("cohort_dependency_blockers", [])
        group_examples = {
            gid: [
                blockers_table[i]
                for i in g.get("dependency_blocker_indices", [])
                if i < len(blockers_table)
            ][:max_examples]
            for gid, g in sorted(atomic_groups.items())
            if g.get("status") == "failed"
        }
        group_examples = dict(list(group_examples.items())[:max_examples])
        group_commitment = make_collection_commitment(
            atomic_groups, "atomic_group", g_total
        )
        atomic_summary = {
            "total": g_total,
            "passed": g_passed,
            "effective": g_effective,
            "blocked": g_blocked,
            "examples": group_examples,
            "commitment": group_commitment,
        }
        omitted["atomic_groups"] = group_commitment
        bounded_examples["atomic_groups"] = group_examples

    for name, value in source_doc.items():
        if isinstance(value, (dict, list, tuple, set, frozenset)):
            omitted.setdefault(name, make_collection_commitment(value,
                "mapping_entry" if isinstance(value, dict) else "sequence_element"))

    compact_doc = {
        "schema": COMPLETE_SCHEMA,
        "status": status,
        "classification": classification,
        "enforcement_complete": enforcement_complete,
        "complete": True,
        "counts": {"total_files": census},
        "totals": {"census": census, "eligible": el_total, "assigned": as_total, "enforced": enf_total, "residual": res_total},
        "roots": roots,
        "finding_counts": finding_counts,
        "cohorts": cohort_summary,
        "bindings": bindings,
        "timings": timings,
        "bounded_examples": bounded_examples,
        "omitted_collections": omitted,
        "sanitized_source_commitment": {
            "canonical_version": CANONICAL_VERSION,
            "sha256": hashlib.sha256(canonical_json_bytes(source_doc)).hexdigest(),
        },
    }
    if atomic_summary is not None:
        compact_doc["atomic_groups"] = atomic_summary
    validate_retention_evidence_schema(compact_doc)
    return compact_doc


def create_incomplete_retention_evidence(
    *,
    error: str,
    raw_output: str = "",
    classification: str = "tool-failure",
    returncode: int | None = None,
    failure_stage: str = "execution",
) -> dict[str, Any]:
    """Create a strictly validated incomplete retention evidence document."""
    raw_bytes = canonical_json_bytes(raw_output)
    incomplete_doc: dict[str, Any] = {
        "schema": INCOMPLETE_SCHEMA,
        "status": "failed",
        "classification": classification,
        "enforcement_complete": False,
        "complete": False,
        "error": error,
        "failure_stage": failure_stage,
        "returncode": returncode,
        "counts": {"total_files": 0},
        "totals": {"census": 0, "eligible": 0, "assigned": 0, "enforced": 0, "residual": 0},
        "roots": {},
        "finding_counts": {},
        "cohorts": {
            "total": 0, "admitted": 0, "pending": 0, "passed": 0, "failed": 0,
            "regression_count": 0, "regressions": [],
        },
        "bindings": {
            "candidate_scope": "incomplete-failure",
            "inventory_path": "tools/ci/python_retention_inventory.json",
        },
        "timings": {
            "validation_duration_seconds": 0.0,
            "cohort_evaluation_duration_seconds": 0.0,
            "duration_seconds": 0.0,
        },
        "bounded_examples": {"residual": {}, "blockers": {}},
        "omitted_collections": {},
        "sanitized_source_commitment": {
            "canonical_version": CANONICAL_VERSION,
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        },
    }
    validate_retention_evidence_schema(incomplete_doc)
    return incomplete_doc
