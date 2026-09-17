"""Retained coverage evidence preserves actual lines and branch outcomes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import coverage
import pytest

import runner_coverage
import runner_coverage_execution
import runner_coverage_reports
from test_report import write_html_report


def test_session_report_after_environment_exit_precedes_explicit_cleanup(tmp_path: Path) -> None:
    source = tmp_path / "recorded.py"
    source.write_text("value = 1\n")
    session = runner_coverage.ChildCoverageSession(coverage_module=coverage, source_root=tmp_path)
    try:
        with session:
            collector = session.create_coverage(coverage)
            collector.get_data().add_lines({str(source): {1}})
        assert session.session_dir.exists()
        records = runner_coverage.coverage_records_from_json(collector, [source])
        assert records[0].covered_lines == 1
    finally:
        session.cleanup()
    assert not session.session_dir.exists()


def test_raw_coverage_export_preserves_uncovered_branch(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "def choose(flag):\n    if flag:\n        return 1\n    return 2\n",
        encoding="utf-8",
    )
    collector = coverage.Coverage(branch=True, data_file=None, config_file=False)
    request.addfinalizer(lambda: collector.get_data().close(force=True))
    namespace: dict[str, object] = {}
    collector.start()
    try:
        exec(compile(source.read_text() + "choose(True)\n", str(source), "exec"), namespace)
    finally:
        collector.stop()
    output = tmp_path / "retained" / "coverage.json"
    with patch.object(runner_coverage, "SOURCE_ROOT", tmp_path):
        records = runner_coverage.coverage_records_from_json(
            collector, [source], json_report_path=output,
        )
        unexported = runner_coverage.coverage_records_from_json(collector, [source])
        summary = runner_coverage.collect_coverage_summary(
            collector, "unit", runner_coverage.coverage_policy_for_suite("unit"),
        )
    assert records == unexported
    assert summary.covered_branches == 1
    payload = json.loads(output.read_text())
    assert len(payload["files"]) == 1
    measured = next(iter(payload["files"].values()))
    assert 3 in measured["executed_lines"]
    assert 4 in measured["missing_lines"]
    assert [2, 3] in measured["executed_branches"]
    assert [2, 4] in measured["missing_branches"]
    assert records[0].total_branches == 2
    assert records[0].covered_branches == 1

    # The HTML owner replaces latest/; the raw report must survive regeneration.
    report_root = tmp_path / "reports"
    raw_report = report_root / "unit" / "coverage.json"
    raw_report.parent.mkdir(parents=True)
    raw_report.write_bytes(output.read_bytes())
    write_html_report(
        report_root=report_root, suite_name="unit", test_records=(),
        coverage=summary, repo_root=tmp_path,
    )
    assert raw_report.read_bytes() == output.read_bytes()
    summary_path = report_root / "unit" / "latest" / "summary.json"
    assert summary_path.exists()
    report_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert report_summary["coverage"]["status"] == "measured"
    assert report_summary["coverage"]["passed"] is False
    assert report_summary["coverage"]["line"]["covered"] == summary.covered_lines
    assert report_summary["coverage"]["line"]["total"] == summary.total_lines
    assert report_summary["coverage"]["branch"]["covered"] == 1
    assert report_summary["coverage"]["branch"]["total"] == 2
    index_path = report_root / "unit" / "latest" / "index.html"
    assert index_path.exists()
    index_html = index_path.read_text(encoding="utf-8")
    assert "Line coverage" in index_html
    assert "Branch coverage" in index_html
    # A genuine measured summary cannot manufacture the separate abrupt
    # obligation. Persist its unavailable evidence alongside unchanged counts.
    obligations = {"legs": {
        "M": {"status": "passed", "measurement": {"state": "measured"}},
        "A": {"status": "blocked", "measurement": {"state": "unavailable"}},
    }}
    paired_index = write_html_report(
        report_root=report_root, suite_name="staging", test_records=(),
        coverage=summary, repo_root=tmp_path, staging_obligations=obligations,
    )
    paired = json.loads((paired_index.parent / "summary.json").read_text())
    assert paired["staging_obligations"] == obligations
    assert paired["coverage"]["branch"] == report_summary["coverage"]["branch"]
    assert "Staging evidence: not qualified" in paired_index.read_text()
    assert "A: blocked; measurement unavailable" in paired_index.read_text()


def test_export_write_failure_is_not_silently_discarded(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n", encoding="utf-8")
    collector = coverage.Coverage(data_file=None, config_file=False)
    request.addfinalizer(lambda: collector.get_data().close(force=True))
    collector.start()
    try:
        exec(compile(source.read_text(), str(source), "exec"), {})
    finally:
        collector.stop()
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("occupied", encoding="utf-8")
    with pytest.raises(FileExistsError):
        runner_coverage.coverage_records_from_json(
            collector, [source], json_report_path=blocked_parent / "coverage.json",
        )
    assert not (blocked_parent / "coverage.json").exists()
    assert blocked_parent.read_text(encoding="utf-8") == "occupied"


def test_runner_coverage_decomposition_exports_and_parity() -> None:
    """Verify that runner_coverage re-exports decomposed symbols identically."""
    reexported_from_reports = (
        "DEFAULT_INT_LINE_HARD_THRESHOLD",
        "DEFAULT_INT_BRANCH_HARD_THRESHOLD",
        "DEFAULT_UNIT_STATEMENT_HARD_THRESHOLD",
        "DEFAULT_UNIT_BRANCH_HARD_THRESHOLD",
        "DEFAULT_ADVISORY_THRESHOLD",
        "CoveragePolicy",
        "coverage_policy_for_suite",
        "coverage_file_status",
        "coverage_json_path",
        "coverage_record_from_summary",
        "coverage_record_from_analysis",
        "percentage",
        "is_relative_to",
        "report_coverage",
    )
    for name in reexported_from_reports:
        assert hasattr(runner_coverage, name), f"missing export {name} on runner_coverage"
        assert getattr(runner_coverage, name) is getattr(runner_coverage_reports, name)

    assert hasattr(runner_coverage, "ShardDiagnosticSnapshot")
    assert runner_coverage.ShardDiagnosticSnapshot is runner_coverage_execution.ShardDiagnosticSnapshot
    assert hasattr(runner_coverage, "ChildCoverageSession")


def test_coverage_record_summary_int_coercion_robustness(tmp_path: Path) -> None:
    """Verify summary record numeric extraction handles varied types cleanly."""
    fake_path = tmp_path / "test.py"
    summary_data: dict[str, object] = {
        "num_statements": "10",
        "covered_lines": 8,
        "num_branches": 4.0,
        "covered_branches": 2,
    }
    rec = runner_coverage.coverage_record_from_summary(fake_path, summary_data)
    assert rec.executable_lines == 10
    assert rec.covered_lines == 8
    assert rec.line_percent == 80.0
    assert rec.total_branches == 4
    assert rec.covered_branches == 2
    assert rec.branch_percent == 50.0

    # Absent keys retain the old default; malformed present counts must fail.
    empty = runner_coverage_reports.coverage_record_from_summary(fake_path, {})
    assert empty.executable_lines == empty.covered_lines == 0
    for key in summary_data:
        for value, error in ((None, TypeError), ("invalid", ValueError), (object(), TypeError)):
            with pytest.raises(error):
                runner_coverage_reports.coverage_record_from_summary(
                    fake_path, {**summary_data, key: value}
                )


def test_runner_coverage_reports_direct_invocation(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    """Verify direct usage of runner_coverage_reports with custom source_root."""
    source = tmp_path / "mod.py"
    source.write_text("a = 1\nb = 2\n", encoding="utf-8")
    collector = coverage.Coverage(branch=False, data_file=None, config_file=False)
    request.addfinalizer(lambda: collector.get_data().close(force=True))
    collector.start()
    try:
        exec(compile(source.read_text(), str(source), "exec"), {})
    finally:
        collector.stop()

    policy = runner_coverage_reports.coverage_policy_for_suite("unit")
    summary = runner_coverage_reports.collect_coverage_summary(
        collector, "unit", policy, source_root=tmp_path,
    )
    assert summary.total_lines == 2
    assert summary.covered_lines == 2
    assert summary.line_percent == 100.0
    assert summary.passed is True
    assert len(summary.files) == 1
    assert summary.files[0].path == source.resolve()
    assert summary.files[0].covered_lines == 2
    assert summary.files[0].executable_lines == 2
    assert summary.files[0].line_percent == 100.0
# REPOMAP-PUBLIC-V002-FIX9-R1 dynamic boundary re-attestation
