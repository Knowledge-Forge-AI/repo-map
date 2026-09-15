"""Derive per-path diagnostic facts for retained-product ratchet results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_QUALITY_SECTIONS = ("ruff", "mypy", "file_length")
_TYPE_TIERS = frozenset({"T0", "T1-seed"})


def _records(section: object, key: str) -> list[Mapping[str, Any]]:
    if not isinstance(section, Mapping):
        return []
    raw = section.get(key, [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _selection(snapshot: Mapping[str, Any]) -> tuple[list[str], dict[str, str]]:
    selection = snapshot.get("selection")
    modules = selection.get("modules", []) if isinstance(selection, Mapping) else []
    if not isinstance(modules, list):
        return [], {}
    tiers: dict[str, str] = {}
    for item in modules:
        if not isinstance(item, Mapping):
            continue
        path, tier = item.get("path"), item.get("tier")
        if isinstance(path, str) and path and isinstance(tier, str):
            tiers[path] = tier
    return sorted(tiers), tiers


def _actual_finding_paths(snapshot: Mapping[str, Any]) -> dict[str, set[str]]:
    paths: dict[str, set[str]] = {section: set() for section in _QUALITY_SECTIONS}
    ruff = _records(snapshot.get("ruff"), "findings")
    paths["ruff"] = {
        str(item["path"]) for item in ruff if isinstance(item.get("path"), str)
    }
    mypy = _records(snapshot.get("mypy"), "findings")
    paths["mypy"] = {
        str(item["path"]) for item in mypy if isinstance(item.get("path"), str)
    }
    lengths = _records(snapshot.get("file_length"), "ceilings")
    lengths.extend(_records(snapshot.get("file_length"), "hard_failures"))
    paths["file_length"] = {
        str(item["path"]) for item in lengths if isinstance(item.get("path"), str)
    }
    edges = _records(snapshot.get("migration_direction_imports"), "edges")
    paths["migration_direction_imports"] = {
        str(item["source_path"])
        for item in edges
        if isinstance(item.get("source_path"), str)
    }
    return paths


def _identity(item: Mapping[str, Any], fields: Sequence[str]) -> tuple[object, ...]:
    return tuple(item.get(field) for field in fields)


def _historical_paths(
    actual: Sequence[Mapping[str, Any]],
    baseline: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
    path_field: str,
) -> set[str]:
    before = {_identity(item, fields): item for item in baseline}
    allowed: set[str] = set()
    for item in actual:
        previous = before.get(_identity(item, fields))
        if previous is None or not isinstance(item.get(path_field), str):
            continue
        actual_count = item.get("count", item.get("line_count"))
        baseline_count = previous.get("count", previous.get("line_count"))
        if isinstance(actual_count, int) and isinstance(baseline_count, int) and actual_count <= baseline_count:
            allowed.add(str(item[path_field]))
    return allowed


def _type_evidence(
    type_evidence: Mapping[str, Any] | None,
    required: set[str],
) -> tuple[set[str], str]:
    if not required:
        return set(), "not-required"
    if not isinstance(type_evidence, Mapping):
        return set(), "not-provided"
    proven = type_evidence.get("profile_executed_paths")
    if not isinstance(proven, list):
        proven = type_evidence.get("blocking_targets")
    proven_paths = (
        {path for path in proven if isinstance(path, str)}
        if isinstance(proven, list)
        else set()
    )
    if type_evidence.get("status") == "passed" and not type_evidence.get("blocking_inventory"):
        matched = proven_paths & required
        if required <= proven_paths:
            return matched, "passed"
    return set(), "incomplete"


def build_product_profile_facts(
    snapshot: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    type_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return actual product profile facts without changing ratchet decisions."""
    selected, tiers = _selection(snapshot)
    selected_set = set(selected)
    actual = _actual_finding_paths(snapshot)
    ruff_actual = _records(snapshot.get("ruff"), "findings")
    mypy_actual = _records(snapshot.get("mypy"), "findings")
    length_section = snapshot.get("file_length")
    length_actual = _records(length_section, "ceilings")
    length_actual.extend(_records(length_section, "hard_failures"))
    edge_actual = _records(snapshot.get("migration_direction_imports"), "edges")
    historical = set()
    historical |= _historical_paths(
        ruff_actual,
        _records(baseline.get("ruff"), "findings"),
        ("path", "code", "message", "fingerprint"),
        "path",
    )
    historical |= _historical_paths(
        mypy_actual,
        _records(baseline.get("mypy"), "findings"),
        ("module", "path", "error_code", "normalized_fingerprint"),
        "path",
    )
    historical |= _historical_paths(
        length_actual,
        _records(baseline.get("file_length"), "ceilings"),
        ("path",),
        "path",
    )
    before_edges = {
        _identity(item, ("source_module", "source_path", "target_module", "target_tier"))
        for item in _records(baseline.get("migration_direction_imports"), "edges")
    }
    historical |= {
        str(item["source_path"])
        for item in edge_actual
        if _identity(item, ("source_module", "source_path", "target_module", "target_tier")) in before_edges
    }
    findings = set().union(*actual.values()) & selected_set
    required_type = {path for path in selected if tiers.get(path) in _TYPE_TIERS}
    proven_type, type_status = _type_evidence(type_evidence, required_type)
    unknown = required_type - proven_type
    clean = selected_set - findings - unknown
    return {
        "profile_executed_paths": selected,
        "clean_under_profile": sorted(clean),
        "finding_paths": sorted(findings),
        "tool_failure_paths": [],
        "unknown_paths": sorted(unknown),
        "finding_or_tool_failure_paths": sorted(findings),
        "evidence_complete": True,
        "actual_finding_paths": {
            name: sorted(values & selected_set) for name, values in actual.items()
        },
        "historical_allowed_paths": sorted(historical & selected_set),
        "type_evidence": {
            "required_paths": sorted(required_type),
            "proven_paths": sorted(proven_type),
            "unresolved_paths": sorted(unknown),
            "status": type_status,
        },
    }
