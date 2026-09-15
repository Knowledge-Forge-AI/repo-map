"""Real child coverage evidence and incomplete terminal receipt regressions."""

import os
from pathlib import Path
import subprocess
import sys

import coverage
import pytest

from runner_coverage import ChildCoverageSession
from runner_coverage_execution import read_registered_children


@pytest.mark.parametrize('work', ['pass', 'raise SystemExit(7)'])
def test_clean_no_selected_work_has_actual_collector_receipt_and_uncovered_source(tmp_path, work):
    source = tmp_path / 'source'
    source.mkdir()
    target = source / 'uncovered.py'
    target.write_text('VALUE = 42\n')
    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / 'measure', source_root=source, suite='int')
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            result = subprocess.run([sys.executable, '-c', work], capture_output=True)
            runner.stop()
            runner.save()
            assert result.returncode == (7 if '7' in work else 0)
            registered = read_registered_children(session.child_manifest_dir, session.session_dir.name, 'int')
            assert len(registered) == 1
            pid, record = next(iter(registered.items()))
            assert record['cov_start'] == 1 and record['exited']
            terminal = (session.child_manifest_dir / f'{pid}.exit').read_text()
            assert 'measurement=no_selected_hits\n' in terminal
            data = session.combine(runner).get_data()
            assert not data.lines(str(target))
    finally:
        session.cleanup()


def test_bootstrap_failure_is_recorded_and_rejected(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'uncovered.py').write_text('VALUE = 1\n')
    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / 'measure', source_root=source, suite='int')
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            env = dict(os.environ, COVERAGE_PROCESS_START=str(tmp_path / 'missing.rc'))
            result = subprocess.run([sys.executable, '-c', 'pass'], env=env, capture_output=True)
            runner.stop()
            runner.save()
            assert result.returncode == 0
            records = read_registered_children(session.child_manifest_dir, session.session_dir.name, 'int')
            record = next(iter(records.values()))
            assert record['cov_start'] == 0 and record['bootstrap_error']
            with pytest.raises(RuntimeError, match='bootstrap failed'):
                session.combine(runner)
    finally:
        session.cleanup()


@pytest.mark.parametrize('role', ['inherited-python', 'conformance-abrupt'])
def test_actual_abrupt_child_preopened_terminal_is_not_clean_exit(tmp_path, role):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'uncovered.py').write_text('VALUE = 1\n')
    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / 'measure', source_root=source, suite='int')
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            result = subprocess.run([sys.executable, '-c', 'import os; os._exit(17)'],
                                    env=dict(os.environ, COVERAGE_CHILD_LAUNCH_ROLE=role), capture_output=True)
            runner.stop()
            runner.save()
            assert result.returncode == 17
            records = read_registered_children(session.child_manifest_dir, session.session_dir.name, 'int')
            pid, record = next(iter(records.items()))
            assert (session.child_manifest_dir / f'{pid}.exit').read_bytes() == b''
            assert not record['exited']
            with pytest.raises(RuntimeError, match='terminal receipt is incomplete'):
                session.combine(runner)
            diagnostic = session.diagnostic_snapshots[-1]
            assert diagnostic.launch_role == role
            assert diagnostic.termination_outcome == (
                'declared_abrupt_measurement_incomplete' if role == 'conformance-abrupt'
                else 'unknown_termination_measurement_incomplete'
            )
    finally:
        session.cleanup()


def test_actual_child_save_failure_remains_failed_measurement(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'uncovered.py').write_text('VALUE = 1\n')
    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / 'measure', source_root=source, suite='int')
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            code = "import coverage\ndef fail(): raise OSError('fixture')\ncoverage.Coverage.current().save = fail\n"
            result = subprocess.run([sys.executable, '-c', code], capture_output=True)
            runner.stop()
            runner.save()
            assert result.returncode == 0
            records = read_registered_children(session.child_manifest_dir, session.session_dir.name, 'int')
            assert next(iter(records.values()))['terminal_error'] == 'OSError'
            with pytest.raises(RuntimeError, match='coverage save failure'):
                session.combine(runner)
    finally:
        session.cleanup()


def test_clean_child_lost_shard_is_distinct_from_abrupt_terminal_refusal(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'uncovered.py').write_text('VALUE = 1\n')
    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / 'measure', source_root=source, suite='int')
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            try:
                result = subprocess.run([sys.executable, '-c', 'pass'], capture_output=True)
            finally:
                runner.stop()
            runner.save()
            assert result.returncode == 0
            records = read_registered_children(session.child_manifest_dir, session.session_dir.name, 'int')
            record = next(iter(records.values()))
            assert record['cov_start'] == 1 and record['exited']
            shard = Path(record['shard'])
            assert shard.is_file()
            shard.unlink()  # Inject loss after an authentic clean terminal receipt.
            with pytest.raises(RuntimeError, match='child process executed without producing coverage data'):
                session.combine(runner)
            diagnostic = session.diagnostic_snapshots[-1]
            assert diagnostic.termination_outcome == 'clean_exit_no_shard'
            assert diagnostic.file_type == 'missing'
    finally:
        session.cleanup()
    assert not session.session_dir.exists()


