"""Reporting, policy thresholds, and JSON export helpers for test runner coverage."""

from __future__ import annotations

import json
from collections.abc import Buffer, Callable
from dataclasses import dataclass
from pathlib import Path
import sys
import tempfile
from typing import Any, Protocol, SupportsIndex, SupportsInt, runtime_checkable

from test_report import (
    CoverageFileRecord,
    CoverageSummary,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "src" / "main" / "python"

DEFAULT_INT_LINE_HARD_THRESHOLD = 80.0
DEFAULT_INT_BRANCH_HARD_THRESHOLD = 80.0
DEFAULT_UNIT_STATEMENT_HARD_THRESHOLD = 85.0
DEFAULT_UNIT_BRANCH_HARD_THRESHOLD = 85.0
DEFAULT_ADVISORY_THRESHOLD = 90.0


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def percentage(part: int, whole: int) -> float:
    if whole == 0:
        return 100.0
    return (part / whole) * 100.0


@dataclass(frozen=True)
class CoveragePolicy:
    line_hard_threshold: float
    branch_hard_threshold: float
    line_warn_threshold: float
    branch_warn_threshold: float


def coverage_policy_for_suite(
    suite_name: str,
    threshold_override: float | None = None,
) -> CoveragePolicy:
    if suite_name in {"int", "staging"}:
        line_hard = DEFAULT_INT_LINE_HARD_THRESHOLD
        branch_hard = DEFAULT_INT_BRANCH_HARD_THRESHOLD
    elif suite_name == "unit":
        line_hard = DEFAULT_UNIT_STATEMENT_HARD_THRESHOLD
        branch_hard = DEFAULT_UNIT_BRANCH_HARD_THRESHOLD
    else:
        raise ValueError(f"coverage is not defined for suite {suite_name!r}")
    if threshold_override is not None:
        line_hard = threshold_override
        branch_hard = threshold_override
    return CoveragePolicy(
        line_hard_threshold=line_hard,
        branch_hard_threshold=branch_hard,
        line_warn_threshold=DEFAULT_ADVISORY_THRESHOLD,
        branch_warn_threshold=DEFAULT_ADVISORY_THRESHOLD,
    )


def coverage_file_status(
    result: CoverageFileRecord,
    summary: CoverageSummary,
) -> str:
    if (
        result.line_percent < summary.line_hard_threshold
        or result.branch_percent < summary.branch_hard_threshold
    ):
        return "warn"
    if (
        result.line_percent < summary.line_warn_threshold
        or result.branch_percent < summary.branch_warn_threshold
    ):
        return "warn"
    return "pass"


def coverage_json_path(path_text: str, repo_root: Path | None = None) -> Path | None:
    root = repo_root or REPO_ROOT
    path = Path(path_text)
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve()
    except OSError:
        return None


@runtime_checkable
class _SupportsTrunc(Protocol):
    def __trunc__(self) -> int: ...


def _int_from_summary(value: object) -> int:
    """Preserve integer conversion failures instead of inventing zero coverage."""
    if isinstance(value, (str, Buffer, SupportsInt, SupportsIndex, _SupportsTrunc)):
        return int(value)
    raise TypeError(f"coverage count cannot be converted to int: {type(value).__name__}")


def coverage_record_from_summary(
    path: Path,
    summary: dict[str, object],
) -> CoverageFileRecord:
    total_lines = _int_from_summary(summary.get("num_statements", 0))
    covered_lines = _int_from_summary(summary.get("covered_lines", 0))
    total_branches = _int_from_summary(summary.get("num_branches", 0))
    covered_branches = _int_from_summary(summary.get("covered_branches", 0))
    return CoverageFileRecord(
        path=path,
        executable_lines=total_lines,
        covered_lines=covered_lines,
        line_percent=percentage(covered_lines, total_lines),
        total_branches=total_branches,
        covered_branches=covered_branches,
        branch_percent=percentage(covered_branches, total_branches),
    )


def coverage_record_from_analysis(coverage_runner: Any, path: Path) -> CoverageFileRecord:
    analysis = coverage_runner._analyze(str(path))
    numbers = analysis.numbers
    total_lines = _int_from_summary(getattr(numbers, "n_statements", 0))
    missing_lines = _int_from_summary(getattr(numbers, "n_missing", 0))
    total_branches = _int_from_summary(getattr(numbers, "n_branches", 0))
    missing_branches = _int_from_summary(getattr(numbers, "n_missing_branches", 0))
    covered_lines = max(0, total_lines - missing_lines)
    covered_branches = max(0, total_branches - missing_branches)
    return CoverageFileRecord(
        path=path,
        executable_lines=total_lines,
        covered_lines=covered_lines,
        line_percent=percentage(covered_lines, total_lines),
        total_branches=total_branches,
        covered_branches=covered_branches,
        branch_percent=percentage(covered_branches, total_branches),
    )


def coverage_records_from_json(
    coverage_runner: Any,
    source_files: list[Path],
    *,
    json_report_path: Path | None = None,
    source_root: Path | None = None,
    repo_root: Path | None = None,
) -> list[CoverageFileRecord]:
    effective_source_root = source_root or SOURCE_ROOT
    effective_repo_root = repo_root or REPO_ROOT
    with tempfile.TemporaryDirectory(prefix="repomap-coverage-json-") as tmpdir:
        report_path = Path(tmpdir) / "coverage.json"
        coverage_runner.json_report(
            morfs=[str(path) for path in source_files],
            outfile=str(report_path),
            pretty_print=False,
        )
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        if json_report_path is not None:
            json_report_path.parent.mkdir(parents=True, exist_ok=True)
            json_report_path.write_bytes(report_path.read_bytes())

    records_by_path: dict[Path, CoverageFileRecord] = {}
    for path_text, file_payload in payload.get("files", {}).items():
        path = coverage_json_path(path_text, repo_root=effective_repo_root)
        if path is None or not is_relative_to(path, effective_source_root):
            continue
        records_by_path[path] = coverage_record_from_summary(
            path,
            file_payload.get("summary", {}),
        )

    records: list[CoverageFileRecord] = []
    for path in source_files:
        resolved = path.resolve()
        if resolved in records_by_path:
            records.append(records_by_path[resolved])
        else:
            records.append(coverage_record_from_analysis(coverage_runner, resolved))
    return records


def collect_coverage_summary(
    coverage_runner: Any,
    suite_name: str,
    policy: CoveragePolicy,
    *,
    json_report_path: Path | None = None,
    source_root: Path | None = None,
    records_fn: Callable[..., list[CoverageFileRecord]] | None = None,
) -> CoverageSummary:
    effective_source_root = source_root or SOURCE_ROOT
    source_files = sorted(effective_source_root.rglob("*.py"))
    if not source_files:
        raise RuntimeError("no Python source files found for coverage")

    get_records = records_fn or coverage_records_from_json
    file_results = get_records(
        coverage_runner,
        source_files,
        json_report_path=json_report_path,
        source_root=effective_source_root,
    )
    total_lines = sum(result.executable_lines for result in file_results)
    covered_lines = sum(result.covered_lines for result in file_results)
    total_branches = sum(result.total_branches for result in file_results)
    covered_branches = sum(result.covered_branches for result in file_results)
    return CoverageSummary(
        suite_name=suite_name,
        line_hard_threshold=policy.line_hard_threshold,
        branch_hard_threshold=policy.branch_hard_threshold,
        line_warn_threshold=policy.line_warn_threshold,
        branch_warn_threshold=policy.branch_warn_threshold,
        total_lines=total_lines,
        covered_lines=covered_lines,
        line_percent=percentage(covered_lines, total_lines),
        total_branches=total_branches,
        covered_branches=covered_branches,
        branch_percent=percentage(covered_branches, total_branches),
        files=tuple(file_results),
    )


def report_coverage(
    summary: CoverageSummary,
    *,
    repo_root: Path | None = None,
) -> bool:
    effective_repo_root = repo_root or REPO_ROOT
    print()
    print(f"Coverage summary for {summary.suite_name} suite:")
    print(
        f"  aggregate line coverage: {summary.covered_lines}/{summary.total_lines} "
        f"({summary.line_percent:.1f}%; hard {summary.line_hard_threshold:.1f}%, "
        f"advisory {summary.line_warn_threshold:.1f}%)"
    )
    print(
        f"  aggregate branch coverage: "
        f"{summary.covered_branches}/{summary.total_branches} "
        f"({summary.branch_percent:.1f}%; hard "
        f"{summary.branch_hard_threshold:.1f}%, advisory "
        f"{summary.branch_warn_threshold:.1f}%)"
    )

    for result in summary.files:
        status = coverage_file_status(result, summary)
        print(
            f"  {status}: {result.path.relative_to(effective_repo_root)} "
            f"lines {result.covered_lines}/{result.executable_lines} "
            f"({result.line_percent:.1f}%), branches "
            f"{result.covered_branches}/{result.total_branches} "
            f"({result.branch_percent:.1f}%)"
        )

    passed = True
    if summary.line_percent < summary.line_hard_threshold:
        passed = False
        print(
            f"ERROR: aggregate line coverage {summary.line_percent:.1f}% is below "
            f"{summary.line_hard_threshold:.1f}%",
            file=sys.stderr,
        )
    elif summary.line_percent < summary.line_warn_threshold:
        print(
            f"ADVISORY: {summary.suite_name} line coverage "
            f"{summary.line_percent:.1f}% is below "
            f"{summary.line_warn_threshold:.1f}%; hard gate is "
            f"{summary.line_hard_threshold:.1f}%."
        )

    if summary.branch_percent < summary.branch_hard_threshold:
        passed = False
        print(
            f"ERROR: aggregate branch coverage {summary.branch_percent:.1f}% is below "
            f"{summary.branch_hard_threshold:.1f}%",
            file=sys.stderr,
        )
    elif summary.branch_percent < summary.branch_warn_threshold:
        print(
            f"ADVISORY: {summary.suite_name} branch coverage "
            f"{summary.branch_percent:.1f}% is below "
            f"{summary.branch_warn_threshold:.1f}%; hard gate is "
            f"{summary.branch_hard_threshold:.1f}%."
        )

    return passed
