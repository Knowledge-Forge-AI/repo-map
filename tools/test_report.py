"""Static HTML report rendering for RepoMap tests."""

from __future__ import annotations

import html
import json
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from test_report_coverage import (
    CoverageState,
    CoverageStatus,
    coverage_badge_status as _coverage_badge_status,
    coverage_notice as _coverage_notice,
    coverage_payload as _coverage_payload,
    coverage_unavailable_row as _coverage_unavailable_row,
    normalize_coverage_status as _normalize_coverage_status,
    record_report_error as _record_report_error,
)

STATIC_SOURCE_DIR = Path(__file__).resolve().parent / "test" / "report" / "static"

def report_docker_projection(projection: dict[str, int], *, boundary: str) -> None:
    """Print exactly what was derived; never substitute a literal zero."""
    from repomap_test_support.resource_docker_boundary import PROJECTION_FIELDS

    print(f"Docker residue boundary ({boundary}):")
    if not projection:
        print("  <no observed population: boundary construction failed>")
        return
    for field in PROJECTION_FIELDS:
        value = projection[field] if field in projection else "<not-derived>"
        print(f"  {field}: {value}")

@dataclass(frozen=True)
class TestRecord:
    test_id: str
    test_file: str
    status: str
    duration_seconds: float
    message: str = ""

@dataclass(frozen=True)
class CoverageFileRecord:
    path: Path
    executable_lines: int
    covered_lines: int
    line_percent: float
    total_branches: int
    covered_branches: int
    branch_percent: float

    @property
    def percent(self) -> float:
        return self.line_percent

@dataclass(frozen=True)
class CoverageSummary:
    suite_name: str
    line_hard_threshold: float
    branch_hard_threshold: float
    line_warn_threshold: float
    branch_warn_threshold: float
    total_lines: int
    covered_lines: int
    line_percent: float
    total_branches: int
    covered_branches: int
    branch_percent: float
    files: tuple[CoverageFileRecord, ...]

    @property
    def passed(self) -> bool:
        return (
            self.line_percent >= self.line_hard_threshold
            and self.branch_percent >= self.branch_hard_threshold
        )

    @property
    def threshold(self) -> float:
        return self.line_hard_threshold

    @property
    def total_covered(self) -> int:
        return self.covered_lines

    @property
    def aggregate_percent(self) -> float:
        return self.line_percent

@dataclass(frozen=True)
class GoCoverageSummary:
    suite_name: str
    hard_threshold: float
    total_statements: int
    covered_statements: int
    statement_percent: float
    branch_status: str = "N/A"
    diagnostic_category: str = ""

    @property
    def passed(self) -> bool:
        if self.total_statements <= 0:
            return False
        return (self.covered_statements / self.total_statements) >= (
            self.hard_threshold / 100.0
        )

def write_html_report(
    *,
    report_root: Path,
    suite_name: str,
    test_records: tuple[TestRecord, ...],
    coverage: CoverageSummary | None,
    repo_root: Path,
    generated_at: datetime | None = None,
    go_coverage: GoCoverageSummary | None = None,
    coverage_status: CoverageStatus | CoverageState | None = None,
    coverage_error: str | None = None,
    coverage_diagnostics: Sequence[Mapping[str, Any]] = (),
    staging_obligations: Mapping[str, Any] | None = None,
) -> Path:
    generated_at = generated_at or datetime.now(UTC)
    output_dir = report_root / suite_name / "latest"
    if output_dir.is_symlink():
        raise RuntimeError("report output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    status = _normalize_coverage_status(
        coverage,
        coverage_status,
        detail=coverage_error,
        diagnostics=coverage_diagnostics,
    )
    summary = _test_summary(test_records)
    # Persist the test and coverage evidence before any optional static asset or
    # HTML rendering work.  A rendering error must leave a usable report.
    _write_summary_json(
        output_dir / "summary.json",
        suite_name,
        test_records,
        coverage,
        summary,
        coverage_status=status,
        go_coverage=go_coverage,
        staging_obligations=staging_obligations,
    )
    summary_path = output_dir / "summary.json"
    try:
        index_path = output_dir / "index.html"
        index_path.unlink(missing_ok=True)
        static_dir = output_dir / "static"
        static_dir.mkdir(parents=True, exist_ok=True)
        (static_dir / "report.css").unlink(missing_ok=True)
        (static_dir / "report.js").unlink(missing_ok=True)
        shutil.copyfile(STATIC_SOURCE_DIR / "report.css", static_dir / "report.css")
        shutil.copyfile(STATIC_SOURCE_DIR / "report.js", static_dir / "report.js")

        html_output = _render_index(
            suite_name=suite_name,
            test_records=test_records,
            coverage=coverage,
            coverage_status=status,
            repo_root=repo_root,
            generated_at=generated_at,
            summary=summary,
            go_coverage=go_coverage,
            staging_obligations=staging_obligations,
        )
        index_path.write_text(html_output, encoding="utf-8")
        return index_path
    except Exception as error:
        _record_report_error(summary_path, error)
        raise

