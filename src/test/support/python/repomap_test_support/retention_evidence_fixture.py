"""Complete deterministic retention reports for evidence contract tests."""
from __future__ import annotations

from typing import Any
from ci.python_retention_reporting import PROFILES, add_profile_progress
from ci.python_retention_cohort_checks import compact_cohort_records
from ci.python_retention_cohorts import COHORT_SCHEMA


def evidence_source(*, status: str = "passed", cohort_count: int = 2,
                    file_count: int = 10, regressions: list[str] | None = None,
                    root: str = "tools") -> dict[str, Any]:
    """Construct real result fields, with all paths covered by stable cohorts."""
    prefix = "tools/tool_" if root == "tools" else "src/main/python/repomap_kg/module_"
    files = [f"{prefix}{i}.py" for i in range(file_count)]
    reg_list = sorted(regressions or [])
    cohorts: list[dict[str, Any]] = []
    results: dict[str, Any] = {}
    enforced: list[str] = []
    checks: dict[str, Any] = {r: {"status": "passed", "paths": [], "reason": "empty applicable set"} for r in PROFILES}
    findings = [{"path": files[i % file_count], "code": "assignment", "message": "synthetic finding", "line": 1}
                for i, _ in enumerate(reg_list)]
    if root == "tools":
        for i in range(cohort_count):
            cid = f"cohort_{i:04d}"
            members = files[i::cohort_count]
            admission = "admitted" if status == "passed" or reg_list else "pending"
            passed = cid not in reg_list
            cohort = dict(id=cid, root=root, admission=admission, members=members,
                          rationale="Synthetic stable responsibility", governing_profile=PROFILES[root])
            cohorts.append(cohort)
            effective = passed and admission == "admitted"
            if effective:
                enforced.extend(members)
            results[cid] = dict(cohort, status="passed" if passed else "failed",
                evidence_complete=passed, effective_enforcement=effective,
                direct_findings={"ruff": [], "mypy": [reg_list.index(cid)] if not passed else [], "file_length": []},
                dependency_finding_indices=[], governed_dependencies=[], ungoverned_dependencies=[],
                dependency_blockers=[] if passed else ["direct findings present"], duration_seconds=0.001)
    elif status == "passed":
        enforced = files[:]
    checks[root] = dict(status="failed" if findings or root == "product" and status != "passed" else "passed",
                        paths=files[:], analyzed_paths=files[:], unknown_paths=[], duration_seconds=0.1,
                        checks={name: dict(status="failed" if name == "mypy" and findings else "passed",
                                           completed=True, count=len(findings) if name == "mypy" else 0,
                                           findings=findings if name == "mypy" else [], **({"limit": 400} if name == "file_length" else {}))
                                for name in ("ruff", "mypy", "file_length")})
    if root == "product" and status != "passed":
        checks[root].update(classification="tool-failure", tool_failure="QualityProfileError", returncode=2,
                            message="synthetic checker failure")
    inventory_path = "tools/ci/python_retention_inventory.json"
    source: dict[str, Any] = dict(status=status,
        classification="passed" if status == "passed" else "ratchet-regression" if reg_list else "tool-failure" if root == "product" else "policy-finding",
        enforcement_complete=status == "passed", census_complete=True, closure_valid=True, root_separation_valid=True,
        candidate_scope="existing-index-and-nonignored-untracked", counts={"total_files": file_count},
        candidate_sha256={path: f"{i:064x}" for i, path in enumerate(files)},
        eligible={r: files[:] if r == root else [] for r in PROFILES},
        assigned={r: files[:] if r == root else [] for r in PROFILES},
        enforced={r: sorted(enforced) if r == root else [] for r in PROFILES},
        eligible_minus_enforced={r: sorted(set(files)-set(enforced)) if r == root else [] for r in PROFILES},
        unassigned={r: [] for r in PROFILES},
        cohort_schema=COHORT_SCHEMA, cohorts=cohorts, cohort_results=results, cohort_regressions=reg_list,
        check_results=checks, path_transitions=[], inventory_path=inventory_path, ratchet_sha256="b"*64,
        governing_inputs={inventory_path: {"sha256": "a"*64, "bytes": 100},
                          "tools/ci/retained_python_ratchets.json": {"sha256": "b"*64, "bytes": 100}},
        history={"candidate": {"commit": "c"*40, "tree": "d"*40}, "candidate_inventory_sha256": "a"*64,
                 "comparison_basis": {"method": "first-parent", "commits": ["e"*40], "trees": ["f"*40],
                                      "audited_revisions": [{"commit": "e"*40, "tree": "f"*40, "inventory_sha256": "1"*64}]}},
        environment={"sha256": "2"*64, "input_count": 1, "versions": [["mypy", "2.1.0"]]},
        duration_seconds=1.0, validation_duration_seconds=0.1, cohort_evaluation_duration_seconds=0.1)
    source = compact_cohort_records(add_profile_progress(source))
    source.setdefault("cohort_dependency_paths", [])
    source.setdefault("cohort_dependency_blockers", [])
    return source
