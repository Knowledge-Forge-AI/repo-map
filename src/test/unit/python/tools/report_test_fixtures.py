import os
import shutil
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[5]

import run_tests

def coverage_summary(
    *,
    suite_name: str = "unit",
    line_percent: float = 100.0,
    branch_percent: float = 100.0,
    line_hard_threshold: float = 80.0,
    branch_hard_threshold: float = 80.0,
    line_warn_threshold: float = 85.0,
    branch_warn_threshold: float = 85.0,
):
    return run_tests.CoverageSummary(
        suite_name=suite_name,
        line_hard_threshold=line_hard_threshold,
        branch_hard_threshold=branch_hard_threshold,
        line_warn_threshold=line_warn_threshold,
        branch_warn_threshold=branch_warn_threshold,
        total_lines=100,
        covered_lines=int(line_percent),
        line_percent=line_percent,
        total_branches=100,
        covered_branches=int(branch_percent),
        branch_percent=branch_percent,
        files=(
            run_tests.CoverageFileRecord(
                path=REPO_ROOT / "src/main/python/repomap_kg/example.py",
                executable_lines=100,
                covered_lines=int(line_percent),
                line_percent=line_percent,
                total_branches=100,
                covered_branches=int(branch_percent),
                branch_percent=branch_percent,
            ),
        ),
    )


class MockedIntRunnerSeen(TypedDict, total=False):
    discovery: dict[str, object]
    discovery_calls: list[dict[str, object]]
    pytest_args: list[str]
    pg_port: str | None
    pg_runtime: str | None
    leg_order: list[str]
    report_path: Path