def _write_summary_json(
    path: Path,
    suite_name: str,
    test_records: tuple[TestRecord, ...],
    coverage: CoverageSummary | None,
    summary: dict[str, int],
    coverage_status: CoverageStatus | CoverageState | None = None,
    coverage_error: str | None = None,
    coverage_diagnostics: Sequence[Mapping[str, Any]] = (),
    go_coverage: GoCoverageSummary | None = None,
    staging_obligations: Mapping[str, Any] | None = None,
) -> None:
    status = _normalize_coverage_status(
        coverage,
        coverage_status,
        detail=coverage_error,
        diagnostics=coverage_diagnostics,
    )
    coverage_payload = _coverage_payload(coverage, status)
    payload: dict[str, Any] = {
        "suite": suite_name,
        "tests": summary,
        "coverage": coverage_payload,
        "records": [asdict(record) for record in test_records],
    }
    if go_coverage is not None:
        payload["go_coverage"] = {
            "statement": {
                "covered": go_coverage.covered_statements,
                "total": go_coverage.total_statements,
                "percent": round(go_coverage.statement_percent, 1),
                "hard_threshold": go_coverage.hard_threshold,
                "passed": go_coverage.passed,
            },
            "branch": "N/A",
            "passed": go_coverage.passed,
        }
    if staging_obligations is not None:
        payload["staging_obligations"] = dict(staging_obligations)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _render_index(
    *,
    suite_name: str,
    test_records: tuple[TestRecord, ...],
    coverage: CoverageSummary | None,
    coverage_status: CoverageStatus | CoverageState | None = None,
    repo_root: Path,
    generated_at: datetime,
    summary: dict[str, int],
    go_coverage: GoCoverageSummary | None = None,
    staging_obligations: Mapping[str, Any] | None = None,
) -> str:
    from test_report_coverage import obligations_notice
    obligations = obligations_notice(staging_obligations)
    status = _normalize_coverage_status(coverage, coverage_status)
    test_status = "failed" if summary["failed"] else "passed"
    coverage_badge_status = _coverage_badge_status(coverage, status)
    generated = generated_at.astimezone(UTC).isoformat(timespec="seconds")
    test_rows = "\n".join(_test_row(record) for record in test_records)
    coverage_rows = (
        "\n".join(_coverage_row(record, coverage, repo_root) for record in coverage.files)
        if coverage is not None
        else _coverage_unavailable_row(status)
    )
    coverage_notice = _coverage_notice(status) if status.state != "measured" else ""
    badge_items = [
        _status_badge("Tests", f"{summary['passed']}/{summary['total']} passed", test_status),
    ]
    if coverage is None:
        badge_items.append(_status_badge("Coverage", status.state, coverage_badge_status))
    else:
        badge_items.append(
            _status_badge("Line coverage", f"{coverage.line_percent:.1f}%", coverage_badge_status)
        )
        badge_items.append(
            _status_badge("Branch coverage", f"{coverage.branch_percent:.1f}%", coverage_badge_status)
        )
    if go_coverage is not None:
        go_status = "passed" if go_coverage.passed else "failed"
        badge_items.append(
            _status_badge("Go statement", f"{go_coverage.statement_percent:.1f}%", go_status)
        )
        badge_items.append(_status_badge("Go branch", "N/A", "passed"))
    badges_markup = "\n          ".join(badge_items)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>RepoMap Test Report</title>
    <link rel="stylesheet" href="static/report.css">
    <script src="static/report.js" defer></script>
  </head>
  <body>
    <main>
      <header class="report-header">
        <div class="report-heading">
          <p class="report-eyebrow">Static host-safe report</p>
          <h1>RepoMap Test Report</h1>
          <p class="report-subtitle">Generated for the {html.escape(suite_name)} suite at {html.escape(generated)}. Test results and line/branch coverage use the same dark report language as the nix-darwin reports.</p>
        </div>
        <div class="report-badges" aria-label="Report summary">
          {badges_markup}
        </div>
      </header>
      {obligations}

      <section class="tree-section" aria-labelledby="coverage-heading">
        <div class="section-heading">
          <h2 id="coverage-heading">Coverage: source files</h2>
        </div>
        <div class="tree-grid grid-header">
          <div class="cell path-cell">Path</div>
          <div class="cell metric-cell">Lines</div>
          <div class="cell metric-cell">Covered</div>
          <div class="cell metric-cell">Line Coverage</div>
          <div class="cell metric-cell">Branches</div>
          <div class="cell metric-cell">Covered</div>
          <div class="cell metric-cell">Branch Coverage</div>
          <div class="cell status-cell">Status</div>
        </div>
        {coverage_notice}
        {coverage_rows}
      </section>

      <section class="tree-section" aria-labelledby="tests-heading" data-tree-id="tests">
        <div class="section-heading">
          <h2 id="tests-heading">Test results: cases</h2>
        </div>
        <div class="test-grid grid-header">
          <div class="cell path-cell">Test</div>
          <div class="cell metric-cell">File</div>
          <div class="cell metric-cell">Time</div>
          <div class="cell metric-cell">Status</div>
          <div class="cell metric-cell">Info</div>
          <div class="cell status-cell">Result</div>
        </div>
        {test_rows}
      </section>
    </main>
  </body>
