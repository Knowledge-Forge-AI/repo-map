import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[5]

import test_report
import run_tests

from src.test.unit.python.tools.report_test_fixtures import ReportTestCase, coverage_summary


class ReportGeneratorUnitTests(ReportTestCase):
    def test_write_html_report_outputs_dark_static_report_and_summary(self):
        report_path = test_report.write_html_report(
            report_root=self.tmpdir,
            suite_name="unit",
            repo_root=REPO_ROOT,
            generated_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
            test_records=(
                test_report.TestRecord(
                    test_id="pkg.TestCase.test_passes",
                    test_file="src/test/unit/python/pkg/test_file.py",
                    status="passed",
                    duration_seconds=0.0123,
                ),
                test_report.TestRecord(
                    test_id="pkg.TestCase.test_<unsafe&>",
                    test_file="src/test/unit/python/pkg/test_other.py",
                    status="failed",
                    duration_seconds=0.0345,
                    message="expected <thing&> to be escaped",
                ),
            ),
            coverage=coverage_summary(line_percent=87.5, branch_percent=87.5),
        )

        self.assertEqual(report_path, self.tmpdir / "unit" / "latest" / "index.html")
        html_output = report_path.read_text(encoding="utf-8")
        css_output = (report_path.parent / "static" / "report.css").read_text(
            encoding="utf-8"
        )
        js_output = (report_path.parent / "static" / "report.js").read_text(
            encoding="utf-8"
        )
        summary = json.loads((report_path.parent / "summary.json").read_text())

        self.assertIn("RepoMap Test Report", html_output)
        self.assertIn("Static host-safe report", html_output)
        self.assertIn("Tests: 1/2 passed", html_output)
        self.assertIn("Line coverage: 87.5%", html_output)
        self.assertIn("Branch coverage: 87.5%", html_output)
        self.assertIn("pkg.TestCase.test_&lt;unsafe&amp;&gt;", html_output)
        self.assertNotIn("pkg.TestCase.test_<unsafe&>", html_output)
        self.assertIn("color-scheme: dark", css_output)
        self.assertIn("status-badge", css_output)
        self.assertIn("sessionStorage", js_output)
        self.assertEqual(
            summary["tests"],
            {"failed": 1, "passed": 1, "skipped": 0, "total": 2},
        )
        self.assertEqual(summary["coverage"]["line"]["percent"], 87.5)
        self.assertEqual(summary["coverage"]["branch"]["percent"], 87.5)
        self.assertEqual(summary["coverage"]["status"], "measured")


    def test_unavailable_coverage_persists_records_and_anomaly_evidence(self):
        latest = self.tmpdir / "unit" / "latest"
        latest.mkdir(parents=True)
        anomaly = latest / "coverage_anomaly_snapshot.json"
        anomaly.write_text('{"historical": true}\n', encoding="utf-8")
        status = test_report.CoverageStatus(
            "unavailable",
            detail="coverage collection failed",
            diagnostics=(
                {"stage": "combine", "reader_status": "missing_shard"},
            ),
        )

        report_path = test_report.write_html_report(
            report_root=self.tmpdir,
            suite_name="unit",
            repo_root=REPO_ROOT,
            test_records=(
                test_report.TestRecord(
                    test_id="pkg.test_failure",
                    test_file="src/test/unit/python/pkg/test_file.py",
                    status="failed",
                    duration_seconds=0.01,
                    message="assertion failed",
                ),
            ),
            coverage=None,
            coverage_status=status,
        )

        summary = json.loads((report_path.parent / "summary.json").read_text())
        html_output = report_path.read_text(encoding="utf-8")
        self.assertEqual(summary["tests"]["failed"], 1)
        self.assertEqual(summary["records"][0]["test_id"], "pkg.test_failure")
        self.assertEqual(summary["coverage"]["status"], "unavailable")
        self.assertFalse(summary["coverage"]["passed"])
        self.assertEqual(summary["coverage"]["diagnostics"][0]["stage"], "combine")
        self.assertIn("Coverage: unavailable", html_output)
        self.assertIn("coverage collection failed", html_output)
        self.assertTrue(anomaly.exists())
        self.assertEqual(anomaly.read_text(encoding="utf-8"), '{"historical": true}\n')


    def test_summary_survives_renderer_failure_and_records_secondary_error(self):
        status = test_report.CoverageStatus("incomplete", detail="missing child shard")
        with patch.object(
            test_report,
            "_render_index",
            side_effect=RuntimeError("renderer exploded"),
        ):
            with self.assertRaisesRegex(RuntimeError, "renderer exploded"):
                test_report.write_html_report(
                    report_root=self.tmpdir,
                    suite_name="unit",
                    repo_root=REPO_ROOT,
                    test_records=(
                        test_report.TestRecord(
                            test_id="pkg.test_failure",
                            test_file="src/test/unit/python/pkg/test_file.py",
                            status="failed",
                            duration_seconds=0.01,
                        ),
                    ),
                    coverage=None,
                    coverage_status=status,
                )

        summary_path = self.tmpdir / "unit" / "latest" / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(summary["coverage"]["status"], "incomplete")
        self.assertEqual(summary["records"][0]["status"], "failed")
        self.assertEqual(summary["report"]["status"], "failed")
        self.assertIn("renderer exploded", summary["report"]["error"])
        self.assertFalse((summary_path.parent / "index.html").exists())


    def test_recording_pytest_plugin_collects_test_records(self):
        plugin = run_tests.RecordingPytestPlugin()

        plugin.pytest_runtest_logreport(
            self.pytest_report(
                nodeid="pkg/test_file.py::test_passes",
                status="passed",
            )
        )
        plugin.pytest_runtest_logreport(
            self.pytest_report(
                nodeid="pkg/test_file.py::test_skips",
                when="setup",
                status="skipped",
                longreprtext="demonstrating skip capture",
            )
        )
        plugin.pytest_runtest_logreport(
            self.pytest_report(
                nodeid="pkg/test_other.py::test_fails",
                status="failed",
                longreprtext="expected failure text",
            )
        )

        self.assertEqual(len(plugin.test_records), 3)
        statuses = {record.status for record in plugin.test_records}
        self.assertEqual(statuses, {"passed", "skipped", "failed"})
        self.assertTrue(
            all(record.duration_seconds >= 0 for record in plugin.test_records)
        )
        self.assertTrue(
            all(record.test_file for record in plugin.test_records),
            plugin.test_records,
        )
        self.assertIn("expected failure text", plugin.test_records[-1].message)


    def test_runner_report_flag_writes_report_from_pytest_records(self):
        coverage = coverage_summary()
        report_path = self.tmpdir / "unit" / "latest" / "index.html"

        def fake_run_pytest(pytest_module, pytest_args, plugin):
            self.assertEqual(
                self.strip_centralized_basetemp(pytest_args),
                [str(run_tests.TEST_ROOTS["unit"])],
            )
            plugin.add_record(
                self.pytest_report(nodeid="pkg/test_file.py::test_passes"),
                "passed",
            )
            return 0

        def fake_run_pytest_with_coverage(
            coverage_module, pytest_module, pytest_args, plugin
        ):
            return fake_run_pytest(pytest_module, pytest_args, plugin), object()

        with (
            patch.object(run_tests, "import_pytest", return_value=self.fake_pytest()),
            patch.object(run_tests, "import_coverage", return_value=object()),
            patch.object(
                run_tests,
                "run_pytest_with_coverage",
                side_effect=fake_run_pytest_with_coverage,
            ),
            patch.object(
                run_tests,
                "collect_coverage_summary",
                return_value=coverage,
            ),
            patch.object(run_tests, "report_coverage", return_value=True),
            patch.object(
                run_tests,
                "write_html_report",
                return_value=report_path,
            ) as write_html_report,
        ):
            exit_code = run_tests.main(
                ["--suite", "unit", "--report", "--report-dir", str(self.tmpdir)]
            )

        self.assertEqual(exit_code, 0)
        write_html_report.assert_called_once()
        kwargs = write_html_report.call_args.kwargs
        self.assertEqual(kwargs["report_root"], self.tmpdir)
        self.assertEqual(kwargs["suite_name"], "unit")
        self.assertEqual(kwargs["coverage"], coverage)
        self.assertEqual(len(kwargs["test_records"]), 1)
        self.assertEqual(kwargs["test_records"][0].status, "passed")


    def test_recording_plugin_captures_call_phase_skip_with_reason(self):
        plugin = run_tests.RecordingPytestPlugin()
        report = self.pytest_report(
            nodeid="pkg/test_file.py::test_call_skip",
            when="call",
            status="skipped",
            longrepr=("pkg/test_file.py", 42, "Skipped: skip from test call body"),
        )
        plugin.pytest_runtest_logreport(report)

        self.assertEqual(len(plugin.test_records), 1)
        record = plugin.test_records[0]
        self.assertEqual(record.test_id, "pkg/test_file.py::test_call_skip")
        self.assertEqual(record.status, "skipped")
        self.assertEqual(record.message, "skip from test call body")


    def test_recording_plugin_captures_call_phase_skip_from_longreprtext(self):
        plugin = run_tests.RecordingPytestPlugin()
        report = self.pytest_report(
            nodeid="pkg/test_file.py::test_call_skip_text",
            when="call",
            status="skipped",
            longreprtext="Skipped: dynamic condition not met",
        )
        plugin.pytest_runtest_logreport(report)

        self.assertEqual(len(plugin.test_records), 1)
        record = plugin.test_records[0]
        self.assertEqual(record.status, "skipped")
        self.assertEqual(record.message, "dynamic condition not met")


    def test_recording_plugin_teardown_failure_overrides_passed_with_unique_node_id(self):
        plugin = run_tests.RecordingPytestPlugin()
        nodeid = "pkg/test_file.py::test_passes_then_teardown_fails"
        call_report = self.pytest_report(nodeid=nodeid, when="call", status="passed")
        teardown_report = self.pytest_report(
            nodeid=nodeid,
            when="teardown",
            status="failed",
            longreprtext="fixture cleanup error",
        )

        plugin.pytest_runtest_logreport(call_report)
        self.assertEqual(len(plugin.test_records), 1)
        self.assertEqual(plugin.test_records[0].status, "passed")

        plugin.pytest_runtest_logreport(teardown_report)
        self.assertEqual(len(plugin.test_records), 1)
        record = plugin.test_records[0]
        self.assertEqual(record.test_id, nodeid)
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.message, "fixture cleanup error")


    def test_recording_plugin_teardown_failure_overrides_skipped_with_unique_node_id(self):
        plugin = run_tests.RecordingPytestPlugin()
        nodeid = "pkg/test_file.py::test_skips_then_teardown_fails"
        setup_report = self.pytest_report(
            nodeid=nodeid,
            when="setup",
            status="skipped",
            longrepr=("pkg/test_file.py", 10, "Skipped: platform unsupported"),
        )
        teardown_report = self.pytest_report(
            nodeid=nodeid,
            when="teardown",
            status="failed",
            longreprtext="teardown hook failed",
        )

        plugin.pytest_runtest_logreport(setup_report)
        self.assertEqual(len(plugin.test_records), 1)
        self.assertEqual(plugin.test_records[0].status, "skipped")

        plugin.pytest_runtest_logreport(teardown_report)
        self.assertEqual(len(plugin.test_records), 1)
        record = plugin.test_records[0]
        self.assertEqual(record.test_id, nodeid)
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.message, "teardown hook failed")


    def test_recording_plugin_call_failure_preserved_when_teardown_also_fails(self):
        plugin = run_tests.RecordingPytestPlugin()
        nodeid = "pkg/test_file.py::test_fails_and_teardown_fails"
        call_report = self.pytest_report(
            nodeid=nodeid,
            when="call",
            status="failed",
            longreprtext="assertion error in test body",
        )
        teardown_report = self.pytest_report(
            nodeid=nodeid,
            when="teardown",
            status="failed",
            longreprtext="secondary teardown failure",
        )

        plugin.pytest_runtest_logreport(call_report)
        plugin.pytest_runtest_logreport(teardown_report)
        self.assertEqual(len(plugin.test_records), 1)
        record = plugin.test_records[0]
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.message, "assertion error in test body")
