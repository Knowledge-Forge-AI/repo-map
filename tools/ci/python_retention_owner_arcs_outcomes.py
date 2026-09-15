"""Remaining complete export-owner methods; inert source, never executed."""
SOURCE = r'''    def test_regr5_raw_count_threshold_boundaries_and_cross_suite_contamination(self):
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
'''
