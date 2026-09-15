"""Unit tests for child coverage runner export, reconciliation, and threshold regressions."""

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

    def test_regr5_raw_count_threshold_boundaries_and_cross_suite_contamination(self):
        def make_summary(suite: str, cov_lines: int, tot_lines: int, cov_branches: int, tot_branches: int) -> CoverageSummary:
            pol = runner_coverage.coverage_policy_for_suite(suite)
            return CoverageSummary(
                suite_name=suite,
                line_hard_threshold=pol.line_hard_threshold, branch_hard_threshold=pol.branch_hard_threshold,
                line_warn_threshold=pol.line_warn_threshold, branch_warn_threshold=pol.branch_warn_threshold,
                total_lines=tot_lines, covered_lines=cov_lines,
                line_percent=runner_coverage.percentage(cov_lines, tot_lines),
                total_branches=tot_branches, covered_branches=cov_branches,
                branch_percent=runner_coverage.percentage(cov_branches, tot_branches),
                files=(),
            )

        u_sub_l = make_summary("unit", 8499, 10000, 8500, 10000)
        self.assertEqual(round(u_sub_l.line_percent, 1), 85.0); self.assertLess(u_sub_l.line_percent, 85.0); self.assertFalse(u_sub_l.passed)
        u_sub_b = make_summary("unit", 8500, 10000, 8499, 10000)
        self.assertEqual(round(u_sub_b.branch_percent, 1), 85.0); self.assertLess(u_sub_b.branch_percent, 85.0); self.assertFalse(u_sub_b.passed)
        u_exact = make_summary("unit", 8500, 10000, 8500, 10000)
        self.assertEqual(u_exact.line_percent, 85.0); self.assertEqual(u_exact.branch_percent, 85.0); self.assertTrue(u_exact.passed)

        i_sub_l = make_summary("int", 7999, 10000, 8000, 10000)
        self.assertEqual(round(i_sub_l.line_percent, 1), 80.0); self.assertLess(i_sub_l.line_percent, 80.0); self.assertFalse(i_sub_l.passed)
        i_sub_b = make_summary("int", 8000, 10000, 7999, 10000)
        self.assertEqual(round(i_sub_b.branch_percent, 1), 80.0); self.assertLess(i_sub_b.branch_percent, 80.0); self.assertFalse(i_sub_b.passed)
        i_exact = make_summary("int", 8000, 10000, 8000, 10000)
        self.assertEqual(i_exact.line_percent, 80.0); self.assertEqual(i_exact.branch_percent, 80.0); self.assertTrue(i_exact.passed)

        self.assertFalse(make_summary("int", 7500, 10000, 8000, 10000).passed)
        int_pol = runner_coverage.coverage_policy_for_suite("int")
        unit_pol = runner_coverage.coverage_policy_for_suite("unit")
        self.assertEqual(int_pol.line_hard_threshold, 80.0); self.assertEqual(unit_pol.line_hard_threshold, 85.0)
        self.assertFalse(make_summary("unit", 8400, 10000, 8500, 10000).passed)

        with self.assertRaises(ValueError):
            runner_coverage.coverage_policy_for_suite("smoke")
        with self.assertRaises(ValueError):
            runner_coverage.coverage_policy_for_suite("system")

        self.assertNotIn("smoke", {"unit", "int", "staging"})
        self.assertNotIn("system", {"unit", "int", "staging"})

        go_source = Path(build_go_helper.__file__).read_text(encoding="utf-8")
        self.assertIn("total_percent < 85.0", go_source)
        self.assertIn("Go statement coverage", go_source)

        with tempfile.TemporaryDirectory(prefix="regr5-go-") as tmp:
            session = runner_coverage.ChildCoverageSession(scratch_dir=Path(tmp) / "regr5_go_check")
            try:
                go_files = [s for s in session.source_paths if str(s).endswith(".go")]
                self.assertEqual(go_files, [])
                u_sum = make_summary("unit", 8500, 10000, 8500, 10000)
                self.assertEqual(u_sum.total_branches, 10000); self.assertEqual(u_sum.covered_branches, 8500)
            finally:
                session.cleanup()

    def test_regr6_per_child_reconciliation_eight_required_conditions(self):
        # 1. Parent + valid child: parent and child shards combine cleanly
        s1 = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "c1", source_root=self.tmpdir)
        s1._write_config(); parent_cov1 = s1.create_coverage(coverage); parent_cov1.start(); parent_cov1.stop(); parent_cov1.save()
        c1 = s1.data_dir / ".coverage.child.2001.def"; cov = coverage.Coverage(data_file=str(c1)); cov.start(); cov.stop(); cov.save()
        (s1.child_manifest_dir / "2001.start").write_text("pid=2001\n", encoding="utf-8")
        (s1.child_manifest_dir / "2001.exit").write_text(f"pid=2001\nshard={c1}\n", encoding="utf-8")
        s1.combine(parent_cov1)
        self.assertTrue(s1.data_file.exists()); self.assertFalse(c1.exists())

        # 2. Parent + missing child: parent shard present, child missing shard -> raises even with valid parent shard
        s2 = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "c2", source_root=self.tmpdir)
        s2._write_config(); parent_cov2 = s2.create_coverage(coverage); parent_cov2.start(); parent_cov2.stop(); parent_cov2.save()
        (s2.child_manifest_dir / "99992.start").write_text("pid=99992\n", encoding="utf-8")
        (s2.child_manifest_dir / "99992.exit").write_text(f"pid=99992\nshard={s2.data_dir / '.coverage.child.99992.none'}\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "coverage shard for child PID 99992 is missing"):
            s2.combine(parent_cov2)
        self.assertEqual(s2.diagnostic_snapshots[0].termination_outcome, "clean_exit_no_shard")

        # 3. One valid child + another missing child: sibling shard does not mask missing child
        dead_pid = 99990
        while True:
            try:
                os.kill(dead_pid, 0); dead_pid -= 1
            except OSError:
                break
        s3 = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "c3", source_root=self.tmpdir)
        s3._write_config(); c3 = s3.data_dir / ".coverage.child.2003.abc"; cov = coverage.Coverage(data_file=str(c3)); cov.start(); cov.stop(); cov.save()
        (s3.child_manifest_dir / "2003.start").write_text("pid=2003\n", encoding="utf-8"); (s3.child_manifest_dir / "2003.exit").write_text(f"pid=2003\nshard={c3}\n", encoding="utf-8")
        (s3.child_manifest_dir / f"{dead_pid}.start").write_text(f"pid={dead_pid}\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, f"coverage shard for child PID {dead_pid} is missing"):
            s3.combine(s3.create_coverage(coverage))
        self.assertEqual(s3.diagnostic_snapshots[0].termination_outcome, "abrupt_termination_no_shard")

        # 4. Liveness check: still-live child retains uncertainty (live_child_no_shard)
        s4 = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "c4", source_root=self.tmpdir)
        s4._write_config(); my_pid = os.getpid(); (s4.child_manifest_dir / f"{my_pid}.start").write_text(f"pid={my_pid}\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, f"coverage shard for child PID {my_pid} is missing"):
            s4.combine(s4.create_coverage(coverage))
        self.assertEqual(s4.diagnostic_snapshots[0].termination_outcome, "live_child_no_shard")

        # 5. Bootstrap failure is missing measurement, never a silent coverage waiver
        s5 = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "c5", source_root=self.tmpdir)
        s5._write_config(); parent_cov5 = s5.create_coverage(coverage); parent_cov5.start(); parent_cov5.stop(); parent_cov5.save()
        (s5.child_manifest_dir / "3005.start").write_text("pid=3005\ncov_start=0\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "child coverage bootstrap failed"):
            s5.combine(parent_cov5)
        self.assertEqual(s5.diagnostic_snapshots[0].termination_outcome, "uninstrumented_child")

        # 6. Valid zero-selected-hit child: valid SQLite shard with zero hits combines cleanly
        s6 = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "c6", source_root=self.tmpdir)
        s6._write_config(); z6 = s6.data_dir / ".coverage.child.2006.abc"; cov = coverage.Coverage(data_file=str(z6)); cov.start(); cov.stop(); cov.save()
        (s6.child_manifest_dir / "2006.start").write_text("pid=2006\n", encoding="utf-8"); (s6.child_manifest_dir / "2006.exit").write_text(f"pid=2006\nshard={z6}\n", encoding="utf-8")
        s6.combine(s6.create_coverage(coverage))
        self.assertFalse(z6.exists())

        # 7. Existing corrupt shard: non-empty corrupt header rejected
        s7 = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "c7", source_root=self.tmpdir)
        s7._write_config(); corrupt7 = s7.data_dir / ".coverage.child.2007.abc"; corrupt7.write_bytes(b"INVALID_HEADER_BYTES")
        (s7.child_manifest_dir / "2007.start").write_text("pid=2007\n", encoding="utf-8"); (s7.child_manifest_dir / "2007.exit").write_text(f"pid=2007\nshard={corrupt7}\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "invalid SQLite header"):
            s7.combine(s7.create_coverage(coverage))

        # 8. Sequential / nested sessions with reused scratch directory: manifests and shards purged
        reused = self.tmpdir / "reused_scratch"
        with runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=reused, source_root=self.tmpdir) as sess1:
            sess1._write_config(); (sess1.child_manifest_dir / "8888.start").touch(); (sess1.data_dir / ".coverage.old.shard").touch()
        with runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=reused, source_root=self.tmpdir) as sess2:
            self.assertFalse((sess2.child_manifest_dir / "8888.start").exists())
            self.assertFalse((sess2.data_dir / ".coverage.old.shard").exists())

    def test_regr7_synthetic_child_end_to_end_and_receipt_substitution_discipline(self):
        # 1. Receipt pointing outside the selected shard set
        s1 = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "ext1", source_root=self.tmpdir)
        s1._write_config()
        ext = self.tmpdir / "external.file"; ext.write_text("not a shard", encoding="utf-8")
        (s1.child_manifest_dir / "4001.start").write_text("pid=4001\n", encoding="utf-8")
        (s1.child_manifest_dir / "4001.exit").write_text(f"pid=4001\nshard={ext}\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "child coverage shard escapes invocation data directory"):
            s1.combine(s1.create_coverage(coverage))

        # 2. Sibling receipt substitution: two children claiming the same shard
        s2 = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "sib2", source_root=self.tmpdir)
        s2._write_config()
        sh = s2.data_dir / ".coverage.child.5001.abc"
        cov = coverage.Coverage(data_file=str(sh)); cov.start(); cov.stop(); cov.save()
        (s2.child_manifest_dir / "5001.start").write_text("pid=5001\n", encoding="utf-8")
        (s2.child_manifest_dir / "5001.exit").write_text(f"pid=5001\nshard={sh}\n", encoding="utf-8")
        (s2.child_manifest_dir / "5002.start").write_text("pid=5002\n", encoding="utf-8")
        (s2.child_manifest_dir / "5002.exit").write_text(f"pid=5002\nshard={sh}\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "coverage shard for child PID 5002 is missing"):
            s2.combine(s2.create_coverage(coverage))

        # 3. Parent receipt substitution: child claiming parent shard
        s3 = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "par3", source_root=self.tmpdir)
        s3._write_config()
        parent_cov3 = s3.create_coverage(coverage)
        parent_cov3.start(); parent_cov3.stop(); parent_cov3.save()
        (s3.child_manifest_dir / "6002.start").write_text("pid=6002\n", encoding="utf-8")
        (s3.child_manifest_dir / "6002.exit").write_text(f"pid=6002\nshard={s3.data_file}\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "coverage shard for child PID 6002 is missing"):
            s3.combine(parent_cov3)

        # 4. Positive path: valid attributable child shard combines cleanly
        s4 = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / "pos4", source_root=self.tmpdir)
        s4._write_config()
        sh4 = s4.data_dir / ".coverage.child.7001.abc"
        cov = coverage.Coverage(data_file=str(sh4)); cov.start(); cov.stop(); cov.save()
        (s4.child_manifest_dir / "7001.start").write_text("pid=7001\n", encoding="utf-8")
        (s4.child_manifest_dir / "7001.exit").write_text(f"pid=7001\nshard={sh4}\n", encoding="utf-8")
        s4.combine(s4.create_coverage(coverage))
        self.assertFalse(sh4.exists())
