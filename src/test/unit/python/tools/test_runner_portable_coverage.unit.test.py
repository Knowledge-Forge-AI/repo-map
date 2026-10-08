"""Unit tests for runner_portable_coverage scoped adapter and portable child measurement."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Any
import unittest
from unittest.mock import patch

import coverage
import repomap_kg.coordinator._portable_worker_launch as pwl
from repomap_kg.coordinator._protocol_validation import WorkerLaunchError
from repomap_kg.coordinator._worker_launch import WorkerLaunchSpec
from repomap_test_support.run25_portable_workflows import (
    TINY_PORTABLE_CHILD_CODE as CHILD_CODE,
    build_run25_worker_limits,
)
from runner_coverage import ChildCoverageSession
from runner_coverage_capability import (
    CapabilityContainmentError,
    CapabilityRefusalError,
    CapabilityValidationError,
)
from runner_portable_coverage import (
    _CoveredManagedProcess,
    make_portable_worker_spec_adapter,
    scoped_portable_coverage_adapter,
    validate_shard_directory_integrity,
)


class RunnerPortableCoverageUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="repomap-port-cov-test-")).resolve()
        self.source_dir = self.tmpdir / "src"
        self.source_dir.mkdir(parents=True)
        self.child_file = self.source_dir / "tiny_portable_child.py"
        self.child_file.write_text(CHILD_CODE, encoding="utf-8")
        self.repo_root = Path(__file__).resolve().parents[5]
        self.src_main = self.repo_root / "src/main/python"
        self.session = ChildCoverageSession(
            coverage_module=coverage, scratch_dir=self.tmpdir / "session",
            source_root=self.source_dir, suite="int",
        )
        self.cap = self.session.issue_portable_capability(
            suite="int", permitted_python_paths=[self.source_dir, self.src_main],
            portable_command=("-m", "tiny_portable_child"),
        )
        self.identity = {"job_id": "job-1", "attempt": 1}
        self.limits = build_run25_worker_limits()

    def tearDown(self) -> None:
        try:
            self.session.cleanup()
        finally:
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _assert_child_reaped_and_marked(self, result: Any) -> None:
        self.assertTrue(result.waited and result.process_group_cleaned)
        self.assertIn(result.returncode, (0, -15))
        token = next(iter(self.cap.launched_commands))
        self.assertIn("cov_start=1", (self.session.child_manifest_dir / f"{token}.start").read_text(encoding="utf-8"))
        self.assertIn("complete=1", (self.session.child_manifest_dir / f"{token}.exit").read_text(encoding="utf-8"))

    def _make_spec(
        self, *, extra_env: dict[str, str] | None = None,
        pypath: str | None = None, extra_args: tuple[str, ...] | None = None,
    ) -> WorkerLaunchSpec:
        env = {
            "PYTHONPATH": pypath if pypath is not None else f"{self.source_dir}:{self.src_main}",
            "HOME": str(self.tmpdir), "TMPDIR": str(self.tmpdir),
        }
        if extra_env:
            env.update(extra_env)
        argv = [sys.executable, "-m", "tiny_portable_child", "--job-id", "job-1", "--attempt", "1"]
        if extra_args:
            argv.extend(extra_args)
        return WorkerLaunchSpec(argv=tuple(argv), environment=env, cwd=self.tmpdir)

    def test_actual_child_arc_and_line_measurement_end_to_end(self) -> None:
        runner = self.session.create_coverage(coverage)
        runner.start()
        try:
            spec = self._make_spec()
            with scoped_portable_coverage_adapter(self.session, self.cap):
                result = pwl.run_worker_spec(spec, self.identity, self.limits)
                self.assertEqual(result.terminal.get("status"), "succeeded")
        finally:
            runner.stop()
            runner.save()

        self._assert_child_reaped_and_marked(result)
        self.assertFalse(result.terminated or result.killed)

        for shard in self.session.data_dir.glob(".coverage.*"):
            child_data = coverage.CoverageData(basename=str(shard))
            child_data.read()
        combined = self.session.combine(runner)
        data = combined.get_data()

        target_file = str(self.child_file.resolve())
        self.assertIn(target_file, data.measured_files())
        lines = set(data.lines(target_file))
        self.assertIn(12, lines)
        self.assertNotIn(14, lines)
        arcs = set(data.arcs(target_file))
        self.assertIn((11, 12), arcs)
        self.assertNotIn((11, 14), arcs)
        self.assertIs(self.session.combine(runner), combined)

    def test_actual_child_cooperative_cancellation_measurement(self) -> None:
        import threading
        runner = self.session.create_coverage(coverage)
        runner.start()
        try:
            cancel_event = threading.Event()
            cancel_event.set()
            spec = self._make_spec(extra_args=("--mode", "cancel"))
            with scoped_portable_coverage_adapter(self.session, self.cap):
                result = pwl.run_worker_spec(spec, self.identity, self.limits, cancel_event=cancel_event)
                self.assertEqual(result.terminal.get("status"), "cancelled")
        finally:
            runner.stop()
            runner.save()

        self._assert_child_reaped_and_marked(result)
        combined = self.session.combine(runner)
        self.assertIn(str(self.child_file.resolve()), combined.get_data().measured_files())

    def _run_worker_under_coverage(self, **make_spec_kwargs: Any) -> tuple[Any, Any]:
        runner = self.session.create_coverage(coverage)
        runner.start()
        try:
            spec = self._make_spec(**make_spec_kwargs)
            with scoped_portable_coverage_adapter(self.session, self.cap):
                result = pwl.run_worker_spec(spec, self.identity, self.limits)
        finally:
            runner.stop()
            runner.save()
        return runner, result

    def test_actual_child_expected_bounded_failure_measurement(self) -> None:
        runner, result = self._run_worker_under_coverage(extra_args=("--mode", "fail"))
        self.assertEqual(result.terminal.get("status"), "failed")
        self.assertEqual(result.terminal.get("error_category"), "authorization")
        self._assert_child_reaped_and_marked(result)
        self.assertIn(str(self.child_file.resolve()), self.session.combine(runner).get_data().measured_files())

    def test_post_terminal_delay_exceeding_termination_grace_exits_naturally(self) -> None:
        runner, result = self._run_worker_under_coverage(extra_args=("--atexit-sleep", "0.20"))
        self.assertEqual(result.terminal.get("status"), "succeeded")
        self._assert_child_reaped_and_marked(result)
        self.assertFalse(result.heartbeat_timed_out or result.terminated or result.killed)
        self.assertFalse(result.synthesized_terminal)
        self.assertEqual(result.returncode, 0)
        self.assertIn(str(self.child_file.resolve()), self.session.combine(runner).get_data().measured_files())

    def test_completion_deadline_without_receipt_headroom_fails_measurement(self) -> None:
        runner = self.session.create_coverage(coverage)
        runner.start()
        try:
            # Exceed the adapter's three-second process deadline, independently
            # of the 80 ms escalation grace. No terminal can excuse this hang.
            spec = self._make_spec(extra_args=("--atexit-sleep", "10.0"))
            with patch("runner_portable_coverage.RUNNER_MEASUREMENT_RECEIPT_HEADROOM_SECONDS", 0.0):
                with scoped_portable_coverage_adapter(self.session, self.cap):
                    result = pwl.run_worker_spec(spec, self.identity, self.limits)
                    self.assertTrue(result.terminated)
                    self.assertEqual(result.returncode, -15)
                    self.assertEqual(result.terminal.get("message_type"), "worker_exit")
                    self.assertEqual(result.terminal.get("reason"), "completion_timeout")
                    self.assertTrue(result.synthesized_terminal)
                    assert result.original_terminal is not None
                    self.assertEqual(result.original_terminal.get("status"), "succeeded")
                    self.assertTrue(self.session.measurement_errors)
                    self.assertIsInstance(self.session.measurement_errors[0], CapabilityValidationError)
        finally:
            runner.stop()
            runner.save()
        with self.assertRaisesRegex(RuntimeError, "coverage measurement failed"):
            self.session.combine(runner)

    def test_covered_managed_process_unit_contracts(self) -> None:
        mock_inner = unittest.mock.MagicMock()
        mock_inner.poll.return_value = 0
        token = "tok_imm"
        (self.session.child_manifest_dir / f"{token}.exit").write_text("complete=1\n", encoding="utf-8")
        proc = _CoveredManagedProcess(mock_inner, token, self.session.child_manifest_dir, exit_timeout=0.5)
        self.assertTrue(proc._wait_for_exit_receipt())
        proc.terminate_gracefully()
        mock_inner.terminate_gracefully.assert_not_called()

        mock_running = unittest.mock.MagicMock()
        mock_running.poll.return_value = None
        tok_del = "tok_del"
        proc2 = _CoveredManagedProcess(mock_running, tok_del, self.session.child_manifest_dir, exit_timeout=0.03)
        t0 = time.monotonic()
        proc2.terminate_gracefully()
        self.assertGreaterEqual(time.monotonic() - t0, 0.02)
        mock_running.terminate_gracefully.assert_called_once()
        t1 = time.monotonic()
        proc2.kill_tree()
        proc2.cleanup(0.01, 0.01)
        self.assertLess(time.monotonic() - t1, 0.025)
        mock_running.kill_tree.assert_called_once()

    def test_default_portable_environment_has_no_instrumentation_or_credentials(self) -> None:
        from repomap_kg.coordinator._worker_environment import build_portable_worker_environment
        original = pwl.run_worker_spec
        with patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": "fixture-only", "PYTHONPATH": "/foreign"}):
            env = build_portable_worker_environment(workspace_root=self.tmpdir, python_path=self.src_main)
        self.assertIs(pwl.run_worker_spec, original)
        self.assertFalse(any(k.startswith("COVERAGE_") or k.startswith("AWS_") for k in env))
        self.assertEqual(env["PYTHONPATH"], str(self.src_main))

    def test_authorized_environment_passes_only_bounded_fields(self) -> None:
        observed = {}
        def capture(spec, *args, **kwargs):
            observed.update(spec.environment)
            return "primary-result"
        adapter = make_portable_worker_spec_adapter(capture, self.cap, self.session)
        result = adapter(self._make_spec(extra_env={"AWS_SECRET_ACCESS_KEY": "fixture-only"}),
                         self.identity, self.limits)
        self.assertEqual(result, "primary-result")
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", observed)
        self.assertEqual(observed["PYTHONNOUSERSITE"], "1")
        self.assertEqual(observed["COVERAGE_PROCESS_START"], str(self.cap.config_file))
        self.assertTrue(self.session.measurement_errors)

    def test_scoped_adapter_installation_and_restoration_lifecycle(self) -> None:
        orig = pwl.run_worker_spec
        with scoped_portable_coverage_adapter(self.session, self.cap) as adapter:
            self.assertIs(pwl.run_worker_spec, adapter)
            self.assertIsNot(pwl.run_worker_spec, orig)
        self.assertIs(pwl.run_worker_spec, orig)

    def test_negative_containment_and_ambient_rejections(self) -> None:
        with scoped_portable_coverage_adapter(self.session, self.cap) as adapter:
            with self.assertRaises(CapabilityContainmentError):
                adapter(self._make_spec(pypath=f"{self.source_dir}:/unpermitted/rogue/path"), self.identity, self.limits)
            with self.assertRaisesRegex(CapabilityValidationError, "ambient coverage variable rejected"):
                adapter(self._make_spec(extra_env={"COVERAGE_PROCESS_START": "injected_rc"}), self.identity, self.limits)

    def _write_markers(self, token: str, shard: Path | None = None) -> None:
        mf = self.session.child_manifest_dir
        base = (
            f"token={token}\ninvocation={self.cap.invocation_id}\nsuite=int\n"
            f"revision={self.cap.source_commitment}\npid=111\ncov_start=1\ncomplete=1\n"
        )
        (mf / f"{token}.start").write_text(base, encoding="utf-8")
        (mf / f"{token}.exit").write_text(f"{base}shard={shard}\n" if shard else base, encoding="utf-8")

    def test_negative_missing_shard_fails_closed(self) -> None:
        token = self.cap.register_prelaunch_child()
        self._write_markers(token, self.session.data_dir / f".coverage.missing.{token}")
        with self.assertRaisesRegex(CapabilityValidationError, "missing or 0 bytes"):
            self.cap.validate_for_accept(token)

    def test_negative_corrupt_shard_fails_closed(self) -> None:
        token = self.cap.register_prelaunch_child()
        corrupt = self.session.data_dir / f".coverage.corrupt.{token}"
        corrupt.write_bytes(b"NOT_SQLITE_HEADER")
        self._write_markers(token, corrupt)
        with self.assertRaisesRegex(CapabilityValidationError, "invalid SQLite header"):
            self.cap.validate_for_accept(token)

    def test_negative_unregistered_child_and_aggregate_rejected(self) -> None:
        with self.assertRaises(CapabilityRefusalError):
            self.cap.validate_for_accept("unregistered_token_abc")
        for path in (self.session.data_dir / ".coverage.fabricated.999", self.session.data_dir / ".coverage"):
            path.write_bytes(b"data")
            with self.assertRaisesRegex(RuntimeError, "unregistered coverage shard rejected"):
                validate_shard_directory_integrity(
                    data_dir=self.session.data_dir, allowed_shards=set(), parent_shard=None,
                    snapshot_fn=self.session._create_snapshot, record_fn=self.session._record_diagnostic,
                )
            path.unlink()

    def test_cross_suite_and_unbound_receipts_cannot_enter_integration(self) -> None:
        from runner_coverage_execution import read_registered_children
        for suite in ("unit", "smoke", "system"):
            with self.subTest(suite=suite):
                (self.session.child_manifest_dir / "10001.start").write_text(f"pid=10001\ninvocation={self.cap.invocation_id}\nsuite={suite}\n")
                with self.assertRaisesRegex(RuntimeError, "suite identity mismatch"):
                    read_registered_children(self.session.child_manifest_dir, expected_invocation=self.cap.invocation_id, expected_suite="int")
        (self.session.child_manifest_dir / "10001.start").write_text("pid=10001\nsuite=int\n")
        with self.assertRaisesRegex(RuntimeError, "invocation identity mismatch"):
            read_registered_children(self.session.child_manifest_dir, expected_invocation=self.cap.invocation_id, expected_suite="int")

    def test_negative_symlink_escape_and_suite_refusal(self) -> None:
        token = self.cap.register_prelaunch_child()
        target = self.tmpdir / "outside_target"
        target.touch()
        (self.session.child_manifest_dir / f"{token}.sym").symlink_to(target)
        with self.assertRaises(CapabilityContainmentError):
            self.cap.validate_for_accept(token)
        for suite in ("unit", "smoke", "system", "inert"):
            with self.subTest(suite=suite):
                with self.assertRaises(CapabilityRefusalError):
                    self.session.issue_portable_capability(suite=suite)

    def test_negative_cancelled_child_without_shard_records_diagnostic(self) -> None:
        def failing_inner(*args: object, **kwargs: object) -> None:
            raise WorkerLaunchError("simulated_worker_crash")
        adapter = make_portable_worker_spec_adapter(failing_inner, self.cap, self.session)
        with self.assertRaises(WorkerLaunchError) as caught:
            adapter(self._make_spec(), self.identity, self.limits)
        self.assertTrue(any("child coverage measurement failure" in note for note in caught.exception.__notes__))
        self.assertTrue(self.session.measurement_errors)
        runner = self.session.create_coverage(coverage)
        runner.start()
        runner.stop()
        runner.save()
        with self.assertRaisesRegex(RuntimeError, "coverage measurement failed"):
            self.session.combine(runner)
