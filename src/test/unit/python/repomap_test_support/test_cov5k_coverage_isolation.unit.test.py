"""Unit tests verifying test_support COV5K child processes maintain coverage isolation."""

from __future__ import annotations

import os
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import coverage
from repomap_kg.coordinator.protocol import WorkerLaunchSpec, run_worker_spec
from repomap_test_support.synthetic_worker_adapter import run_synthetic_worker
import runner_coverage
from runner_coverage_execution import prepare_child_coverage_environment
from repomap_test_support.scale28_preparation_worker_fixtures import (
    exit_with_synthetic_descendant,
)
from repomap_test_support.test_cov5k_r2_fix1_executor_preparation import (
    _enact_forced_tail,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation import (
    _forced_tail_for_observations,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation_conditions import (
    _condition_activity,
)
from repomap_test_support.test_cov5k_r2_fix2_preparation_execution import (
    _warm_preparation_worker_imports,
)

REPO_ROOT = Path(__file__).resolve().parents[5]


class Cov5kCoverageIsolationUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="repomap-cov5k-isolation-")
        self.tmp_path = Path(self.temp_dir.name).resolve()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_cpu_contention_natural_exit_produces_no_unregistered_shard(self) -> None:
        session_scratch = self.tmp_path / "session_cpu"
        with runner_coverage.ChildCoverageSession(
            coverage_module=coverage,
            scratch_dir=session_scratch,
            source_root=REPO_ROOT,
        ) as session:
            processes = []
            real_popen = subprocess.Popen

            def launch(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                processes.append(process)
                return process

            with patch("subprocess.Popen", side_effect=launch):
                with _condition_activity("cpu_contention", self.tmp_path, "cpu_test") as (key, pid):
                    self.assertEqual(key, "contention_pid")
                    self.assertEqual(pid, processes[0].pid)
                    self.assertEqual(processes[0].wait(timeout=10), 0)

            shards = [
                p.name for p in session.data_dir.iterdir()
                if p.name == ".coverage" or p.name.startswith(".coverage.")
            ]
            self.assertEqual(shards, [])
            combined = session.combine()
            self.assertFalse(combined)

    def test_forced_tail_produces_no_unregistered_shard(self) -> None:
        session_scratch = self.tmp_path / "session_forced_tail"
        with runner_coverage.ChildCoverageSession(
            coverage_module=coverage,
            scratch_dir=session_scratch,
            source_root=REPO_ROOT,
        ) as session:
            real_popen = subprocess.Popen
            environments = []

            def launch(*args, **kwargs):
                environments.append(kwargs.get("env", os.environ))
                return real_popen(*args, **kwargs)

            with patch("subprocess.Popen", side_effect=launch):
                signal_name, pid, retcode = _enact_forced_tail()
            self.assertEqual(len(environments), 1)
            self.assertFalse(any(key.startswith("COVERAGE_") for key in environments[0]))
            self.assertIn(signal_name, {"SIGTERM", "SIGKILL"})
            self.assertIsInstance(pid, int)
            self.assertNotEqual(retcode, 0)

            shards = [
                p.name for p in session.data_dir.iterdir()
                if p.name == ".coverage" or p.name.startswith(".coverage.")
            ]
            self.assertEqual(shards, [])
            combined = session.combine()
            self.assertFalse(combined)

    def test_forced_tail_for_observations_produces_no_unregistered_shard(self) -> None:
        session_scratch = self.tmp_path / "session_obs_tail"
        with runner_coverage.ChildCoverageSession(
            coverage_module=coverage,
            scratch_dir=session_scratch,
            source_root=REPO_ROOT,
        ) as session:
            sig, pid, ret, stdout_closed = _forced_tail_for_observations(
                ("preparation_timeout",)
            )
            self.assertIn(sig, {"SIGTERM", "SIGKILL"})
            self.assertIsInstance(pid, int)
            self.assertTrue(stdout_closed)

            shards = [
                p.name for p in session.data_dir.iterdir()
                if p.name == ".coverage" or p.name.startswith(".coverage.")
            ]
            self.assertEqual(shards, [])
            combined = session.combine()
            self.assertFalse(combined)

    def test_warm_preparation_worker_imports_produces_no_unregistered_shard(self) -> None:
        session_scratch = self.tmp_path / "session_warmup"
        with runner_coverage.ChildCoverageSession(
            coverage_module=coverage,
            scratch_dir=session_scratch,
            source_root=REPO_ROOT,
        ) as session:
            _warm_preparation_worker_imports()

            shards = [
                p.name for p in session.data_dir.iterdir()
                if p.name == ".coverage" or p.name.startswith(".coverage.")
            ]
            self.assertEqual(shards, [])
            combined = session.combine()
            self.assertFalse(combined)

    def test_exit_with_synthetic_descendant_produces_no_unregistered_shard(self) -> None:
        session_scratch = self.tmp_path / "session_descendant"
        with runner_coverage.ChildCoverageSession(
            coverage_module=coverage,
            scratch_dir=session_scratch,
            source_root=REPO_ROOT,
        ) as session:
            spec = MagicMock(pgdata_root=str(self.tmp_path))
            with patch("os._exit") as mock_exit:
                exit_with_synthetic_descendant(spec)
                mock_exit.assert_called_once_with(17)

            pid_file = self.tmp_path / "descendant.pid"
            self.assertTrue(pid_file.is_file())
            descendant_pid = int(pid_file.read_text(encoding="ascii").strip())
            try:
                # Descendant is alive before cleanup
                os.kill(descendant_pid, 0)
            finally:
                try:
                    os.kill(descendant_pid, signal.SIGKILL)
                    os.waitpid(descendant_pid, 0)
                except OSError:
                    pass

            shards = [
                p.name for p in session.data_dir.iterdir()
                if p.name == ".coverage" or p.name.startswith(".coverage.")
            ]
            self.assertEqual(shards, [])
            combined = session.combine()
            self.assertFalse(combined)

    def test_synthetic_async_worker_cancellation_launch_produces_no_unregistered_shard(self) -> None:
        session_scratch = self.tmp_path / "session_async_worker"
        with runner_coverage.ChildCoverageSession(
            coverage_module=coverage,
            scratch_dir=session_scratch,
            source_root=REPO_ROOT,
        ) as session:
            python_paths = (
                str(REPO_ROOT / "tools"),
                str(REPO_ROOT / "src/main/python"),
                str(REPO_ROOT / "src/test/support/python"),
            )
            clean_env = prepare_child_coverage_environment(
                family="unmeasured",
                extra_env={
                    "PYTHONPATH": os.pathsep.join(python_paths),
                    "LANG": "C.UTF-8",
                },
            )
            identity = {"job_id": "cov5k-async-cancel", "attempt": 1}
            child_session = self.tmp_path / "worker_session"
            receipt = self.tmp_path / "grandchild.json"
            # The launcher is intentionally unmeasured. Inside the real worker,
            # activate coverage before run_mode reaches its actual Popen seam.
            # Observe that seam without replacing the real process launch.
            script = "\n".join((
                "import json, os, sys",
                "from pathlib import Path",
                "from unittest.mock import patch",
                "import coverage",
                "from runner_coverage import ChildCoverageSession",
                "from repomap_test_support import synthetic_async_worker as worker",
                "real_popen = worker.subprocess.Popen",
                "def observed(*args, **kwargs):",
                "    process = real_popen(*args, **kwargs)",
                "    evidence = {'ambient': bool(os.environ.get('COVERAGE_PROCESS_START')),",
                "                'child': any(k.startswith('COVERAGE_') for k in kwargs['env']),",
                "                'pid': process.pid}",
                f"    Path({str(receipt)!r}).write_text(json.dumps(evidence))",
                "    return process",
                f"with ChildCoverageSession(coverage_module=coverage, scratch_dir=Path({str(child_session)!r}), source_root=Path({str(REPO_ROOT)!r})):",
                "    with patch.object(worker.subprocess, 'Popen', observed):",
                "        worker.main(sys.argv[1:])",
            ))
            spec = WorkerLaunchSpec(
                argv=(
                    sys.executable,
                    "-c",
                    script,
                    "--mode",
                    "non_cooperative_cancellation",
                    "--job-id",
                    str(identity["job_id"]),
                    "--attempt",
                    str(identity["attempt"]),
                ),
                environment=clean_env,
                cwd=REPO_ROOT,
                request_cancellation=True,
            )
            limits = {
                # Cold imports and nested coverage setup precede the hello.
                # Leave startup headroom on contended qualification runners.
                "process_deadline_seconds": 30.0,
                "heartbeat_seconds": 0.5,
                "hello_deadline_seconds": 10.0,
                "cancellation_after_seconds": 0.05,
                "cancel_deadline_seconds": 0.1,
                "process_termination_grace_seconds": 0.1,
                "max_diagnostic_bytes": 128,
            }
            result = run_worker_spec(spec, identity, limits)
            self.assertTrue(result.terminated)
            self.assertTrue(result.killed)
            self.assertTrue(result.process_group_cleaned)
            self.assertTrue(result.waited)
            self.assertEqual(result.terminal.get("reason"), "cancelled")
            evidence = json.loads(receipt.read_text())
            self.assertTrue(evidence["ambient"])
            self.assertFalse(evidence["child"])
            self.assertEqual(list((child_session / "shards").iterdir()), [])
            self.assertEqual(list((child_session / "child_procs").iterdir()), [])

            shards = [
                p.name for p in session.data_dir.iterdir()
                if p.name == ".coverage" or p.name.startswith(".coverage.")
            ]
            self.assertEqual(shards, [])
            combined = session.combine()
            self.assertFalse(combined)

    def test_synthetic_worker_adapter_has_self_contained_import_paths(self) -> None:
        with patch.dict(os.environ):
            os.environ.pop("PYTHONPATH", None)
            result = run_synthetic_worker(
                "success", {"job_id": "import-path-proof", "attempt": 1},
                {"process_deadline_seconds": 2.0, "hello_deadline_seconds": 1.0},
            )
        self.assertIsNone(result.protocol_error)
        self.assertTrue(result.waited)
        self.assertEqual(result.terminal["status"], "succeeded")
