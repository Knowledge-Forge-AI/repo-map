"""Scoped subject proof for measured usage routing; no collector or process is started."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import ast
import os
import sys
from typing import Any

import pytest

from common_lore_index.coordinator._usage_observation import UsageSettlement
from common_lore_index.coordinator._worker_launch import WorkerLaunchSpec
from runner_coverage_capability import (
    CapabilityContainmentError, CapabilityRefusalError, CapabilityValidationError,
    ChildCoverageCapability, compute_source_commitment,
)
from runner_portable_coverage import make_portable_worker_spec_adapter
from runner_usage_command import validate_usage_arguments, validate_usage_probe
from runner_usage_coverage import MeasuredUsageObserver, require_usage_settlement


class _ProcessObserver:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def observe_launch(self, **kwargs):
        self.calls.append(kwargs)


def _roots(tmp_path: Path):
    session = tmp_path / "session"
    session.mkdir(mode=0o700)
    for name in ("bootstrap", "child_procs", "shards"):
        (session / name).mkdir(mode=0o700)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    return session, session / "child_procs", session / "shards", private


def _observer(tmp_path: Path):
    session_dir, manifest, data, _ = _roots(tmp_path)
    session = SimpleNamespace(
        process_observer=_ProcessObserver(), bootstrap_capability=object(),
    )
    cap = SimpleNamespace(invocation_id="inv", session_dir=session_dir,
                          child_manifest_dir=manifest, data_dir=data, launched_pids={})
    observer = MeasuredUsageObserver(
        session=session, capability=cap, token="a" * 32,
        environment={"PYTHONPATH": "/support:/main", "COVERAGE_CHILD_TEST_OWNER": "b" * 64},
        identity={"job_id": "job", "attempt": 1},
        job_context={"argv": (sys.executable, "-m", "repomap_test_support.usage_worker")},
    )
    return observer, session, cap


class _SubjectCapability(ChildCoverageCapability):
    """Typed test subject with inert capability gates and real adapter routing."""

    def __init__(self, session: Any, session_dir: Path, manifest: Path, data: Path) -> None:
        super().__init__(
            session=session,
            invocation_id="inv",
            suite="int",
            source_commitment="rev",
            session_dir=session_dir,
            config_file=session_dir / "coverage.rc",
            bootstrap_dir=session_dir / "bootstrap",
            child_manifest_dir=manifest,
            data_dir=data,
            config_sha256="",
            bootstrap_sha256="",
            expected_config_bytes=b"",
            expected_bootstrap_bytes=b"",
            path_identities={},
            permitted_python_paths=(Path("/main"),),
            portable_command=("-m", "common_lore_index.coordinator.portable_worker"),
        )

    def validate_for_launch(self) -> None:
        return None

    def register_prelaunch_child(self, token: str | None = None) -> str:
        value = token or "a" * 32
        self.registered_tokens.add(value)
        return value

    def paths_for_command(self, command: tuple[str, ...]) -> tuple[Path, ...]:
        if command == ("-m", "repomap_test_support.usage_worker"):
            return (Path("/support"), Path("/main"))
        return (Path("/main"),)

    def validate_for_accept(self, token: str, pid: int | None = None) -> Path:
        return self.data_dir / "shard"


def _subject(tmp_path: Path):
    session_dir, manifest, data, _ = _roots(tmp_path)
    session = SimpleNamespace(process_observer=_ProcessObserver(), bootstrap_capability=object())
    return session, _SubjectCapability(session, session_dir, manifest, data)


def test_native_callback_settlement_is_strict_and_preserves_metadata(tmp_path: Path) -> None:
    observer, session, cap = _observer(tmp_path)
    observer.launched(41)
    observer.settled(UsageSettlement(41, 0, True, True, True, True, True))
    result = SimpleNamespace(returncode=0, waited=True, process_group_cleaned=True)
    require_usage_settlement(observer, result)
    assert cap.launched_pids == {"a" * 32: 41}
    launch = session.process_observer.calls[0]
    assert launch["host_pid"] == 41 and launch["ppid"] == os.getpid()
    assert tuple(launch["argv"])[1:3] == ("-m", "repomap_test_support.usage_worker")
    assert launch["env"]["PYTHONPATH"] == "/support:/main"


@pytest.mark.parametrize("facts", (
    UsageSettlement(42, 0, True, True, True, True, False),
    UsageSettlement(41, 0, True, False, True, True, False),
))
def test_incomplete_or_wrong_settlement_fails_closed(tmp_path: Path, facts: UsageSettlement) -> None:
    observer, _, _ = _observer(tmp_path)
    observer.launched(41)
    with pytest.raises(CapabilityValidationError):
        observer.settled(facts)
        require_usage_settlement(observer, SimpleNamespace(returncode=0, waited=True,
                                                          process_group_cleaned=True))


def test_duplicate_settlement_is_refused(tmp_path: Path) -> None:
    observer, _, _ = _observer(tmp_path)
    observer.launched(41)
    facts = UsageSettlement(41, 0, True, True, True, True, True)
    observer.settled(facts)
    with pytest.raises(CapabilityValidationError, match="duplicated"):
        observer.settled(facts)


def test_settlement_status_mismatch_is_refused(tmp_path: Path) -> None:
    observer, _, _ = _observer(tmp_path)
    observer.launched(41)
    observer.settled(UsageSettlement(41, 0, True, True, True, True, True))
    with pytest.raises(CapabilityValidationError, match="synchronously reaped"):
        require_usage_settlement(
            observer, SimpleNamespace(returncode=1, waited=True, process_group_cleaned=True),
        )


def test_settlement_subclass_is_not_native_frozen_type(tmp_path: Path) -> None:
    class ForeignSettlement(UsageSettlement):
        pass

    observer, _, _ = _observer(tmp_path)
    observer.launched(41)
    with pytest.raises(CapabilityValidationError, match="unknown type"):
        observer.settled(ForeignSettlement(41, 0, True, True, True, True, True))


def test_usage_argument_probe_and_root_boundaries_are_closed(tmp_path: Path) -> None:
    session, manifest, data, private = _roots(tmp_path)
    with pytest.raises(CapabilityValidationError, match="forbidden"):
        validate_usage_arguments(("--case", "nominal", "--probe-path", str(private / "p"), "--capability", "/c", "--job-id", "j", "--attempt", "1"), measured_only=False)
    probe = private / "p"
    assert validate_usage_probe(probe, case="block", session_dir=session, child_manifest_dir=manifest, data_dir=data) == probe
    standalone = private / "standalone"
    assert validate_usage_probe(standalone, case="block") == standalone
    assert validate_usage_arguments(
        ("--case", "block", "--probe-path", str(standalone), "--capability", "/c",
         "--job-id", "j", "--attempt", "1"), measured_only=False,
    ) == ("block", standalone)
    probe.write_text("foreign", encoding="ascii")
    with pytest.raises(CapabilityContainmentError, match="absent"):
        validate_usage_probe(probe, case="block")


def test_usage_unknown_case_and_ambient_coverage_are_rejected() -> None:
    with pytest.raises(CapabilityValidationError, match="not admitted"):
        validate_usage_arguments(("--case", "arbitrary", "--capability", "/c", "--job-id", "j", "--attempt", "1"))


def test_adapter_subject_forwards_native_observer_without_factory(monkeypatch, tmp_path: Path) -> None:
    session, cap = _subject(tmp_path)
    seen = {}
    def fake_prepare(base, **kwargs):
        env = dict(base)
        env.update(kwargs.get("extra_env") or {})
        return env
    monkeypatch.setattr("runner_coverage_execution.prepare_child_coverage_environment", fake_prepare)
    def original(spec, identity, limits, **kwargs):
        seen.update(kwargs)
        kwargs["_usage_observer"].launched(51)
        kwargs["_usage_observer"].settled(UsageSettlement(51, 0, True, True, True, True, True))
        return SimpleNamespace(returncode=0, waited=True, process_group_cleaned=True)
    adapter = make_portable_worker_spec_adapter(original, cap, session)
    spec = WorkerLaunchSpec(
        argv=(sys.executable, "-m", "repomap_test_support.usage_worker", "--case", "nominal", "--capability", "/cap", "--job-id", "job", "--attempt", "1"),
        environment={"PYTHONPATH": "/support:/main"},
        cwd=tmp_path,
    )
    with pytest.raises(CapabilityValidationError, match="requires collect_usage"):
        adapter(spec, {"job_id": "job", "attempt": 1}, {})
    adapter(spec, {"job_id": "job", "attempt": 1}, {}, collect_usage=True)
    assert seen["collect_usage"] is True and "_launch_process" not in seen
    assert session.process_observer.calls[0]["host_pid"] == 51

    bad = WorkerLaunchSpec(spec.argv, {"PYTHONPATH": "/support:/main", "COVERAGE_BAD": "1"}, tmp_path)
    with pytest.raises(CapabilityValidationError, match="ambient coverage"):
        adapter(bad, {"job_id": "job", "attempt": 1}, {}, collect_usage=True)


def test_adapter_subject_accepts_existing_production_collect_usage_opt_in(monkeypatch, tmp_path: Path) -> None:
    session, cap = _subject(tmp_path)
    seen = {}
    def fake_prepare(base, **kwargs):
        env = dict(base)
        env.update(kwargs.get("extra_env") or {})
        return env
    monkeypatch.setattr("runner_coverage_execution.prepare_child_coverage_environment", fake_prepare)
    def original(spec, identity, limits, **kwargs):
        seen.update(kwargs)
        kwargs["_usage_observer"].launched(52)
        kwargs["_usage_observer"].settled(UsageSettlement(52, 0, True, True, True, True, True))
        return SimpleNamespace(returncode=0, waited=True, process_group_cleaned=True)
    adapter = make_portable_worker_spec_adapter(original, cap, session)
    spec = WorkerLaunchSpec(
        argv=(sys.executable, "-m", "common_lore_index.coordinator.portable_worker", "--capability", "/cap", "--job-id", "job", "--attempt", "1"),
        environment={"PYTHONPATH": "/main"},
        cwd=tmp_path,
    )
    adapter(spec, {"job_id": "job", "attempt": 1}, {}, collect_usage=True)
    assert seen["collect_usage"] is True and "_launch_process" not in seen
    assert session.process_observer.calls[0]["host_pid"] == 52


def test_real_command_gate_requires_committed_test_authority_and_exact_roots(tmp_path: Path) -> None:
    _, cap = _subject(tmp_path)
    command = ("-m", "repomap_test_support.usage_worker")
    # Exercise the actual gate, rather than the subject's routing override.
    select = ChildCoverageCapability.paths_for_command
    with pytest.raises(CapabilityRefusalError, match="test-conformance authority"):
        select(cap, command)
    root = Path(__file__).resolve().parents[5]
    support, product = root / "src/test/support/python", root / "src/main/python"
    cap.conformance_root = support
    cap.conformance_commitment = compute_source_commitment(support)
    cap.permitted_python_paths = (product,)
    assert select(cap, command) == (support, product)
    cap.conformance_commitment = "foreign"
    with pytest.raises(CapabilityValidationError, match="source commitment"):
        select(cap, command)
    cap.conformance_commitment = compute_source_commitment(support)
    cap.permitted_python_paths = (tmp_path,)
    with pytest.raises(CapabilityContainmentError, match="product source root"):
        select(cap, command)
    with pytest.raises(CapabilityValidationError, match="command identity"):
        select(cap, ("-m", "arbitrary.module"))


def test_closed_fixture_context_keeps_exact_refusal_and_collector_lifetime() -> None:
    from ci.python_retention_owner_capability import SOURCE
    from ci.python_retention_owner_contract import validate_owner_context

    owner = "src/test/unit/python/tools/test_runner_coverage_capability.unit.test.py"
    root = Path(__file__).resolve().parents[5]
    validate_owner_context(owner, ast.parse((root / owner).read_text()))
    for changed in (
        SOURCE.replace("repomap_test_support.usage_worker", "arbitrary.module"),
        SOURCE.replace("cov.stop()", "pass"),
    ):
        with pytest.raises(ValueError, match="owner context differs"):
            validate_owner_context(owner, ast.parse(changed))