@pytest.mark.parametrize('fault', ['foreign-invocation', 'foreign-source', 'empty-terminal',
                                 'foreign-shard', 'symlink-shard', 'corrupt-shard', 'false-hits'])
def test_actual_child_receipts_and_shards_reject_foreign_or_incomplete_evidence(tmp_path, fault):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'uncovered.py').write_text('VALUE = 1\n')
    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / 'measure', source_root=source, suite='int')
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            result = subprocess.run([sys.executable, '-c', 'pass'], capture_output=True)
            runner.stop()
            runner.save()
            assert result.returncode == 0
            pid = next(iter(read_registered_children(session.child_manifest_dir)))
            terminal = session.child_manifest_dir / f'{pid}.exit'
            start = session.child_manifest_dir / f'{pid}.start'
            fields = dict(line.split('=', 1) for line in terminal.read_text().splitlines())
            shard = Path(fields['shard'])
            if fault == 'foreign-invocation':
                fields['invocation'] = 'old-invocation'
            elif fault == 'foreign-source':
                start.write_text(start.read_text().replace(fields['revision'], 'foreign-source'))
            elif fault == 'foreign-shard':
                outside = tmp_path / shard.name
                outside.write_bytes(shard.read_bytes())
                fields['shard'] = str(outside)
            elif fault == 'symlink-shard':
                outside = tmp_path / shard.name
                outside.write_bytes(shard.read_bytes())
                shard.unlink()
                shard.symlink_to(outside)
            elif fault == 'corrupt-shard':
                shard.write_bytes(b'not coverage data')
            elif fault == 'false-hits':
                fields['measurement'] = 'selected_hits'
            terminal.write_text('' if fault == 'empty-terminal' else
                                ''.join(f'{k}={v}\n' for k, v in fields.items()))
            with pytest.raises(RuntimeError):
                session.combine(runner)
    finally:
        session.cleanup()


def test_auxiliary_runtime_process_exemption_and_provenance(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'uncovered.py').write_text('VALUE = 1\n')
    session = ChildCoverageSession(
        coverage_module=coverage, scratch_dir=tmp_path / 'measure', source_root=source, suite='int'
    )
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            env = dict(os.environ)

            res_ordinary = subprocess.run(
                [sys.executable, '-c', 'import sys; pass', 'multiprocessing.resource_tracker'],
                env=env,
                capture_output=True,
            )
            assert res_ordinary.returncode == 0

            handshake_fifo = tmp_path / 'handshake.fifo'
            release_fifo = tmp_path / 'release.fifo'
            os.mkfifo(str(handshake_fifo))
            os.mkfifo(str(release_fifo))
            env_handshake = dict(
                env,
                COVERAGE_CHILD_HANDSHAKE_FIFO=str(handshake_fifo),
                COVERAGE_CHILD_RELEASE_FIFO=str(release_fifo),
            )
            launcher_cmd = '\n'.join([
                "import multiprocessing.resource_tracker as rt, os",
                "rt.ensure_running()",
                "manifest = os.environ['COVERAGE_CHILD_MANIFEST_DIR']",
                "with open(os.environ['COVERAGE_CHILD_HANDSHAKE_FIFO'], 'r', encoding='utf-8') as hf:",
                "    line = hf.readline()",
                "child_pid = line.split(':')[0]",
                "assert os.path.exists(os.path.join(manifest, f'{child_pid}.start'))",
                "with open(os.environ['COVERAGE_CHILD_RELEASE_FIFO'], 'w', encoding='utf-8') as rf:",
                "    rf.write('ok' + chr(10))",
            ])
            res_tracker = subprocess.run(
                [sys.executable, '-c', launcher_cmd],
                env=env_handshake,
                capture_output=True,
                timeout=10.0,
            )
            assert res_tracker.returncode == 0

            runner.stop()
            runner.save()
            records = read_registered_children(session.child_manifest_dir, session.session_dir.name, 'int')
            assert len(records) >= 2

            ordinary_records = [
                r for r in records.values()
                if r.get('role') == 'inherited-python' and r.get('launch_shape') == 'cpython:-c'
            ]
            assert len(ordinary_records) == 2
            for ord_rec in ordinary_records:
                assert ord_rec['strict'] is True
                assert ord_rec['auxiliary'] is False

            ordinary_pids = [
                pid for pid, r in records.items()
                if r.get('role') == 'inherited-python' and r.get('launch_shape') == 'cpython:-c'
            ]

            aux_records = [r for r in records.values() if r.get('role') == 'auxiliary-runtime']
            assert len(aux_records) >= 1
            assert aux_records[0]['auxiliary'] is True
            assert aux_records[0]['strict'] is False
            assert aux_records[0]['launch_shape'] == 'cpython:resource_tracker'
            assert aux_records[0]['ppid'] in ordinary_pids

            combined = session.combine(runner)
            assert combined is not None
    finally:
        session.cleanup()


