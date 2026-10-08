"""Companion unit tests for runner_portable_coverage testing deadline adjustment and diagnostic capture."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import MagicMock

import coverage
from repomap_kg.coordinator._worker_launch import WorkerLaunchSpec
from runner_coverage import ChildCoverageSession
from runner_portable_coverage import (
    RUNNER_MEASURED_CHILD_HELLO_DEADLINE_SECONDS,
    RUNNER_MEASURED_CHILD_PROCESS_DEADLINE_SECONDS,
    _CoveredManagedProcess,
    make_portable_worker_spec_adapter,
)


class RunnerPortableCoverageCompanionUnitTests(unittest.TestCase):
    """Targeted companion tests for measured child limits, wrapper receipts, and diagnostics."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="repomap-test-cov-comp-"))
        self.source_dir = self.tmpdir / "src"
        self.source_dir.mkdir(parents=True)
        self.session = ChildCoverageSession(
            coverage_module=coverage,
            scratch_dir=self.tmpdir / "session",
            source_root=self.source_dir,
            suite="int",
        )
        self.cap = self.session.issue_portable_capability(
            suite="int",
            permitted_python_paths=[self.source_dir],
            portable_command=("-m", "unit_test_companion"),
        )
        self.identity = {"job_id": "job-comp-1", "attempt": 1}
        self.spec = WorkerLaunchSpec(
            argv=(sys.executable, "-m", "unit_test_companion"),
            environment={"PYTHONPATH": str(self.source_dir)},
            cwd=self.tmpdir,
        )

    def tearDown(self) -> None:
        try:
            self.session.cleanup()
        finally:
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_hello_deadline_adjustment_dict_low_and_high(self) -> None:
        captured_limits: list[Any] = []

        def dummy_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            captured_limits.append(lims)
            return SimpleNamespace(returncode=0, terminal={"status": "succeeded"})

        adapter = make_portable_worker_spec_adapter(dummy_runner, self.cap, self.session)

        # 1. Low deadline (0.5s hello, 0.8s process) is raised to (2.0s, 3.0s)
        low_dict = {"hello_deadline_seconds": 0.5, "process_deadline_seconds": 0.8, "job_timeout_seconds": 30.0}
        res = adapter(self.spec, self.identity, low_dict)
        self.assertEqual(res.terminal["status"], "succeeded")
        self.assertEqual(len(captured_limits), 1)
        self.assertIsInstance(captured_limits[0], dict)
        self.assertEqual(
            captured_limits[0]["hello_deadline_seconds"],
            RUNNER_MEASURED_CHILD_HELLO_DEADLINE_SECONDS,
        )
        self.assertEqual(
            captured_limits[0]["process_deadline_seconds"],
            RUNNER_MEASURED_CHILD_PROCESS_DEADLINE_SECONDS,
        )
        self.assertEqual(captured_limits[0]["job_timeout_seconds"], 30.0)

        # 2. High deadline (5.0s, 6.0s) is retained intact
        high_dict = {"hello_deadline_seconds": 5.0, "process_deadline_seconds": 6.0, "job_timeout_seconds": 30.0}
        res2 = adapter(self.spec, self.identity, high_dict)
        self.assertEqual(res2.terminal["status"], "succeeded")
        self.assertEqual(len(captured_limits), 2)
        self.assertEqual(captured_limits[1]["hello_deadline_seconds"], 5.0)
        self.assertEqual(captured_limits[1]["process_deadline_seconds"], 6.0)

    def test_hello_deadline_adjustment_namespace_low_and_high(self) -> None:
        captured_limits: list[Any] = []

        def dummy_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            captured_limits.append(lims)
            return SimpleNamespace(returncode=0, terminal={"status": "succeeded"})

        adapter = make_portable_worker_spec_adapter(dummy_runner, self.cap, self.session)

        # 1. SimpleNamespace with 0.5s/0.8s is raised to 2.0s/3.0s without duplicate kwarg error
        low_ns = SimpleNamespace(hello_deadline_seconds=0.5, process_deadline_seconds=0.8, heartbeat_interval_seconds=1.0)
        res = adapter(self.spec, self.identity, low_ns)
        self.assertEqual(res.terminal["status"], "succeeded")
        self.assertEqual(len(captured_limits), 1)
        self.assertIsInstance(captured_limits[0], SimpleNamespace)
        self.assertEqual(
            captured_limits[0].hello_deadline_seconds,
            RUNNER_MEASURED_CHILD_HELLO_DEADLINE_SECONDS,
        )
        self.assertEqual(
            captured_limits[0].process_deadline_seconds,
            RUNNER_MEASURED_CHILD_PROCESS_DEADLINE_SECONDS,
        )
        self.assertEqual(captured_limits[0].heartbeat_interval_seconds, 1.0)

        # 2. SimpleNamespace with 4.5s/5.5s is retained
        high_ns = SimpleNamespace(hello_deadline_seconds=4.5, process_deadline_seconds=5.5, heartbeat_interval_seconds=1.0)
        res2 = adapter(self.spec, self.identity, high_ns)
        self.assertEqual(res2.terminal["status"], "succeeded")
        self.assertEqual(len(captured_limits), 2)
        self.assertEqual(captured_limits[1].hello_deadline_seconds, 4.5)
        self.assertEqual(captured_limits[1].process_deadline_seconds, 5.5)

    def test_covered_managed_process_wait_and_receipt_detection(self) -> None:
        token = "token-test-proc-1"
        inner_proc = MagicMock()
        inner_proc.pid = 99999
        inner_proc.poll.return_value = None

        proc = _CoveredManagedProcess(
            inner_proc,
            token,
            self.session.child_manifest_dir,
            exit_timeout=0.05,
        )

        # Attribute delegation
        self.assertEqual(proc.pid, 99999)
        self.assertIsNone(proc.poll())

        # When exit file is missing, _wait_for_exit_receipt returns False
        self.assertFalse(proc._wait_for_exit_receipt())

        # A new process with exit file created and completed poll
        token2 = "token-test-proc-2"
        inner_proc2 = MagicMock()
        inner_proc2.pid = 99998
        inner_proc2.poll.return_value = 0
        exit_path = self.session.child_manifest_dir / f"{token2}.exit"
        exit_path.write_text("complete=1\n", encoding="utf-8")
        proc2 = _CoveredManagedProcess(
            inner_proc2,
            token2,
            self.session.child_manifest_dir,
            exit_timeout=0.05,
        )
        self.assertTrue(proc2._wait_for_exit_receipt())

        # Verify terminate calls inner terminate
        proc.terminate()
        inner_proc.terminate.assert_called_once()

    def test_acceptance_failure_diagnostic_enrichment(self) -> None:
        def launch_mock(argv: Any, **kwargs: Any) -> Any:
            inner = MagicMock()
            inner.pid = 12345
            inner.returncode = -15
            inner.poll.return_value = -15
            env = kwargs.get("environment") or {}
            tok = env.get("COVERAGE_CHILD_REGISTRATION_TOKEN", "")
            if tok:
                start_p = self.session.child_manifest_dir / f"{tok}.start"
                start_p.write_text(f"pid=12345\ninvocation={self.cap.invocation_id}\nsuite=int\ncov_start=1\n")
                exit_p = self.session.child_manifest_dir / f"{tok}.exit"
                exit_p.write_bytes(b"")  # 0-byte exit marker reproduces acceptance failure
            return inner

        def dummy_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            launch_fn = kwargs["_launch_process"]
            proc = launch_fn(spec.argv, environment=spec.environment)
            return SimpleNamespace(
                returncode=-15,
                synthesized_terminal=True,
                terminal={"status": "failed", "reason": "hello_timeout"},
                process=proc,
                waited=True,
                process_group_cleaned=True,
                protocol_error=None,
                hello_timed_out=True,
                process_timed_out=False,
                heartbeat_timed_out=False,
            )

        adapter = make_portable_worker_spec_adapter(dummy_runner, self.cap, self.session)

        # Workload returns result without raising, but acceptance failure is recorded
        result = adapter(self.spec, self.identity, {"hello_deadline_seconds": 0.5}, _launch_process=launch_mock)
        self.assertEqual(result.returncode, -15)
        self.assertEqual(result.terminal["status"], "failed")

        # Ensure diagnostic snapshot was enriched with all markers
        self.assertTrue(len(self.session.diagnostic_snapshots) >= 1)
        diag = self.session.diagnostic_snapshots[0]
        self.assertIn("exit_bytes=0", diag.reader_status)
        self.assertIn("retcode=-15", diag.reader_status)
        self.assertIn("reason=hello_timeout", diag.reader_status)
        self.assertIn("timeouts=h:True/p:False/hb:False", diag.reader_status)
        self.assertIn("cov_start=1", diag.reader_status)
        self.assertIn("child terminal receipt empty (0 bytes)", diag.reader_status)
        self.assertEqual(diag.file_type, "missing_or_corrupt")
        self.assertEqual(diag.termination_outcome, "child_measurement_failed")

        # Session records measurement error preventing quiet loss
        self.assertTrue(len(self.session.measurement_errors) >= 1)
        self.assertIn("child terminal receipt empty", str(self.session.measurement_errors[0]))


if __name__ == "__main__":
    unittest.main()
