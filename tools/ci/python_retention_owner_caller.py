"""Maintained complete owner AST; parsed but never executed."""
SOURCE = r'''
"""Unit tests for child coverage collection, deterministic combination, and path mapping."""
from __future__ import annotations
from functools import partial
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import coverage
import runner_coverage
import run_tests
REPO_ROOT = Path(__file__).resolve().parents[5]
TOOLS_DIR = REPO_ROOT / 'tools'
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

class ChildCoverageTestCase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix='repomap-child-cov-test-')).resolve()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

class ChildCoverageSessionUnitTests(ChildCoverageTestCase):

    def test_run_pytest_with_coverage_default_caller_path_and_reporting(self):
        source_dir = self.tmpdir / 'src_caller'
        source_dir.mkdir()
        mod_file = source_dir / 'caller_mod.py'
        mod_file.write_text("def hello(): return 'world'\n", encoding='utf-8')
        dummy_pytest = SimpleNamespace()
        dummy_plugin = SimpleNamespace(test_records=[])

        def fake_run_pytest(pm, pa, pl):
            import importlib
            caller_mod = importlib.import_module('caller_mod')
            assert caller_mod.hello() == 'world'
            return 0
        with patch.dict(sys.modules), patch.object(sys, 'path', [str(source_dir)] + sys.path):
            sys.modules.pop('caller_mod', None)
            with patch.object(run_tests, 'run_pytest', side_effect=fake_run_pytest), patch.object(run_tests, 'ChildCoverageSession', partial(runner_coverage.ChildCoverageSession, source_root=source_dir)):
                exit_code, runner = run_tests.run_pytest_with_coverage(coverage, dummy_pytest, [], dummy_plugin, scratch_dir=None, source_paths=[source_dir])
        session = getattr(runner, '_repomap_session', None)
        if isinstance(session, runner_coverage.ChildCoverageSession):
            self.addCleanup(session.cleanup)
        self.assertEqual(exit_code, 0)
        self.assertIsNotNone(session)
        assert isinstance(session, runner_coverage.ChildCoverageSession)
        self.assertIsNotNone(session._temp_dir)
        json_out = self.tmpdir / 'caller_cov.json'
        runner.json_report(morfs=[str(mod_file.resolve())], outfile=str(json_out))
        self.assertTrue(json_out.exists())
        cov_payload = json.loads(json_out.read_text(encoding='utf-8'))
        mod_key = str(mod_file.resolve())
        self.assertIn(mod_key, cov_payload['files'])
        mod_summary = cov_payload['files'][mod_key]['summary']
        self.assertEqual(mod_summary['covered_lines'], 1)
        self.assertEqual(mod_summary['num_statements'], 1)
        self.assertEqual(mod_summary['missing_lines'], 0)
        self.assertIn(1, cov_payload['files'][mod_key]['executed_lines'])
        self.assertEqual(cov_payload['files'][mod_key]['missing_lines'], [])
        data = runner.get_data()
        self.assertIn(mod_key, data.measured_files())
        self.assertEqual(data.lines(mod_key), [1])
        session.cleanup()
        self.assertIsNone(session._temp_dir)
        self.assertFalse(session.session_dir.exists())

    def test_normal_child_return_measures_and_combines_coverage(self):
        source_dir = self.tmpdir / 'src'
        source_dir.mkdir()
        mod_file = source_dir / 'sample_mod.py'
        mod_file.write_text('def compute(a, b):\n    return a + b\n', encoding='utf-8')
        child_script = self.tmpdir / 'run_child.py'
        child_script.write_text(f'import sys\nsys.path.insert(0, {str(source_dir)!r})\nimport sample_mod\nassert sample_mod.compute(2, 3) == 5\n', encoding='utf-8')
        with runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / 'session', source_root=source_dir) as session:
            runner = session.create_coverage(coverage)
            runner.start()
            try:
                proc = subprocess.run([sys.executable, str(child_script)], capture_output=True, text=True, check=False)
                self.assertEqual(proc.returncode, 0, proc.stderr)
            finally:
                runner.stop()
                runner.save()
                session.combine(runner)
            data = runner.get_data()
            measured = data.measured_files()
            self.assertIn(str(mod_file.resolve()), measured)

    def test_nonzero_return_preserves_primary_failure(self):

        def fake_run_pytest_failing(pytest_module, pytest_args, plugin):
            return 1
        dummy_pytest = SimpleNamespace()
        dummy_plugin = SimpleNamespace()
        with patch.object(run_tests, 'run_pytest', side_effect=fake_run_pytest_failing):
            exit_code, runner = run_tests.run_pytest_with_coverage(coverage, dummy_pytest, [], dummy_plugin, scratch_dir=self.tmpdir / 'fail_session')
            self.assertEqual(exit_code, 1)

        def fake_run_pytest_raising(pytest_module, pytest_args, plugin):
            raise RuntimeError('primary assertion failure in runner')
        with self.assertRaisesRegex(RuntimeError, 'primary assertion failure'):
            with patch.object(run_tests, 'run_pytest', side_effect=fake_run_pytest_raising):
                run_tests.run_pytest_with_coverage(coverage, dummy_pytest, [], dummy_plugin, scratch_dir=self.tmpdir / 'raise_session')

    def test_sequential_attempt_isolation_purges_stale_shards(self):
        session_scratch = self.tmpdir / 'session_isolation'
        shards_dir = session_scratch / 'shards'
        shards_dir.mkdir(parents=True)
        stale_shard_1 = shards_dir / '.coverage.host.1234.stale1'
        stale_shard_2 = shards_dir / '.coverage.host.5678.stale2'
        stale_shard_1.write_text('fake shard 1', encoding='utf-8')
        stale_shard_2.write_text('fake shard 2', encoding='utf-8')
        self.assertTrue(stale_shard_1.exists())
        self.assertTrue(stale_shard_2.exists())
        with runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=session_scratch, source_root=self.tmpdir):
            self.assertFalse(stale_shard_1.exists())
            self.assertFalse(stale_shard_2.exists())

    def test_source_copy_mapping_remaps_to_canonical_source(self):
        canonical_dir = (self.tmpdir / 'canonical').resolve()
        canonical_dir.mkdir()
        canonical_file = canonical_dir / 'target_module.py'
        canonical_file.write_text("def action():\n    return 'canonical'\n", encoding='utf-8')
        copied_dir = (self.tmpdir / 'copied').resolve()
        copied_dir.mkdir()
        copied_file = copied_dir / 'target_module.py'
        copied_file.write_text("def action():\n    return 'canonical'\n", encoding='utf-8')
        child_script = self.tmpdir / 'run_mapped_child.py'
        child_script.write_text(f"import sys\nsys.path.insert(0, {str(copied_dir)!r})\nimport target_module\nassert target_module.action() == 'canonical'\n", encoding='utf-8')
        with runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / 'mapped_session', source_root=canonical_dir, source_paths=[copied_dir]) as session:
            runner = session.create_coverage(coverage)
            runner.start()
            try:
                proc = subprocess.run([sys.executable, str(child_script)], capture_output=True, text=True, check=False)
                self.assertEqual(proc.returncode, 0, proc.stderr)
            finally:
                runner.stop()
                runner.save()
                runner = session.combine(runner)
            data = runner.get_data()
            measured = data.measured_files()
            self.assertIn(str(canonical_file), measured)
            self.assertNotIn(str(copied_file), measured)

    def test_scratch_dir_none_allows_reporting_after_context_exit(self):
        source_dir = self.tmpdir / 'src_none'
        source_dir.mkdir()
        mod_file = source_dir / 'sample_mod.py'
        mod_file.write_text('def compute(a, b):\n    return a * b\n', encoding='utf-8')
        child_script = self.tmpdir / 'run_child_none.py'
        child_script.write_text(f'import sys\nsys.path.insert(0, {str(source_dir)!r})\nimport sample_mod\nassert sample_mod.compute(4, 5) == 20\n', encoding='utf-8')
        session = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=None, source_root=source_dir)
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            try:
                proc = subprocess.run([sys.executable, str(child_script)], capture_output=True, text=True, check=False)
                self.assertEqual(proc.returncode, 0, proc.stderr)
            finally:
                runner.stop()
                runner.save()
                runner = session.combine(runner)
        self.assertTrue(session.data_file.exists())
        data = runner.get_data()
        self.assertIn(str(mod_file.resolve()), data.measured_files())
        json_out = self.tmpdir / 'cov.json'
        runner.json_report(morfs=[str(mod_file.resolve())], outfile=str(json_out))
        self.assertTrue(json_out.exists())
        session.cleanup()
        self.assertIsNone(session._temp_dir)
        self.assertFalse(session.session_dir.exists())
        session.cleanup()
        self.assertFalse(session.session_dir.exists())

    def test_canonical_mapping_preserves_line_and_branch_coverage(self):
        canonical_dir = (self.tmpdir / 'canon_branch').resolve()
        canonical_dir.mkdir()
        canonical_file = canonical_dir / 'branch_mod.py'
        canonical_file.write_text('def decide(val):\n    if val > 0:\n        return 1\n    else:\n        return -1\n', encoding='utf-8')
        copied_dir = (self.tmpdir / 'copy_branch').resolve()
        copied_dir.mkdir()
        copied_file = copied_dir / 'branch_mod.py'
        copied_file.write_text('def decide(val):\n    if val > 0:\n        return 1\n    else:\n        return -1\n', encoding='utf-8')
        child_script = self.tmpdir / 'run_branch_child.py'
        child_script.write_text(f'import sys\nsys.path.insert(0, {str(copied_dir)!r})\nimport branch_mod\nassert branch_mod.decide(10) == 1\n', encoding='utf-8')
        with runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / 'branch_session', source_root=canonical_dir, source_paths=[copied_dir]) as session:
            runner = session.create_coverage(coverage)
            runner.start()
            try:
                proc = subprocess.run([sys.executable, str(child_script)], capture_output=True, text=True, check=False)
                self.assertEqual(proc.returncode, 0, proc.stderr)
            finally:
                runner.stop()
                runner.save()
                runner = session.combine(runner)
            data = runner.get_data()
            measured = data.measured_files()
            self.assertIn(str(canonical_file), measured)
            self.assertNotIn(str(copied_file), measured)
            _, executable, _, missing, _ = runner.analysis2(str(canonical_file))
            self.assertEqual(executable, [1, 2, 3, 5])
            self.assertNotIn(1, missing)
            self.assertNotIn(2, missing)
            self.assertNotIn(3, missing)
            self.assertIn(5, missing)
            arcs = data.arcs(str(canonical_file))
            self.assertIsNotNone(arcs)
            self.assertIn((2, 3), arcs)
            self.assertNotIn((2, 5), arcs)

    def test_non_identical_copied_source_rejected(self):
        canonical_dir = (self.tmpdir / 'canon_reject').resolve()
        canonical_dir.mkdir()
        canonical_file = canonical_dir / 'target_module.py'
        canonical_file.write_text('def run(): return 1\n', encoding='utf-8')
        mismatched_dir = (self.tmpdir / 'mismatched').resolve()
        mismatched_dir.mkdir()
        session = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / 'reject_session', source_root=canonical_dir, source_paths=[mismatched_dir])
        same_size_file = mismatched_dir / 'target_module.py'
        same_size_file.write_text('def run(): return 2\n', encoding='utf-8')
        self.assertFalse(session._verify_source_identity(mismatched_dir))
        self.assertTrue(any(('sha256 mismatch' in r for r in session.source_rejections)))
        diff_size_file = mismatched_dir / 'target_module.py'
        diff_size_file.write_text('def run(): return 2  # modified\n', encoding='utf-8')
        self.assertFalse(session._verify_source_identity(mismatched_dir))
        self.assertEqual(session.source_rejections[-1], f'{diff_size_file}: file mismatch with {canonical_file}')
        session._write_config()
        config_text = session.config_file.read_text(encoding='utf-8')
        self.assertNotIn(str(mismatched_dir), config_text)
        missing_file_dir = (self.tmpdir / 'empty_copy').resolve()
        missing_file_dir.mkdir()
        self.assertFalse(session._verify_source_identity(missing_file_dir))
        self.assertTrue(any(('no python files' in r or 'file inventory mismatch' in r for r in session.source_rejections)))

    def test_empty_or_corrupt_shard_raises_during_combine(self):
        session = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / 'corrupt_session', source_root=self.tmpdir)
        with session:
            runner = session.create_coverage(coverage)
            corrupt_shard = session.data_dir / '.coverage.host.1234.empty'
            corrupt_shard.touch()
            (session.child_manifest_dir / '1234.start').write_text('pid=1234\n', encoding='utf-8')
            (session.child_manifest_dir / '1234.exit').write_text(f'pid=1234\nshard={corrupt_shard}\n', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'empty or unreadable'):
                session.combine(runner)

    def test_run_pytest_with_coverage_combined_outcome_matrix(self):
        dummy_pytest = SimpleNamespace()
        dummy_plugin = SimpleNamespace(test_records=['dummy_record'])
        for primary_outcome in ['success', 'nonzero', 'exception']:
            with self.subTest(primary_outcome=primary_outcome):
                session = runner_coverage.ChildCoverageSession(coverage_module=coverage, scratch_dir=self.tmpdir / f'matrix_session_{primary_outcome}', source_root=self.tmpdir)

                def fake_run(pm, pa, pl):
                    corrupt = session.data_dir / '.coverage.child.9999.corrupt'
                    corrupt.touch()
                    (session.child_manifest_dir / '9999.start').write_text('pid=9999\n', encoding='utf-8')
                    (session.child_manifest_dir / '9999.exit').write_text(f'pid=9999\nshard={corrupt}\n', encoding='utf-8')
                    if primary_outcome == 'success':
                        return 0
                    elif primary_outcome == 'nonzero':
                        return 1
                    else:
                        raise RuntimeError('primary suite crash')
                try:
                    with patch.object(run_tests, 'run_pytest', side_effect=fake_run):
                        if primary_outcome == 'exception':
                            with self.assertRaisesRegex(RuntimeError, 'primary suite crash'):
                                run_tests.run_pytest_with_coverage(coverage, dummy_pytest, [], dummy_plugin, session=session)
                        else:
                            exit_code, runner = run_tests.run_pytest_with_coverage(coverage, dummy_pytest, [], dummy_plugin, session=session)
                            expected_exit = 0 if primary_outcome == 'success' else 1
                            self.assertEqual(exit_code, expected_exit)
                            err = getattr(runner, '_instrumentation_error', None)
                            self.assertIsNotNone(err)
                            assert isinstance(err, str)
                            self.assertIn('empty or unreadable', err)
                finally:
                    session.cleanup()
                    self.assertIsNone(session._temp_dir)
'''
