"""Validate batched evidence before attributing any cohort credit."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def checked_findings(check: Mapping[str, Any], members: set[str]) -> tuple[
    dict[str, list[dict[str, Any]]], list[str]
]:
    """Keep malformed, partial and failed tool output distinct from direct debt."""
    errors: list[str] = []
    output: dict[str, list[dict[str, Any]]] = {}
    if (check.get("status") not in {"passed", "failed"}
            or check.get("classification") == "tool-failure" or check.get("tool_failure")
            or check.get("returncode") not in (None, 0, 1)):
        errors.append("root tool failure")
    requested = check.get("paths")
    analyzed = check.get("analyzed_paths")
    if (not isinstance(requested, list) or not isinstance(analyzed, list)
            or any(not isinstance(p, str) for p in requested + analyzed)
            or set(requested) != set(analyzed) or not members <= set(analyzed)
            or check.get("unknown_paths")):
        errors.append("root incomplete path attestation")
    checks = check.get("checks")
    for name in ("ruff", "mypy", "file_length"):
        item = checks.get(name) if isinstance(checks, Mapping) else None
        if (not isinstance(item, Mapping) or item.get("completed") is not True
                or item.get("status") not in {"passed", "failed"}):
            errors.append(f"root incomplete {name} check")
            continue
        findings = item.get("findings")
        if (not isinstance(findings, list) or any(
            not isinstance(f, dict) or not isinstance(f.get("path"), str) or not f["path"]
            or ("code" in f and not isinstance(f["code"], str))
            or ("message" in f and not isinstance(f["message"], str))
            for f in findings
        )):
            errors.append(f"root malformed {name} findings")
            continue
        # Attributed statuses may pass with preserved raw findings, but an
        # unexplained failed tool status cannot authorize zero-debt members.
        if not findings and item["status"] == "failed":
            errors.append(f"root unexplained {name} failure")
        if name == "file_length" and item.get("limit", 400) != 400:
            errors.append("root file-length limit mismatch")
        if name != "mypy" and any(f["path"] not in members for f in findings):
            errors.append(f"root unknown attribution for {name}")
        output[name] = findings
    return output, errors


def reachable_paths(starts: Sequence[str], graph: Mapping[str, Sequence[str]]) -> set[str]:
    """Return the static transitive dependency population without recursive IO."""
    found: set[str] = set()
    pending = list(starts)
    while pending:
        path = pending.pop()
        if path in found:
            continue
        found.add(path)
        pending.extend(graph.get(path, ()))
    return found


def compact_cohort_records(result: dict[str, Any]) -> dict[str, Any]:
    """Index repeated dependency paths and blockers without dropping evidence."""
    records = result.get("cohort_results", {})
    groups = result.get("atomic_groups")
    if not records and not groups:
        return result
    rec_paths = {
        path
        for record in records.values()
        for field in ("governed_dependencies", "ungoverned_dependencies")
        for path in record.get(field, [])
    }
    grp_paths = (
        {
            path
            for group in groups.values()
            for field in ("external_dependencies", "ungoverned_dependencies")
            for path in group.get(field, [])
        }
        if groups
        else set()
    )
    paths = sorted(rec_paths | grp_paths)
    rec_reasons = {
        reason
        for record in records.values()
        for reason in record.get("dependency_blockers", [])
    }
    grp_reasons = (
        {
            reason
            for group in groups.values()
            for reason in group.get("dependency_blockers", [])
        }
        if groups
        else set()
    )
    reasons = sorted(rec_reasons | grp_reasons)
    path_index = {path: index for index, path in enumerate(paths)}
    reason_index = {reason: index for index, reason in enumerate(reasons)}
    compact = {}
    for cid, record in records.items():
        item = dict(record)
        for field in ("governed", "ungoverned"):
            if f"{field}_dependencies" in item:
                item[f"{field}_dependency_indices"] = [
                    path_index[path] for path in item.pop(f"{field}_dependencies", [])
                ]
        if "dependency_blockers" in item:
            item["dependency_blocker_indices"] = [
                reason_index[reason] for reason in item.pop("dependency_blockers", [])
            ]
        compact[cid] = item
    out = dict(
        result,
        cohort_results=compact,
        cohort_dependency_paths=paths,
        cohort_dependency_blockers=reasons,
    )
    if groups is not None:
        compact_groups = {}
        for gid, group in groups.items():
            g_item = dict(group)
            if "external_dependencies" in g_item:
                g_item["external_dependency_indices"] = [
                    path_index[path] for path in g_item.pop("external_dependencies", [])
                ]
            if "ungoverned_dependencies" in g_item:
                g_item["ungoverned_dependency_indices"] = [
                    path_index[path] for path in g_item.pop("ungoverned_dependencies", [])
                ]
            if "dependency_blockers" in g_item:
                g_item["dependency_blocker_indices"] = [
                    reason_index[reason] for reason in g_item.pop("dependency_blockers", [])
                ]
            compact_groups[gid] = g_item
        out["atomic_groups"] = compact_groups
    return out
