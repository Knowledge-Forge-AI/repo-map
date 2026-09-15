"""Reporting and compact summary formatting for Python retention inventory."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ci.python_quality_profiles import derive_profile_path_facts


PROFILES = {
    "product": "retained_python_ratchets",
    "tools": "clean_tooling",
    "test_support": "clean_test_support",
    "test_owners": "clean_test_owners",
    "conftest": "clean_conftest",
    "fixtures": "clean_fixture_owners",
}


def _path_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


def _category(
    count: int,
    paths: list[str],
    references: Mapping[str, list[str]],
    preferred_ref: str,
) -> dict[str, Any]:
    if paths:
        if paths == references.get(preferred_ref):
            return {"count": count, "paths_ref": preferred_ref}
        for name, referenced_paths in references.items():
            if paths == referenced_paths:
                return {"count": count, "paths_ref": name}
    return {"count": count, "paths": paths}


def _progress_facts(
    root: str, check_result: Mapping[str, Any] | None, assigned: list[str],
) -> dict[str, Any]:
    """Return profile facts, keeping ratchet-only product checks unknown."""
    if check_result is None:
        return derive_profile_path_facts({}, assigned)

    explicit = check_result.get("profile_path_facts")
    if isinstance(explicit, Mapping):
        facts = dict(explicit)
        expected = set(assigned)
        executed = set(_path_list(facts.get("profile_executed_paths")))
        clean = set(_path_list(facts.get("clean_under_profile")))
        findings = set(_path_list(facts.get("finding_paths")))
        failures = set(_path_list(facts.get("tool_failure_paths")))
        unknown = set(_path_list(facts.get("unknown_paths")))
        if not all(paths <= expected for paths in (executed, clean, findings, failures, unknown)):
            return derive_profile_path_facts({}, assigned)
        if facts.get("evidence_complete") is not True or not clean <= executed:
            return derive_profile_path_facts({}, assigned)
        unknown |= expected - (executed | clean | findings | failures | unknown)
        return {
            "profile_executed_paths": sorted(executed),
            "clean_under_profile": sorted(clean),
            "finding_paths": sorted(findings),
            "tool_failure_paths": sorted(failures),
            "unknown_paths": sorted(unknown),
            "finding_or_tool_failure_paths": sorted(
                set(_path_list(facts.get("finding_or_tool_failure_paths")))
                | findings | failures | unknown
            ),
            "evidence_complete": facts.get("evidence_complete") is True,
        }

    # The retained product checker proves historical/ratchet policy, not a
    # complete per-path Ruff/mypy/length execution.  Keep those paths unknown.
    if root == "product":
        return derive_profile_path_facts({}, assigned)
    return derive_profile_path_facts(check_result, assigned)


def _failed_solely_governed_dependencies(
    check_result: Mapping[str, Any] | None, governed: set[str],
) -> bool:
    if check_result is None or check_result.get("status") == "passed":
        return check_result is not None
    if (
        check_result.get("classification") == "tool-failure"
        or check_result.get("tool_failure")
        or (check_result.get("returncode") is not None and check_result.get("returncode") not in (0, 1))
        or check_result.get("reason") == "profile path attestation mismatch"
    ):
        return False
    checks = check_result.get("checks")
    if not isinstance(checks, Mapping):
        return False
    for name in ("ruff", "file_length"):
        c = checks.get(name)
        if isinstance(c, Mapping) and (c.get("findings") or c.get("status") not in ("passed", None)):
            return False
    mypy = checks.get("mypy")
    if not isinstance(mypy, Mapping) or not isinstance(mypy.get("findings"), list):
        return False
    requested = set(_path_list(check_result.get("paths")))
    return all(
        isinstance(f, Mapping) and (
            f.get("path") in governed and f.get("path") not in requested
        )
        for f in mypy["findings"]
    )


def _cohort_root(record: Mapping[str, Any]) -> str | None:
    root = record.get("root")
    return root if isinstance(root, str) and root in PROFILES else None


def build_profile_progress(result: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Build honest per-root profile progress without granting enforcement credit."""
    eligible_map, assigned_map = result.get("eligible", {}), result.get("assigned", {})
    check_map, enforced_map = result.get("check_results", {}), result.get("enforced", {})
    cohort_results = result.get("cohort_results", {})
    cohort_regressions = set(_path_list(result.get("cohort_regressions", [])))
    progress: dict[str, dict[str, Any]] = {}

    cohorts_by_root: dict[str, list[tuple[str, Mapping[str, Any]]]] = {root: [] for root in PROFILES}
    if isinstance(cohort_results, Mapping):
        for cid, crec in cohort_results.items():
            if isinstance(crec, Mapping) and (croot := _cohort_root(crec)) in cohorts_by_root:
                cohorts_by_root[croot].append((str(cid), crec))
    if isinstance(result.get("cohorts"), list):
        for item in result["cohorts"]:
            if isinstance(item, Mapping) and "id" in item and (croot := _cohort_root(item)) in cohorts_by_root:
                cid = str(item["id"])
                if cid not in {c[0] for c in cohorts_by_root[croot]}:
                    crec = cohort_results.get(cid, item) if isinstance(cohort_results, Mapping) else item
                    if isinstance(crec, Mapping):
                        cohorts_by_root[croot].append((cid, crec))

    for root, profile in PROFILES.items():
        eligible = _path_list(eligible_map.get(root) if isinstance(eligible_map, Mapping) else [])
        assigned = _path_list(assigned_map.get(root) if isinstance(assigned_map, Mapping) else [])
        raw_check = check_map.get(root) if isinstance(check_map, Mapping) else None
        check_result = raw_check if isinstance(raw_check, Mapping) else None
        facts = _progress_facts(root, check_result, assigned)
        executed = _path_list(facts.get("profile_executed_paths"))
        clean = _path_list(facts.get("clean_under_profile"))
        findings_or_failures = _path_list(facts.get("finding_or_tool_failure_paths"))
        unknown = _path_list(facts.get("unknown_paths"))
        effective = _path_list(enforced_map.get(root) if isinstance(enforced_map, Mapping) else [])

        root_cohorts = cohorts_by_root[root]
        cohort_effective: set[str] = set()
        if root_cohorts:
            cohort_effective = {
                m for cid, crec in root_cohorts
                if crec.get("status") == "passed" and cid not in cohort_regressions
                and crec.get("effective_enforcement") is True
                and crec.get("admission") == "admitted" and crec.get("evidence_complete") is True
                for m in _path_list(crec.get("members"))
            }
            # Reporting never manufactures credit from diagnostic or pending passes.

        references = {"eligible": eligible, "assigned": assigned, "enforced": effective}

        if root_cohorts:
            complete = (
                all(
                    crec.get("status") == "passed" and cid not in cohort_regressions
                    and crec.get("classification") != "tool-failure" and not crec.get("tool_failure")
                    and crec.get("evidence_complete") is True
                    and crec.get("admission") == "admitted"
                    and crec.get("effective_enforcement") is True
                    for cid, crec in root_cohorts
                )
                and set(eligible) <= {m for _, c in root_cohorts for m in _path_list(c.get("members"))}
            )
            closed = (
                complete and set(effective) == set(eligible) == cohort_effective
                and _failed_solely_governed_dependencies(check_result, {
                    p for paths in enforced_map.values() for p in _path_list(paths)
                })
            )
        else:
            closed = (
                check_result is not None and check_result.get("status") == "passed"
                and set(effective) == set(eligible)
            )

        progress[root] = {
            "profile": profile,
            "eligible": _category(len(eligible), eligible, references, "eligible"),
            "assigned": _category(len(assigned), assigned, references, "assigned"),
            "profile_executed": _category(len(executed), executed, references, "assigned"),
            "clean_under_profile": _category(len(clean), clean, references, "assigned"),
            "findings_or_tool_failures": _category(
                len(findings_or_failures), findings_or_failures, references, "unknown"
            ),
            "unknown": _category(len(unknown), unknown, references, "assigned"),
            "effectively_enforced": _category(len(effective), effective, references, "enforced"),
            "root_closure": {"closed": closed, "status": "closed" if closed else "open"},
        }
    return progress


