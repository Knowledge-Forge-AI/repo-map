"""Fail-closed cohort evidence evaluation and dependency resolution."""

from __future__ import annotations

from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ci.python_retention_atomic import build_atomic_groups
from ci.python_retention_cohort_checks import checked_findings, reachable_paths
from ci.python_retention_dependencies import (
    build_dependency_graph,
    cohort_leaving_dependencies,
    find_cross_cohort_cycles,
    validate_candidate_path,
)

COHORT_PROFILES = {
    "tools": "clean_tooling",
    "test_support": "clean_test_support",
    "test_owners": "clean_test_owners",
}
VALID_ADMISSIONS = frozenset({"pending", "admitted"})


class CohortEvidenceError(ValueError):
    """Cohort inputs, roots, or members violated the evidence contract."""


def category_for_path(path: str) -> str:
    """Return canonical retention root classification for a path."""
    if path.startswith("src/main/python/"):
        return "product"
    if path.startswith("src/test/fixtures/"):
        return "fixtures"
    if path == "src/test/conftest.py":
        return "conftest"
    if path.startswith("src/test/support/python/"):
        return "test_support"
    if path.startswith(("src/test/unit/python/", "src/test/int/python/")):
        return "test_owners"
    if path.startswith("tools/"):
        return "tools"
    raise CohortEvidenceError(f"Python path has no maintained root: {path}")


def _get_tool_check(root_check: Mapping[str, Any], tool: str) -> Mapping[str, Any] | None:
    nested = root_check.get("checks")
    if isinstance(nested, Mapping) and tool in nested and isinstance(nested[tool], Mapping):
        return nested[tool]
    top = root_check.get(tool)
    return top if isinstance(top, Mapping) else None


def _validate_cohort_definitions(
    cohorts: Sequence[Mapping[str, Any]],
    candidate_paths: Sequence[str],
    repo_root: Path,
) -> tuple[dict[str, list[str]], set[str]]:
    blockers: dict[str, list[str]] = {}
    seen_members: dict[str, str] = {}
    seen_ids: set[str] = set()
    candidate_set = set(candidate_paths)

    for c in cohorts:
        if not isinstance(c, Mapping):
            raise CohortEvidenceError("cohort definition must be a mapping")
        cid = c.get("id")
        if not isinstance(cid, str) or not cid.strip():
            raise CohortEvidenceError(f"invalid cohort id: {cid!r}")
        if cid in seen_ids:
            raise CohortEvidenceError(f"duplicate cohort id: {cid}")
        seen_ids.add(cid)
        blockers[cid] = []

        root = c.get("root")
        if root not in COHORT_PROFILES:
            blockers[cid].append(f"unsupported cohort root: {root}")

        profile = c.get("governing_profile")
        if profile != COHORT_PROFILES.get(str(root)):
            blockers[cid].append(f"governing profile mismatch: {profile} != {COHORT_PROFILES.get(str(root))}")

        admission = c.get("admission")
        if admission not in VALID_ADMISSIONS:
            blockers[cid].append(f"invalid admission state: {admission}")

        rationale = c.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            blockers[cid].append("missing or empty rationale")

        members = c.get("members")
        if not isinstance(members, (list, tuple)) or not members:
            blockers[cid].append("cohort members must be a non-empty sequence")
            continue

        for m in members:
            if not isinstance(m, str) or not m.endswith(".py"):
                blockers[cid].append(f"bad member path: {m!r}")
                continue
            if m not in candidate_set:
                blockers[cid].append(f"bad member not in candidate paths: {m}")
                continue
            try:
                validate_candidate_path(m, repo_root)
            except Exception as error:
                blockers[cid].append(f"bad member alias or traversal: {m} ({error})")
                continue
            try:
                cat = category_for_path(m)
                if cat != root:
                    blockers[cid].append(f"bad member root mismatch: {m} ({cat} != {root})")
            except CohortEvidenceError as error:
                blockers[cid].append(f"bad member classification error: {error}")
            if m in seen_members:
                message = f"duplicate member across cohorts: {m} in {seen_members[m]} and {cid}"
                blockers[cid].append(message)
                blockers[seen_members[m]].append(message)
            seen_members[m] = cid

    return blockers, seen_ids


