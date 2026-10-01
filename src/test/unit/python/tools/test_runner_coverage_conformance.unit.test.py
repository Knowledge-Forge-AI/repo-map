"""Collection-enabled proofs for the closed conformance launch identity."""

from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys

import coverage
import pytest

from repomap_kg.coordinator import _portable_worker_launch as launch
from repomap_kg.coordinator._worker_launch import WorkerLaunchSpec
from repomap_test_support.portable_worker_conformance import run_portable_worker_conformance
from runner_coverage import ChildCoverageSession
from runner_coverage_capability import CapabilityContainmentError, CapabilityValidationError
from runner_coverage_conformance import CONFORMANCE_COMMAND
from runner_coverage_execution import read_registered_children
from runner_integration_obligations import COV5G_OWNER_SHA256
from runner_portable_coverage import make_portable_worker_spec_adapter, scoped_portable_coverage_adapter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[5]


def test_crash_command_role_and_primary_outcome_survive_missing_measurement(tmp_path):
    """Exercise the real adapter with a supervisor double, without a workload."""
    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / 'measure', suite='int')
    cap = session.issue_portable_capability(allow_test_conformance=True)
    observed = []
    primary = RuntimeError('supervised fixture failure')

    def supervisor(spec, *args, **kwargs):
        observed.append(spec)
        raise primary

    adapter = make_portable_worker_spec_adapter(supervisor, cap, session)
    paths = (ROOT / 'src/test/support/python', ROOT / 'src/main/python')
    spec = WorkerLaunchSpec(
        argv=(sys.executable, *CONFORMANCE_COMMAND, '--case', 'crash:after-materialization',
              '--capability', 'fixture', '--job-id', 'job-1', '--attempt', '1'),
        environment={'PYTHONPATH': os.pathsep.join(map(str, paths))}, cwd=tmp_path,
    )
    try:
        with pytest.raises(RuntimeError, match='supervised fixture failure') as caught:
            adapter(spec, {}, object())
        assert caught.value is primary
        assert len(observed) == 1
        assert observed[0].environment['COVERAGE_CHILD_LAUNCH_ROLE'] == 'conformance-abrupt'
        assert session.measurement_errors
        diagnostic = session.diagnostic_snapshots[-1]
        assert diagnostic.launch_role == 'conformance-abrupt'
        assert diagnostic.termination_outcome == 'declared_abrupt_measurement_incomplete'
        assert diagnostic.stage == 'post_worker_reap'
        assert any('child coverage measurement failure' in note for note in primary.__notes__)
    finally:
        session.cleanup()


@pytest.mark.parametrize('case,status', [
    ('failure:artifact_missing', 'failed'),
    ('authority:write', 'failed'),
    ('authority:socket', 'failed'),
    ('authority:subprocess', 'failed'),
    ('authority:database-import', 'failed'),
    ('receipt:write_failed', 'failed'),
    ('cancel:before_manifest', 'cancelled'),
    ('crash:after-materialization', None),
])
def test_actual_conformance_supervisor_preserves_guard_cleanup_and_measurement(tmp_path, case, status):
    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / 'measure', suite='int')
    cap = session.issue_portable_capability(allow_test_conformance=True)
    runner = session.create_coverage(coverage)
    root = tmp_path / 'workload'
    root.mkdir()
    sentinel = root / 'outside'
    sentinel.write_bytes(b'unchanged')
    original = launch.run_worker_spec
    launches = []

    def recording_supervisor(spec, *args, **kwargs):
        launches.append(spec)
        return original(spec, *args, **kwargs)

    try:
        runner.start()
        with patch.object(launch, 'run_worker_spec', recording_supervisor):
            with scoped_portable_coverage_adapter(session, cap):
                result, _ = run_portable_worker_conformance(root, case, probe_path=sentinel)
        runner.stop()
        runner.save()
        assert launch.run_worker_spec is original
        assert len(launches) == 1
        assert launches[0].argv[1:3] == CONFORMANCE_COMMAND
        assert launches[0].environment['COVERAGE_CHILD_REGISTRATION_TOKEN'] in cap.registered_tokens
        assert result.waited and result.process_group_cleaned
        assert not list((root / 'workspace').iterdir())
        assert sentinel.read_bytes() == b'unchanged'
        if status is None:
            assert result.synthesized_terminal
            assert session.measurement_errors
            with pytest.raises(RuntimeError, match='coverage measurement failed'):
                session.combine(runner)
        else:
            assert result.terminal['status'] == status
            if case.startswith('authority:'):
                assert result.terminal['error_category'] == 'unsupported_capability'
            if case.startswith('receipt:'):
                snapshot = result.terminal['portable_snapshot']
                assert snapshot['receipt'] is None
                assert snapshot['receipt_status'] == 'unavailable'
                assert snapshot['receipt_diagnostic'] == 'write_failed'
            assert not session.measurement_errors
            data = session.combine(runner).get_data()
            worker = str(ROOT / 'src/main/python/repomap_kg/coordinator/portable_worker.py')
            assert data.lines(worker)
            assert data.arcs(worker)
    finally:
        runner.stop()
        session.cleanup()


