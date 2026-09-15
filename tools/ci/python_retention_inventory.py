#!/usr/bin/env python3
"""Validate and enforce complete Python retention inventory closure and root separation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ci.python_retention_history_git import HistoryContext
from ci.retained_python_ratchets import RatchetContractError, validate_baseline
from ci.python_retention_cohorts import validate_cohorts
from ci.python_retention_cohort_evidence import evaluate_cohorts
from ci.python_retention_cohort_checks import compact_cohort_records
from ci.python_retention_environment import bind_environment
from ci.python_quality_profiles import check_paths
from ci.python_quality_ownership import attribute_product_dependencies
from ci.python_fixture_authority import FixtureAuthorityError, validate_fixture_manifest
from ci.python_retention_authorities import (
    RetentionAuthorityError, bind_inputs, validate_consistency, verify_bindings,
    validate_transition_history, validate_ownership_transitions,
)
from ci.python_retention_reporting import (
    PROFILES as PROFILES,
    compact_profile_result as compact_profile_result,
    format_compact_summary as format_compact_summary,
    render_inventory_text,
    add_profile_progress,
)


SCHEMA_VERSION = "repomap-python-retention-inventory-v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INVENTORY_PATH = REPO_ROOT / "tools" / "ci" / "python_retention_inventory.json"
DEFAULT_RATCHET_PATH = REPO_ROOT / "tools" / "ci" / "retained_python_ratchets.json"


def category_for_path(path: str) -> str:
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
    raise InventoryValidationError(f"Python path has no maintained root: {path}")


class InventoryValidationError(RuntimeError):
    """The retention inventory violated closure, categorization, or root separation."""


def load_inventory(inventory_path: Path = DEFAULT_INVENTORY_PATH) -> dict[str, Any]:
    if not inventory_path.is_file():
        raise InventoryValidationError(f"inventory file not found: {inventory_path}")
    try:
        with open(inventory_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError) as error:
        raise InventoryValidationError(f"failed to load inventory: {error}") from error
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        raise InventoryValidationError("inventory schema mismatch or invalid structure")
    return data


def git_candidate_python_files(repo_root: Path = REPO_ROOT) -> list[str]:
    """Return existing index plus nonignored untracked paths, losslessly."""
    try:
        raw = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "*.py"],
            cwd=repo_root, stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise InventoryValidationError("failed to query Git candidate files") from error
    return sorted({os.fsdecode(path) for path in raw.split(b"\0")
                   if path and (repo_root / os.fsdecode(path)).is_file()})


def validate_path_history(
    repo_root: Path, inventory_path: Path, current: set[str], data: dict,
    *, context: HistoryContext | None = None,
):
    """Preserve the public validation exception while exposing immutable history evidence."""
    from ci.python_retention_history import HistoryValidationError, validate_path_history as validate
    try:
        return validate(repo_root, inventory_path, current, data, context=context)
    except HistoryValidationError as error:
        raise InventoryValidationError(str(error)) from error


def validate_inventory(repo_root: Path = REPO_ROOT, inventory_path: Path = DEFAULT_INVENTORY_PATH,
                       ratchet_path: Path = DEFAULT_RATCHET_PATH,
                       *, context: HistoryContext | None = None) -> dict[str, Any]:
    """Reconcile the candidate census and assignments; never imply checks ran."""

    started = time.monotonic()
    data = load_inventory(inventory_path)
    files = data.get("files", [])
    if not isinstance(files, list):
        raise InventoryValidationError("inventory files collection is invalid")

    inventory_by_path: dict[str, dict[str, Any]] = {}
    for entry in files:
        if not isinstance(entry, dict) or "path" not in entry:
            raise InventoryValidationError("malformed file entry in inventory")
        path = entry["path"]
        if not isinstance(path, str) or not path.endswith(".py"):
            raise InventoryValidationError("invalid Python path")
        if (Path(path).is_absolute() or ".." in Path(path).parts
                or not (repo_root / path).resolve().is_relative_to(repo_root.resolve())):
            raise InventoryValidationError("inventory path escapes repository")
        if entry.get("root") != category_for_path(path):
            raise InventoryValidationError(f"incorrect root classification: {path}")
        confidence = entry.get("confidence")
        if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise InventoryValidationError(f"invalid finite confidence: {path}")
        if not isinstance(entry.get("rationale"), str) or not entry["rationale"].strip():
            raise InventoryValidationError(f"missing rationale: {path}")
        if not isinstance(entry.get("maintained_executable"), bool):
            raise InventoryValidationError(f"missing executable classification: {path}")
        profile = entry.get("governing_profile")
        analysis_input = (entry["root"] == "fixtures" and not entry["maintained_executable"]
                          and profile == "analysis_input")
        if not isinstance(profile, str) or (profile not in PROFILES.values() and not analysis_input):
            raise InventoryValidationError(f"unknown or inapplicable governing profile: {path}")
        if not entry["maintained_executable"] and entry["root"] != "fixtures":
            raise InventoryValidationError(f"non-executable exclusion requires fixture root: {path}")
        if (confidence < 0.8 or not entry["maintained_executable"]):
            if not isinstance(entry.get("counterevidence"), str) or not entry["counterevidence"].strip():
                raise InventoryValidationError(f"exclusion requires counterevidence: {path}")
        if path in inventory_by_path:
            raise InventoryValidationError(f"duplicate path in inventory: {path}")
        inventory_by_path[path] = entry

    tracked_files = git_candidate_python_files(repo_root)
    tracked_set = set(tracked_files)
    inventory_set = set(inventory_by_path)

    untracked_in_inventory = inventory_set - tracked_set
    if untracked_in_inventory:
        raise InventoryValidationError(
            f"inventory contains files absent from Git candidate: {sorted(untracked_in_inventory)[:5]}"
        )

    missing_from_inventory = tracked_set - inventory_set
    if missing_from_inventory:
        raise InventoryValidationError(
            f"Git candidate python files missing from inventory: {sorted(missing_from_inventory)[:5]}"
        )

    transitions = validate_path_history(repo_root, inventory_path, inventory_set, data, context=context)
    cohorts = validate_cohorts(data)
    try:
        fixture_result = validate_fixture_manifest(
            repo_root, repo_root / "tools/ci/python_fixture_authority.json")
        fixture_entries = fixture_result.get("entries")
        if not isinstance(fixture_entries, list):
            raise InventoryValidationError("fixture authority did not attest entries")
        for fixture in fixture_entries:
            if not isinstance(fixture, dict):
                raise InventoryValidationError("fixture authority entry is malformed")
            executable = fixture["role"] == "executable_first_party"
            if fixture["path"] not in inventory_by_path:
                raise InventoryValidationError(f"fixture authority path absent from Git candidate inventory: {fixture['path']}")
            if inventory_by_path[fixture["path"]]["maintained_executable"] != executable:
                raise InventoryValidationError(f"fixture classification contradicts role authority: {fixture['path']}")
    except FixtureAuthorityError as error:
        raise InventoryValidationError(str(error)) from error

    counts = {
        "total_files": len(files),
        "product_files": sum(1 for e in files if e.get("root") == "product"),
        "product_retained_ratchet_files": sum(1 for e in files if e.get("status") == "retained_ratchet"),
        "product_deferred_files": sum(1 for e in files if e.get("status") == "deferred_decomposition"),
        "tools_files": sum(1 for e in files if e.get("root") == "tools"),
        "test_support_files": sum(1 for e in files if e.get("root") == "test_support"),
        "executable_test_files": sum(1 for e in files if e.get("root") == "test_owners"),
        "unit_test_files": sum(1 for e in files if e.get("status") == "active_unit_test"),
        "int_test_files": sum(1 for e in files if e.get("status") == "active_int_test"),
        "conftest_root_files": sum(1 for e in files if e.get("root") == "conftest"),
        "fixture_files": sum(1 for e in files if e.get("root") == "fixtures"),
    }

    try:
        ratchet_data = json.loads(ratchet_path.read_text(encoding="utf-8"))
        validate_baseline(ratchet_data)
        selection = ratchet_data["selection"]["modules"]
        ratchet_paths = [item["path"] for item in selection]
    except (OSError, ValueError, KeyError, TypeError, RatchetContractError) as error:
        raise InventoryValidationError("required ratchet data missing or invalid") from error
    if len(ratchet_paths) != len(set(ratchet_paths)):
        raise InventoryValidationError("duplicate ratchet selection")
    if any(not isinstance(p, str) or not p.startswith("src/main/python/")
           for p in ratchet_paths):
        raise InventoryValidationError("root separation violation in product ratchet")
    inventory_retained = {e["path"] for e in files if e.get("status") == "retained_ratchet"}
    if inventory_retained != set(ratchet_paths):
        raise InventoryValidationError("inventory retained set does not match ratchet selection")
    try:
        validate_consistency(repo_root, files, selection)
        ownership_path = repo_root / "tools/ci/python_type_ownership.json"
        if ratchet_data["ownership"]["sha256"] != hashlib.sha256(ownership_path.read_bytes()).hexdigest():
            raise RetentionAuthorityError("ratchet baseline does not bind effective type ownership")
        validate_transition_history(repo_root, [entry["commit"] for entry in
                                    transitions.evidence["comparison_basis"]["audited_revisions"]])
        validate_ownership_transitions(repo_root, files, [entry["commit"] for entry in
                                       transitions.evidence["comparison_basis"]["audited_revisions"]])
        governing_inputs = bind_inputs(repo_root, inventory_path, ratchet_path)
    except (RetentionAuthorityError, ValueError) as error:
        raise InventoryValidationError(str(error)) from error
    eligible: dict[str, list[str]] = {root: [] for root in PROFILES}
    assigned: dict[str, list[str]] = {root: [] for root in PROFILES}
    for entry in files:
        if not entry["maintained_executable"] or entry["confidence"] < 0.8:
            continue
        root = entry["root"]
        path = entry["path"]
        eligible[root].append(path)
        profile = entry.get("governing_profile")
        if profile != PROFILES[root]:
            continue
        if root != "product" or path in ratchet_paths:
            assigned[root].append(path)
    residual = {root: sorted(set(eligible[root]) - set(assigned[root])) for root in PROFILES}
    return {
        "status": "not_checked",
        **({"cohorts": cohorts, "cohort_schema": data["cohort_schema"]}
           if "cohort_schema" in data else {}),
        "validation_duration_seconds": time.monotonic() - started,
        "counts": counts,
        "root_separation_valid": True,
        "closure_valid": True,
        "census_complete": True,
        "candidate_sha256": {path: hashlib.sha256((repo_root / path).read_bytes()).hexdigest()
                             for path in sorted(inventory_set)},
        "path_transitions": list(transitions),
        "history": transitions.evidence,
        "fixture_authority": fixture_result,
        "ratchet_sha256": hashlib.sha256(ratchet_path.read_bytes()).hexdigest(),
        "candidate_scope": "existing-index-and-nonignored-untracked",
        "minimum_confidence": 0.8,
        "eligible": {root: sorted(paths) for root, paths in eligible.items()},
        "assigned": {root: sorted(paths) for root, paths in assigned.items()},
        "unassigned": residual,
        "enforcement_complete": False,
        "check_results": {},
        "governing_inputs": governing_inputs,
        "inventory_path": inventory_path.resolve().relative_to(repo_root.resolve()).as_posix(),
    }


def check_inventory(result: dict[str, Any], repo_root: Path, ratchet_path: Path) -> dict[str, Any]:
    """Execute closed quality owners for the exact reconciled candidate."""
    started = time.monotonic()
    environment = bind_environment() if result.get("cohort_schema") else None
    checks: dict[str, Any] = {}
    original = result["candidate_sha256"]
    def candidate_unchanged() -> bool:
        verify_bindings(repo_root, result["governing_inputs"],
                        repo_root / result["inventory_path"], ratchet_path)
        return (hashlib.sha256(ratchet_path.read_bytes()).hexdigest() == result["ratchet_sha256"]
                and set(git_candidate_python_files(repo_root)) == set(original)
                and all(hashlib.sha256((repo_root / path).read_bytes()).hexdigest() == digest
                        for path, digest in original.items()))
    if not candidate_unchanged():
        raise InventoryValidationError("candidate changed before quality checks")
    for root, paths in result["assigned"].items():
        if not paths:
            checks[root] = {"status": "passed", "paths": [], "reason": "empty applicable set"}
        elif root == "product":
            command = [sys.executable, "tools/ci/retained_python_ratchets.py",
                       "--baseline", str(ratchet_path)]
            run = subprocess.run(command, cwd=repo_root, capture_output=True, text=True,
                                 check=False, timeout=300)
            try:
                document = json.loads(run.stdout)
            except ValueError:
                document = {}
            passed = (run.returncode == 0
                      and document.get("schema") == "repomap-retained-python-ratchets-result-v1"
                      and document.get("classification") == "passed")
            type_run = subprocess.run(
                [sys.executable, "tools/ci/python_type_check.py"], cwd=repo_root,
                capture_output=True, text=True, check=False, timeout=300)
            try:
                type_result = json.loads(type_run.stdout)
            except ValueError:
                type_result = {}
            passed = (passed and type_run.returncode == 0
                      and type_result.get("schema") == "repomap-python-type-check-v1"
                      and "tool_failure" not in type_result
                      and not type_result.get("blocking_inventory")
                      and not type_result.get("architecture_violations"))
            tool_failed = (
                run.returncode not in (0, 1) or type_run.returncode not in (0, 1)
                or document.get("schema") != "repomap-retained-python-ratchets-result-v1"
                or type_result.get("schema") != "repomap-python-type-check-v1"
                or "tool_failure" in type_result
            )
            checks[root] = {
                "status": "passed" if passed else "failed", "paths": paths,
                "profile_path_facts": document.pop("profile_path_facts", None),
                "returncode": run.returncode, "type_returncode": type_run.returncode,
                "classification": "tool-failure" if tool_failed else (
                    "passed" if passed else "policy-finding"
                ),
                "checks": {"retained_ratchet": document, "type_ownership": type_result},
            }
        else:
            checks[root] = compact_profile_result(
                check_paths(tuple(paths), repo_root=repo_root, raise_on_error=False)
            )
            if sorted(checks[root].get("paths", [])) != sorted(paths):
                checks[root] = {"status": "failed", "reason": "profile path attestation mismatch"}
    if not candidate_unchanged():
        raise InventoryValidationError("candidate changed during quality checks")
    product_check = checks.get("product", {})
    if product_check.get("status") == "passed":
        for root in checks:
            if root != "product":
                checks[root] = attribute_product_dependencies(
                    checks[root], result["assigned"]["product"],
                )
    effective = {root: result["assigned"][root] if checks[root]["status"] == "passed" else []
                 for root in PROFILES}
    cohort_evidence = evaluate_cohorts(
        result["cohorts"], checks, repo_root, sorted(original),
        result["assigned"]["product"] if product_check.get("status") == "passed" else [],
    ) if result.get("cohort_schema") else {}
    effective.update(cohort_evidence.get("enforced", {}))
    if environment is not None and bind_environment() != environment:
        raise InventoryValidationError("installed tool or typing inputs changed during enforcement")
    if not candidate_unchanged():
        raise InventoryValidationError("candidate changed during cohort evaluation")
    result = dict(result, cohort_results=cohort_evidence.get("cohort_results", {}),
                  atomic_groups=cohort_evidence.get("atomic_groups", {}),
                  cohort_regressions=cohort_evidence.get("regressions", []),
                  cohort_evaluation_duration_seconds=cohort_evidence.get("evaluation_duration_seconds", 0),
                  environment=environment, duration_seconds=(
                      result.get("validation_duration_seconds", 0) + time.monotonic() - started))
    residual = {root: sorted(set(result["eligible"][root]) - set(effective[root]))
                for root in PROFILES}
    passed = not any(residual.values()) and all(
        c["status"] == "passed" for root, c in checks.items()
        if root not in cohort_evidence.get("enforced", {}))
    classification = "ratchet-regression" if result["cohort_regressions"] else (
        "tool-failure" if any(c.get("classification") == "tool-failure" or c.get("tool_failure")
                              for c in checks.values()) else "passed" if passed else "policy-finding")
    return compact_cohort_records(add_profile_progress(dict(result, classification=classification,
                status="passed" if passed else "failed", check_results=checks,
                enforced=effective, eligible_minus_enforced=residual, enforcement_complete=passed)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="repository root directory")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY_PATH, help="inventory json file path")
    parser.add_argument("--ratchet", type=Path, default=DEFAULT_RATCHET_PATH, help="ratchet json file path")
    parser.add_argument("--check", action="store_true", help="execute applicable quality owners")
    parser.add_argument("--json", action="store_true", help="output JSON result")
    args = parser.parse_args(argv)

    try:
        result = validate_inventory(repo_root=args.repo_root, inventory_path=args.inventory, ratchet_path=args.ratchet)
        if args.check:
            result = check_inventory(result, args.repo_root, args.ratchet)
        if args.json:
            print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        else:
            print(render_inventory_text(result, check_mode=args.check))
        return 2 if result.get("cohort_regressions") else (0 if result["status"] == "passed" else 1)
    except (InventoryValidationError, RetentionAuthorityError, OSError, subprocess.SubprocessError) as error:
        if args.json:
            print(json.dumps({"status": "failed", "error": str(error)}, indent=2))
        else:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
