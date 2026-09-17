"""Unit tests for runner_coverage_capability structured capability and boundaries."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import coverage
from runner_coverage import ChildCoverageSession
from runner_coverage_capability import (
    CapabilityContainmentError,
    CapabilityRefusalError,
    CapabilityValidationError,
    ChildCoverageCapability,
    compute_source_commitment,
)


class ChildCoverageCapabilityUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="repomap-cap-test-")).resolve()
        self.source_root = self.tmpdir / "src"
        self.source_root.mkdir(parents=True)
        (self.source_root / "sample.py").write_text("def fn():\n    return 42\n", encoding="utf-8")
        self.session_dir = self.tmpdir / "session"
        self.session = ChildCoverageSession(
            scratch_dir=self.session_dir,
            source_root=self.source_root,
            suite="int",
        )
        self.session._write_config()
        self.session._write_sitecustomize()
        self.config_file = self.session.config_file
        self.bootstrap_dir = self.session.bootstrap_dir
        self.manifest_dir = self.session.child_manifest_dir
        self.data_dir = self.session.data_dir

    def tearDown(self) -> None:
        self.session.cleanup()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_capability(self, suite: str = "int") -> ChildCoverageCapability:
        self.session.suite = suite
        return self.session.issue_portable_capability(suite=suite)

    def test_capability_issuance_valid_int_and_staging(self) -> None:
        cap_int = self._make_capability(suite="int")
        self.assertTrue(cap_int.active)
        self.assertEqual(cap_int.suite, "int")

        cap_staging = self._make_capability(suite="staging")
        self.assertTrue(cap_staging.active)
        self.assertEqual(cap_staging.suite, "staging")

    def test_capability_refusal_for_disallowed_suites(self) -> None:
        for disallowed in ("unit", "smoke", "system", "inert", "unknown"):
            with self.subTest(suite=disallowed):
                with self.assertRaises(CapabilityRefusalError):
                    self._make_capability(suite=disallowed)

    def test_source_commitment_deterministic_and_tamper_detected(self) -> None:
        c1 = compute_source_commitment(self.source_root)
        c2 = compute_source_commitment(self.source_root)
        self.assertEqual(c1, c2)

        cap = self._make_capability(suite="int")
        self.assertEqual(cap.source_commitment, c1)

        # Mutate source file
        (self.source_root / "sample.py").write_text("def fn():\n    return 99\n", encoding="utf-8")
        with self.assertRaisesRegex(CapabilityValidationError, "stale source revision"):
            cap.validate_for_launch()

    def test_capability_bootstrap_tampering_fails_closed(self) -> None:
        cap = self._make_capability(suite="int")
        sc = self.bootstrap_dir / "sitecustomize.py"
        sc.write_text("# tampered bootstrap\n", encoding="utf-8")
        with self.assertRaisesRegex(CapabilityValidationError, "bootstrap sitecustomize content or sha256 mismatch"):
            cap.validate_for_launch()

    def test_capability_config_tampering_fails_closed(self) -> None:
        cap = self._make_capability(suite="int")
        self.config_file.write_text("[run]\nbranch=False\n# tampered\n", encoding="utf-8")
        with self.assertRaises(CapabilityValidationError):
            cap.validate_for_launch()

    def test_prelaunch_registration_and_accept_validation(self) -> None:
        cap = self._make_capability(suite="int")
        token = cap.register_prelaunch_child()
        self.assertIn(token, cap.registered_tokens)
        self.assertTrue((self.manifest_dir / f"{token}.expected").is_file())

        with self.assertRaises(CapabilityValidationError):
            cap.register_prelaunch_child(token=token)

        with self.assertRaisesRegex(CapabilityValidationError, "start marker missing"):
            cap.validate_for_accept(token)

        start_marker = self.manifest_dir / f"{token}.start"
        start_marker.write_text(
            f"token={token}\ninvocation={cap.invocation_id}\nsuite=int\nrevision={cap.source_commitment}\npid=12345\ncov_start=1\ncomplete=1\nmeasurement=selected_hits\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CapabilityValidationError, "terminal exit marker missing"):
            cap.validate_for_accept(token)

        exit_marker = self.manifest_dir / f"{token}.exit"
        exit_marker.write_text(
            f"token={token}\ninvocation={cap.invocation_id}\nsuite=int\nrevision={cap.source_commitment}\npid=12345\ncov_start=1\ncomplete=1\nmeasurement=selected_hits\nshard=\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CapabilityValidationError, "no coverage shard recorded"):
            cap.validate_for_accept(token)

        zero_shard = self.data_dir / f".coverage.zero.{token}"
        zero_shard.touch()
        exit_marker.write_text(
            f"token={token}\ninvocation={cap.invocation_id}\nsuite=int\nrevision={cap.source_commitment}\npid=12345\ncov_start=1\ncomplete=1\nmeasurement=selected_hits\nshard={zero_shard}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CapabilityValidationError, "missing or 0 bytes"):
            cap.validate_for_accept(token)

        corrupt_shard = self.data_dir / f".coverage.corrupt.{token}"
        corrupt_shard.write_bytes(b"INVALID_SQLITE_HEADER")
        exit_marker.write_text(
            f"token={token}\ninvocation={cap.invocation_id}\nsuite=int\nrevision={cap.source_commitment}\npid=12345\ncov_start=1\ncomplete=1\nmeasurement=selected_hits\nshard={corrupt_shard}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CapabilityValidationError, "invalid SQLite header"):
            cap.validate_for_accept(token)

        valid_shard = self.data_dir / f".coverage.valid.{token}"
        cov = coverage.Coverage(data_file=str(valid_shard), source=[str(self.source_root)])
        cov.start()
        try:
            sample = self.source_root / "sample.py"
            exec(compile(sample.read_text(), str(sample), "exec"), {})
        finally:
            cov.stop()
        cov.save()

        exit_marker.write_text(
            f"token={token}\ninvocation={cap.invocation_id}\nsuite=int\nrevision={cap.source_commitment}\npid=12345\ncov_start=1\ncomplete=1\nmeasurement=selected_hits\nshard={valid_shard}\n",
            encoding="utf-8",
        )
        # Direct registration must receive the same receipt/content validation
        # as adapter-launched children; absence of launch metadata is no waiver.
        self.assertNotIn(token, cap.launched_commands)
        valid_start = start_marker.read_text(encoding="utf-8")
        valid_exit = exit_marker.read_text(encoding="utf-8")
        for marker, valid, field in (
            (start_marker, valid_start, "cov_start=1\n"),
            (exit_marker, valid_exit, "complete=1\n"),
            (exit_marker, valid_exit, "measurement=selected_hits\n"),
        ):
            with self.subTest(field=field):
                marker.write_text(valid.replace(field, ""), encoding="utf-8")
                with self.assertRaises(CapabilityValidationError):
                    cap.validate_for_accept(token)
                marker.write_text(valid, encoding="utf-8")
        exit_marker.write_text(
            valid_exit.replace("measurement=selected_hits", "measurement=no_selected_hits"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CapabilityValidationError, "measurement content mismatch"):
            cap.validate_for_accept(token)
        exit_marker.write_text(valid_exit, encoding="utf-8")
        accepted_path = cap.validate_for_accept(token)
        self.assertEqual(accepted_path, valid_shard)

        # Track actual reader connections on both acceptance and content refusal.
        # Keeping references makes settlement independent of garbage collection.
        connections: list[sqlite3.Connection] = []
        connect = sqlite3.connect

        def tracked_connect(*args, **kwargs):
            connection = connect(*args, **kwargs)
            connections.append(connection)
            return connection

        with patch("sqlite3.connect", side_effect=tracked_connect):
            self.assertEqual(cap.validate_for_accept(token), valid_shard)
            success_count = len(connections)
            self.assertGreater(success_count, 0)
            exit_marker.write_text(
                valid_exit.replace("measurement=selected_hits", "measurement=no_selected_hits"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CapabilityValidationError, "measurement content mismatch"):
                cap.validate_for_accept(token)
            self.assertGreater(len(connections), success_count)
        for connection in connections:
            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
                connection.execute("SELECT 1")

    def test_duplicate_marker_key_rejected(self) -> None:
        cap = self._make_capability(suite="int")
        token = cap.register_prelaunch_child()
        start_marker = self.manifest_dir / f"{token}.start"
        start_marker.write_text(
            f"token={token}\ntoken=duplicate\ninvocation={cap.invocation_id}\nsuite=int\npid=12345\ncov_start=1\ncomplete=1\nmeasurement=selected_hits\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CapabilityValidationError, "duplicate marker key 'token'"):
            cap.validate_for_accept(token)

    def test_marker_symlink_rejected(self) -> None:
        cap = self._make_capability(suite="int")
        token = cap.register_prelaunch_child()
        sym_marker = self.manifest_dir / f"{token}.sym"
        sym_marker.symlink_to(self.manifest_dir / f"{token}.expected")
        with self.assertRaises(CapabilityContainmentError):
            cap.validate_for_accept(token)

    def test_deactivated_capability_refuses_launch(self) -> None:
        cap = self._make_capability(suite="int")
        cap.deactivate()
        self.assertFalse(cap.active)
        with self.assertRaises(CapabilityRefusalError):
            cap.validate_for_launch()

    def test_acceptance_rechecks_config_and_bootstrap(self) -> None:
        for target in (self.config_file, self.bootstrap_dir / "sitecustomize.py"):
            with self.subTest(target=target.name):
                cap = self._make_capability()
                token = cap.register_prelaunch_child()
                target.write_text("changed after launch\n", encoding="utf-8")
                with self.assertRaisesRegex(CapabilityValidationError, "content or sha256 mismatch"):
                    cap.validate_for_accept(token)

    def test_wrong_invocation_root_and_token_fail_closed(self) -> None:
        cap = self._make_capability()
        original = cap.invocation_id
        cap.invocation_id = "prior-run"
        with self.assertRaises(CapabilityValidationError):
            cap.validate_for_launch()
        cap.invocation_id = original
        cap.data_dir = self.tmpdir
        with self.assertRaises(CapabilityContainmentError):
            cap.validate_for_launch()
        cap.data_dir = self.session.data_dir
        with self.assertRaises(CapabilityValidationError):
            cap.register_prelaunch_child("../foreign")

    def test_reused_parent_root_creates_separate_invocations(self) -> None:
        second = ChildCoverageSession(scratch_dir=self.session_dir,
                                      source_root=self.source_root, suite="int")
        try:
            self.assertNotEqual(second.session_dir, self.session.session_dir)
            self.assertNotEqual(second.data_dir, self.session.data_dir)
            self.assertEqual(list(second.data_dir.iterdir()), [])
        finally:
            second.cleanup()

    def test_cleanup_revokes_capability(self) -> None:
        cap = self._make_capability()
        self.session.cleanup()
        with self.assertRaises(CapabilityRefusalError):
            cap.validate_for_launch()
        self.session.cleanup()
        with self.assertRaises(CapabilityRefusalError):
            cap.validate_for_launch()

    def test_fixture_cleanup_stops_collector_and_preserves_primary_error_on_injected_failure(self) -> None:
        incoming_collector = coverage.Coverage.current()
        failure = RuntimeError("injected fixture failure")
        read_text = Path.read_text

        def fail_sample_read(path: Path, *args, **kwargs) -> str:
            if path == self.source_root / "sample.py":
                raise failure
            return read_text(path, *args, **kwargs)

        with patch.object(Path, "read_text", autospec=True, side_effect=fail_sample_read):
            with self.assertRaisesRegex(RuntimeError, "injected fixture failure") as caught:
                self.test_prelaunch_registration_and_accept_validation()
        self.assertIs(caught.exception, failure)
        self.assertEqual(list(self.data_dir.glob(".coverage.valid.*")), [])
        self.assertIs(coverage.Coverage.current(), incoming_collector)


    def test_cleanup_without_ambient_collector_in_child(self) -> None:
        env = os.environ.copy()
        env.pop("COVERAGE_PROCESS_START", None)
        env.pop("COVERAGE_CHILD_MANIFEST_DIR", None)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[5] / "tools")
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve())], env=env,
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Ran 1 test", result.stderr)

    @staticmethod
    def _before_sentinel() -> int:
        return 17

    @staticmethod
    def _after_sentinel() -> int:
        return 23

    def test_cleanup_restores_outer_collector_and_measures_sentinels(self) -> None:
        parent = coverage.Coverage.current()
        outer = coverage.Coverage(data_file=None, config_file=False)
        outer.start()
        try:
            self.assertEqual(self._before_sentinel(), 17)
            self.test_fixture_cleanup_stops_collector_and_preserves_primary_error_on_injected_failure()
            self.assertIs(coverage.Coverage.current(), outer)
            self.assertEqual(self._after_sentinel(), 23)
        finally:
            outer.stop()
            self.assertIs(coverage.Coverage.current(), parent)
        measured = outer.get_data().lines(str(Path(__file__).resolve())) or []
        self.assertIn(self._before_sentinel.__code__.co_firstlineno + 2, measured)
        self.assertIn(self._after_sentinel.__code__.co_firstlineno + 2, measured)

    def test_restoration_assertion_detects_collector_lifetime_faults(self) -> None:
        parent = coverage.Coverage.current()
        real_start = coverage.Coverage.start
        real_stop = coverage.Coverage.stop
        for fault in ("unstopped_inner", "stopped_outer", "replaced_outer"):
            with self.subTest(fault=fault):
                outer = coverage.Coverage(data_file=None, config_file=False)
                owned = [outer]
                outer.start()

                def track_start(collector: coverage.Coverage) -> None:
                    real_start(collector)
                    owned.append(collector)

                def faulty_stop(collector: coverage.Coverage) -> None:
                    if fault == "unstopped_inner":
                        return
                    real_stop(collector)
                    if fault == "stopped_outer":
                        real_stop(outer)
                    else:
                        replacement = coverage.Coverage(data_file=None, config_file=False)
                        track_start(replacement)

                try:
                    with patch.object(coverage.Coverage, "start", track_start), patch.object(
                        coverage.Coverage, "stop", faulty_stop,
                    ):
                        with self.assertRaisesRegex(AssertionError, "is not"):
                            self.test_fixture_cleanup_stops_collector_and_preserves_primary_error_on_injected_failure()
                finally:
                    # Only test-owned collectors, in stack order, even on assertion failure.
                    for collector in reversed(owned):
                        if coverage.Coverage.current() is collector:
                            real_stop(collector)
                    self.assertIs(coverage.Coverage.current(), parent)


if __name__ == "__main__":
    if coverage.Coverage.current() is not None:
        raise AssertionError("child unexpectedly inherited a collector")
    unittest.main(defaultTest=(
        "ChildCoverageCapabilityUnitTests."
        "test_fixture_cleanup_stops_collector_and_preserves_primary_error_on_injected_failure"
    ))
# REPOMAP-PUBLIC-V002-FIX10-R1 dynamic boundary re-attestation