</html>
"""


def _test_summary(records: tuple[TestRecord, ...]) -> dict[str, int]:
    total = len(records)
    passed = sum(1 for record in records if record.status == "passed")
    skipped = sum(1 for record in records if record.status == "skipped")
    failed = total - passed - skipped
    return {"total": total, "passed": passed, "failed": failed, "skipped": skipped}


def _status_badge(label: str, value: str, status: str) -> str:
    text = f"{label}: {value}"
    return (
        f'<span class="status-badge status-{html.escape(status, quote=True)}" '
        f'title="{html.escape(text, quote=True)}">{html.escape(text)}</span>'
    )


def _test_row(record: TestRecord) -> str:
    message = record.message.strip()
    info = message.splitlines()[0][:80] if message else ""
    return "\n".join(
        [
            '<div class="test-grid row">',
            f'  <div class="cell path-cell" title="{html.escape(record.test_id, quote=True)}">{html.escape(record.test_id)}</div>',
            f'  <div class="cell metric-cell" title="{html.escape(record.test_file, quote=True)}">{html.escape(record.test_file)}</div>',
            f'  <div class="cell metric-cell">{record.duration_seconds:.3f}s</div>',
            f'  <div class="cell metric-cell">{html.escape(record.status)}</div>',
            f'  <div class="cell metric-cell" title="{html.escape(info, quote=True)}">{html.escape(info)}</div>',
            f'  <div class="cell status-cell status-{html.escape(record.status)}">{html.escape(record.status)}</div>',
            "</div>",
        ],
    )


def _coverage_row(record: CoverageFileRecord, coverage: CoverageSummary, repo_root: Path) -> str:
    status = _coverage_file_status(record, coverage)
    display_path = _display_path(record.path, repo_root)
    return "\n".join(
        [
            '<div class="tree-grid row">',
            f'  <div class="cell path-cell" title="{html.escape(display_path, quote=True)}">{html.escape(display_path)}</div>',
            f'  <div class="cell metric-cell">{record.executable_lines}</div>',
            f'  <div class="cell metric-cell">{record.covered_lines}</div>',
            f'  <div class="cell metric-cell">{record.line_percent:.1f}%</div>',
            f'  <div class="cell metric-cell">{record.total_branches}</div>',
            f'  <div class="cell metric-cell">{record.covered_branches}</div>',
            f'  <div class="cell metric-cell">{record.branch_percent:.1f}%</div>',
            f'  <div class="cell status-cell status-{status}">{status}</div>',
            "</div>",
        ],
    )


def _coverage_file_status(record: CoverageFileRecord, coverage: CoverageSummary) -> str:
    if (
        record.line_percent < coverage.line_hard_threshold
        or record.branch_percent < coverage.branch_hard_threshold
    ):
        return "warn"
    if (
        record.line_percent < coverage.line_warn_threshold
        or record.branch_percent < coverage.branch_warn_threshold
    ):
        return "warn"
    return "pass"


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()