def test_conformance_paths_never_expand_production_and_invalid_launches_refuse(tmp_path):
    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / 'measure', suite='int')
    cap = session.issue_portable_capability(allow_test_conformance=True)
    seen = []
    adapter = make_portable_worker_spec_adapter(lambda *a, **k: seen.append(a), cap, session)
    paths = (ROOT / 'src/test/support/python', ROOT / 'src/main/python')
    spec = WorkerLaunchSpec(
        argv=(sys.executable, *CONFORMANCE_COMMAND, '--case', 'failure:artifact_missing',
              '--capability', 'fixture', '--job-id', 'job-1', '--attempt', '1'),
        environment={'PYTHONPATH': os.pathsep.join(map(str, paths))}, cwd=tmp_path,
    )
    try:
        production = replace(spec, argv=(sys.executable, *cap.portable_command))
        with pytest.raises(CapabilityContainmentError):
            adapter(production, {}, object())
        with pytest.raises(CapabilityValidationError):
            adapter(replace(spec, argv=(sys.executable, '-m', 'unapproved')), {}, object())
        with pytest.raises(CapabilityValidationError):
            adapter(replace(spec, argv=(*spec.argv, '--unexpected')), {}, object())
        with pytest.raises(CapabilityValidationError):
            adapter(replace(spec, environment={**spec.environment, 'COVERAGE_FILE': 'foreign'}), {}, object())
        cap.conformance_commitment = 'mismatched'
        with pytest.raises(CapabilityValidationError, match='commitment'):
            adapter(spec, {}, object())
        assert not seen
    finally:
        session.cleanup()


def test_canonical_production_launch_through_original_supervisor_is_measured(tmp_path):
    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path / 'measure', suite='int')
    cap = session.issue_portable_capability()
    runner = session.create_coverage(coverage)
    original_command = launch._run_portable_worker_command
    observed = []

    def canonical_command(*args, **kwargs):
        kwargs.update(module='repomap_kg.coordinator.portable_worker', module_arguments=(), python_paths=())
        return original_command(*args, **kwargs)

    original_supervisor = launch.run_worker_spec

    def record(spec, *args, **kwargs):
        observed.append(spec)
        return original_supervisor(spec, *args, **kwargs)

    root = tmp_path / 'workload'
    root.mkdir()
    try:
        runner.start()
        with patch.object(launch, '_run_portable_worker_command', canonical_command):
            with patch.object(launch, 'run_worker_spec', record):
                with scoped_portable_coverage_adapter(session, cap):
                    result, _ = run_portable_worker_conformance(root, 'failure:artifact_missing')
        runner.stop()
        runner.save()
        assert result.terminal['status'] == 'succeeded'
        assert result.waited and result.process_group_cleaned
        assert observed[0].argv[1:3] == cap.portable_command
        assert str(ROOT / 'src/test/support/python') not in observed[0].environment['PYTHONPATH']
        assert not session.measurement_errors
        data = session.combine(runner).get_data()
        assert data.arcs(str(ROOT / 'src/main/python/repomap_kg/coordinator/portable_worker.py'))
    finally:
        runner.stop()
        session.cleanup()


def test_direct_capability_requires_explicit_test_conformance_opt_in(tmp_path):
    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path, suite='int')
    try:
        cap = session.issue_portable_capability()
        assert cap.conformance_root is None
        assert cap.paths_for_command(cap.portable_command) == cap.permitted_python_paths
        with pytest.raises(CapabilityValidationError, match='invalid worker command identity'):
            cap.paths_for_command(CONFORMANCE_COMMAND)
    finally:
        session.cleanup()


@pytest.mark.parametrize('suite', ['int', 'staging'])
def test_canonical_test_session_explicitly_binds_conformance(tmp_path, suite):
    session = ChildCoverageSession(coverage_module=coverage, scratch_dir=tmp_path, suite=suite)
    try:
        with session:
            cap = session._portable_capability
            assert cap.paths_for_command(CONFORMANCE_COMMAND)[0] == ROOT / 'src/test/support/python'
            assert ROOT / 'src/test/support/python' not in cap.paths_for_command(cap.portable_command)
    finally:
        session.cleanup()


