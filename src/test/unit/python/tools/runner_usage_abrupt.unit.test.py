"""Unit contracts for exact usage abrupt evidence (no process injection)."""

from __future__ import annotations

from dataclasses import asdict, replace
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from common_lore_index.coordinator._worker_launch import WorkerLaunchSpec
import sys

import pytest

from runner_abrupt_evidence import AbruptRunnerContext, UsageAbruptLaunch
from runner_integration_obligations import AbruptDeclaration
from common_lore_index.coordinator._usage_observation import UsageSettlement


NODE = (
    "src/test/int/python/repomap_kg/coordinator/usage_reaper.int.test.py"
    "::test_sigkill_still_yields_rusage_and_a_negative_return_code"
)
DECLARATION = AbruptDeclaration(
    NODE, "usage-self-sigkill", -9, "pre_hello", "native.launch",
    "fixture._prepare", "native.reaper", "native.cleanup", "sigkill",
)


def _context(verify=lambda: None) -> AbruptRunnerContext:
    context = AbruptRunnerContext(
        nodeids=(NODE,), invocation_id="i" * 32, source_sha256="s" * 64,
        verify_source=verify, declarations=(DECLARATION,),
    )
    context.select_test(NODE)
    return context


def _facts(launched_pid: int, returncode: int = -9, **overrides: object) -> UsageSettlement:
    values: dict[str, Any] = dict(
        pid=launched_pid, returncode=returncode, waited=True,
        process_group_cleaned=True, readers_closed=True, streams_closed=True,
        proven=True,
    )
    values.update(overrides)
    return UsageSettlement(**values)


def test_usage_observer_accepts_only_native_pid_and_immutable_settlement() -> None:
    context = _context()
    launch = context.begin_usage("usage-self-sigkill", "sigkill")
    assert isinstance(launch, UsageAbruptLaunch)
    launch.launched(321)
    launch.observed_checkpoint("pre_hello", 321)
    launch.settled(_facts(321))
    record = context.record_usage()
    assert record["pid"] == 321
    assert record["returncode"] == -9
    assert record["measurement"] == "unavailable"
    assert record["cleanup"] is True


@pytest.mark.parametrize("bad", (
    {"pid": 322},
    {"returncode": -15},
    {"process_group_cleaned": False},
    {"readers_closed": False},
    {"streams_closed": False},
    {"proven": False},
))
def test_usage_observer_rejects_wrong_identity_status_or_unproved_cleanup(bad) -> None:
    context = _context()
    launch = context.begin_usage("usage-self-sigkill", "sigkill")
    launch.launched(321)
    launch.observed_checkpoint("pre_hello", 321)
    with pytest.raises(RuntimeError, match="settlement is unproved"):
        launch.settled(_facts(321, **bad))
    assert not context.records


def test_usage_observer_rejects_checkpoint_pid_mismatch_and_missing_settlement() -> None:
    context = _context()
    launch = context.begin_usage("usage-self-sigkill", "sigkill")
    launch.launched(321)
    with pytest.raises(RuntimeError, match="checkpoint PID mismatch"):
        launch.observed_checkpoint("pre_hello", 322)
    with pytest.raises(RuntimeError, match="evidence is incomplete"):
        context.record_usage()
    assert not context.records


def test_mutable_or_incomplete_settlement_is_not_accepted() -> None:
    context = _context()
    launch = context.begin_usage("usage-self-sigkill", "sigkill")
    launch.launched(321)
    launch.observed_checkpoint("pre_hello", 321)
    with pytest.raises(RuntimeError, match="immutable native facts"):
        launch.settled(SimpleNamespace(**asdict(_facts(321))))
    assert not context.records

    launch.settled(_facts(321))
    launch.settlement = SimpleNamespace(**asdict(_facts(321, proven=False)))
    with pytest.raises(RuntimeError, match="immutable native facts"):
        context.record_usage()
    assert not context.records


def test_usage_selection_rejects_unknown_case_or_duplicate_launch() -> None:
    context = _context()
    with pytest.raises(RuntimeError, match="undeclared or repeated"):
        context.begin_usage("usage-self-sigkill", "block")
    context.begin_usage("usage-self-sigkill", "sigkill")
    with pytest.raises(RuntimeError, match="undeclared or repeated"):
        context.begin_usage("usage-self-sigkill", "sigkill")


