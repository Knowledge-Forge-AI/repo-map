import io
import json
import os
from contextlib import nullcontext, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[5]

import test_report
import run_tests

from src.test.unit.python.tools.report_test_fixtures import ReportTestCase, coverage_summary


class ReportGeneratorUnitTests(ReportTestCase):
    def test_default_runner_report_registers_top_level_evidence_owner(self):
        run_root = self.tmpdir / "run"
        run_root.mkdir()
        layout = SimpleNamespace(run_root=run_root)
        resource_run = Mock()
        resource_run.bounded_subprocess.return_value = nullcontext()

        with (
            patch.object(run_tests, "establish_test_scratch", return_value=layout),
            patch.object(
                run_tests.TestResourceRun, "start", return_value=resource_run
            ),
            patch.object(run_tests, "run_selected_suites", return_value=0),
        ):
            exit_code = run_tests.main(["--suite", "unit", "--report"])

        evidence_root = run_root / "evidence"
        self.assertEqual(exit_code, 0)
        resource_run.retain_evidence.assert_called_once_with(
            evidence_root,
            reason="report_source",
        )
        self.assertTrue((evidence_root / "test-report").is_dir())
        resource_run.close.assert_called_once_with(run_tests.TerminalOutcome.PASSED)


    def test_runner_report_lifecycle_preserves_primary_and_secondary_failures(self):
        report_root = self.tmpdir / "lifecycle-report"
        args = SimpleNamespace(
            suite="unit",
            threshold=None,
            jobs="1",
            no_coverage=False,
            report=True,
            report_dir=report_root,
        )
        session = SimpleNamespace(
            diagnostic_snapshots=(
                SimpleNamespace(
                    to_dict=lambda: {
                        "stage": "combine",
                        "reader_status": "missing_shard",
                    },
                ),
            ),
            cleanup=Mock(),
        )
        coverage_runner = SimpleNamespace(
            _instrumentation_error="missing child shard",
            _repomap_session=session,
        )
        pytest_module = SimpleNamespace(
            ExitCode=SimpleNamespace(NO_TESTS_COLLECTED=5),
        )

        def fake_run_pytest_with_coverage(
            coverage_module, pytest_module_arg, pytest_args, plugin
        ):
            plugin.add_record(
                self.pytest_report(
                    nodeid="pkg/test_file.py::test_primary_failure",
                    status="failed",
                    longreprtext="primary assertion failure",
                ),
                "failed",
            )
            return 1, coverage_runner

        with (
            patch.object(run_tests, "validate_runner_options"),
            patch.object(run_tests, "import_pytest", return_value=pytest_module),
            patch.object(run_tests, "import_coverage", return_value=object()),
            patch.object(
                run_tests,
                "establish_run",
                return_value=SimpleNamespace(pytest_basetemp=self.tmpdir / "pt"),
            ),
            patch.object(run_tests, "pytest_environment_for", return_value=nullcontext()),
            patch.object(
                run_tests,
                "run_pytest_with_coverage",
                side_effect=fake_run_pytest_with_coverage,
            ),
            patch(
                "go_runner_coverage.evaluate_go_integration_gate",
                return_value=(None, True),
            ),
            patch.object(
                test_report,
                "_render_index",
                side_effect=RuntimeError("renderer exploded"),
            ),
        ):
            exit_code = run_tests.run_pytest_suites(args, (), [])

        self.assertEqual(exit_code, 1)
        session.cleanup.assert_called_once_with()
        summary_path = report_root / "unit" / "latest" / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(summary["records"][0]["status"], "failed")
        self.assertEqual(summary["coverage"]["status"], "incomplete")
        self.assertEqual(summary["coverage"]["diagnostics"][0]["stage"], "combine")
        self.assertEqual(summary["report"]["status"], "failed")
        self.assertIn("renderer exploded", summary["report"]["error"])
        anomaly_path = report_root / "unit" / "latest" / "coverage_anomaly_snapshot.json"
        self.assertTrue(anomaly_path.exists())


    def test_runner_unit_suite_uses_pytest_path_and_does_not_set_postgres_env(self):
        coverage = coverage_summary()
        seen = {}
        scratch_authority = {
            key: os.environ[key]
            for key in (
                "REPOMAP_TEST_SCRATCH_ROOT",
                "REPOMAP_TEST_RUN_ROOT",
                "REPOMAP_TEST_PROJECT",
                "REPOMAP_TEST_PHASE",
            )
            if key in os.environ
        }

        def fake_run_pytest(pytest_module, pytest_args, plugin):
            seen["pytest_args"] = pytest_args
            seen["pg_port"] = os.environ.get("REPOMAP_TEST_PG_CONTAINER_PORT")
            seen["pg_runtime"] = os.environ.get("REPOMAP_TEST_PG_CONTAINER_RUNTIME")
            plugin.add_record(
                self.pytest_report(nodeid="pkg/test_file.py::test_passes"),
                "passed",
            )
            return 0

        def fake_run_pytest_with_coverage(
            coverage_module, pytest_module, pytest_args, plugin
        ):
            return fake_run_pytest(pytest_module, pytest_args, plugin), object()

        with patch.dict(os.environ, {}, clear=True):
            os.environ.update(scratch_authority)
            with (
                patch.object(
                    run_tests, "import_pytest", return_value=self.fake_pytest()
                ),
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
            ):
                exit_code = run_tests.main(["--suite", "unit", "--", "-k", "baseline"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            self.strip_centralized_basetemp(seen["pytest_args"]),
            [str(run_tests.TEST_ROOTS["unit"]), "-k", "baseline"],
        )
        self.assertIsNone(seen["pg_port"])
        self.assertIsNone(seen["pg_runtime"])


    def test_runner_int_suite_sets_container_harness_environment(self):
        passing_go_summary = test_report.GoCoverageSummary(
            suite_name="int",
            hard_threshold=80.0,
            total_statements=10,
            covered_statements=10,
            statement_percent=100.0,
            branch_status="N/A",
            diagnostic_category="passed",
        )
        exit_code, seen, boundary, resource_run = self._execute_mocked_int_runner(
            passing_go_summary, True
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            self.strip_centralized_basetemp(seen["pytest_args"]),
            [str(run_tests.TEST_ROOTS["int"]), "-k", "postgres"],
        )
        self.assertEqual(seen["pg_port"], "55444")
        self.assertEqual(seen["pg_runtime"], "docker")
        self.assert_staging_discovery_call(seen)
        self.assertEqual(boundary.verify_terminal.call_count, 2)
        boundary.close.assert_called_once_with(resource_run)


    def test_runner_int_suite_fails_when_go_integration_evaluator_fails(self):
        failing_go_summary = test_report.GoCoverageSummary(
            suite_name="int",
            hard_threshold=80.0,
            total_statements=10,
            covered_statements=5,
            statement_percent=50.0,
            branch_status="N/A",
            diagnostic_category="below_threshold",
        )
        exit_code, seen, boundary, resource_run = self._execute_mocked_int_runner(
            failing_go_summary, False
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(seen["pg_port"], "55444")
        self.assertEqual(seen["pg_runtime"], "docker")
        self.assert_staging_discovery_call(seen)
        self.assertEqual(boundary.verify_terminal.call_count, 1)
        boundary.close.assert_called_once_with(resource_run)


    def test_runner_int_suite_fails_and_refuses_execution_when_discovery_fails(self):
        from runner_staging_discovery_contract import PopulationDiscoveryError
        from staging_report_contract import execution_succeeded, qualifies

        discovery_error = PopulationDiscoveryError(
            "discovery child failed with exit 1; synthetic failure"
        )
        exit_code, seen, boundary, resource_run = self._execute_mocked_int_runner(
            None, False, discovery_error=discovery_error
        )
        self.assertEqual(exit_code, 1)
        self.assert_staging_discovery_call(seen)
        self.assertEqual(seen["leg_order"], [])
        self.assertEqual(boundary.verify_terminal.call_count, 1)
        boundary.close.assert_called_once_with(resource_run)

        report_path = seen["report_path"]
        self.assertTrue(report_path.exists())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["errors"], ["accounting: PopulationDiscoveryError"])
        self.assertEqual(report["partition"], {})
        for leg in ("M", "A"):
            self.assertEqual(report["legs"][leg]["status"], "not_selected")
            self.assertEqual(report["legs"][leg]["records"], [])
        self.assertFalse(execution_succeeded(report) or qualifies(report))


    def test_runner_can_build_explicit_unit_and_int_paths(self):
        self.assertEqual(
            run_tests.build_pytest_args(("unit", "int"), []),
            [str(run_tests.TEST_ROOTS["unit"]), str(run_tests.TEST_ROOTS["int"])],
        )


    def test_runner_prepares_go_environment_before_pytest(self):
        with (
            patch.object(
                run_tests,
                "prepare_go_test_environment",
                return_value=None,
            ) as prepare,
            patch.object(run_tests, "run_pytest_suites", return_value=3),
        ):
            exit_code = run_tests.main(["--suite", "unit"])

        self.assertEqual(exit_code, 3)
        prepare.assert_called_once_with("unit")


    def test_go_preflight_builds_for_pytest_suites_and_validates_unit(self):
        helper = self.tmpdir / "repomap-go-extract"
        for suite, validation_calls in (("int", 0), ("unit", 1), ("staging", 0)):
            with self.subTest(suite=suite):
                with (
                    patch.object(run_tests, "validate_go_sources") as validate,
                    patch.object(
                        run_tests,
                        "build_go_helper",
                        return_value=helper,
                    ) as build,
                    patch.dict(os.environ, {}, clear=True),
                ):
                    self.prepare_go_test_environment(suite)
                    self.assertEqual(
                        os.environ["REPOMAP_GO_HELPER"],
                        str(helper),
                    )

                self.assertEqual(validate.call_count, validation_calls)
                build.assert_called_once()
                output_root = build.call_args.kwargs["package_root"]
                self.assertEqual(output_root.name, "helper")
                self.assertEqual(output_root.parent.name, "t")
                self.assertEqual(output_root.parent.parent.name, "go")


    def test_go_preflight_failure_is_reported_by_runner(self):
        stderr = io.StringIO()
        with (
            patch.object(
                run_tests,
                "prepare_go_test_environment",
                side_effect=RuntimeError("Go validation failed"),
            ),
            patch.object(run_tests, "run_pytest_suites") as pytest_run,
            redirect_stderr(stderr),
        ):
            exit_code = run_tests.main(["--suite", "unit"])

        self.assertEqual(exit_code, 2)
        self.assertIn("Go validation failed", stderr.getvalue())
        pytest_run.assert_not_called()


    def test_runner_smoke_suite_delegates_to_smoke_without_pytest(self):
        args = SimpleNamespace(suite="smoke", report=False, jobs="1")
        resource_run = Mock()
        with (
            patch.object(run_tests, "run_smoke_suite", return_value=0) as smoke,
            patch.object(
                run_tests,
                "run_pytest_suites",
                side_effect=AssertionError("smoke must not run pytest"),
            ),
        ):
            exit_code = run_tests.run_selected_suites(args, [], resource_run)

        self.assertEqual(exit_code, 0)
        smoke.assert_called_once_with(args, resource_run, None)


    def test_runner_staging_suite_runs_integration_after_smoke_success(self):
        args = SimpleNamespace(suite="staging")
        resource_run = Mock()
        with (
            patch.object(run_tests, "prepare_go_test_environment"),
            patch.object(run_tests, "run_pytest_suites", return_value=0) as pytest_run,
            patch.object(run_tests, "run_smoke_suite", return_value=0) as smoke,
        ):
            exit_code = run_tests.run_selected_suites(args, [], resource_run)

        self.assertEqual(exit_code, 0)
        pytest_run.assert_called_once()
        self.assertEqual(pytest_run.call_args.args[1], ("int",))
        smoke.assert_called_once_with(args, resource_run, None)


    def test_runner_staging_suite_returns_smoke_failure_before_pytest(self):
        args = SimpleNamespace(suite="staging")
        resource_run = Mock()
        with (
            patch.object(run_tests, "prepare_go_test_environment"),
            patch.object(run_tests, "run_pytest_suites") as pytest_run,
            patch.object(run_tests, "run_smoke_suite", return_value=7),
        ):
            exit_code = run_tests.run_selected_suites(args, [], resource_run)

        self.assertEqual(exit_code, 7)
        pytest_run.assert_not_called()


    def test_runner_staging_suite_returns_integration_failure_after_smoke(self):
        args = SimpleNamespace(suite="staging")
        resource_run = Mock()
        with (
            patch.object(run_tests, "prepare_go_test_environment"),
            patch.object(run_tests, "run_pytest_suites", return_value=3),
            patch.object(run_tests, "run_smoke_suite", return_value=0) as smoke,
        ):
            exit_code = run_tests.run_selected_suites(args, [], resource_run)

        self.assertEqual(exit_code, 3)
        smoke.assert_called_once()