def _run_victim_trial(tmp_path, role, owner, victim_fields=None):
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    (source / "uncovered.py").write_text("VALUE = 1\n")
    session = ChildCoverageSession(
        coverage_module=coverage, scratch_dir=tmp_path / "measure", source_root=source, suite="int"
    )
    with session:
        runner = session.create_coverage(coverage)
        runner.start()
        env = dict(os.environ)
        if role:
            env["COVERAGE_CHILD_LAUNCH_ROLE"] = role
        if owner:
            env["COVERAGE_CHILD_TEST_OWNER"] = owner
        result = subprocess.run(
            [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"],
            env=env,
            capture_output=True,
        )
        assert result.returncode == -15
        records = read_registered_children(session.child_manifest_dir, session.session_dir.name, "int")
        pid, _ = next(iter(records.items()))
        if victim_fields is not None:
            defaults = {
                "pid": str(pid), "ppid": str(os.getpid()), "invocation": session.session_dir.name,
                "suite": "int", "owner": owner or "", "case_id": "c1", "parent_action": "KILL",
                "exitcode": "-15", "backend_disappeared": "1", "descriptor_closed": "1",
                "process_cleaned": "1",
            }
            defaults.update(victim_fields)
            content = "\n".join(f"{k}={v}" for k, v in defaults.items()) + "\n"
            (session.child_manifest_dir / f"{pid}.victim").write_text(content, encoding="utf-8")
        runner.stop()
        runner.save()
        return session, runner


def test_intentional_victim_verified_receipt_and_diagnostic_snapshot(tmp_path):
    session, runner = _run_victim_trial(tmp_path, "intentional-victim", COV5G_OWNER_SHA256, {})
    try:
        session.combine(runner)
        snaps = [s for s in session.diagnostic_snapshots if s.file_type == "intentional_victim"]
        assert len(snaps) == 1
        snap = snaps[0]
        assert snap.reader_status == "intentional_victim_receipt_verified"
        assert snap.termination_outcome == "intentional_victim_terminated"
        assert snap.launch_role == "intentional-victim"
        assert snap.test_owner == COV5G_OWNER_SHA256
    finally:
        session.cleanup()


@pytest.mark.parametrize("role,owner,fields", [
    ("inherited-python", None, None),
    ("intentional-victim", "a" * 64, {"owner": "a" * 64}),
    ("intentional-victim", COV5G_OWNER_SHA256, None),
    ("intentional-victim", COV5G_OWNER_SHA256, {"exitcode": "0"}),
    ("intentional-victim", COV5G_OWNER_SHA256, {"exitcode": "1"}),
    ("intentional-victim", COV5G_OWNER_SHA256, {"backend_disappeared": "0"}),
    ("intentional-victim", COV5G_OWNER_SHA256, {"descriptor_closed": "0"}),
    ("intentional-victim", COV5G_OWNER_SHA256, {"process_cleaned": "0"}),
])
def test_victim_failure_cases_fail_closed(tmp_path, role, owner, fields):
    session, runner = _run_victim_trial(tmp_path, role, owner, fields)
    try:
        with pytest.raises(RuntimeError, match="child terminal receipt is incomplete"):
            session.combine(runner)
    finally:
        session.cleanup()


def test_graceful_child_and_intentional_victim_coexist(tmp_path):
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    mod = source / "worker_mod.py"
    mod.write_text("def worker_job():\n    return 42\n")
    session = ChildCoverageSession(
        coverage_module=coverage, scratch_dir=tmp_path / "measure", source_root=source, suite="int"
    )
    with session:
        runner = session.create_coverage(coverage)
        runner.start()

        # 1. Graceful child produces normal coverage shard
        graceful_env = dict(os.environ)
        res_graceful = subprocess.run(
            [sys.executable, "-c", f"import sys; sys.path.insert(0, '{source}'); import worker_mod; assert worker_mod.worker_job() == 42"],
            env=graceful_env,
            capture_output=True,
        )
        assert res_graceful.returncode == 0

        # 2. Intentional victim child terminates abruptly with verified receipt
        victim_env = dict(os.environ)
        victim_env["COVERAGE_CHILD_LAUNCH_ROLE"] = "intentional-victim"
        victim_env["COVERAGE_CHILD_TEST_OWNER"] = COV5G_OWNER_SHA256
        res_victim = subprocess.run(
            [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"],
            env=victim_env,
            capture_output=True,
        )
        assert res_victim.returncode == -15

        records = read_registered_children(session.child_manifest_dir, session.session_dir.name, "int")
        victim_pid = next(pid for pid, r in records.items() if r.get("role") == "intentional-victim")
        victim_content = (
            f"pid={victim_pid}\n"
            f"ppid={os.getpid()}\n"
            f"invocation={session.session_dir.name}\n"
            f"suite=int\n"
            f"owner={COV5G_OWNER_SHA256}\n"
            f"case_id=c1\n"
            f"parent_action=KILL\n"
            f"exitcode=-15\n"
            f"backend_disappeared=1\n"
            f"descriptor_closed=1\n"
            f"process_cleaned=1\n"
        )
        (session.child_manifest_dir / f"{victim_pid}.victim").write_text(victim_content, encoding="utf-8")

        runner.stop()
        runner.save()
        try:
            combined = session.combine(runner)
            data = combined.get_data()
            assert data.lines(str(mod))
            snaps = [s for s in session.diagnostic_snapshots if s.file_type == "intentional_victim"]
            assert len(snaps) == 1
            assert snaps[0].reader_status == "intentional_victim_receipt_verified"
        finally:
            session.cleanup()