def test_usage_selection_requires_population_and_owner_hash() -> None:
    bad_owner = replace(DECLARATION, owner_sha256="0" * 64)
    context = AbruptRunnerContext(
        nodeids=(NODE,), invocation_id="i" * 32, source_sha256="s" * 64,
        verify_source=lambda: None, declarations=(bad_owner,),
    )
    context.select_test(NODE)
    with pytest.raises(RuntimeError, match="undeclared or repeated"):
        context.begin_usage("usage-self-sigkill", "sigkill")

    outside = AbruptRunnerContext(
        nodeids=("different-node",), invocation_id="i" * 32, source_sha256="s" * 64,
        verify_source=lambda: None, declarations=(DECLARATION,),
    )
    outside.nodeid = NODE
    with pytest.raises(RuntimeError, match="undeclared or repeated"):
        outside.begin_usage("usage-self-sigkill", "sigkill")


def test_usage_environment_removes_coverage_and_owned_session_paths(tmp_path) -> None:
    context = _context()
    context.session = SimpleNamespace(
        session_dir=tmp_path / "session", bootstrap_dir=tmp_path / "bootstrap",
    )
    original = {
        "COVERAGE_PROCESS_START": "forbidden",
        "PYTHONPATH": ":".join((str(tmp_path / "session"), str(tmp_path / "src"), str(tmp_path / "bootstrap"))),
        "LANG": "C",
    }
    clean = context._usage_environment(original)
    assert "COVERAGE_PROCESS_START" not in clean
    assert clean["PYTHONPATH"] == str(tmp_path / "src")


def _usage_spec(root, case="sigkill", probe=None):
    args = ["--case", case]
    if probe is not None:
        args.extend(("--probe-path", str(probe)))
    args.extend(("--capability", str(root / "capability.json"), "--job-id", "job-usage", "--attempt", "1"))
    repo_root = Path(__file__).resolve().parents[5]
    return WorkerLaunchSpec(
        argv=(sys.executable, "-m", "repomap_test_support.usage_worker", *args),
        environment={
            "PYTHONPATH": os.pathsep.join((
                str(repo_root / "src/test/support/python"), str(repo_root / "src/main/python"),
            )),
            "COVERAGE_PROCESS_START": "forbidden",
        },
        cwd=root,
    )


def test_bind_session_calls_native_observer_and_records_sigkill(monkeypatch, tmp_path) -> None:
    import common_lore_index.coordinator._portable_worker_launch as owner

    context = _context()
    root = tmp_path
    spec = _usage_spec(root)
    result = SimpleNamespace(
        stderr="REPOMAP_ABRUPT_CHECKPOINT pre_hello 321\n",
        stderr_truncated=False,
    )
    calls = []

    def native(specification, identity, limits, **kwargs):
        calls.append((specification, kwargs))
        observer = kwargs["_usage_observer"]
        observer.launched(321)
        observer.settled(_facts(321))
        return result

    monkeypatch.setattr(owner, "run_worker_spec", native)
    with context.bind_session(None):
        received: object = owner.run_worker_spec(spec, {"job_id": "job-usage", "attempt": 1}, {}, collect_usage=True)
        assert received is result
    assert len(calls) == 1
    assert context.records[NODE]["returncode"] == -9
    assert "COVERAGE_PROCESS_START" not in calls[0][0].environment


def test_bind_session_preserves_no_result_keyboard_interrupt_and_records_native_facts(monkeypatch, tmp_path) -> None:
    import common_lore_index.coordinator._portable_worker_launch as owner

    context = _context()
    block_node = NODE.replace("test_sigkill_still_yields_rusage_and_a_negative_return_code",
                             "test_a_parent_interrupt_kills_the_whole_group_and_preserves_the_original")
    declaration = replace(DECLARATION, nodeid=block_node, role="usage-parent-interrupt",
                          launch_case="block", owner_sha256="")
    context = AbruptRunnerContext(
        nodeids=(block_node,), invocation_id="i" * 32, source_sha256="s" * 64,
        verify_source=lambda: None, declarations=(declaration,),
    )
    context.select_test(block_node)
    probe = tmp_path / "worker.pid"
    spec = _usage_spec(tmp_path, case="block", probe=probe)
    primary = KeyboardInterrupt("primary")

    def native(specification, identity, limits, **kwargs):
        observer = kwargs["_usage_observer"]
        observer.launched(321)
        observer.settled(_facts(321))
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, b"321\n")
        finally:
            os.close(descriptor)
        raise primary

    monkeypatch.setattr(owner, "run_worker_spec", native)
    with context.bind_session(None):
        with pytest.raises(KeyboardInterrupt, match="primary") as raised:
            owner.run_worker_spec(spec, {"job_id": "job-usage", "attempt": 1}, {}, collect_usage=True)
    assert raised.value is primary
    assert context.records[block_node]["cleanup"] is True