def add_profile_progress(result: dict[str, Any]) -> dict[str, Any]:
    """Attach diagnostic profile progress while preserving enforcement fields."""
    return dict(result, profile_progress=build_profile_progress(result))


def compact_profile_result(result: dict[str, Any]) -> dict[str, Any]:
    """Keep each complete checker result once; omit only identical legacy aliases."""
    nested = result.get("checks", {})
    if not isinstance(nested, dict):
        return result
    return {
        key: value for key, value in result.items()
        if key not in ("ruff", "mypy", "file_length") or nested.get(key) != value
    }


def format_compact_summary(
    result: dict[str, Any],
    *,
    max_examples: int = 3,
    multiline: bool = False,
) -> str:
    """Format a compact failure summary: status/census/enrollment/residual/per-root tool vs finding/bounded examples."""
    status = result.get("status", "unknown")
    counts = result.get("counts", {})
    total_census = counts.get("total_files", len(result.get("candidate_sha256", {})))

    eligible_dict, assigned_dict = result.get("eligible", {}), result.get("assigned", {})
    enforced_dict = result.get("enforced", {})
    residual_dict = result.get("eligible_minus_enforced", result.get("unassigned", {}))

    eligible_count = sum(len(paths) for paths in eligible_dict.values())
    assigned_count = sum(len(paths) for paths in assigned_dict.values())
    profile_progress = result.get("profile_progress") or build_profile_progress(result)
    enforced_count = (
        sum(p["effectively_enforced"]["count"] for p in profile_progress.values())
        if profile_progress else sum(len(paths) for paths in enforced_dict.values())
    )

    cohort_results = result.get("cohort_results")
    cohort_regressions = [str(x) for x in result.get("cohort_regressions", []) if isinstance(x, str)]
    cohorts_list = result.get("cohorts")
    cohort_count = (
        len(cohorts_list) if isinstance(cohorts_list, list)
        else (len(cohort_results) if isinstance(cohort_results, dict) else 0)
    )
    has_cohort_ext = bool(
        "cohort_schema" in result or "cohort_regressions" in result
        or "cohort_results" in result or "cohorts" in result or "duration_seconds" in result
    )
    classification = result.get("classification")
    duration = result.get("duration_seconds")

    if has_cohort_ext and profile_progress:
        residual_count = sum(
            max(0, p["eligible"]["count"] - p["effectively_enforced"]["count"])
            for p in profile_progress.values()
        )
    else:
        residual_count = sum(len(paths) for paths in residual_dict.values())

    check_results = result.get("check_results", {})
    roots_in_scope = sorted(set(PROFILES) | set(eligible_dict) | set(check_results))

    root_details: list[tuple[str, str, int]] = []
    for root in roots_in_scope:
        if root not in eligible_dict and root not in check_results:
            continue
        res = check_results.get(root, {})
        root_st = res.get("status")
        if root_st == "passed":
            kind = "passed"
        elif (
            res.get("classification") == "tool-failure" or res.get("tool_failure")
            or (res.get("returncode") is not None and res.get("returncode") not in (0, 1))
            or res.get("reason") == "profile path attestation mismatch"
        ):
            kind = "tool-failure"
        elif root_st == "failed":
            kind = "finding"
        elif not root_st and root in residual_dict and len(residual_dict[root]) > 0:
            kind = "unassigned"
        else:
            kind = root_st or "not-checked"
        root_details.append((root, kind, len(residual_dict.get(root, []))))

    bounded_examples = {
        root: residual_dict[root][:max_examples]
        for root in roots_in_scope if residual_dict.get(root)
    }
    closed_roots = sum(1 for p in profile_progress.values() if p.get("root_closure", {}).get("closed"))
    total_roots = len(profile_progress)
    timing_str = f"{duration:.2f}s" if isinstance(duration, float) else f"{duration}s"
    bounded_reg = cohort_regressions[:max_examples]

    if multiline:
        lines = [f"status: {status}"]
        if classification is not None:
            lines.append(f"classification: {classification}")
        lines.extend([
            f"census: {total_census}",
            f"enrollment: eligible={eligible_count}, assigned={assigned_count}, enforced={enforced_count}",
            f"residual: {residual_count}",
        ])
        if has_cohort_ext:
            cparts = [f"cohorts: {cohort_count} total", f"regressions={len(cohort_regressions)}"]
            if duration is not None:
                cparts.append(f"timing={timing_str}")
            cparts.append(f"closure={closed_roots}/{total_roots}")
            lines.append(", ".join(cparts))
            if cohort_regressions:
                lines.append(f"bounded regressions: {bounded_reg}")
        lines.append("per-root breakdown:")
        for root, kind, res_len in root_details:
            res_str = f" ({res_len} residual)" if res_len > 0 else ""
            clean = profile_progress.get(root, {}).get("clean_under_profile", {}).get("count")
            progress = f"; clean_under_profile={clean}" if clean is not None else ""
            lines.append(f"  {root}: {kind}{res_str}{progress}")
        if bounded_examples:
            lines.append("bounded residual examples:")
            for root, examples in bounded_examples.items():
                lines.append(f"  {root}: {examples}")
        return "\n".join(lines)
    else:
        root_strs = [
            f"{root}={kind}" + (f" ({res_len} residual)" if res_len > 0 else "")
            for root, kind, res_len in root_details
        ]
        roots_joined = ", ".join(root_strs) if root_strs else "none"
        clean_counts = {
            root: item["clean_under_profile"]["count"]
            for root, item in profile_progress.items()
            if "clean_under_profile" in item and "count" in item["clean_under_profile"]
        }
        parts = [f"status={status}"]
        if classification is not None:
            parts.append(f"classification={classification}")
        parts.extend([
            f"census={total_census}",
            f"enrollment: eligible={eligible_count}, assigned={assigned_count}, enforced={enforced_count}",
            f"residual={residual_count}",
        ])
        if has_cohort_ext:
            reg_str = f"regressions={len(cohort_regressions)} {bounded_reg}" if cohort_regressions else "regressions=0"
            cparts = [f"cohorts={cohort_count}", reg_str]
            if duration is not None:
                cparts.append(f"timing={timing_str}")
            cparts.append(f"closure={closed_roots}/{total_roots}")
            parts.append(", ".join(cparts))
        parts.append(f"roots: {roots_joined}")
        if clean_counts:
            parts.append(f"clean_under_profile={clean_counts}")
        if bounded_examples:
            ex_strs = [f"{root}={examples}" for root, examples in bounded_examples.items()]
            parts.append(f"examples: {', '.join(ex_strs)}")
        return "; ".join(parts)


def render_inventory_text(result: dict[str, Any], check_mode: bool = False) -> str:
    """Render human-readable inventory summary text."""
    lines = [
        f"python-retention-inventory: {result['status']}",
        f"census files: {result['counts']['total_files']}",
        f"enforcement complete: {result['enforcement_complete']}",
    ]
    if "classification" in result:
        lines.append(f"classification: {result['classification']}")
    if "cohort_regressions" in result:
        lines.append(f"cohort regressions: {len(result['cohort_regressions'])}")
    if check_mode and result["status"] != "passed":
        lines.append(format_compact_summary(result, multiline=True))
    return "\n".join(lines)