def test_auxiliary_runtime_delayed_startup_retains_parent_provenance(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'uncovered.py').write_text('VALUE = 1\n')
    session = ChildCoverageSession(
        coverage_module=coverage, scratch_dir=tmp_path / 'measure', source_root=source, suite='int'
    )
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            pause_fifo = tmp_path / 'pause.fifo'
            handshake_fifo = tmp_path / 'handshake_delayed.fifo'
            release_fifo = tmp_path / 'release_delayed.fifo'
            os.mkfifo(str(pause_fifo))
            os.mkfifo(str(handshake_fifo))
            os.mkfifo(str(release_fifo))
            env = dict(
                os.environ,
                COVERAGE_CHILD_BOOTSTRAP_PAUSE_FIFO=str(pause_fifo),
                COVERAGE_CHILD_HANDSHAKE_FIFO=str(handshake_fifo),
                COVERAGE_CHILD_RELEASE_FIFO=str(release_fifo),
            )
            launcher_cmd = '\n'.join([
                "import multiprocessing.resource_tracker as rt, os",
                "rt.ensure_running()",
                "manifest = os.environ['COVERAGE_CHILD_MANIFEST_DIR']",
                "with open(os.environ['COVERAGE_CHILD_HANDSHAKE_FIFO'], 'r', encoding='utf-8') as hf:",
                "    line = hf.readline()",
                "child_pid = line.split(':')[0]",
                "assert os.path.exists(os.path.join(manifest, f'{child_pid}.start'))",
                "with open(os.environ['COVERAGE_CHILD_RELEASE_FIFO'], 'w', encoding='utf-8') as rf:",
                "    rf.write('ok' + chr(10))",
            ])
            proc = subprocess.Popen([sys.executable, '-c', launcher_cmd], env=env)
            with open(str(pause_fifo), 'w', encoding='utf-8') as pf:
                pf.write('resume' + chr(10))
            assert proc.wait(timeout=10.0) == 0

            runner.stop()
            runner.save()
            records = read_registered_children(session.child_manifest_dir, session.session_dir.name, 'int')
            aux_records = [r for r in records.values() if r.get('role') == 'auxiliary-runtime']
            assert len(aux_records) >= 1
            assert aux_records[0]['ppid'] == proc.pid
            assert aux_records[0]['auxiliary'] is True
            assert aux_records[0]['strict'] is False
    finally:
        session.cleanup()


def test_tracker_lookalike_and_spoofed_role_remain_strict(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'uncovered.py').write_text('VALUE = 1\n')
    session = ChildCoverageSession(
        coverage_module=coverage, scratch_dir=tmp_path / 'measure', source_root=source, suite='int'
    )
    try:
        with session:
            runner = session.create_coverage(coverage)
            runner.start()
            env = dict(os.environ)

            # Lookalike with extra statement: not an exact tracker invocation
            cmd_lookalike = (
                'from multiprocessing.resource_tracker import main; print("not-tracker")'
            )
            res1 = subprocess.run([sys.executable, '-c', cmd_lookalike], env=env, capture_output=True)
            assert res1.returncode == 0
            assert b"not-tracker" in res1.stdout

            # Lookalike script name
            script_file = tmp_path / "resource_tracker_lookalike.py"
            script_file.write_text("print('script-lookalike')\n")
            res2 = subprocess.run([sys.executable, str(script_file)], env=env, capture_output=True)
            assert res2.returncode == 0

            # Spoofed auxiliary-runtime role passed via environment
            env_spoof = dict(env, COVERAGE_CHILD_LAUNCH_ROLE='auxiliary-runtime')
            res3 = subprocess.run([sys.executable, '-c', 'pass'], env=env_spoof, capture_output=True)
            assert res3.returncode == 0

            runner.stop()
            runner.save()
            records = read_registered_children(session.child_manifest_dir, session.session_dir.name, 'int')

            # None of these lookalike or spoofed processes may be granted auxiliary exemption
            assert len(records) >= 3
            for r in records.values():
                assert r.get('auxiliary') is False
                assert r.get('strict') is True
                assert r.get('role') != 'auxiliary-runtime'
    finally:
        session.cleanup()

