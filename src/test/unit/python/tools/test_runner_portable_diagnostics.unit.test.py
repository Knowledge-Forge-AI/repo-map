"""Unit tests for runner_portable_diagnostics and R2 primary outcome preservation."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import MagicMock, patch

import coverage
from repomap_kg.coordinator._worker_launch import WorkerLaunchSpec
from runner_coverage import ChildCoverageSession
from runner_portable_coverage import make_portable_worker_spec_adapter
from runner_portable_diagnostics import (
    MAX_MARKER_DISPLAY_BYTES,
    read_bounded_marker,
    stat_exit_marker,
)


class CustomWorkloadError(RuntimeError):
    """Custom error representing a failure during child workload execution."""


class BrokenStringError(Exception):
    """Exception whose __str__ raises to verify exception-rendering protection."""

    def __str__(self) -> str:
        raise RuntimeError("injected exception-rendering failure")


class FailingAddNoteError(Exception):
    """Exception whose add_note raises to verify add_note protection."""

    def add_note(self, note: str) -> None:
        raise RuntimeError("injected add_note failure")


class RunnerPortableDiagnosticsUnitTests(unittest.TestCase):
    """Focused unit tests verifying R2 diagnostic boundaries and primary outcome preservation."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="repomap-test-diag-")).resolve()
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
            portable_command=("-m", "diag_test_companion"),
        )
        self.identity = {"job_id": "job-diag-1", "attempt": 1}
        self.spec = WorkerLaunchSpec(
            argv=(sys.executable, "-m", "diag_test_companion"),
            environment={"PYTHONPATH": str(self.source_dir)},
            cwd=self.tmpdir,
        )

    def tearDown(self) -> None:
        try:
            self.session.cleanup()
        finally:
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_original_workload_exception_preserved(self) -> None:
        """Original workload exception object and type are preserved when measurement fails."""
        original_exc = CustomWorkloadError("primary workload failed")

        def failing_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            raise original_exc

        adapter = make_portable_worker_spec_adapter(failing_runner, self.cap, self.session)

        with self.assertRaises(CustomWorkloadError) as cm:
            adapter(self.spec, self.identity, {"hello_deadline_seconds": 0.5})

        self.assertIs(cm.exception, original_exc)
        notes = getattr(cm.exception, "__notes__", [])
        self.assertTrue(any("child coverage measurement failure" in n for n in notes))

    def test_measurement_error_present_despite_enrichment_failure(self) -> None:
        """Measurement error is recorded in session even when diagnostic enrichment fails."""
        token = "tok_enrich_fail"
        exit_p = self.session.child_manifest_dir / f"{token}.exit"
        exit_p.write_bytes(b"")

        def dummy_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            launch_fn = kwargs["_launch_process"]
            proc = launch_fn(spec.argv, environment=spec.environment)
            return SimpleNamespace(
                returncode=-15,
                terminal={"status": "failed"},
                waited=True,
                process_group_cleaned=True,
                process=proc,
            )

        def mock_launch(argv: Any, **kwargs: Any) -> Any:
            inner = MagicMock()
            inner.pid = 77771
            inner.poll.return_value = -15
            env = kwargs.get("environment") or {}
            tok = env.get("COVERAGE_CHILD_REGISTRATION_TOKEN", "")
            if tok:
                start_p = self.session.child_manifest_dir / f"{tok}.start"
                start_p.write_text(
                    f"pid=77771\ninvocation={self.cap.invocation_id}\nsuite=int\ncov_start=1\n"
                )
                exit_p = self.session.child_manifest_dir / f"{tok}.exit"
                exit_p.write_bytes(b"")
            return inner

        adapter = make_portable_worker_spec_adapter(dummy_runner, self.cap, self.session)

        with patch.object(
            self.session, "_create_snapshot", side_effect=RuntimeError("snapshot_crash")
        ):
            res = adapter(
                self.spec, self.identity, {"hello_deadline_seconds": 0.5}, _launch_process=mock_launch
            )

        self.assertEqual(res.returncode, -15)
        self.assertTrue(len(self.session.measurement_errors) >= 1)
        self.assertIn("child terminal receipt empty", str(self.session.measurement_errors[0]))
        err_notes = getattr(self.session.measurement_errors[0], "__notes__", [])
        self.assertTrue(any("diagnostic recording failure" in n for n in err_notes))

    def test_successful_workload_with_lost_measurement_is_incomplete(self) -> None:
        """Successful workload with lost measurement fails combine and is never silently complete."""
        def mock_launch(argv: Any, **kwargs: Any) -> Any:
            inner = MagicMock()
            inner.pid = 77772
            inner.poll.return_value = 0
            env = kwargs.get("environment") or {}
            tok = env.get("COVERAGE_CHILD_REGISTRATION_TOKEN", "")
            if tok:
                (self.session.child_manifest_dir / f"{tok}.exit").write_bytes(b"")
            return inner

        def dummy_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            launch_fn = kwargs["_launch_process"]
            proc = launch_fn(spec.argv, environment=spec.environment)
            return SimpleNamespace(
                returncode=0,
                terminal={"status": "succeeded"},
                waited=True,
                process_group_cleaned=True,
                process=proc,
            )

        adapter = make_portable_worker_spec_adapter(dummy_runner, self.cap, self.session)
        res = adapter(
            self.spec, self.identity, {"hello_deadline_seconds": 0.5}, _launch_process=mock_launch
        )
        self.assertEqual(res.terminal["status"], "succeeded")

        runner = self.session.create_coverage(coverage)
        runner.start()
        runner.stop()
        runner.save()

        with self.assertRaisesRegex(RuntimeError, "coverage measurement failed"):
            self.session.combine(runner)

    def test_unrecorded_measurement_failure_raises_immediately(self) -> None:
        """When recording measurement error in session fails, adapter raises immediately."""
        def dummy_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            return SimpleNamespace(
                returncode=0,
                terminal={"status": "succeeded"},
                waited=True,
                process_group_cleaned=True,
            )

        adapter = make_portable_worker_spec_adapter(dummy_runner, self.cap, self.session)

        with patch.object(
            self.session,
            "record_measurement_error",
            side_effect=RuntimeError("session_record_error_crashed"),
        ):
            with self.assertRaises(RuntimeError) as cm:
                adapter(self.spec, self.identity, {"hello_deadline_seconds": 0.5})

        self.assertIn("unrecorded coverage measurement failure", str(cm.exception))
        self.assertIn("recording failure: session_record_error_crashed", str(cm.exception))

    def test_combined_workload_measurement_diagnostic_fault_represented(self) -> None:
        """One combined workload + measurement + diagnostic fault is represented in notes."""
        original_exc = CustomWorkloadError("workload_and_measurement_failed")

        def failing_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            raise original_exc

        adapter = make_portable_worker_spec_adapter(failing_runner, self.cap, self.session)

        with patch(
            "runner_portable_diagnostics.capture_portable_acceptance_diagnostic",
            side_effect=RuntimeError("diagnostic_hook_broken"),
        ):
            with self.assertRaises(CustomWorkloadError) as cm:
                adapter(self.spec, self.identity, {"hello_deadline_seconds": 0.5})

        self.assertIs(cm.exception, original_exc)
        notes = getattr(cm.exception, "__notes__", [])
        self.assertTrue(any("child coverage measurement failure" in n for n in notes))
        self.assertTrue(any("diagnostic recording failure" in n for n in notes))

    def test_bounded_marker_read_and_truncation(self) -> None:
        """Bounded marker read reads at most MAX_READ_BYTES and distinguishes truncation."""
        test_file = self.tmpdir / "oversized.start"
        long_line = "token=" + ("a" * (MAX_MARKER_DISPLAY_BYTES + 100)) + "\n"
        test_file.write_text(long_line, encoding="utf-8")

        status, display, fields = read_bounded_marker(test_file)
        self.assertEqual(status, "truncated_read")
        self.assertTrue(display.endswith("[truncated]"))

    def test_strict_utf8_decode_and_escaped_fallback(self) -> None:
        """Strict UTF-8 decode distinguishes invalid bytes and formats escaped fallback."""
        bad_file = self.tmpdir / "invalid_utf8.start"
        bad_file.write_bytes(b"pid=1234\ncorrupt=\xff\xfe\x00\x80\n")

        status, display, fields = read_bounded_marker(bad_file)
        self.assertEqual(status, "invalid_utf8")
        self.assertIn("[invalid_utf8]", display)
        self.assertEqual(fields, {})

    def test_marker_whitelist_no_secret_dump(self) -> None:
        """Start marker parsing whitelists expected fields and prevents secret leakage."""
        marker_file = self.tmpdir / "secrets.start"
        content = (
            "token=safe_token_123\n"
            "pid=4567\n"
            "AWS_SECRET_ACCESS_KEY=super_secret_credentials\n"
            "DATABASE_PASSWORD=dont_leak_me\n"
            "cov_start=1\n"
        )
        marker_file.write_text(content, encoding="utf-8")

        status, display, fields = read_bounded_marker(marker_file)
        self.assertEqual(status, "valid")
        self.assertIn("safe_token_123", display)
        self.assertIn("cov_start", display)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", display)
        self.assertNotIn("super_secret_credentials", display)
        self.assertNotIn("DATABASE_PASSWORD", display)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", fields)

    def test_exit_marker_states_missing_empty_stat_failure(self) -> None:
        """stat_exit_marker distinctly reports missing, empty, and present states."""
        missing_p = self.tmpdir / "nonexistent.exit"
        st_missing, sz_missing = stat_exit_marker(missing_p)
        self.assertEqual(st_missing, "missing")
        self.assertEqual(sz_missing, -1)

        empty_p = self.tmpdir / "empty.exit"
        empty_p.write_bytes(b"")
        st_empty, sz_empty = stat_exit_marker(empty_p)
        self.assertEqual(st_empty, "empty")
        self.assertEqual(sz_empty, 0)

        present_p = self.tmpdir / "present.exit"
        present_p.write_text("complete=1\n", encoding="utf-8")
        st_pres, sz_pres = stat_exit_marker(present_p)
        self.assertEqual(st_pres, "present")
        self.assertGreater(sz_pres, 0)

        with patch.object(Path, "stat", side_effect=OSError("permission denied")):
            st_err, sz_err = stat_exit_marker(present_p)
            self.assertEqual(st_err, "exit_stat_failure")
            self.assertEqual(sz_err, -1)

    def test_invalid_utf8_unwhitelisted_canary_redacted(self) -> None:
        """Synthetic unapproved canary plus invalid UTF-8 does not appear in display or fields."""
        canary = "UNWHITELISTED_DIAGNOSTIC_CANARY"
        bad_file = self.tmpdir / "invalid_canary.start"
        bad_file.write_bytes(f"unwhitelisted_field={canary}\n".encode() + b"\xff")

        status, display, fields = read_bounded_marker(bad_file)
        self.assertEqual(status, "invalid_utf8")
        self.assertNotIn(canary, display)
        self.assertNotIn(canary, str(fields))
        self.assertIn("[invalid_utf8]", display)

    def test_acceptance_str_failure_preserves_workload_exception(self) -> None:
        """Raising __str__ in acceptance exception preserves original workload exception."""
        original_exc = CustomWorkloadError("original_workload_failure")
        def failing_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            raise original_exc
        adapter = make_portable_worker_spec_adapter(failing_runner, self.cap, self.session)
        with patch.object(self.cap, "validate_for_accept", side_effect=BrokenStringError()):
            with self.assertRaises(CustomWorkloadError) as cm:
                adapter(self.spec, self.identity, {"hello_deadline_seconds": 0.5})
        self.assertIs(cm.exception, original_exc)

    def test_measurement_recording_str_failure_preserves_workload_exception(self) -> None:
        """Raising __str__ in record_measurement_error preserves original workload exception."""
        original_exc = CustomWorkloadError("workload_failed_recording_broken")
        def failing_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            raise original_exc
        adapter = make_portable_worker_spec_adapter(failing_runner, self.cap, self.session)
        with patch.object(self.session, "record_measurement_error", side_effect=BrokenStringError()):
            with self.assertRaises(CustomWorkloadError) as cm:
                adapter(self.spec, self.identity, {"hello_deadline_seconds": 0.5})
        self.assertIs(cm.exception, original_exc)

    def test_diagnostic_hook_str_failure_preserves_workload_exception(self) -> None:
        """Raising __str__ in diagnostic capture hook preserves original workload exception."""
        original_exc = CustomWorkloadError("workload_failed_hook_broken")
        def failing_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            raise original_exc
        adapter = make_portable_worker_spec_adapter(failing_runner, self.cap, self.session)
        with patch(
            "runner_portable_diagnostics.capture_portable_acceptance_diagnostic",
            side_effect=BrokenStringError(),
        ):
            with self.assertRaises(CustomWorkloadError) as cm:
                adapter(self.spec, self.identity, {"hello_deadline_seconds": 0.5})
        self.assertIs(cm.exception, original_exc)

    def test_failing_add_note_preserves_workload_exception(self) -> None:
        """Failing add_note on workload exception does not replace workload exception."""
        original_exc = FailingAddNoteError("workload_error_with_bad_add_note")
        def failing_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            raise original_exc
        adapter = make_portable_worker_spec_adapter(failing_runner, self.cap, self.session)
        with self.assertRaises(FailingAddNoteError) as cm:
            adapter(self.spec, self.identity, {"hello_deadline_seconds": 0.5})
        self.assertIs(cm.exception, original_exc)

    def test_original_workload_cancellation_identity_preserved(self) -> None:
        """KeyboardInterrupt in workload preserves exception identity and type."""
        original_exc = KeyboardInterrupt("user_cancelled")
        def cancelling_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            raise original_exc
        adapter = make_portable_worker_spec_adapter(cancelling_runner, self.cap, self.session)
        with self.assertRaises(KeyboardInterrupt) as cm:
            adapter(self.spec, self.identity, {"hello_deadline_seconds": 0.5})
        self.assertIs(cm.exception, original_exc)

    def test_new_interrupt_during_acceptance_reraised(self) -> None:
        """KeyboardInterrupt occurring during acceptance handling is re-raised immediately."""
        def mock_launch(argv: Any, **kwargs: Any) -> Any:
            inner = MagicMock()
            inner.pid = 77775
            inner.poll.return_value = 0
            return inner

        def dummy_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            proc = kwargs["_launch_process"](spec.argv, environment=spec.environment)
            return SimpleNamespace(
                returncode=0, terminal={"status": "succeeded"}, waited=True,
                process_group_cleaned=True, process=proc,
            )

        adapter = make_portable_worker_spec_adapter(dummy_runner, self.cap, self.session)
        with patch.object(self.cap, "validate_for_accept", side_effect=KeyboardInterrupt("interrupt_on_accept")):
            with self.assertRaises(KeyboardInterrupt) as cm:
                adapter(self.spec, self.identity, {"hello_deadline_seconds": 0.5}, _launch_process=mock_launch)
        self.assertIn("interrupt_on_accept", str(cm.exception))

    def test_successful_workload_with_diagnostic_recording_failure(self) -> None:
        """Successful workload preserves success when diagnostic recording hook fails."""
        def mock_launch(argv: Any, **kwargs: Any) -> Any:
            inner = MagicMock()
            inner.pid = 77773
            inner.poll.return_value = 0
            return inner

        def dummy_runner(spec: Any, ident: Any, lims: Any, **kwargs: Any) -> Any:
            proc = kwargs["_launch_process"](spec.argv, environment=spec.environment)
            return SimpleNamespace(
                returncode=0, terminal={"status": "succeeded"}, waited=True,
                process_group_cleaned=True, process=proc,
            )

        adapter = make_portable_worker_spec_adapter(dummy_runner, self.cap, self.session)
        with patch(
            "runner_portable_diagnostics.capture_portable_acceptance_diagnostic",
            side_effect=RuntimeError("diagnostic_hook_failed"),
        ):
            res = adapter(
                self.spec, self.identity, {"hello_deadline_seconds": 0.5}, _launch_process=mock_launch
            )
        self.assertEqual(res.terminal["status"], "succeeded")
        self.assertEqual(res.returncode, 0)


if __name__ == "__main__":
    unittest.main()
