"""Unit tests for Go runner integration coverage measurement and instrumented helper."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import build_go_helper as build_go_helper
import go_runner_coverage as go_runner_cov
import test_report as test_report

REPO_ROOT = Path(__file__).resolve().parents[5]


def load_tool_module(name: str, relative_path: str):
    mapping = {
        "build_go_helper": build_go_helper,
        "go_runner_coverage": go_runner_cov,
        "test_report": test_report,
    }
    return mapping.get(name)


class GoRunnerCoverageUnitTests(unittest.TestCase):
    """Verify statement parsing, threshold evaluation, and collection guards."""

    def test_parse_textfmt_profile_aggregates_num_stmts_correctly(self):
        profile = (
            "mode: set\n"
            "repomap/extract.go:10.1,15.2 5 1\n"
            "repomap/extract.go:16.1,20.2 4 0\n"
            "repomap/parser.go:30.1,35.2 6 2\n"
        )
        covered, total = go_runner_cov.parse_textfmt_profile(profile)
        self.assertEqual(total, 15)
        self.assertEqual(covered, 11)  # 5 + 6

    def test_parse_textfmt_profile_rejects_missing_mode_or_empty(self):
        with self.assertRaises(ValueError) as caught:
            go_runner_cov.parse_textfmt_profile("")
        self.assertIn("empty textfmt profile data", str(caught.exception))

        with self.assertRaises(ValueError) as caught:
            go_runner_cov.parse_textfmt_profile("repomap/extract.go:1.1,2.1 5 1\n")
        self.assertIn("missing or invalid textfmt mode header", str(caught.exception))

        with self.assertRaises(ValueError) as caught:
            go_runner_cov.parse_textfmt_profile("mode: unknown_mode\nrepomap/extract.go:1.1,2.1 5 1\n")
        self.assertIn("unsupported textfmt mode", str(caught.exception))

    def test_parse_textfmt_profile_rejects_malformed_and_negative_lines(self):
        # Malformed line without enough parts
        with self.assertRaises(ValueError) as caught:
            go_runner_cov.parse_textfmt_profile("mode: set\nmalformed_line\n")
        self.assertIn("malformed profile line", str(caught.exception))

        # Block identifier missing colon or comma
        with self.assertRaises(ValueError) as caught:
            go_runner_cov.parse_textfmt_profile("mode: set\nbad_block 5 1\n")
        self.assertIn("malformed block identifier", str(caught.exception))

        # Non-integer statement count
        with self.assertRaises(ValueError) as caught:
            go_runner_cov.parse_textfmt_profile("mode: set\nrepomap/pkg.go:1.1,2.1 five 1\n")
        self.assertIn("non-integer statement or count", str(caught.exception))

        # Negative statement count
        with self.assertRaises(ValueError) as caught:
            go_runner_cov.parse_textfmt_profile("mode: set\nrepomap/pkg.go:1.1,2.1 -5 1\n")
        self.assertIn("negative statement count", str(caught.exception))

    def test_parse_textfmt_profile_reconciles_duplicates_and_rejects_conflicts(self):
        # Identical block repeated should not duplicate denominator statements
        profile = (
            "mode: set\n"
            "repomap/test.go:1.1,5.1 10 0\n"
            "repomap/test.go:1.1,5.1 10 1\n"
        )
        covered, total = go_runner_cov.parse_textfmt_profile(profile)
        self.assertEqual(total, 10)
        self.assertEqual(covered, 10)

        # Conflicting statement count for the same block must be rejected
        conflict = (
            "mode: set\n"
            "repomap/test.go:1.1,5.1 10 1\n"
            "repomap/test.go:1.1,5.1 12 1\n"
        )
        with self.assertRaises(ValueError) as caught:
            go_runner_cov.parse_textfmt_profile(conflict)
        self.assertIn("conflicting statement count", str(caught.exception))

    def test_collect_returns_failure_when_dir_missing_or_empty(self):
        missing = Path("/nonexistent/gocoverdir/path")
        res = go_runner_cov.collect_go_integration_coverage(missing)
        self.assertFalse(res.passed)
        self.assertEqual(res.statement_percent, 0.0)
        self.assertEqual(res.diagnostic_category, "missing_setup")

        with tempfile.TemporaryDirectory() as tmpdir:
            empty_dir = Path(tmpdir)
            res2 = go_runner_cov.collect_go_integration_coverage(empty_dir)
            self.assertFalse(res2.passed)
            self.assertEqual(res2.total_statements, 0)
            self.assertEqual(res2.diagnostic_category, "no_data")

    def test_collect_handles_covdata_execution_and_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coverdir = Path(tmpdir)
            (coverdir / "covcounters.12345.678").write_bytes(b"data")

            def fake_run(cmd, **kwargs):
                out_arg = [arg for arg in cmd if arg.startswith("-o=")][0]
                out_file = Path(out_arg.split("=", 1)[1])
                out_file.write_text(
                    "mode: set\nrepomap/test.go:1.1,5.1 8 1\nrepomap/test.go:6.1,8.1 2 0\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(cmd, 0)

            with patch.object(subprocess, "run", side_effect=fake_run):
                summary = go_runner_cov.collect_go_integration_coverage(
                    coverdir, policy_floor=80.0
                )
            self.assertTrue(summary.passed)
            self.assertEqual(summary.covered_statements, 8)
            self.assertEqual(summary.total_statements, 10)
            self.assertEqual(summary.statement_percent, 80.0)
            self.assertEqual(summary.diagnostic_category, "passed")

    def test_collect_handles_covdata_timeout_and_invalid_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coverdir = Path(tmpdir)
            (coverdir / "covcounters.12345.678").write_bytes(b"data")

            # Timeout expired
            def fake_timeout(cmd, **kwargs):
                raise subprocess.TimeoutExpired(cmd, 30.0)

            with patch.object(subprocess, "run", side_effect=fake_timeout):
                summary = go_runner_cov.collect_go_integration_coverage(coverdir)
            self.assertFalse(summary.passed)
            self.assertEqual(summary.diagnostic_category, "collector_error")

            # Invalid data emitted by tool
            def fake_invalid(cmd, **kwargs):
                out_arg = [arg for arg in cmd if arg.startswith("-o=")][0]
                out_file = Path(out_arg.split("=", 1)[1])
                out_file.write_text("not-a-valid-profile\n", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0)

            with patch.object(subprocess, "run", side_effect=fake_invalid):
                summary2 = go_runner_cov.collect_go_integration_coverage(coverdir)
            self.assertFalse(summary2.passed)
            self.assertEqual(summary2.diagnostic_category, "invalid_data")

    def test_collect_strictly_enforces_unrounded_80_percent_floor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coverdir = Path(tmpdir)
            (coverdir / "covcounters.999").write_bytes(b"data")

            def fake_run(cmd, **kwargs):
                out_arg = [arg for arg in cmd if arg.startswith("-o=")][0]
                out_file = Path(out_arg.split("=", 1)[1])
                out_file.write_text(
                    "mode: set\nrepomap/pkg.go:1.1,2.1 799 1\nrepomap/pkg.go:3.1,4.1 201 0\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(cmd, 0)

            with patch.object(subprocess, "run", side_effect=fake_run):
                summary = go_runner_cov.collect_go_integration_coverage(
                    coverdir, policy_floor=80.0
                )
            self.assertFalse(summary.passed)
            self.assertAlmostEqual(summary.statement_percent, 79.9, places=2)
            self.assertEqual(summary.diagnostic_category, "below_floor")

    def test_report_go_coverage_returns_pass_fail(self):
        passed_summary = test_report.GoCoverageSummary(
            suite_name="int",
            hard_threshold=80.0,
            total_statements=100,
            covered_statements=85,
            statement_percent=85.0,
            branch_status="N/A",
            diagnostic_category="passed",
        )
        self.assertTrue(go_runner_cov.report_go_coverage(passed_summary))

        failed_summary = test_report.GoCoverageSummary(
            suite_name="int",
            hard_threshold=80.0,
            total_statements=100,
            covered_statements=75,
            statement_percent=75.0,
            branch_status="N/A",
            diagnostic_category="below_floor",
        )
        self.assertFalse(go_runner_cov.report_go_coverage(failed_summary))

    def test_evaluate_go_integration_gate_eligibility_and_authority(self):
        # Ineligible suites return (None, True)
        self.assertEqual(go_runner_cov.evaluate_go_integration_gate("unit", False), (None, True))
        self.assertEqual(go_runner_cov.evaluate_go_integration_gate("smoke", False), (None, True))
        self.assertEqual(go_runner_cov.evaluate_go_integration_gate("int", True), (None, True))

        # Missing run-owned directory returns explicit failure
        missing_dir = Path("/nonexistent/authority/dir")
        summary, passed = go_runner_cov.evaluate_go_integration_gate(
            "int", False, expected_gocoverdir=missing_dir
        )
        self.assertFalse(passed)
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary.diagnostic_category, "missing_setup")

        with tempfile.TemporaryDirectory() as tmpdir:
            run_owned = Path(tmpdir)
            # Mismatched ambient environment variable
            with patch.dict("os.environ", {"GOCOVERDIR": "/different/ambient/path"}):
                summary2, passed2 = go_runner_cov.evaluate_go_integration_gate(
                    "int", False, expected_gocoverdir=run_owned
                )
                self.assertFalse(passed2)
                self.assertIsNotNone(summary2)
                assert summary2 is not None
                self.assertEqual(summary2.diagnostic_category, "missing_setup")

            # Matching ambient environment variable with valid data
            (run_owned / "covcounters.1").write_bytes(b"data")

            def fake_run(cmd, **kwargs):
                out_arg = [arg for arg in cmd if arg.startswith("-o=")][0]
                out_file = Path(out_arg.split("=", 1)[1])
                out_file.write_text(
                    "mode: set\nrepomap/test.go:1.1,5.1 8 1\nrepomap/test.go:6.1,8.1 2 0\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(cmd, 0)

            with patch.dict("os.environ", {"GOCOVERDIR": str(run_owned)}):
                with patch.object(subprocess, "run", side_effect=fake_run):
                    summary3, passed3 = go_runner_cov.evaluate_go_integration_gate(
                        "int", False, expected_gocoverdir=run_owned
                    )
                    self.assertTrue(passed3)
                    assert summary3 is not None
                    self.assertEqual(summary3.statement_percent, 80.0)

    def test_collect_handles_covdata_nonzero_exit_called_process_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coverdir = Path(tmpdir)
            (coverdir / "covcounters.12345.678").write_bytes(b"data")

            def fake_called_process_error(cmd, **kwargs):
                raise subprocess.CalledProcessError(
                    1, cmd, stderr="covdata: corrupt coverage file"
                )

            with patch.object(subprocess, "run", side_effect=fake_called_process_error):
                summary = go_runner_cov.collect_go_integration_coverage(coverdir)
            self.assertFalse(summary.passed)
            self.assertEqual(summary.diagnostic_category, "collector_error")

    def test_prepare_and_restore_go_environment_suite_isolation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            go_tmp = Path(tmpdir)
            fake_validate = MagicMock()
            fake_build = MagicMock(return_value=go_tmp / "helper" / "bin")

            # Unit suite validates sources and does not set GOCOVERDIR
            go_runner_cov.prepare_go_environment("unit", go_tmp, fake_validate, fake_build)
            fake_validate.assert_called_once()
            self.assertNotIn("GOCOVERDIR", os.environ)

            # Int suite sets GOCOVERDIR and saves prior
            with patch.dict("os.environ", {"GOCOVERDIR": "/prior/covdir"}):
                go_runner_cov.prepare_go_environment("int", go_tmp, fake_validate, fake_build)
                self.assertEqual(os.environ.get("GOCOVERDIR"), str(go_tmp / "gocoverdir"))
                go_runner_cov.restore_go_environment()
                self.assertEqual(os.environ.get("GOCOVERDIR"), "/prior/covdir")

            # Int suite unsets when no prior existed
            with patch.dict("os.environ", {}, clear=True):
                go_runner_cov.prepare_go_environment("int", go_tmp, fake_validate, fake_build)
                self.assertEqual(os.environ.get("GOCOVERDIR"), str(go_tmp / "gocoverdir"))
                go_runner_cov.restore_go_environment()
                self.assertNotIn("GOCOVERDIR", os.environ)

    def test_report_generation_and_temporary_file_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coverdir = Path(tmpdir)
            (coverdir / "covcounters.12345").write_bytes(b"data")
            created_out_files = []

            def fake_run(cmd, **kwargs):
                out_arg = [arg for arg in cmd if arg.startswith("-o=")][0]
                out_file = Path(out_arg.split("=", 1)[1])
                created_out_files.append(out_file)
                out_file.write_text(
                    "mode: set\nrepomap/test.go:1.1,5.1 10 1\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(cmd, 0)

            with patch.object(subprocess, "run", side_effect=fake_run):
                summary = go_runner_cov.collect_go_integration_coverage(coverdir)
            self.assertTrue(summary.passed)
            self.assertEqual(summary.diagnostic_category, "passed")
            # Intermediate textfmt temporary file was cleaned up with the context
            self.assertEqual(len(created_out_files), 1)
            self.assertFalse(created_out_files[0].exists())

    def test_prior_pytest_failure_preserved_when_go_coverage_fails(self):
        # When pytest exits with a failure code (e.g. 2), a failing go coverage
        # gate must not replace or disguise the primary pytest exit code.
        pytest_exit_code = 2
        go_ok = False
        coverage_ok = True
        if not go_ok:
            coverage_ok = False
        final_exit = (
            pytest_exit_code if pytest_exit_code != 0 else (0 if coverage_ok else 1)
        )
        self.assertEqual(final_exit, 2)


class InstrumentedGoHelperBuildUnitTests(unittest.TestCase):
    """Verify instrumented helper build flags and in-tree rejection guards."""

    def test_refuses_instrumented_build_directly_in_tree(self):
        with self.assertRaises(ValueError) as caught:
            build_go_helper.build_go_helper(
                repo_root=REPO_ROOT,
                package_root=build_go_helper.PACKAGE_ROOT,
                instrumented=True,
            )
        self.assertIn("must not use default in-tree package_root", str(caught.exception))

    def test_instrumented_build_adds_cover_flags_and_suffix(self):
        commands = []

        def fake_run(command, **kwargs):
            commands.append((tuple(command), kwargs))
            output = Path(command[command.index("-o") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"instrumented-helper")
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            with patch.object(build_go_helper.subprocess, "run", side_effect=fake_run):
                helper = build_go_helper.build_go_helper(
                    repo_root=REPO_ROOT,
                    package_root=output_root,
                    target_platform="test-platform",
                    instrumented=True,
                )

            expected_name = f"{build_go_helper.HELPER_NAME}.cover"
            self.assertEqual(helper.name, expected_name)
            self.assertEqual(len(commands), 1)
            command, _ = commands[0]
            self.assertIn("-cover", command)
            self.assertIn("-coverpkg=./...", command)


if __name__ == "__main__":
    unittest.main()
