"""Real tiny child controls for prelaunch abrupt accounting and strict measurement."""

import os
from pathlib import Path
import subprocess
import sys

import coverage
import pytest

from runner_abrupt_evidence import AbruptRunnerContext
from runner_coverage import ChildCoverageSession
from runner_integration_obligations import AbruptDeclaration

NODE = "src/test/int/python/fixture.int.test.py::test_abrupt"
SOURCE = "a" * 64


def context(verify=lambda: None):
    declaration = AbruptDeclaration(NODE, "tiny-abrupt", 17, "checkpoint", "unit-child")
    result = AbruptRunnerContext(nodeids=(NODE,), invocation_id="b" * 32,
        source_sha256=SOURCE, verify_source=verify, declarations=(declaration,))
    result.select_test(NODE)
    return result


def test_real_abrupt_child_has_observed_start_exit_and_no_measurement(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.py").write_text("VALUE = 1\n")
    ctx = context()
    with ChildCoverageSession(coverage_module=coverage, source_root=source) as session:
        with ctx.bind_session(session):
            launch = ctx.begin("tiny-abrupt")
            process = launch.launched(subprocess.Popen(
                [sys.executable, "-c", "import os; print('checkpoint', flush=True); os._exit(17)"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env=ctx.child_environment()))
            try:
                stdout, stderr = process.communicate(timeout=5)
                assert stderr == ""
                launch.observed_checkpoint(stdout.strip())
                record = launch.settle(process.returncode, cleanup=process.poll() is not None)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
            assert record["pid"] == process.pid
            assert record["parent_pid"] == os.getpid()
            assert record["started_ns"] <= record["settled_ns"]
            assert record["measurement"] == "unavailable"
            assert not list(session.child_manifest_dir.iterdir())
            assert not list(session.data_dir.iterdir())
    session.cleanup()


def test_real_measured_child_retains_lines_arcs_and_missing_shard_refusal(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    sample = source / "sample.py"
    sample.write_text("def choose(flag):\n    if flag:\n        return 1\n    return 2\n")
    session = ChildCoverageSession(coverage_module=coverage, source_root=source)
    try:
        with session:
            runner = session.create_coverage()
            runner.start()
            environment = dict(os.environ)
            environment["PYTHONPATH"] += os.pathsep + str(source)
            child = subprocess.run([sys.executable, "-c", "import sample; sample.choose(True)"],
                env=environment, capture_output=True, text=True, timeout=5)
            runner.stop()
            runner.save()
            assert child.returncode == 0, child.stderr
            combined = session.combine(runner)
            data = combined.get_data()
            assert 3 in data.lines(str(sample))
            assert 4 not in data.lines(str(sample))
            assert (2, 3) in data.arcs(str(sample))
            assert (2, 4) not in data.arcs(str(sample))
        # Separate invocation: an orderly measured child with its real shard
        # removed must fail, even when workload and sibling data passed.
        missing = ChildCoverageSession(coverage_module=coverage, source_root=source)
        try:
            with missing:
                parent = missing.create_coverage()
                parent.start()
                env = dict(os.environ)
                env["PYTHONPATH"] += os.pathsep + str(source)
                completed = subprocess.run([sys.executable, "-c", "import sample; sample.choose(True)"],
                    env=env, capture_output=True, timeout=5)
                parent.stop()
                parent.save()
                assert completed.returncode == 0
                child_shards = list(missing.child_manifest_dir.glob("*.shard"))
                assert len(child_shards) == 1
                Path(child_shards[0].read_text()).unlink()
                with pytest.raises(RuntimeError):
                    missing.combine(parent)
        finally:
            missing.cleanup()
    finally:
        session.cleanup()


@pytest.mark.parametrize("returncode,checkpoint,cleanup", [
    (0, "checkpoint", True), (1, "checkpoint", True),
    (-9, "checkpoint", True), (17, None, True), (17, "checkpoint", False),
])
def test_unproved_abrupt_result_is_not_accepted(returncode, checkpoint, cleanup):
    from types import SimpleNamespace
    ctx = context()
    launch = ctx.begin("tiny-abrupt")
    launch.launched(SimpleNamespace(pid=123))
    if checkpoint:
        launch.observed_checkpoint(checkpoint)
    with pytest.raises(RuntimeError):
        launch.settle(returncode, cleanup=cleanup)
    assert not ctx.records


def test_source_drift_and_arbitrary_role_or_duplicate_launch_refused():
    ctx = context()
    with pytest.raises(RuntimeError):
        ctx.begin("arbitrary")
    ctx.begin("tiny-abrupt")
    with pytest.raises(RuntimeError):
        ctx.begin("tiny-abrupt")
    with pytest.raises(RuntimeError):
        ctx.select_test(NODE + "[case]")
    def drift():
        raise RuntimeError("source mismatch")
    with pytest.raises(RuntimeError, match="source mismatch"):
        context(drift).begin("tiny-abrupt")


def test_go_observer_records_real_supervisor_termination_and_restores_owners(tmp_path):
    from repomap_kg.extractors.languages import go_protocol as owner
    from repomap_test_support.staging_abrupt_launch import observe_go_hang
    from runner_integration_obligations import GO_HANG_NODE
    ctx = AbruptRunnerContext(nodeids=(GO_HANG_NODE,), invocation_id="b" * 32,
        source_sha256=SOURCE, verify_source=lambda: None)
    ctx.select_test(GO_HANG_NODE)
    command = (sys.executable, "-c",
        "import sys,json,time; sys.stdin.readline(); "
        "print(json.dumps(dict(protocol_version=1,type='file_end',sequence=0,"
        "path='tiny.go',observation_count=0,diagnostic_count=0,truncated=False)),flush=True); "
        "time.sleep(5)")
    original = (owner.subprocess, owner.threading, owner.validate_go_protocol_message)
    with ctx.bind_session(None), observe_go_hang(command):
        with pytest.raises(owner.GoProtocolError, match="did not exit"):
            list(owner.iter_go_protocol_observations(
                tmp_path, ["tiny.go"], command, cleanup_timeout=0.2))
    assert (owner.subprocess, owner.threading, owner.validate_go_protocol_message) == original
    record = ctx.records[GO_HANG_NODE]
    assert record["returncode"] == -15
    assert record["checkpoint"] == "file_end"
    assert record["cleanup"] is True


def test_spawn_configuration_restores_ambient_values_after_launch_failure(monkeypatch):
    monkeypatch.setenv("COVERAGE_PROCESS_START", "unit-owned-placeholder")
    monkeypatch.setenv("PYTHONPATH", "unit-owned-path")
    before = dict(os.environ)
    ctx = context()
    with pytest.raises(RuntimeError, match="spawn failure"):
        with ctx.spawn_environment():
            assert "COVERAGE_PROCESS_START" not in os.environ
            assert os.environ["PYTHONPATH"] == before["PYTHONPATH"]
            raise RuntimeError("spawn failure")
    assert dict(os.environ) == before


def test_declared_conformance_fault_bypasses_only_its_prelaunch_registration(tmp_path):
    from repomap_test_support.portable_worker_conformance import run_portable_worker_conformance
    from runner_integration_obligations import SEAM_NODE
    ctx = AbruptRunnerContext(nodeids=(SEAM_NODE,), invocation_id="b" * 32,
        source_sha256=SOURCE, verify_source=lambda: None)
    ctx.select_test(SEAM_NODE)
    session = ChildCoverageSession(coverage_module=coverage, suite="int")
    root = tmp_path / "workload"
    root.mkdir()
    try:
        with session, ctx.bind_session(session):
            runner = session.create_coverage()
            runner.start()
            try:
                abrupt, _ = run_portable_worker_conformance(root, "crash:after-materialization")
                assert abrupt.returncode == 17 and abrupt.process_group_cleaned
                assert not session._portable_capability.registered_tokens
                ordinary_root = tmp_path / "ordinary"
                ordinary_root.mkdir()
                ordinary, _ = run_portable_worker_conformance(ordinary_root, "failure:artifact_missing")
                assert ordinary.terminal["status"] == "failed"
                assert len(session._portable_capability.registered_tokens) == 1
            finally:
                runner.stop()
                runner.save()
            assert ctx.records[SEAM_NODE]["returncode"] == 17
            assert not session.measurement_errors
            # Only ordinary A data exists; this isolated session is never M.
            assert session.combine(runner).get_data().measured_files()
            assert not list((root / "workspace").iterdir())
    finally:
        session.cleanup()


def test_two_sessions_restore_the_enclosing_collector(tmp_path):
    enclosing = coverage.Coverage.current()
    for leg in ("M", "A"):
        source = tmp_path / leg
        source.mkdir()
        (source / "sample.py").write_text("VALUE = 1\n")
        session = ChildCoverageSession(coverage_module=coverage, source_root=source)
        try:
            with session:
                runner = session.create_coverage()
                assert isinstance(runner, coverage.Coverage)
                runner.start()
                assert coverage.Coverage.current() is runner
                runner.stop()
                runner.save()
            assert coverage.Coverage.current() is enclosing
        finally:
            session.cleanup()
        assert coverage.Coverage.current() is enclosing


def test_old_descendant_artifact_refuses_before_any_launch(tmp_path):
    from repomap_test_support.staging_abrupt_launch import observe_scale28_crash
    (tmp_path / "descendant.launch.json").write_text('{}')
    with pytest.raises(RuntimeError, match="predates"):
        with observe_scale28_crash(tmp_path):
            pytest.fail("old artifact must refuse before launch")
