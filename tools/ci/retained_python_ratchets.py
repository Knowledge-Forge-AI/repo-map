#!/usr/bin/env python3
"""Enforce architecture-derived quality ratchets for retained Python."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
from typing import Mapping, Sequence

if __package__ in (None, ""):
    tools_root = Path(__file__).resolve().parents[1]
    if str(tools_root) not in sys.path:
        sys.path.insert(0, str(tools_root))

from ci.file_length_policy import (
    FAILURE_LIMIT,
    WARNING_LIMIT,
)
from ci.python_type_check import (
    TypeCheckToolError,
    _attest_environment,
)
from ci.python_type_ownership import (
    DEFAULT_MANIFEST,
    ROOT,
    OwnershipManifest,
    OwnershipManifestError,
    load_manifest,
    maintained_modules,
)
from ci.retained_python_comparison import (
    _relative as _relative,
    compare_counted,
    compare_file_lengths,
    compare_selection,
    file_length_inventory as _file_length_inventory,
    has_policy_deltas,
    migration_edges as _migration_edges,
    mypy_inventory as _mypy_inventory,
    normalize_ruff_inventory as _normalize_ruff_inventory,
    result_comparison,
    select_retained_modules as _select_retained_modules,
    selection_delta as selection_delta,
    summary_counts,
)
from ci.retained_python_records import (
    BASELINE_SCHEMA as BASELINE_SCHEMA,
    BaselineDocument,
    FileLengthRecord,
    ImportEdgeRecord,
    MypyFindingRecord,
    RecordValidationError,
    RuffFindingRecord,
    SelectionModuleRecord,
    SnapshotDocument,
    baseline_document as baseline_document,
    render_document,
    write_baseline_atomic,
)
from ci.retained_python_contract import (
    EXPECTED_MYPY_CONFIG as EXPECTED_MYPY_CONFIG,
    EXPECTED_TOOLS as EXPECTED_TOOLS,
    RatchetContractError as RatchetContractError,
    RETAINED_CLASSES as RETAINED_CLASSES,
    RETAINED_TIERS as RETAINED_TIERS,
    RESULT_SCHEMA as RESULT_SCHEMA,
    RUFF_RULES as RUFF_RULES,
    validate_baseline as validate_baseline,
)
from ci.python_retention_product_progress import build_product_profile_facts


def select_retained_modules(
    modules: Mapping[str, Path], manifest: OwnershipManifest, repo_root: Path = ROOT
) -> tuple[SelectionModuleRecord, ...]:
    try:
        return _select_retained_modules(modules, manifest, RETAINED_CLASSES, repo_root)
    except RecordValidationError as error:
        raise RatchetContractError(str(error)) from error


def normalize_ruff_inventory(
    findings: object, selected_paths: frozenset[str], repo_root: Path = ROOT
) -> tuple[RuffFindingRecord, ...]:
    try:
        return _normalize_ruff_inventory(findings, selected_paths, repo_root)
    except RecordValidationError as error:
        raise RatchetContractError(str(error)) from error


def mypy_inventory(
    output: str,
    manifest: OwnershipManifest,
    selected_modules: frozenset[str],
    repo_root: Path = ROOT,
) -> tuple[MypyFindingRecord, ...]:
    try:
        return _mypy_inventory(output, manifest, selected_modules, repo_root)
    except RecordValidationError as error:
        raise RatchetContractError(str(error)) from error


def migration_edges(
    manifest: OwnershipManifest,
    modules: Mapping[str, Path],
    repo_root: Path = ROOT,
) -> tuple[ImportEdgeRecord, ...]:
    try:
        return _migration_edges(manifest, modules, repo_root)
    except RecordValidationError as error:
        raise RatchetContractError(str(error)) from error


def file_length_inventory(
    selection: Sequence[Mapping[str, object]], repo_root: Path = ROOT
) -> tuple[tuple[FileLengthRecord, ...], tuple[FileLengthRecord, ...]]:
    try:
        return _file_length_inventory(selection, repo_root)
    except RecordValidationError as error:
        raise RatchetContractError(str(error)) from error



def compare_snapshot(
    snapshot: SnapshotDocument,
    baseline: BaselineDocument,
    *,
    mode: str,
) -> dict[str, object]:
    validate_baseline(baseline)
    selection = compare_selection(snapshot["selection"]["modules"], baseline["selection"]["modules"])
    ruff = compare_counted(snapshot["ruff"]["findings"], baseline["ruff"]["findings"], ("path", "code", "message", "fingerprint"))
    mypy = compare_counted(snapshot["mypy"]["findings"], baseline["mypy"]["findings"], ("module", "path", "error_code", "normalized_fingerprint"))
    imports = compare_counted(
        [dict(item, count=1) for item in snapshot["migration_direction_imports"]["edges"]],
        [dict(item, count=1) for item in baseline["migration_direction_imports"]["edges"]],
        ("source_module", "source_path", "target_module", "target_tier"),
    )
    for values in (
        imports["new"],
        imports["increased"],
        imports["removed"],
        imports["decreased"],
        imports["unchanged"],
    ):
        for item in values:
            item.pop("count", None)
    lengths = compare_file_lengths(snapshot["file_length"]["ceilings"], baseline["file_length"]["ceilings"])
    ownership_match = snapshot["ownership"] == baseline["ownership"]
    tools_match = snapshot["tools"] == baseline["tools"]
    comparisons = (selection, ruff, mypy, imports, lengths)
    blocking = (
        not ownership_match
        or not tools_match
        or bool(snapshot["file_length"]["hard_failures"])
        or has_policy_deltas(comparisons)
    )
    counts = Counter(item["ownership_class"] for item in snapshot["selection"]["modules"])
    tiers = Counter(item["tier"] for item in snapshot["selection"]["modules"])
    summary = summary_counts(comparisons)
    summary["hard_failures"] = len(snapshot["file_length"]["hard_failures"])
    profile_facts = build_product_profile_facts(snapshot, baseline)
    return {
        "schema": RESULT_SCHEMA, "mode": mode,
        "status": "rejected" if blocking else "accepted",
        "classification": "policy-finding" if blocking else "passed",
        "ownership": {**snapshot["ownership"], "baseline_sha256": baseline["ownership"]["sha256"], "sha256_match": ownership_match},
        "selection": {"module_count": len(snapshot["selection"]["modules"]), "file_count": len({item["path"] for item in snapshot["selection"]["modules"]}), "ownership_classes": dict(sorted(counts.items())), "tiers": dict(sorted(tiers.items())), "comparison": result_comparison(selection)},
        "tools": {**snapshot["tools"], "baseline_match": tools_match},
        "ruff": {"actual_count": sum(item["count"] for item in snapshot["ruff"]["findings"]), "baseline_count": sum(item["count"] for item in baseline["ruff"]["findings"]), "comparison": result_comparison(ruff)},
        "mypy": {"actual_count": sum(item["count"] for item in snapshot["mypy"]["findings"]), "baseline_count": sum(item["count"] for item in baseline["mypy"]["findings"]), "comparison": result_comparison(mypy)},
        "migration_direction_imports": {"actual_count": len(snapshot["migration_direction_imports"]["edges"]), "baseline_count": len(baseline["migration_direction_imports"]["edges"]), "comparison": result_comparison(imports)},
        "file_length": {"warning_limit": WARNING_LIMIT, "failure_limit": FAILURE_LIMIT, "actual_count": len(snapshot["file_length"]["ceilings"]), "baseline_count": len(baseline["file_length"]["ceilings"]), "hard_failures": snapshot["file_length"]["hard_failures"], "comparison": result_comparison(lengths)},
        "summary": dict(summary),
        "profile_path_facts": profile_facts,
    }


def _run(
    command: list[str], *, repo_root: Path = ROOT
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=repo_root, check=False, capture_output=True, text=True, timeout=300, env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"})


def ruff_files_command(paths: Sequence[str]) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--isolated",
        "--show-files",
        "--no-cache",
        *paths,
    )


def ruff_command(paths: Sequence[str]) -> tuple[str, ...]:
    return (sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py312", "--select", "F", "--ignore-noqa", "--output-format", "json", "--no-cache", *paths)


def mypy_command(paths: Sequence[str]) -> tuple[str, ...]:
    return (sys.executable, "-m", "mypy", "--config-file", "pyproject.toml", "--follow-imports=silent", "--no-error-summary", "--cache-dir=/dev/null", *paths)


def _attest_ruff_files(
    output: str, selected_paths: frozenset[str], repo_root: Path
) -> None:
    observed = []
    for raw_path in output.splitlines():
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = repo_root / candidate
        observed.append(_relative(candidate, repo_root))
    if len(observed) != len(set(observed)) or frozenset(observed) != selected_paths:
        raise RatchetContractError("Ruff file selection was incomplete")


def collect_snapshot(
    manifest_path: Path = DEFAULT_MANIFEST, *, repo_root: Path = ROOT
) -> SnapshotDocument:
    modules = maintained_modules(repo_root)
    manifest = load_manifest(manifest_path, modules=modules)
    selection = select_retained_modules(modules, manifest, repo_root)
    manifest_relative = _relative(manifest_path, repo_root)
    tracked_run = _run(
        ["git", "ls-files", "--error-unmatch", manifest_relative],
        repo_root=repo_root,
    )
    if tracked_run.returncode != 0:
        raise RatchetContractError("ownership manifest is not tracked")
    attestation = _attest_environment()
    ruff_version = importlib.metadata.version("ruff")
    if attestation["versions"]["mypy"] != EXPECTED_TOOLS["mypy"] or ruff_version != EXPECTED_TOOLS["ruff"]:
        raise RatchetContractError("unexpected pinned tool version")
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    target_version = pyproject["tool"]["ruff"]["target-version"]
    if target_version != "py312" or pyproject["tool"]["mypy"] != EXPECTED_MYPY_CONFIG:
        raise RatchetContractError("unexpected static-analysis configuration")
    paths = tuple(item["path"] for item in selection)
    ruff_files_run = _run(list(ruff_files_command(paths)), repo_root=repo_root)
    if ruff_files_run.returncode != 0:
        raise RatchetContractError(
            f"Ruff file attestation failure: exit={ruff_files_run.returncode}"
        )
    _attest_ruff_files(ruff_files_run.stdout, frozenset(paths), repo_root)
    ruff_run = _run(list(ruff_command(paths)), repo_root=repo_root)
    if ruff_run.returncode not in {0, 1}:
        raise RatchetContractError(f"Ruff tool failure: exit={ruff_run.returncode}")
    try:
        ruff_json = json.loads(ruff_run.stdout)
    except json.JSONDecodeError as error:
        raise RatchetContractError("Ruff JSON is invalid") from error
    future = frozenset(item["module"] for item in selection if item["tier"] == "T1-future")
    future_paths = tuple(item["path"] for item in selection if item["tier"] == "T1-future")
    mypy_run = _run(list(mypy_command(future_paths)), repo_root=repo_root)
    if mypy_run.returncode not in {0, 1}:
        raise RatchetContractError(f"mypy tool failure: exit={mypy_run.returncode}")
    mypy_output = mypy_run.stdout + mypy_run.stderr
    inventory = mypy_inventory(mypy_output, manifest, future, repo_root)
    if mypy_run.returncode == 1 and sum(" error: " in line for line in mypy_output.splitlines()) != sum(item["count"] for item in inventory):
        raise RatchetContractError("mypy emitted an unparseable error")
    ceilings, hard = file_length_inventory(selection, repo_root)
    snapshot: SnapshotDocument = {
        "ownership": {"manifest_path": manifest_relative, "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()},
        "tools": {"mypy": EXPECTED_TOOLS["mypy"], "ruff": EXPECTED_TOOLS["ruff"], "ruff_rules": list(RUFF_RULES), "ruff_target_version": target_version},
        "selection": {"ownership_classes": list(RETAINED_CLASSES), "tiers": list(RETAINED_TIERS), "modules": list(selection)},
        "ruff": {"findings": list(normalize_ruff_inventory(ruff_json, frozenset(paths)))},
        "mypy": {"findings": list(inventory)},
        "migration_direction_imports": {"edges": list(migration_edges(manifest, modules, repo_root))},
        "file_length": {"warning_limit": WARNING_LIMIT, "failure_limit": FAILURE_LIMIT, "ceilings": list(ceilings), "hard_failures": list(hard)},
    }
    return snapshot


def _lineage_contract():
    from ci.retained_python_ratchet_lineage import (
        DEFAULT_SCOPE_TRANSITIONS,
        LineagePolicyError,
        audit_candidate_lineage,
    )
    return DEFAULT_SCOPE_TRANSITIONS, LineagePolicyError, audit_candidate_lineage


def main(argv: list[str] | None = None) -> int:
    default_scopes, lineage_policy_error, audit_lineage = _lineage_contract()
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=Path("tools/ci/retained_python_ratchets.json"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--scope-transitions", type=Path, default=default_scopes)
    parser.add_argument("--generate-baseline", action="store_true")
    args = parser.parse_args(argv)
    mode = "generate-baseline" if args.generate_baseline else "check"
    try:
        baseline_path = args.baseline if args.baseline.is_absolute() else ROOT / args.baseline
        if not baseline_path.is_file():
            raise RatchetContractError("initialized baseline is missing")
        try:
            baseline_relative = baseline_path.resolve().relative_to(ROOT.resolve())
        except ValueError as error:
            raise RatchetContractError("baseline path escapes repository root") from error
        snapshot = collect_snapshot(args.manifest)
        if args.generate_baseline:
            if snapshot["file_length"]["hard_failures"]:
                document = baseline_document(snapshot)
                result = compare_snapshot(snapshot, document, mode=mode)
                print(render_document(result), end="")
                return 1
            document = baseline_document(snapshot)
            validate_baseline(document)
            audit_lineage(
                ROOT,
                baseline_relative,
                document,
                args.scope_transitions,
            )
            write_baseline_atomic(baseline_path, document)
            result = compare_snapshot(snapshot, document, mode=mode)
        else:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            audit_lineage(
                ROOT,
                baseline_relative,
                baseline,
                args.scope_transitions,
            )
            result = compare_snapshot(snapshot, baseline, mode=mode)
        print(render_document(result), end="")
        return 0 if result["classification"] == "passed" else 1
    except lineage_policy_error:
        failure = {
            "schema": RESULT_SCHEMA,
            "mode": mode,
            "status": "rejected",
            "classification": "policy-finding",
            "policy_finding": "baseline-lineage",
        }
        print(render_document(failure), end="")
        return 1
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        importlib.metadata.PackageNotFoundError,
        OwnershipManifestError,
        RatchetContractError,
        TypeCheckToolError,
    ) as error:
        failure = {"schema": RESULT_SCHEMA, "mode": mode, "status": "failed", "classification": "tool-failure", "tool_failure": type(error).__name__}
        print(render_document(failure), end="")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