def test_bind_session_omits_record_when_block_witness_is_missing(monkeypatch, tmp_path) -> None:
    import common_lore_index.coordinator._portable_worker_launch as owner

    block_node = NODE.replace("test_sigkill_still_yields_rusage_and_a_negative_return_code",
                             "test_a_parent_interrupt_kills_the_whole_group_and_preserves_the_original")
    declaration = replace(DECLARATION, nodeid=block_node, role="usage-parent-interrupt",
                          launch_case="block", owner_sha256="")
    context = AbruptRunnerContext(
        nodeids=(block_node,), invocation_id="i" * 32, source_sha256="s" * 64,
        verify_source=lambda: None, declarations=(declaration,),
    )
    context.select_test(block_node)
    spec = _usage_spec(tmp_path, case="block", probe=tmp_path / "missing.pid")
    result = SimpleNamespace(stderr="", stderr_truncated=False)

    def native(specification, identity, limits, **kwargs):
        observer = kwargs["_usage_observer"]
        observer.launched(321)
        observer.settled(_facts(321))
        return result

    monkeypatch.setattr(owner, "run_worker_spec", native)
    with context.bind_session(None):
        with pytest.raises(RuntimeError, match="witness is invalid"):
            owner.run_worker_spec(spec, {"job_id": "job-usage", "attempt": 1}, {},
                                  collect_usage=True)
    assert not context.records


def test_bind_session_preserves_primary_when_record_verification_fails(monkeypatch, tmp_path) -> None:
    import common_lore_index.coordinator._portable_worker_launch as owner

    block_node = NODE.replace("test_sigkill_still_yields_rusage_and_a_negative_return_code",
                             "test_a_parent_interrupt_kills_the_whole_group_and_preserves_the_original")
    declaration = replace(DECLARATION, nodeid=block_node, role="usage-parent-interrupt",
                          launch_case="block", owner_sha256="")

    verification_calls = 0

    def drift() -> None:
        nonlocal verification_calls
        verification_calls += 1
        if verification_calls > 1:
            raise RuntimeError("source drift")

    context = AbruptRunnerContext(
        nodeids=(block_node,), invocation_id="i" * 32, source_sha256="s" * 64,
        verify_source=drift, declarations=(declaration,),
    )
    context.select_test(block_node)
    probe = tmp_path / "worker.pid"
    spec = _usage_spec(tmp_path, case="block", probe=probe)

    def native(specification, identity, limits, **kwargs):
        observer = kwargs["_usage_observer"]
        observer.launched(321)
        observer.settled(_facts(321))
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, b"321\n")
        finally:
            os.close(descriptor)
        raise KeyboardInterrupt("primary")

    monkeypatch.setattr(owner, "run_worker_spec", native)
    with context.bind_session(None):
        with pytest.raises(KeyboardInterrupt, match="primary") as raised:
            owner.run_worker_spec(spec, {"job_id": "job-usage", "attempt": 1}, {},
                                  collect_usage=True)
    assert raised.value.__notes__ == ["usage abrupt checkpoint evidence failure: RuntimeError"]
    assert not context.records


def test_bind_session_rejects_injected_observer_or_wrong_interpreter_before_native(monkeypatch, tmp_path) -> None:
    import common_lore_index.coordinator._portable_worker_launch as owner

    context = _context()
    called = []

    def native(*args, **kwargs):
        called.append(True)
        raise AssertionError("native callback should not run")

    monkeypatch.setattr(owner, "run_worker_spec", native)
    spec = _usage_spec(tmp_path)
    spec = replace(spec, argv=("/wrong/python", *spec.argv[1:]))
    with context.bind_session(None):
        with pytest.raises(RuntimeError, match="interpreter identity"):
            owner.run_worker_spec(spec, {"job_id": "job-usage", "attempt": 1}, {}, collect_usage=True)
        with pytest.raises(RuntimeError, match="observer authority cannot be overridden"):
            owner.run_worker_spec(replace(spec, argv=(sys.executable, *spec.argv[1:])),
                                  {"job_id": "job-usage", "attempt": 1}, {},
                                  collect_usage=True, _usage_observer=cast(Any, object()))
    assert not called
