"""Maintained closed export tails and child coverage AST templates."""

from __future__ import annotations

TAILS = {
    'test_raw_coverage_export_preserves_uncovered_branch': r'''
output = tmp_path / 'retained' / 'coverage.json'
with patch.object(runner_coverage, 'SOURCE_ROOT', tmp_path):
    records = runner_coverage.coverage_records_from_json(collector, [source], json_report_path=output)
    unexported = runner_coverage.coverage_records_from_json(collector, [source])
    summary = runner_coverage.collect_coverage_summary(collector, 'unit', runner_coverage.coverage_policy_for_suite('unit'))
assert records == unexported
assert summary.covered_branches == 1
payload = json.loads(output.read_text())
assert len(payload['files']) == 1
measured = next(iter(payload['files'].values()))
assert 3 in measured['executed_lines']
assert 4 in measured['missing_lines']
assert [2, 3] in measured['executed_branches']
assert [2, 4] in measured['missing_branches']
assert records[0].total_branches == 2
assert records[0].covered_branches == 1
report_root = tmp_path / 'reports'
raw_report = report_root / 'unit' / 'coverage.json'
raw_report.parent.mkdir(parents=True)
raw_report.write_bytes(output.read_bytes())
write_html_report(report_root=report_root, suite_name='unit', test_records=(), coverage=summary, repo_root=tmp_path)
assert raw_report.read_bytes() == output.read_bytes()
summary_path = report_root / 'unit' / 'latest' / 'summary.json'
assert summary_path.exists()
report_summary = json.loads(summary_path.read_text(encoding='utf-8'))
assert report_summary['coverage']['status'] == 'measured'
assert report_summary['coverage']['passed'] is False
assert report_summary['coverage']['line']['covered'] == summary.covered_lines
assert report_summary['coverage']['line']['total'] == summary.total_lines
assert report_summary['coverage']['branch']['covered'] == 1
assert report_summary['coverage']['branch']['total'] == 2
index_path = report_root / 'unit' / 'latest' / 'index.html'
assert index_path.exists()
index_html = index_path.read_text(encoding='utf-8')
assert 'Line coverage' in index_html
assert 'Branch coverage' in index_html
obligations = {'legs': {
    'M': {'status': 'passed', 'measurement': {'state': 'measured'}},
    'A': {'status': 'blocked', 'measurement': {'state': 'unavailable'}},
}}
paired_index = write_html_report(report_root=report_root, suite_name='staging', test_records=(), coverage=summary, repo_root=tmp_path, staging_obligations=obligations)
paired = json.loads((paired_index.parent / 'summary.json').read_text())
assert paired['staging_obligations'] == obligations
assert paired['coverage']['branch'] == report_summary['coverage']['branch']
assert 'Staging evidence: not qualified' in paired_index.read_text()
assert 'A: blocked; measurement unavailable' in paired_index.read_text()
''',
    'test_export_write_failure_is_not_silently_discarded': r'''
blocked_parent = tmp_path / 'not-a-directory'
blocked_parent.write_text('occupied', encoding='utf-8')
with pytest.raises(FileExistsError):
    runner_coverage.coverage_records_from_json(collector, [source], json_report_path=blocked_parent / 'coverage.json')
assert not (blocked_parent / 'coverage.json').exists()
assert blocked_parent.read_text(encoding='utf-8') == 'occupied'
''',
    'test_runner_coverage_reports_direct_invocation': r'''
policy = runner_coverage_reports.coverage_policy_for_suite('unit')
summary = runner_coverage_reports.collect_coverage_summary(collector, 'unit', policy, source_root=tmp_path)
assert summary.total_lines == 2
assert summary.covered_lines == 2
assert summary.line_percent == 100.0
assert summary.passed is True
assert len(summary.files) == 1
assert summary.files[0].path == source.resolve()
assert summary.files[0].covered_lines == 2
assert summary.files[0].executable_lines == 2
assert summary.files[0].line_percent == 100.0
''',
}

CALLER_MOD_TEMPLATE = r'''def test_run_pytest_with_coverage_default_caller_path_and_reporting(self):
    source_dir = self.tmpdir / "src_caller"
    source_dir.mkdir()
    mod_file = source_dir / "caller_mod.py"
    mod_file.write_text("def hello(): return 'world'\n", encoding="utf-8")

    dummy_pytest = SimpleNamespace()
    dummy_plugin = SimpleNamespace(test_records=[])

    def fake_run_pytest(pm, pa, pl):
        import importlib
        caller_mod = importlib.import_module("caller_mod")
        assert caller_mod.hello() == "world"
        return 0

    with patch.dict(sys.modules), patch.object(sys, "path", [str(source_dir)] + sys.path):
        sys.modules.pop("caller_mod", None)
        with patch.object(run_tests, "run_pytest", side_effect=fake_run_pytest), patch.object(run_tests, "ChildCoverageSession", partial(runner_coverage.ChildCoverageSession, source_root=source_dir)):
            exit_code, runner = run_tests.run_pytest_with_coverage(
                coverage, dummy_pytest, [], dummy_plugin, scratch_dir=None, source_paths=[source_dir],
            )

    session = getattr(runner, "_repomap_session", None)
    if isinstance(session, runner_coverage.ChildCoverageSession):
        self.addCleanup(session.cleanup)
    self.assertEqual(exit_code, 0)
    self.assertIsNotNone(session)
    assert isinstance(session, runner_coverage.ChildCoverageSession)
    self.assertIsNotNone(session._temp_dir)
    json_out = self.tmpdir / "caller_cov.json"
    runner.json_report(morfs=[str(mod_file.resolve())], outfile=str(json_out))
    self.assertTrue(json_out.exists())
    cov_payload = json.loads(json_out.read_text(encoding="utf-8"))
    mod_key = str(mod_file.resolve())
    self.assertIn(mod_key, cov_payload["files"])
    mod_summary = cov_payload["files"][mod_key]["summary"]
    self.assertEqual(mod_summary["covered_lines"], 1)
    self.assertEqual(mod_summary["num_statements"], 1)
    self.assertEqual(mod_summary["missing_lines"], 0)
    self.assertIn(1, cov_payload["files"][mod_key]["executed_lines"])
    self.assertEqual(cov_payload["files"][mod_key]["missing_lines"], [])
    data = runner.get_data()
    self.assertIn(mod_key, data.measured_files())
    self.assertEqual(data.lines(mod_key), [1])
    session.cleanup()
    self.assertIsNone(session._temp_dir)
    self.assertFalse(session.session_dir.exists())
'''

DECISION_MOD_TEMPLATE = r'''def test_regr1_nested_coverage_preserves_branch_arcs(self):
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
'''

CHILD_COVERAGE_TEMPLATES = {
    "caller_mod": CALLER_MOD_TEMPLATE,
    "decision_mod": DECISION_MOD_TEMPLATE,
}