class ReportTestCase(unittest.TestCase):
    def strip_centralized_basetemp(self, pytest_args):
        """Assert the runner pins pytest's basetemp, then return the rest.

        SCALE28-FIX12-DIAG1-FIX1 made the runner own the test scratch, so every
        run it launches carries an explicit basetemp beneath the selected run
        root. Asserting it here keeps that contract covered instead of merely
        tolerating the extra arguments.
        """
        self.assertIn("--basetemp", pytest_args)
        index = pytest_args.index("--basetemp")
        basetemp = Path(pytest_args[index + 1])
        self.assertTrue(basetemp.is_absolute())
        self.assertEqual(basetemp.name, "pt")
        self.assertEqual(pytest_args[index + 2], "-o")
        self.assertEqual(
            pytest_args[index + 3],
            f"cache_dir={basetemp / 'cache'}",
        )
        return pytest_args[:index] + pytest_args[index + 4:]


    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="repomap-report-test-"))
        self.prepare_go_test_environment = run_tests.prepare_go_test_environment
        self.go_preflight = patch.object(
            run_tests,
            "prepare_go_test_environment",
            return_value=None,
        )
        self.go_preflight.start()
        self.runner_scratch = [
            patch.object(run_tests, "integration_sandbox_dispatch", return_value=None),
            patch.object(run_tests, "require_integration_sandbox"),
            patch.object(run_tests, "establish_test_scratch", return_value=object()),
            patch.object(run_tests.TestResourceRun, "start", return_value=None),
            patch.object(run_tests, "finalize_run"),
        ]
        for patcher in self.runner_scratch:
            patcher.start()


    def tearDown(self):
        for patcher in reversed(self.runner_scratch):
            patcher.stop()
        self.go_preflight.stop()
        shutil.rmtree(self.tmpdir)


    def _execute_mocked_int_runner(
        self,
        go_summary,
        go_ok: bool,
        *,
        discovery_error: Exception | None = None,
        report_dir: Path | None = None,
    ):
        # Keep this regression hermetic.  It models one sealed collection and
        # the two required legs without collecting or executing integration
        # tests on the host.
        from dataclasses import replace

        import runner_integration_execution as integration_execution
        from runner_integration_obligations import MAINTAINED_ABRUPT_DECLARATIONS
        from runner_integration_population import partition_population
        import runner_staging_discovery

        coverage = coverage_summary(suite_name="int")
        coverage = replace(coverage, files=list(coverage.files))
        seen: MockedIntRunnerSeen = {}
        target_report_dir = report_dir or (
            self.tmpdir / f"int-report-{go_ok}-{discovery_error is not None}"
        )
        run_root = self.tmpdir / f"int-run-{go_ok}-{discovery_error is not None}"
        run_root.mkdir()
        go_tmp = run_root / "go"
        go_tmp.mkdir()
        layout = SimpleNamespace(
            run_root=run_root, pytest_basetemp=run_root / "pt", go_tmp=go_tmp, allocated=True,
        )
        measured_node = "pkg/test_file.py::test_passes"
        abrupt_nodes = tuple(item.nodeid for item in MAINTAINED_ABRUPT_DECLARATIONS)
        population = (measured_node, *abrupt_nodes)
        invocation_id = "1" * 32
        candidate = {"commit": "2" * 40, "source_sha256": "3" * 64}
        sessions: list[object] = []
        leg_order: list[str] = []
        discovery_calls: list[dict[str, object]] = []

        def fake_discover_staging_population(
            args, pytest_args, *, repo_root, source_root, test_support_root,
            invocation_id, candidate_identity, scoped, timeout_seconds=120.0,
            child_script_path=None, declarations=MAINTAINED_ABRUPT_DECLARATIONS,
        ):
            del timeout_seconds, child_script_path
            self.assertEqual(leg_order, [])
            call_info: dict[str, object] = {
                "args": args, "pytest_args": pytest_args, "repo_root": repo_root,
                "source_root": source_root, "test_support_root": test_support_root,
                "invocation_id": invocation_id, "candidate_identity": candidate_identity,
                "scoped": scoped,
                "pg_port": os.environ.get("REPOMAP_TEST_PG_CONTAINER_PORT"),
                "pg_runtime": os.environ.get("REPOMAP_TEST_PG_CONTAINER_RUNTIME"),
            }
            discovery_calls.append(call_info)
            seen["discovery"] = call_info
            if discovery_error is not None:
                raise discovery_error
            return partition_population(
                population, declarations=declarations, suite=args.suite, scoped=scoped,
                deferred_nodes=(), collected_nodes=population,
            )

        class FakeLegPlugin:
            def __init__(self, partition, leg, *, suite, full_population):
                self.partition = partition
                self.leg = leg
                self.suite = suite
                self.full_population = full_population
                self.test_records = ()
                self.executed_nodeids = []
                self.completed_nodeids = []
                self.teardown_failed = False
                self.abrupt_context = None

        class FakeSession:
            def __init__(self, **_kwargs):
                index = len(sessions)
                self.session_dir = run_root / f"session-{index}"
                self.session_dir.mkdir()
                self.bootstrap_dir = run_root / f"bootstrap-{index}"
                self.bootstrap_dir.mkdir()
                sessions.append(self)

            def cleanup(self):
                self.cleaned = True

        class FakeAbruptContext:
            def __init__(self, *, nodeids, invocation_id, source_sha256, verify_source):
                self.nodeids = tuple(nodeids)
                self.invocation_id = invocation_id
                self.source_sha256 = source_sha256
                self.verify_source = verify_source
                self.records = {}

            def select_test(self, nodeid):
                del nodeid

            def bind_session(self, session):
                return nullcontext(self)

        def populate_roles(context, nodes):
            declarations = {item.nodeid: item for item in MAINTAINED_ABRUPT_DECLARATIONS}
            for index, nodeid in enumerate(nodes):
                declaration = declarations[nodeid]
                context.records[nodeid] = {
                    "nodeid": nodeid, "role": declaration.role,
                    "invocation_id": context.invocation_id,
                    "source_sha256": context.source_sha256,
                    "launch_id": f"launch-{index}", "pid": 1000 + index, "parent_pid": 900,
                    "started_ns": 1, "checkpoint": declaration.checkpoint,
                    "returncode": declaration.expected_returncode, "settled_ns": 2,
                    "cleanup": True, "measurement": "unavailable",
                }

        def fake_run_pytest(pytest_module, pytest_args, plugin):
            del pytest_module
            seen["pytest_args"] = pytest_args
            seen["pg_port"] = os.environ.get("REPOMAP_TEST_PG_CONTAINER_PORT")
            seen["pg_runtime"] = os.environ.get("REPOMAP_TEST_PG_CONTAINER_RUNTIME")
            leg_order.append(plugin.leg)
            nodes = plugin.partition.m_nodes if plugin.leg == "M" else plugin.partition.a_nodes
            plugin.test_records = tuple(
                run_tests.TestRecord(nodeid, nodeid.split("::", 1)[0], "passed", 0.0123, "")
                for nodeid in nodes
            )
            plugin.executed_nodeids.extend(nodes)
            plugin.completed_nodeids.extend(nodes)
            if plugin.leg == "A":
                populate_roles(plugin.abrupt_context, nodes)
            return 0

        def fake_run_pytest_with_coverage(
            coverage_module, pytest_module, pytest_args, plugin, **_kwargs
        ):
            del coverage_module
            return fake_run_pytest(pytest_module, pytest_args, plugin), SimpleNamespace(
                _instrumentation_error=None
            )

        resource_run = Mock()
        resource_run.quota_exceeded = False
        resource_run.bounded_subprocess.return_value = nullcontext()
        boundary = Mock()
        boundary.verify_terminal.return_value = {
            k: 0
            for k in (
                "product_or_build_profile_build_count",
                "managed_test_runtime_image_build_count",
                "managed_runtime_build_intermediate_created_count",
                "managed_runtime_build_intermediate_removed_count",
                "managed_runtime_build_intermediate_residue_count",
                "managed_external_base_pull_count",
                "unmanaged_build_count",
                "unmanaged_pull_count",
                "new_managed_external_test_base_images",
                "new_managed_test_runtime_cache_images",
                "new_unattributed_images",
                "new_unattributed_volumes",
                "current_run_ephemeral_image_residue",
                "current_run_image_residue",
                "current_run_volume_residue",
            )
        }

        with patch.dict(
            os.environ,
            {
                "REPOMAP_TEST_PG_CONTAINER_PORT": "old-port",
                "REPOMAP_TEST_PG_CONTAINER_RUNTIME": "old-runtime",
                "REPOMAP_TEST_RUNTIME_IMAGE": "sha256:" + "a" * 64,
            },
            clear=False,
        ):
            with (
                patch.object(run_tests, "import_pytest", return_value=self.fake_pytest()),
                patch.object(run_tests, "import_coverage", return_value=object()),
                patch.object(
                    run_tests, "run_pytest_with_coverage",
                    side_effect=fake_run_pytest_with_coverage,
                ),
                patch.object(run_tests, "run_pytest", side_effect=fake_run_pytest),
                patch.object(run_tests, "collect_coverage_summary", return_value=coverage),
                patch.object(run_tests, "report_coverage", return_value=True),
                patch.object(run_tests, "establish_test_scratch", return_value=layout),
                patch.object(run_tests, "establish_run", return_value=layout),
                patch.object(run_tests.TestResourceRun, "start", return_value=resource_run),
                patch.object(run_tests, "start_runwide_docker_boundary", return_value=boundary),
                patch.object(run_tests, "finalize_run"),
                patch(
                    "go_runner_coverage.evaluate_go_integration_gate",
                    return_value=(go_summary, go_ok),
                ) as mock_go_gate,
                patch.object(
                    runner_staging_discovery, "discover_staging_population",
                    side_effect=fake_discover_staging_population,
                ),
                patch.object(integration_execution, "candidate_identity", return_value=candidate),
                patch.object(
                    integration_execution, "uuid4", return_value=SimpleNamespace(hex=invocation_id),
                ),
                patch.object(integration_execution, "LegPartitionPytestPlugin", FakeLegPlugin),
                patch.object(integration_execution, "ChildCoverageSession", FakeSession),
                patch.object(integration_execution, "AbruptRunnerContext", FakeAbruptContext),
                patch.object(integration_execution, "coverage_diagnostics", return_value=()),
                patch("repomap_test_support.test_scratch.establish_run", return_value=layout),
            ):
                exit_code = run_tests.main(
                    [
                        "--suite", "int",
                        "--pg-container-port", "55444",
                        "--pg-container-runtime", "docker",
                        "--report-dir", str(target_report_dir),
                        "--", "-k", "postgres",
                    ]
                )

            self.assertEqual(os.environ.get("REPOMAP_TEST_PG_CONTAINER_PORT"), "old-port")
            self.assertEqual(os.environ.get("REPOMAP_TEST_PG_CONTAINER_RUNTIME"), "old-runtime")
            self.assertEqual(len(discovery_calls), 1)
            seen["discovery_calls"] = discovery_calls
            seen["leg_order"] = leg_order
            seen["report_path"] = target_report_dir / "int" / "latest" / "staging_contract_report.json"
            if discovery_error is not None:
                mock_go_gate.assert_not_called()
                self.assertEqual(leg_order, [])
                self.assertEqual(len(sessions), 0)
            else:
                mock_go_gate.assert_called_once_with("int", False)
                self.assertEqual(leg_order, ["M", "A"])
                self.assertEqual(len(sessions), 2)
                self.assertTrue(all(getattr(s, "cleaned", False) for s in sessions))

        return exit_code, seen, boundary, resource_run


    def assert_staging_discovery_call(self, seen, *, scoped=False, suite="int"):
        disc = seen["discovery"]
        self.assertEqual(len(seen["discovery_calls"]), 1)
        self.assertEqual(disc["invocation_id"], "1" * 32)
        self.assertEqual(
            disc["candidate_identity"],
            {"commit": "2" * 40, "source_sha256": "3" * 64},
        )
        self.assertEqual(disc["repo_root"], run_tests.REPO_ROOT)
        self.assertEqual(disc["source_root"], run_tests.SOURCE_ROOT)
        self.assertEqual(disc["test_support_root"], run_tests.TEST_SUPPORT_ROOT)
        self.assertEqual(disc["args"].suite, suite)
        self.assertEqual(disc["scoped"], scoped)
        self.assertEqual(disc["pg_port"], "55444")
        self.assertEqual(disc["pg_runtime"], "docker")
        self.assertEqual(
            self.strip_centralized_basetemp(disc["pytest_args"]),
            [str(run_tests.TEST_ROOTS[suite]), "-k", "postgres"],
        )


    def fake_pytest(self):
        return SimpleNamespace(ExitCode=SimpleNamespace(NO_TESTS_COLLECTED=5))


    def pytest_report(
        self,
        *,
        nodeid="pkg/test_file.py::test_passes",
        when="call",
        status="passed",
        longreprtext="",
        longrepr=None,
    ):
        return SimpleNamespace(
            nodeid=nodeid,
            when=when,
            passed=status == "passed",
            skipped=status == "skipped",
            failed=status == "failed",
            longreprtext=longreprtext,
            longrepr=longrepr,
            duration=0.0123,
            location=(nodeid.split("::", 1)[0], 1, nodeid.rsplit("::", 1)[-1]),
        )