def evaluate_cohorts(
    cohorts: list[dict[str, Any]], checks: dict[str, Any], repo_root: Path,
    candidate_paths: Sequence[str], governed_product_paths: Sequence[str],
) -> dict[str, Any]:
    """Revalidate declared cohorts; pending evidence never proves another cohort."""
    started = time.monotonic()
    blockers, _ = _validate_cohort_definitions(cohorts, candidate_paths, repo_root)
    graph = build_dependency_graph(repo_root, candidate_paths)
    cycles = find_cross_cohort_cycles(cohorts, graph["dependencies"])
    seed = {p for p in governed_product_paths
            if p in candidate_paths and p.startswith("src/main/python/")
            and p not in graph["errors"]}
    members = {c["id"]: set(c["members"]) for c in cohorts}
    leaving = {c["id"]: set(cohort_leaving_dependencies(c["members"], graph["dependencies"]))
               for c in cohorts}
    reachable = {c["id"]: reachable_paths(c["members"], graph["dependencies"]) for c in cohorts}
    findings: dict[str, dict[str, list[int]]] = {c["id"]: {name: [] for name in ("ruff", "mypy", "file_length")} for c in cohorts}
    dependency_refs: dict[str, list[int]] = {c["id"]: [] for c in cohorts}
    durations = {c["id"]: 0.0 for c in cohorts}
    for root in COHORT_PROFILES:
        root_cohorts = [c for c in cohorts if c["root"] == root]
        if not root_cohorts:
            continue
        root_members = {p for c in root_cohorts for p in c["members"]}
        raw = checks.get(root, {})
        root_findings, failures = checked_findings(raw, root_members)
        for c in root_cohorts:
            tick = time.monotonic()
            cid = c["id"]
            blockers[cid].extend(failures)
            for name, items in root_findings.items():
                findings[cid][name] = [i for i, item in enumerate(items) if item["path"] in members[cid]]
            if any(findings[cid].values()):
                blockers[cid].append("direct findings present")
            for path in c["members"]:
                if path in graph["dynamic_uncertainty"]:
                    blockers[cid].append(f"dynamic import uncertainty in {path}")
                if path in graph["unresolved_imports"]:
                    blockers[cid].append(f"unresolved imports in {path}: {graph['unresolved_imports'][path]}")
                if path in graph["errors"]:
                    blockers[cid].append(f"file error in {path}")
                elif path in candidate_paths:
                    content = (repo_root / path).read_bytes()
                    if content.count(b"\n") + bool(content and not content.endswith(b"\n")) > 400:
                        blockers[cid].append(f"physical length exceeds 400: {path}")
            durations[cid] += time.monotonic() - tick
        for index, item in enumerate(root_findings.get("mypy", [])):
            path = item["path"]
            if path in root_members:
                continue  # Direct debt belongs to its member; dependents wait for it.
            invalid = path not in candidate_paths or path in graph["errors"]
            stub = item.get("code") in {"import-untyped", "import-not-found"} or "library stub" in item.get("message", "")
            # An exact passing product path is independently governed even if
            # the checker reported it through imports outside our static graph.
            affected = [c for c in root_cohorts if path in reachable[c["id"]]]
            if path in seed and not stub:
                affected = affected or root_cohorts
            elif not affected or invalid:
                for c in root_cohorts:
                    blockers[c["id"]].append(f"root unknown attribution: mypy finding {index}")
                continue
            for c in affected:
                cid = c["id"]
                dependency_refs[cid].append(index)
                if stub:
                    blockers[cid].append(f"missing stub dependency at {path}: finding {index}")
                elif path not in members[cid]:
                    leaving[cid].add(path)
    by_id = {c["id"]: c for c in cohorts}
    atomic_groups, cohort_to_group = build_atomic_groups(
        cycles, by_id, leaving, graph["dependencies"], COHORT_PROFILES
    )
    singleton_ids = {c["id"] for c in cohorts if c["id"] not in cohort_to_group}
    remaining_singletons = set(singleton_ids)
    remaining_groups = set(atomic_groups.keys())
    governed = set(seed)
    passed: set[str] = set()

    while True:
        ready_singletons = [
            cid for cid in sorted(remaining_singletons)
            if not blockers[cid] and leaving[cid] <= governed
        ]
        ready_groups = [
            gid for gid in sorted(remaining_groups)
            if atomic_groups[gid].can_pass(blockers, governed)
        ]
        if not ready_singletons and not ready_groups:
            break
        for cid in ready_singletons:
            tick = time.monotonic()
            passed.add(cid)
            remaining_singletons.remove(cid)
            if by_id[cid]["admission"] == "admitted":
                governed.update(members[cid])
            durations[cid] += time.monotonic() - tick
        for gid in ready_groups:
            tick = time.monotonic()
            group = atomic_groups[gid]
            group.mark_passed()
            remaining_groups.remove(gid)
            for cid in group.cohort_ids:
                passed.add(cid)
            if group.is_all_admitted:
                governed.update(group.all_members)
            duration_per_cid = (time.monotonic() - tick) / max(1, len(group.cohort_ids))
            for cid in group.cohort_ids:
                durations[cid] += duration_per_cid

    for gid in sorted(remaining_groups):
        atomic_groups[gid].mark_failed(governed, blockers)

    for cid in sorted(remaining_singletons):
        unmet = sorted(leaving[cid] - governed)
        if unmet:
            blockers[cid].append("unmet leaving dependencies")

    records = {}
    enforced: dict[str, list[str]] = {root: [] for root in COHORT_PROFILES}
    regressions = []
    for c in cohorts:
        cid = c["id"]
        if cid in cohort_to_group:
            gid = cohort_to_group[cid]
            group = atomic_groups[gid]
            effective = cid in passed and c["admission"] == "admitted"
            if group.status == "passed":
                unmet = []
                gov_deps = sorted(leaving[cid] & governed)
            else:
                unmet = sorted((leaving[cid] - group.all_members) - governed)
                gov_deps = sorted((leaving[cid] - group.all_members) & governed)
            record_extra = {"atomic_group_id": gid}
        else:
            effective = cid in passed and c["admission"] == "admitted"
            unmet = sorted(leaving[cid] - governed)
            gov_deps = sorted(leaving[cid] & governed)
            record_extra = {}

        if effective:
            enforced[c["root"]].extend(c["members"])
        elif c["admission"] == "admitted":
            regressions.append(cid)

        records[cid] = dict(
            {key: value for key, value in c.items() if key != "rationale"},
            definition_ref=f"cohorts[id={cid}]",
            status="passed" if cid in passed else "failed",
            effective_enforcement=effective,
            evidence_complete=cid in passed,
            direct_findings=findings[cid],
            dependency_finding_indices=dependency_refs[cid],
            dependency_blockers=sorted(set(blockers[cid])),
            ungoverned_dependencies=unmet,
            governed_dependencies=gov_deps,
            duration_seconds=durations[cid],
            shared_check_ref=f"check_results.{c['root']}.duration_seconds",
            **record_extra,
        )

    return {
        "cohort_results": records,
        "enforced": {root: sorted(set(paths)) for root, paths in enforced.items()},
        "regressions": sorted(regressions),
        "evaluation_duration_seconds": time.monotonic() - started,
        "atomic_groups": {gid: group.to_record() for gid, group in sorted(atomic_groups.items())},
    }
