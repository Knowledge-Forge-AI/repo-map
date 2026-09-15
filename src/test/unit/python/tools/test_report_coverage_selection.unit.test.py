import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[5]

import run_tests

from src.test.unit.python.tools.report_test_fixtures import ReportTestCase, coverage_summary


class ReportGeneratorUnitTests(ReportTestCase):
    def test_coverage_policy_for_unit_and_int_has_canonical_hard_gates(self):
        unit_policy = run_tests.coverage_policy_for_suite("unit")
        int_policy = run_tests.coverage_policy_for_suite("int")

        self.assertEqual(unit_policy.line_hard_threshold, 85.0)
        self.assertEqual(unit_policy.branch_hard_threshold, 85.0)
        self.assertEqual(unit_policy.line_warn_threshold, 90.0)
        self.assertEqual(unit_policy.branch_warn_threshold, 90.0)
        self.assertEqual(int_policy.line_hard_threshold, 80.0)
        self.assertEqual(int_policy.branch_hard_threshold, 80.0)
        self.assertEqual(int_policy.line_warn_threshold, 90.0)
        self.assertEqual(int_policy.branch_warn_threshold, 90.0)


    def test_coverage_policy_for_staging_uses_integration_hard_80(self):
        policy = run_tests.coverage_policy_for_suite("staging")

        self.assertEqual(policy.line_hard_threshold, 80.0)
        self.assertEqual(policy.branch_hard_threshold, 80.0)
        self.assertEqual(policy.line_warn_threshold, 90.0)
        self.assertEqual(policy.branch_warn_threshold, 90.0)


    def test_coverage_threshold_override_changes_hard_gate_only(self):
        policy = run_tests.coverage_policy_for_suite("unit", threshold_override=75.0)

        self.assertEqual(policy.line_hard_threshold, 75.0)
        self.assertEqual(policy.branch_hard_threshold, 75.0)
        self.assertEqual(policy.line_warn_threshold, 90.0)
        self.assertEqual(policy.branch_warn_threshold, 90.0)


    def test_report_coverage_warns_but_passes_unit_above_hard_below_advisory(self):
        summary = coverage_summary(line_percent=83.0, branch_percent=84.0)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            passed = run_tests.report_coverage(summary)

        self.assertTrue(passed)
        self.assertIn("ADVISORY", stdout.getvalue())
        self.assertIn("line coverage", stdout.getvalue())
        self.assertIn("branch coverage", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")


    def test_report_coverage_fails_unit_branch_below_hard_gate(self):
        summary = coverage_summary(
            line_percent=90.0,
            branch_percent=79.0,
            line_hard_threshold=85.0,
            branch_hard_threshold=85.0,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            passed = run_tests.report_coverage(summary)

        self.assertFalse(passed)
        self.assertIn("branch coverage", stderr.getvalue())
        self.assertIn("85.0%", stderr.getvalue())


    def test_report_coverage_fails_staging_line_below_80(self):
        summary = coverage_summary(
            suite_name="staging",
            line_percent=79.0,
            branch_percent=90.0,
            line_hard_threshold=80.0,
            branch_hard_threshold=80.0,
            line_warn_threshold=85.0,
            branch_warn_threshold=85.0,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            passed = run_tests.report_coverage(summary)

        self.assertFalse(passed)
        self.assertIn("line coverage", stderr.getvalue())
        self.assertIn("80.0%", stderr.getvalue())


    def test_runner_jobs_auto_adds_xdist_args(self):
        self.assertEqual(
            run_tests.build_pytest_args(("unit",), [], jobs="auto"),
            ["-n", "auto", str(run_tests.TEST_ROOTS["unit"])],
        )


    def test_runner_jobs_integer_adds_xdist_worker_count(self):
        self.assertEqual(
            run_tests.build_pytest_args(("unit",), ["-k", "baseline"], jobs="3"),
            ["-n", "3", str(run_tests.TEST_ROOTS["unit"]), "-k", "baseline"],
        )


    def test_runner_jobs_one_stays_serial(self):
        self.assertEqual(
            run_tests.build_pytest_args(("unit",), [], jobs="1"),
            [str(run_tests.TEST_ROOTS["unit"])],
        )


    def test_runner_rejects_invalid_jobs(self):
        with self.assertRaisesRegex(RuntimeError, "--jobs"):
            run_tests.normalize_jobs("0")

        with self.assertRaisesRegex(RuntimeError, "--jobs"):
            run_tests.normalize_jobs("sometimes")


    def test_runner_forwarded_path_selection_replaces_default_path(self):
        selection = "src/test/unit/python/repomap_kg/test_cli.unit.test.py"

        self.assertEqual(
            run_tests.build_pytest_args(("unit",), [selection]),
            [selection],
        )


    def test_runner_rejects_cross_suite_forwarded_path_selection(self):
        selection = "src/test/int/python/repomap_kg/test_storage.int.test.py"

        with self.assertRaisesRegex(RuntimeError, "outside selected suite root"):
            run_tests.build_pytest_args(("unit",), [selection])


    def test_runner_rejects_current_directory_forwarded_selection(self):
        with self.assertRaisesRegex(RuntimeError, "outside selected suite root"):
            run_tests.build_pytest_args(("unit",), ["."])


    def test_runner_parallel_requires_no_coverage(self):
        args = SimpleNamespace(jobs="auto", no_coverage=False, report=False)

        with self.assertRaisesRegex(RuntimeError, "--no-coverage"):
            run_tests.validate_runner_options(args, ("unit",))


    def test_runner_report_requires_coverage(self):
        args = SimpleNamespace(jobs="1", no_coverage=True, report=True)

        with self.assertRaisesRegex(RuntimeError, "--report"):
            run_tests.validate_runner_options(args, ("unit",))


    def test_runner_rejects_parallel_integration_for_now(self):
        args = SimpleNamespace(jobs="auto", no_coverage=True, report=False)

        with self.assertRaisesRegex(RuntimeError, "integration"):
            run_tests.validate_runner_options(args, ("int",))


    def test_runner_parallel_no_coverage_skips_coverage_collection(self):
        seen = {}

        def fake_run_pytest(pytest_module, pytest_args, plugin):
            seen["pytest_args"] = pytest_args
            plugin.add_record(
                self.pytest_report(nodeid="pkg/test_file.py::test_passes"),
                "passed",
            )
            return 0

        with (
            patch.object(run_tests, "import_pytest", return_value=self.fake_pytest()),
            patch.object(run_tests, "import_xdist", return_value=object()),
            patch.object(run_tests, "run_pytest", side_effect=fake_run_pytest),
            patch.object(
                run_tests,
                "collect_coverage_summary",
                side_effect=AssertionError("coverage should be skipped"),
            ),
            patch.object(
                run_tests,
                "report_coverage",
                side_effect=AssertionError("coverage should be skipped"),
            ),
        ):
            exit_code = run_tests.main(
                [
                    "--suite",
                    "unit",
                    "--jobs",
                    "2",
                    "--no-coverage",
                    "--",
                    "-k",
                    "baseline",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            self.strip_centralized_basetemp(seen["pytest_args"]),
            ["-n", "2", str(run_tests.TEST_ROOTS["unit"]), "-k", "baseline"],
        )

