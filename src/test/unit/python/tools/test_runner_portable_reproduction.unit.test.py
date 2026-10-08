"""Unit tests for runner_portable reproduction causal proof and timing controls."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import threading
from typing import Any
import unittest
from unittest.mock import patch

import coverage
import repomap_kg.coordinator._portable_worker_launch as pwl
from repomap_kg.coordinator._worker_launch import WorkerLaunchSpec
from repomap_test_support.run25_portable_workflows import (
    TINY_PORTABLE_CHILD_CODE,
    build_run25_worker_limits,
)
from runner_coverage import ChildCoverageSession
import runner_portable_coverage as rpc
from runner_portable_coverage import scoped_portable_coverage_adapter


class RunnerPortableReproductionUnitTests(unittest.TestCase):
    """Unit tests providing causal proof of timing controls and failure reproduction."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="repomap-repro-test-")).resolve()
        self.source_dir = self.tmpdir / "src"
        self.source_dir.mkdir(parents=True)
        self.child_file = self.source_dir / "tiny_portable_child.py"
        self.child_file.write_text(TINY_PORTABLE_CHILD_CODE, encoding="utf-8")
        self.repo_root = Path(__file__).resolve().parents[5]
        self.src_main = self.repo_root / "src/main/python"
        self.session = ChildCoverageSession(
            coverage_module=coverage,
            scratch_dir=self.tmpdir / "session",
            source_root=self.source_dir,
            suite="int",
        )
        self.cap = self.session.issue_portable_capability(
            suite="int",
            permitted_python_paths=[self.source_dir, self.src_main],
            portable_command=("-m", "tiny_portable_child"),
        )
        self.identity = {"job_id": "job-repro-1", "attempt": 1}
        self.limits = build_run25_worker_limits()

    def tearDown(self) -> None:
        try:
            self.session.cleanup()
        finally:
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_spec(self, *, extra_args: tuple[str, ...] | None = None) -> WorkerLaunchSpec:
        env = {
            "PYTHONPATH": f"{self.source_dir}:{self.src_main}",
            "HOME": str(self.tmpdir),
            "TMPDIR": str(self.tmpdir),
        }
        argv = [sys.executable, "-m", "tiny_portable_child", "--job-id", "job-repro-1", "--attempt", "1"]
        if extra_args:
            argv.extend(extra_args)
        return WorkerLaunchSpec(argv=tuple(argv), environment=env, cwd=self.tmpdir)

    def test_ordinary_non_measured_execution_baseline(self) -> None:
        """Ordinary non-measured execution preserves workload semantics without coverage adapter."""
        spec = self._make_spec()
        result = pwl.run_worker_spec(spec, self.identity, self.limits)
        self.assertEqual(result.terminal.get("status"), "succeeded")
        self.assertEqual(result.returncode, 0)
        self.assertFalse(result.hello_timed_out)
        self.assertFalse(result.process_timed_out)
        self.assertFalse(result.synthesized_terminal)
        self.assertTrue(result.waited)
        self.assertTrue(result.process_group_cleaned)

    def test_real_child_hello_timeout_synthesis(self) -> None:
        """Real child sleeping before hello trips hello_deadline producing synthesized terminal."""
        spec = self._make_spec(extra_args=("--pre-hello-sleep", "0.3"))
        with patch.object(rpc, "RUNNER_MEASURED_CHILD_HELLO_DEADLINE_SECONDS", 0.08), \
             patch.object(rpc, "RUNNER_MEASURED_CHILD_PROCESS_DEADLINE_SECONDS", 1.0):
            limits = dict(vars(self.limits), hello_deadline_seconds=0.08, process_deadline_seconds=1.0)
            with scoped_portable_coverage_adapter(self.session, self.cap):
                result = pwl.run_worker_spec(spec, self.identity, limits)
        self.assertTrue(result.hello_timed_out)
        self.assertTrue(result.synthesized_terminal)
        self.assertTrue(result.terminated)
        self.assertEqual(result.terminal.get("reason"), "hello_timeout")
        self.assertEqual(result.terminal.get("message_type"), "worker_exit")
        self.assertTrue(result.waited)
        self.assertTrue(result.process_group_cleaned)

    def test_real_child_process_timeout_synthesis(self) -> None:
        """Real child completing hello but crossing process deadline trips process_timeout."""
        spec = self._make_spec(extra_args=("--workload-sleep", "0.4"))
        with patch.object(rpc, "RUNNER_MEASURED_CHILD_HELLO_DEADLINE_SECONDS", 1.0), \
             patch.object(rpc, "RUNNER_MEASURED_CHILD_PROCESS_DEADLINE_SECONDS", 0.12), \
             patch.object(rpc, "RUNNER_MEASUREMENT_RECEIPT_HEADROOM_SECONDS", 0.05):
            limits = dict(vars(self.limits), hello_deadline_seconds=1.0, process_deadline_seconds=0.12)
            with scoped_portable_coverage_adapter(self.session, self.cap):
                result = pwl.run_worker_spec(spec, self.identity, limits)
        self.assertFalse(result.hello_timed_out)
        self.assertTrue(result.process_timed_out)
        self.assertTrue(result.synthesized_terminal)
        self.assertTrue(result.terminated)
        self.assertEqual(result.terminal.get("reason"), "process_timeout")
        self.assertEqual(result.terminal.get("message_type"), "worker_exit")
        self.assertTrue(result.waited)
        self.assertTrue(result.process_group_cleaned)

    def test_missing_exit_receipt_discrimination(self) -> None:
        """Missing terminal exit receipt is discriminated from empty receipt."""
        spec = self._make_spec()
        real_run = pwl.run_worker_spec

        def intercept_missing(s: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            res = real_run(s, ident, lims, **kwargs)
            token = next(iter(self.cap.launched_commands))
            exit_p = self.session.child_manifest_dir / f"{token}.exit"
            if exit_p.is_file():
                exit_p.unlink()
            return res

        with patch("repomap_kg.coordinator._portable_worker_launch.run_worker_spec", side_effect=intercept_missing):
            with scoped_portable_coverage_adapter(self.session, self.cap):
                res = pwl.run_worker_spec(spec, self.identity, self.limits)
        self.assertEqual(res.terminal.get("status"), "succeeded")
        self.assertTrue(len(self.session.measurement_errors) >= 1)
        err_msg = str(self.session.measurement_errors[0])
        self.assertIn("terminal exit marker missing", err_msg)
        self.assertNotIn("child terminal receipt empty", err_msg)

    def test_empty_exit_receipt_discrimination(self) -> None:
        """Empty terminal exit receipt (0 bytes) is discriminated from missing receipt."""
        spec = self._make_spec()
        real_run = pwl.run_worker_spec

        def intercept_empty(s: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            res = real_run(s, ident, lims, **kwargs)
            token = next(iter(self.cap.launched_commands))
            exit_p = self.session.child_manifest_dir / f"{token}.exit"
            exit_p.write_bytes(b"")
            return res

        with patch("repomap_kg.coordinator._portable_worker_launch.run_worker_spec", side_effect=intercept_empty):
            with scoped_portable_coverage_adapter(self.session, self.cap):
                res = pwl.run_worker_spec(spec, self.identity, self.limits)
        self.assertEqual(res.terminal.get("status"), "succeeded")
        self.assertTrue(len(self.session.measurement_errors) >= 1)
        err_msg = str(self.session.measurement_errors[0])
        self.assertIn("child terminal receipt empty (0 bytes)", err_msg)
        self.assertNotIn("terminal exit marker missing", err_msg)

    def test_malformed_receipt_discrimination(self) -> None:
        """Incomplete / malformed exit receipt is discriminated from corrupt shard."""
        spec = self._make_spec()
        real_run = pwl.run_worker_spec

        def intercept_incomplete(s: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            res = real_run(s, ident, lims, **kwargs)
            token = next(iter(self.cap.launched_commands))
            exit_p = self.session.child_manifest_dir / f"{token}.exit"
            content = exit_p.read_text(encoding="utf-8")
            exit_p.write_text(content.replace("complete=1", "complete=0"), encoding="utf-8")
            return res

        with patch("repomap_kg.coordinator._portable_worker_launch.run_worker_spec", side_effect=intercept_incomplete):
            with scoped_portable_coverage_adapter(self.session, self.cap):
                res = pwl.run_worker_spec(spec, self.identity, self.limits)
        self.assertEqual(res.terminal.get("status"), "succeeded")
        self.assertTrue(len(self.session.measurement_errors) >= 1)
        err_msg = str(self.session.measurement_errors[0])
        self.assertIn("child terminal receipt incomplete", err_msg)
        self.assertNotIn("invalid SQLite header", err_msg)

    def test_corrupt_coverage_shard_discrimination(self) -> None:
        """Corrupt coverage shard is discriminated from malformed receipt."""
        spec = self._make_spec()
        real_run = pwl.run_worker_spec

        def intercept_corrupt_shard(s: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            res = real_run(s, ident, lims, **kwargs)
            token = next(iter(self.cap.launched_commands))
            for shard in self.session.data_dir.glob(f".coverage.{token}*"):
                shard.write_bytes(b"CORRUPT_NOT_SQLITE_DATA_HEADER")
            return res

        with patch("repomap_kg.coordinator._portable_worker_launch.run_worker_spec", side_effect=intercept_corrupt_shard):
            with scoped_portable_coverage_adapter(self.session, self.cap):
                res = pwl.run_worker_spec(spec, self.identity, self.limits)
        self.assertEqual(res.terminal.get("status"), "succeeded")
        self.assertTrue(len(self.session.measurement_errors) >= 1)
        err_msg = str(self.session.measurement_errors[0])
        self.assertIn("has invalid SQLite header", err_msg)
        self.assertNotIn("child terminal receipt incomplete", err_msg)

    def test_parent_workload_exception_with_measurement_failure(self) -> None:
        """Workload exception is preserved as primary fault when measurement also fails."""
        spec = self._make_spec()

        class ParentWorkloadError(RuntimeError):
            pass

        real_run = pwl.run_worker_spec

        def intercept_crash(s: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            real_run(s, ident, lims, **kwargs)
            token = next(iter(self.cap.launched_commands))
            exit_p = self.session.child_manifest_dir / f"{token}.exit"
            if exit_p.is_file():
                exit_p.unlink()
            raise ParentWorkloadError("parent crashed during execution")

        with patch("repomap_kg.coordinator._portable_worker_launch.run_worker_spec", side_effect=intercept_crash):
            with scoped_portable_coverage_adapter(self.session, self.cap):
                with self.assertRaises(ParentWorkloadError) as ctx:
                    pwl.run_worker_spec(spec, self.identity, self.limits)

        notes = getattr(ctx.exception, "__notes__", [])
        self.assertTrue(any("child coverage measurement failure" in note for note in notes))
        self.assertTrue(len(self.session.measurement_errors) >= 1)

    def test_cooperative_cancellation_preserves_supervisor_contracts(self) -> None:
        """Cooperative child cancellation preserves supervisor reap and group cleanup."""
        spec = self._make_spec(extra_args=("--mode", "cancel"))
        cancel_event = threading.Event()
        with scoped_portable_coverage_adapter(self.session, self.cap):
            cancel_event.set()
            result = pwl.run_worker_spec(spec, self.identity, self.limits, cancel_event=cancel_event)
        self.assertEqual(result.terminal.get("status"), "cancelled")
        self.assertTrue(result.waited)
        self.assertTrue(result.process_group_cleaned)
