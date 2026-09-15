"""Path-level quality evidence and independently governed dependency attribution."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

def _path_values(value: object) -> set[str]:
    if not isinstance(value, (list, tuple, set)):
        return set()
    return {item for item in value if isinstance(item, str) and item}


def derive_profile_path_facts(
    result: Mapping[str, Any], requested_paths: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Derive conservative per-path facts from a completed profile result.

    A path is clean only when all three checks have complete, parseable output
    and the profile attested every requested path. Only dependency paths
    attributed by the inventory to a passing product ratchet may be separated.
    Other dependency and unattributed findings keep requested paths unknown.
    """
    requested = (_path_values(requested_paths) if requested_paths is not None
                 else _path_values(result.get("paths")))
    requested_paths_sorted = sorted(requested)
    empty = {
        "profile_executed_paths": [],
        "clean_under_profile": [],
        "finding_paths": [],
        "tool_failure_paths": [],
        "unknown_paths": [],
        "finding_or_tool_failure_paths": [],
        "evidence_complete": True,
    }
    if not requested:
        return empty

    checks = result.get("checks")
    if not isinstance(checks, Mapping):
        return {
            **empty,
            "unknown_paths": requested_paths_sorted,
            "tool_failure_paths": requested_paths_sorted,
            "finding_or_tool_failure_paths": requested_paths_sorted,
            "evidence_complete": False,
        }

    findings_paths: set[str] = set()
    dependency_or_unattributed = False
    checks_complete = True
    declared_unknown = _path_values(result.get("unknown_paths"))
    if not declared_unknown <= requested:
        dependency_or_unattributed = True
    for check_name in ("file_length", "ruff", "mypy"):
        check = checks.get(check_name)
        if not isinstance(check, Mapping) or check.get("completed") is not True:
            checks_complete = False
            continue
        findings = check.get("findings")
        if not isinstance(findings, list):
            checks_complete = False
            continue
        governed = _path_values(check.get("governed_dependency_paths"))
        for finding in findings:
            if not isinstance(finding, Mapping):
                checks_complete = False
                continue
            path = finding.get("path")
            if isinstance(path, str) and path in requested:
                findings_paths.add(path)
            elif (check_name == "mypy" and isinstance(path, str)
                  and path in governed and path.startswith("src/main/python/")):
                continue
            else:
                dependency_or_unattributed = True

    analyzed = _path_values(result.get("analyzed_paths"))
    attested = checks_complete and analyzed == requested
    tool_failure = bool(result.get("tool_failure") or result.get("classification") == "tool-failure")
    if not attested or tool_failure:
        unknown = set(requested)
        return {
            **empty,
            "finding_paths": sorted(findings_paths),
            "tool_failure_paths": sorted(unknown),
            "unknown_paths": sorted(unknown),
            "finding_or_tool_failure_paths": sorted(unknown),
            "evidence_complete": False,
        }

    if dependency_or_unattributed:
        return {
            **empty,
            "profile_executed_paths": requested_paths_sorted,
            "finding_paths": sorted(findings_paths),
            "unknown_paths": requested_paths_sorted,
            "finding_or_tool_failure_paths": requested_paths_sorted,
            "evidence_complete": True,
        }

    unknown = declared_unknown
    clean = requested - findings_paths - unknown
    return {
        **empty,
        "profile_executed_paths": requested_paths_sorted,
        "clean_under_profile": sorted(clean),
        "finding_paths": sorted(findings_paths),
        "unknown_paths": sorted(unknown),
        "finding_or_tool_failure_paths": sorted(findings_paths | unknown),
        "evidence_complete": True,
    }


def attribute_product_dependencies(
    result: dict[str, Any], governed_product_paths: Sequence[str],
) -> dict[str, Any]:
    """Separate debt only against a current passing, inventory-validated ratchet.

    The inventory caller owns that prerequisite and candidate binding. Raw
    findings/counts remain intact; raw statuses remain available beside the
    ownership-based statuses. Standalone profiles never assume this authority.
    """
    checks = result.get("checks")
    if (not isinstance(checks, Mapping) or result.get("tool_failure")
            or result.get("classification") == "tool-failure"):
        return result
    mypy = checks.get("mypy")
    if (not isinstance(mypy, Mapping) or mypy.get("completed") is not True
            or "status" not in mypy or "status" not in result):
        return result
    findings = mypy.get("findings")
    if not isinstance(findings, list) or not all(isinstance(f, Mapping) for f in findings):
        return result
    requested = _path_values(result.get("paths"))
    governed = {p for p in governed_product_paths
                if p.startswith("src/main/python/") and p not in requested}
    attributed = sorted({f["path"] for f in findings
                         if isinstance(f.get("path"), str) and f["path"] in governed})
    owned_mypy = dict(mypy, raw_status=mypy["status"], governed_dependency_paths=attributed)
    owned_mypy["status"] = (
        "passed" if all(f.get("path") in attributed for f in findings) else "failed"
    )
    owned_checks = dict(checks, mypy=owned_mypy)
    enriched = dict(result, raw_status=result["status"], checks=owned_checks)
    if "mypy" in result:
        enriched["mypy"] = owned_mypy
    facts = derive_profile_path_facts(enriched)
    enriched["status"] = "passed" if (
        all(c.get("status") == "passed" for c in owned_checks.values())
        and facts["evidence_complete"] and not facts["unknown_paths"]
        and set(facts["clean_under_profile"]) == requested
    ) else "failed"
    return enriched
