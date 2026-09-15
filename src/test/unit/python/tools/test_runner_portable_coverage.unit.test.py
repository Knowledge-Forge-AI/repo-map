"""Unit tests for runner_portable_coverage scoped adapter and portable child measurement."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import os

import coverage
import repomap_kg.coordinator._portable_worker_launch as pwl
from repomap_kg.coordinator._protocol_validation import WorkerLaunchError
from repomap_kg.coordinator._worker_launch import WorkerLaunchSpec
from runner_coverage import ChildCoverageSession
from runner_coverage_capability import (
    CapabilityContainmentError,
    CapabilityRefusalError,
    CapabilityValidationError,
)
from runner_portable_coverage import (
    make_portable_worker_spec_adapter,
    scoped_portable_coverage_adapter,
    validate_shard_directory_integrity,
)

CHILD_CODE = '''"""Tiny maintained portable child fixture."""
import argparse, sys
from repomap_kg.coordinator.protocol import (
    MAX_JSONL_LINE_BYTES,
    ProtocolSession,
    decode_jsonl,
    encode_jsonl,
)

def branch_function(flag: bool) -> int:
    if flag:
        chosen = 100
    else:
        chosen = 200
    return chosen

def main() -> int:
    from repomap_kg.coordinator import _portable_authority as authority
    assert authority.install_portable_authority_guard.__module__ == authority.__name__
    from pathlib import Path
    workspace = Path.cwd() / 'guarded-workspace'
    workspace.mkdir()
    authority.install_portable_authority_guard(
        store_root=workspace, workspace_root=workspace,
        code_roots=(Path(__file__).parent, Path(authority.__file__).parents[2]),
    )
    try:
        open(Path.cwd() / 'forbidden-output', 'w')
    except PermissionError:
        pass
    else:
        raise AssertionError('portable guard was weakened')
    val = branch_function(True)
    assert val == 100
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", default="job-1")
    parser.add_argument("--attempt", type=int, default=1)
    args, _ = parser.parse_known_args()
    identity = {"job_id": args.job_id, "attempt": args.attempt}
    session = ProtocolSession(identity)
    hello = {
        "schema_version": 1,
        "message_type": "worker_hello",
        "protocol_versions": [1],
        "worker_generation": "worker-v1",
        "capabilities": ["refresh_graph"],
        "process_nonce": "nonce-1",
    }
    session.accept_worker(hello)
    sys.stdout.buffer.write(encode_jsonl(hello))
    sys.stdout.buffer.flush()

    line = sys.stdin.buffer.readline(MAX_JSONL_LINE_BYTES + 1)
    job_start = decode_jsonl(line)
    session.accept_coordinator(job_start)

    terminal = {
        "schema_version": 1,
        "message_type": "result",
        **identity,
        "job_kind": "refresh_graph",
        "graph_id": job_start["graph_id"],
        "status": "succeeded",
        "started_at": "2026-09-12T12:00:01Z",
        "finished_at": "2026-09-12T12:00:02Z",
        "phase": "complete",
        "files": 1,
        "observations": 1,
        "canonical_nodes": 1,
        "canonical_edges": 1,
        "warnings": [],
        "diagnostics": [],
        "publication_state": "committed",
        "latest_run_identity": "run-1",
        "source_generation": job_start["source_generation"],
        "config_generation": job_start["config_generation"],
        "extractor_generation": "eg1:synth",
        "canonicalizer_generation": "kg1:synth",
        "retryable": False,
        "error_category": None,
    }
    session.accept_worker(terminal)
    sys.stdout.buffer.write(encode_jsonl(terminal))
    sys.stdout.buffer.flush()
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''


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
        self.identity = {"job_id": "job-1", "attempt": 1}
        self.limits = SimpleNamespace(
            process_deadline_seconds=5.0,
            heartbeat_seconds=1.0,
            hello_deadline_seconds=1.0,
            cancellation_after_seconds=0.1,
            cancel_deadline_seconds=0.1,
            process_termination_grace_seconds=0.1,
            max_diagnostic_bytes=4096,
            max_protocol_line_bytes=65536,
            max_array_items=32,
        )

    def tearDown(self) -> None:
        self.session.cleanup()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_spec(
        self,
        *,
        extra_env: dict[str, str] | None = None,
        pypath: str | None = None,
    ) -> WorkerLaunchSpec:
        env = {
            "PYTHONPATH": pypath if pypath is not None else f"{self.source_dir}:{self.src_main}",
            "HOME": str(self.tmpdir),
            "TMPDIR": str(self.tmpdir),
        }
        if extra_env:
            env.update(extra_env)
        return WorkerLaunchSpec(
            argv=(sys.executable, "-m", "tiny_portable_child", "--job-id", "job-1", "--attempt", "1"),
            environment=env,
            cwd=self.tmpdir,
        )

    def test_actual_child_arc_and_line_measurement_end_to_end(self) -> None:
        runner = self.session.create_coverage(coverage)
        runner.start()

        spec = self._make_spec()
        with scoped_portable_coverage_adapter(self.session, self.cap):
            result = pwl.run_worker_spec(spec, self.identity, self.limits)
            self.assertEqual(result.terminal.get("status"), "succeeded")

        runner.stop()
        runner.save()
        for shard in self.session.data_dir.glob(".coverage.*"):
            child_data = coverage.CoverageData(basename=str(shard))
            child_data.read()
            print("synthetic shard lines", child_data.lines(str(self.child_file)))
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
        print("synthetic combined arcs", sorted(arcs))

    def test_default_portable_environment_has_no_instrumentation_or_credentials(self) -> None:
        from repomap_kg.coordinator._worker_environment import build_portable_worker_environment
        original = pwl.run_worker_spec
        with patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": "fixture-only",
                                     "PYTHONPATH": "/foreign", "COVERAGE_PROCESS_START": "/foreign"}):
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

    def test_negative_unpermitted_pythonpath_fails_closed(self) -> None:
        spec = self._make_spec(pypath=f"{self.source_dir}:/unpermitted/rogue/path")
        with scoped_portable_coverage_adapter(self.session, self.cap) as adapter:
            with self.assertRaises(CapabilityContainmentError):
                adapter(spec, self.identity, self.limits)

    def test_negative_ambient_coverage_variable_rejected(self) -> None:
        spec = self._make_spec(extra_env={"COVERAGE_PROCESS_START": "injected_rc"})
        with scoped_portable_coverage_adapter(self.session, self.cap) as adapter:
            with self.assertRaisesRegex(CapabilityValidationError, "ambient coverage variable rejected"):
                adapter(spec, self.identity, self.limits)

    def test_negative_missing_shard_fails_closed(self) -> None:
        token = self.cap.register_prelaunch_child()
        missing_shard = self.session.data_dir / f".coverage.missing.{token}"
        mf = self.session.child_manifest_dir
        (mf / f"{token}.start").write_text(
            f"token={token}\ninvocation={self.cap.invocation_id}\nsuite=int\n"
            f"revision={self.cap.source_commitment}\npid=111\ncov_start=1\ncomplete=1\n",
            encoding="utf-8",
        )
        (mf / f"{token}.exit").write_text(
            f"token={token}\ninvocation={self.cap.invocation_id}\nsuite=int\n"
            f"revision={self.cap.source_commitment}\npid=111\ncov_start=1\ncomplete=1\nshard={missing_shard}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CapabilityValidationError, "missing or 0 bytes"):
            self.cap.validate_for_accept(token)

    def test_negative_corrupt_shard_fails_closed(self) -> None:
        token = self.cap.register_prelaunch_child()
        corrupt = self.session.data_dir / f".coverage.corrupt.{token}"
        corrupt.write_bytes(b"NOT_SQLITE_HEADER")
        mf = self.session.child_manifest_dir
        (mf / f"{token}.start").write_text(
            f"token={token}\ninvocation={self.cap.invocation_id}\nsuite=int\n"
            f"revision={self.cap.source_commitment}\npid=111\ncov_start=1\ncomplete=1\n",
            encoding="utf-8",
        )
        (mf / f"{token}.exit").write_text(
            f"token={token}\ninvocation={self.cap.invocation_id}\nsuite=int\n"
            f"revision={self.cap.source_commitment}\npid=111\ncov_start=1\ncomplete=1\nshard={corrupt}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CapabilityValidationError, "invalid SQLite header"):
            self.cap.validate_for_accept(token)

    def test_negative_unregistered_child_rejected(self) -> None:
        with self.assertRaises(CapabilityRefusalError):
            self.cap.validate_for_accept("unregistered_token_abc")

        unreg = self.session.data_dir / ".coverage.fabricated.999"
        unreg.touch()
        with self.assertRaisesRegex(RuntimeError, "unregistered coverage shard rejected"):
            validate_shard_directory_integrity(
                data_dir=self.session.data_dir,
                allowed_shards=set(),
                parent_shard=None,
                snapshot_fn=self.session._create_snapshot,
                record_fn=self.session._record_diagnostic,
            )
        unreg.unlink()

    def test_unregistered_aggregate_basename_is_rejected(self) -> None:
        foreign = self.session.data_dir / ".coverage"
        foreign.write_bytes(b"foreign aggregate")
        with self.assertRaisesRegex(RuntimeError, "unregistered coverage shard rejected"):
            validate_shard_directory_integrity(
                data_dir=self.session.data_dir, allowed_shards=set(), parent_shard=None,
                snapshot_fn=self.session._create_snapshot, record_fn=self.session._record_diagnostic,
            )

    def test_cross_suite_and_unbound_receipts_cannot_enter_integration(self) -> None:
        from runner_coverage_execution import read_registered_children
        for suite in ("unit", "smoke", "system"):
            with self.subTest(suite=suite):
                marker = self.session.child_manifest_dir / "10001.start"
                marker.write_text(f"pid=10001\ninvocation={self.cap.invocation_id}\nsuite={suite}\n")
                with self.assertRaisesRegex(RuntimeError, "suite identity mismatch"):
                    read_registered_children(self.session.child_manifest_dir,
                                             expected_invocation=self.cap.invocation_id, expected_suite="int")
        marker.write_text("pid=10001\nsuite=int\n")
        with self.assertRaisesRegex(RuntimeError, "invocation identity mismatch"):
            read_registered_children(self.session.child_manifest_dir,
                                     expected_invocation=self.cap.invocation_id, expected_suite="int")

    def test_negative_symlink_escape_fails_closed(self) -> None:
        token = self.cap.register_prelaunch_child()
        target = self.tmpdir / "outside_target"
        target.touch()
        sym = self.session.child_manifest_dir / f"{token}.sym"
        sym.symlink_to(target)
        with self.assertRaises(CapabilityContainmentError):
            self.cap.validate_for_accept(token)

    def test_negative_non_int_suite_refusal(self) -> None:
        for suite in ("unit", "smoke", "system", "inert"):
            with self.subTest(suite=suite):
                with self.assertRaises(CapabilityRefusalError):
                    self.session.issue_portable_capability(suite=suite)

    def test_negative_cancelled_child_without_shard_records_diagnostic(self) -> None:
        def failing_inner(*args: object, **kwargs: object) -> None:
            raise WorkerLaunchError("simulated_worker_crash")

        adapter = make_portable_worker_spec_adapter(failing_inner, self.cap, self.session)
        spec = self._make_spec()
        with self.assertRaises(WorkerLaunchError) as caught:
            adapter(spec, self.identity, self.limits)

        self.assertTrue(
            any("child coverage measurement failure" in note for note in caught.exception.__notes__)
        )
        self.assertTrue(len(self.session.measurement_errors) > 0)

        runner = self.session.create_coverage(coverage)
        runner.start()
        runner.stop()
        runner.save()
        with self.assertRaisesRegex(RuntimeError, "coverage measurement failed"):
            self.session.combine(runner)
