"""Maintained complete export-owner context; parsed but never executed."""
from ci.python_retention_owner_arcs_outcomes import SOURCE as OUTCOMES

SOURCE = r'''"""Unit tests for child coverage runner export, reconciliation, and threshold regressions."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import build_go_helper
import coverage
import runner_coverage
import run_tests
from test_report import CoverageSummary

REPO_ROOT = Path(__file__).resolve().parents[5]
TOOLS_DIR = REPO_ROOT / "tools"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


class CoverageRegressionTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="repomap-work-d-regr-")).resolve()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class WorkDRegressionUnitTests(CoverageRegressionTestCase):
    def test_regr1_nested_coverage_preserves_branch_arcs(self):
        source_dir = self.tmpdir / "src_regr1"; source_dir.mkdir()
        mod_file = source_dir / "decision_mod.py"
        mod_file.write_text("def branch_fn(val):\n    if val > 0:\n        return 1\n    return 0\n", encoding="utf-8")
        parent_cov = coverage.Coverage(branch=True, source=[str(source_dir)], data_file=str(self.tmpdir / ".coverage.parent"))
        self.addCleanup(lambda: parent_cov.get_data().close(force=True))
        parent_cov.start()
        try:
            with runner_coverage.ChildCoverageSession(
                coverage_module=coverage, scratch_dir=self.tmpdir / "child_session", source_root=source_dir,
            ) as session:
                self.addCleanup(session.cleanup)
                child_runner = session.create_coverage(coverage); child_runner.start()
                try:
                    import importlib
                    with patch.dict(sys.modules), patch.object(sys, "path", [str(source_dir)] + sys.path):
                        sys.modules.pop("decision_mod", None)
                        mod = importlib.import_module("decision_mod")
                        self.assertEqual(mod.branch_fn(42), 1)
                finally:
                    child_runner.stop(); child_runner.save(); session.combine(child_runner)

                child_data = session._coverage_runner.get_data()
                mod_path = str(mod_file.resolve())
                self.assertIn(mod_path, child_data.measured_files())
                arcs = child_data.arcs(mod_path)
                self.assertIsNotNone(arcs)
                self.assertIn((2, 3), arcs); self.assertNotIn((2, 4), arcs)
                summary = runner_coverage.collect_coverage_summary(session._coverage_runner, "unit", runner_coverage.coverage_policy_for_suite("unit"), source_root=source_dir)
                self.assertEqual((summary.covered_branches, summary.total_branches, summary.passed), (1, 2, False))
            session.cleanup()
            self.assertIs(coverage.Coverage.current(), parent_cov)
        finally:
            parent_cov.stop(); parent_cov.save()

    def test_regr2_suite_selection_unit_in_process_vs_int_staging_child_session(self):
        dummy_pytest = SimpleNamespace()
        observed_unit_env = {}

        def fake_pytest_unit(pm, pa, pl):
            observed_unit_env["cov_start"] = os.environ.get("COVERAGE_PROCESS_START")
            observed_unit_env["pythonpath"] = os.environ.get("PYTHONPATH", "")
            return 0

        unit_plugin = SimpleNamespace(_suite="unit", test_records=[])
        with patch.object(run_tests, "run_pytest", side_effect=fake_pytest_unit):
            code, runner = run_tests.run_pytest_with_coverage(coverage, dummy_pytest, [], unit_plugin)
            self.assertEqual(code, 0); self.assertIsNone(observed_unit_env["cov_start"])
            assert isinstance(observed_unit_env["pythonpath"], str)
            self.assertNotIn("sitecustomize", observed_unit_env["pythonpath"])
            self.assertFalse(hasattr(runner, "_repomap_session"))

        observed_int_env = {}

        def fake_pytest_int(pm, pa, pl):
            observed_int_env["cov_start"] = os.environ.get("COVERAGE_PROCESS_START")
            observed_int_env["pythonpath"] = os.environ.get("PYTHONPATH", "")
            return 0

        int_plugin = SimpleNamespace(_suite="int", test_records=[])
        with patch.object(run_tests, "run_pytest", side_effect=fake_pytest_int):
            code, runner = run_tests.run_pytest_with_coverage(coverage, dummy_pytest, [], int_plugin)
            self.assertEqual(code, 0); self.assertIsNotNone(observed_int_env["cov_start"])
            session = getattr(runner, "_repomap_session", None)
            self.assertIsNotNone(session)
            assert isinstance(session, runner_coverage.ChildCoverageSession)
            assert isinstance(observed_int_env["pythonpath"], str)
            self.assertIn(str(session.session_dir), observed_int_env["pythonpath"])
            session.cleanup()

        staging_plugin = SimpleNamespace(_suite="staging", test_records=[])
        with patch.object(run_tests, "run_pytest", side_effect=fake_pytest_int):
            code, runner = run_tests.run_pytest_with_coverage(coverage, dummy_pytest, [], staging_plugin)
            self.assertEqual(code, 0)
            session = getattr(runner, "_repomap_session", None)
            self.assertIsNotNone(session)
            assert isinstance(session, runner_coverage.ChildCoverageSession)
            session.cleanup()

    def test_regr3_shard_classification_five_conditions_and_diagnostic_snapshots(self):
        # Condition 1: Valid empty shard
        session = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "shard_valid_empty", source_root=self.tmpdir)
        session._write_config()
        valid_shard = session.data_dir / ".coverage.child.10001.valid.empty"
        empty_cov = coverage.Coverage(data_file=str(valid_shard))
        empty_cov.start(); empty_cov.stop(); empty_cov.save()
        (session.child_manifest_dir / "10001.start").write_text("pid=10001\n", encoding="utf-8")
        (session.child_manifest_dir / "10001.exit").write_text(f"pid=10001\nshard={valid_shard}\n", encoding="utf-8")
        session.combine(session.create_coverage(coverage))
        self.assertFalse(valid_shard.exists())

        # Condition 2: Zero-byte shard
        session = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "shard_zero_byte", source_root=self.tmpdir)
        session._write_config(); zero_shard = session.data_dir / ".coverage.child.10002.zero.byte"; zero_shard.touch()
        (session.child_manifest_dir / "10002.start").write_text("pid=10002\n", encoding="utf-8")
        (session.child_manifest_dir / "10002.exit").write_text(f"pid=10002\nshard={zero_shard}\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "empty or unreadable: zero-byte file"):
            session.combine(session.create_coverage(coverage))
        self.assertEqual(len(session.diagnostic_snapshots), 1)
        snap = session.diagnostic_snapshots[0]
        self.assertEqual(snap.file_type, "zero_byte"); self.assertEqual(snap.size_bytes, 0)
        self.assertEqual(snap.reader_status, "rejected_zero_byte"); self.assertEqual(snap.stage, "pre_combine")

        # Condition 3: Corrupt non-empty shard
        session = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "shard_corrupt_nonempty", source_root=self.tmpdir)
        session._write_config(); bad_bytes = b"NOT_A_SQLITE_DATABASE_HEADER_DATA"
        corrupt_shard = session.data_dir / ".coverage.child.10003.corrupt.data"; corrupt_shard.write_bytes(bad_bytes)
        (session.child_manifest_dir / "10003.start").write_text("pid=10003\n", encoding="utf-8")
        (session.child_manifest_dir / "10003.exit").write_text(f"pid=10003\nshard={corrupt_shard}\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "empty or unreadable: invalid SQLite header"):
            session.combine(session.create_coverage(coverage))
        self.assertEqual(len(session.diagnostic_snapshots), 1)
        snap = session.diagnostic_snapshots[0]
        self.assertEqual(snap.file_type, "corrupt_nonempty"); self.assertEqual(snap.size_bytes, len(bad_bytes))
        self.assertEqual(snap.sha256, hashlib.sha256(bad_bytes).hexdigest())
        self.assertEqual(snap.reader_status, "invalid_sqlite_header"); self.assertEqual(snap.stage, "pre_combine")

        # Condition 4: Unreadable shard
        session = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "shard_unreadable", source_root=self.tmpdir)
        session._write_config()
        unreadable_shard = session.data_dir / ".coverage.child.10004.unreadable"
        unreadable_shard.write_bytes(b"SQLite format 3\x00" + b"\x00" * 80)
        (session.child_manifest_dir / "10004.start").write_text("pid=10004\n", encoding="utf-8")
        (session.child_manifest_dir / "10004.exit").write_text(f"pid=10004\nshard={unreadable_shard}\n", encoding="utf-8")
        runner = session.create_coverage(coverage)
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            with self.assertRaisesRegex(RuntimeError, "empty or unreadable: Permission denied"):
                session.combine(runner)
        self.assertEqual(len(session.diagnostic_snapshots), 1)
        snap = session.diagnostic_snapshots[0]
        self.assertEqual(snap.file_type, "unreadable"); self.assertIn("Permission denied", snap.reader_status)
        self.assertEqual(snap.stage, "pre_combine")

        # Condition 5: In-progress / unconsumed after combine
        session = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "shard_unconsumed", source_root=self.tmpdir)
        session._write_config()
        unconsumed_shard = session.data_dir / ".coverage.child.10005.unconsumed"
        cov2 = coverage.Coverage(data_file=str(unconsumed_shard)); cov2.start(); cov2.stop(); cov2.save()
        (session.child_manifest_dir / "10005.start").write_text("pid=10005\n", encoding="utf-8")
        (session.child_manifest_dir / "10005.exit").write_text(f"pid=10005\nshard={unconsumed_shard}\n", encoding="utf-8")

        class FakeAccumulator(coverage.Coverage):
            def combine(self, *args, **kwargs):
                pass

        with patch.object(coverage, "Coverage", side_effect=lambda *a, **k: FakeAccumulator(*a, **k)):
            with self.assertRaisesRegex(RuntimeError, "unconsumed during combine"):
                session.combine(session.create_coverage(coverage))
        self.assertEqual(len(session.diagnostic_snapshots), 1)
        snap = session.diagnostic_snapshots[0]
        self.assertEqual(snap.file_type, "unconsumed"); self.assertEqual(snap.reader_status, "unconsumed_after_combine")
        self.assertEqual(snap.stage, "post_combine")

    def test_regr4_outcome_matrix_preserves_test_evidence(self):
        matrix = [
            (0, None, True, False, 0),
            (1, None, True, False, 1),
            (0, RuntimeError("suite assertion failed"), True, True, None),
            (0, None, False, False, 0),
            (2, None, False, False, 2),
        ]
        dummy_pytest = SimpleNamespace()
        for primary_code, primary_exc, shard_err, expect_exc, expect_code in matrix:
            with self.subTest(primary_code=primary_code, primary_exc=primary_exc, shard_err=shard_err):
                test_rec = SimpleNamespace(name="test_foo", outcome="passed")
                plugin = SimpleNamespace(_suite="int", test_records=[test_rec])
                session = runner_coverage.ChildCoverageSession(
                    coverage_module=coverage,
                    scratch_dir=self.tmpdir / f"outcome_{primary_code}_{bool(primary_exc)}_{shard_err}",
                    source_root=self.tmpdir,
                )

                def fake_run(pm, pa, pl):
                    if shard_err:
                        corrupt = session.data_dir / ".coverage.child.9998.corrupt"
                        corrupt.touch()
                        (session.child_manifest_dir / "9998.start").write_text("pid=9998\n", encoding="utf-8")
                        (session.child_manifest_dir / "9998.exit").write_text(f"pid=9998\nshard={corrupt}\n", encoding="utf-8")
                    if primary_exc:
                        raise primary_exc
                    return primary_code

                try:
                    with patch.object(run_tests, "run_pytest", side_effect=fake_run):
                        if expect_exc:
                            with self.assertRaisesRegex(RuntimeError, "suite assertion failed"):
                                run_tests.run_pytest_with_coverage(coverage, dummy_pytest, [], plugin, session=session)
                        else:
                            code, runner = run_tests.run_pytest_with_coverage(coverage, dummy_pytest, [], plugin, session=session)
                            self.assertEqual(code, expect_code)
                            if shard_err:
                                self.assertTrue(hasattr(runner, "_instrumentation_error"))
                    self.assertEqual(plugin.test_records, [test_rec])
                finally:
                    session.cleanup()

''' + OUTCOMES
