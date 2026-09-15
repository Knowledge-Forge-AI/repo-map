"""Focused replacement-coordinator readiness contract tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from repomap_kg.coordinator.limits import (
    DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS,
    DEFAULT_LIMITS,
)
from tools.system.config import SystemTestError
from tools.system.replacement_readiness import (
    _health_is_ready,
    _is_new_owner,
    wait_for_replacement_coordinator,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _Timer:
    def __init__(self, clock: _Clock, available_seconds: float) -> None:
        self.clock = clock
        self.deadline = available_seconds

    def remaining_for_test(self) -> float:
        remaining = self.deadline - self.clock.now
        if remaining <= 0:
            raise AssertionError("readiness consumed the inherited cleanup reserve")
        return remaining

    def clamp_timeout(self, requested_timeout: float) -> float:
        return min(requested_timeout, self.remaining_for_test())


def _result(
    returncode: int = 0,
    *,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _running_ps() -> str:
    return json.dumps(
        {"Service": "coordinator", "State": "running", "ID": "container-1"}
    ) + "\n"


def test_replacement_may_use_full_startup_allowance_then_become_ready(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    timer = _Timer(clock, available_seconds=120.0)
    plan = type("Plan", (), {"env_file": tmp_path / "missing"})()
    health_calls = 0

    def compose(_compose_dir, args, **_kwargs):
        nonlocal health_calls
        if "coordinator-health" in args:
            health_calls += 1
            if clock.now <= DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS:
                return _result(1, stderr="ERROR: unavailable")
            return _result(stdout='{"result":"ready","health":{"status":"ready"}}')
        if args[:3] == ["ps", "--all", "--format"]:
            return _result(stdout=_running_ps())
        raise AssertionError(f"unexpected Compose call: {args}")

    identity = wait_for_replacement_coordinator(
        tmp_path,
        plan,
        timer,
        initial_instance_id="initial-instance",
        initial_singleton_epoch=11,
        env={},
        run_compose=compose,
        owner_probe=lambda *_args: {
            "instance_id": "replacement-instance",
            "fencing_epoch": 12,
            "status": "active",
        },
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert (
        DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS
        > DEFAULT_LIMITS.graph_lease_duration_seconds
        > 15
    )
    assert clock.now > DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS
    assert clock.now < (
        DEFAULT_COORDINATOR_STARTUP_WAIT_SECONDS
        + DEFAULT_LIMITS.graph_lease_duration_seconds
    )
    assert identity == {
        "instance_id": "replacement-instance",
        "fencing_epoch": 12,
        "status": "active",
    }


def test_stale_ready_marker_is_not_consulted_for_replacement_identity(
    tmp_path: Path,
) -> None:
    (tmp_path / "system_pause_trigger.ready").write_text(
        "job_id=stale\nattempt=1\n", encoding="utf-8"
    )
    clock = _Clock()
    timer = _Timer(clock, available_seconds=30.0)
    plan = type("Plan", (), {"env_file": tmp_path / "missing"})()
    owners = iter(
        (
            {"instance_id": "initial-instance", "fencing_epoch": 11, "status": "active"},
            {"instance_id": "replacement-instance", "fencing_epoch": 12, "status": "active"},
        )
    )
    health_calls = 0

    def compose(_compose_dir, args, **_kwargs):
        nonlocal health_calls
        if "coordinator-health" in args:
            health_calls += 1
            return _result(stdout='{"result":"ready","health":{"status":"ready"}}')
        if args[:3] == ["ps", "--all", "--format"]:
            return _result(stdout=_running_ps())
        raise AssertionError(f"unexpected Compose call: {args}")

    with patch.object(
        Path,
        "read_text",
        side_effect=AssertionError("readiness markers must not be consulted"),
    ):
        identity = wait_for_replacement_coordinator(
            tmp_path,
            plan,
            timer,
            initial_instance_id="initial-instance",
            initial_singleton_epoch=11,
            env={},
            run_compose=compose,
            owner_probe=lambda *_args: next(owners),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert health_calls == 2
    assert identity["instance_id"] == "replacement-instance"
    assert identity["fencing_epoch"] == 12


def test_replacement_wait_stops_before_inherited_cleanup_reserve(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    timer = _Timer(clock, available_seconds=7.0)
    plan = type("Plan", (), {"env_file": tmp_path / "missing"})()

    def compose(_compose_dir, args, **_kwargs):
        if "coordinator-health" in args:
            return _result(1, stderr="ERROR: unavailable")
        if args[:3] == ["ps", "--all", "--format"]:
            return _result(stdout=_running_ps())
        if args[:3] == ["logs", "--no-color", "--tail"]:
            return _result(stdout="startup still waiting for ownership")
        raise AssertionError(f"unexpected Compose call: {args}")

    with (
        pytest.raises(SystemTestError, match="replacement coordinator readiness deadline") as raised,
    ):
        wait_for_replacement_coordinator(
            tmp_path,
            plan,
            timer,
            initial_instance_id="initial-instance",
            initial_singleton_epoch=11,
            env={},
            run_compose=compose,
            owner_probe=lambda *_args: pytest.fail("owner probe must not run"),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            diagnostic_reserve_seconds=4.0,
        )

    assert timer.remaining_for_test() >= 4.0
    assert "last_health_returncode=1" in str(raised.value)
    assert "compose_ps=" in str(raised.value)
    assert "coordinator_log_tail=" in str(raised.value)


def test_replacement_process_exit_diagnostics_are_bounded_and_redacted(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    timer = _Timer(clock, available_seconds=30.0)
    plan = type("Plan", (), {"env_file": tmp_path / "missing"})()
    private_value = "do-not-report"

    def compose(_compose_dir, args, **_kwargs):
        if "coordinator-health" in args:
            return _result(1, stderr="ERROR: unavailable")
        if args[:3] == ["ps", "--all", "--format"]:
            return _result(
                stdout=json.dumps(
                    {"Service": "coordinator", "State": "exited", "ExitCode": 1}
                ) + "\n"
            )
        if args[:3] == ["logs", "--no-color", "--tail"]:
            return _result(stdout=("x" * 20_000) + f" password={private_value}")
        raise AssertionError(f"unexpected Compose call: {args}")

    with (
        pytest.raises(SystemTestError, match="replacement coordinator process exited") as raised,
    ):
        wait_for_replacement_coordinator(
            tmp_path,
            plan,
            timer,
            initial_instance_id="initial-instance",
            initial_singleton_epoch=11,
            env={},
            run_compose=compose,
            owner_probe=lambda *_args: pytest.fail("owner probe must not run"),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    diagnostic = str(raised.value)
    assert private_value not in diagnostic
    assert "password=[REDACTED]" in diagnostic
    assert "last_health_stderr=ERROR: unavailable" in diagnostic
    assert len(diagnostic.encode("utf-8")) <= DEFAULT_LIMITS.max_diagnostic_bytes


def test_restarting_process_is_polled_until_new_owner_is_ready(tmp_path: Path) -> None:
    clock = _Clock()
    timer = _Timer(clock, available_seconds=30.0)
    health_calls = 0

    def compose(_compose_dir, args, **_kwargs):
        nonlocal health_calls
        if "coordinator-health" in args:
            health_calls += 1
            if health_calls == 1:
                return _result(1, stderr="restart in progress")
            return _result(stdout='{"result":"ready","health":{"status":"ready"}}')
        if args[:3] == ["ps", "--all", "--format"]:
            return _result(
                stdout=json.dumps(
                    {"Service": "coordinator", "State": "restarting"}
                ) + "\n"
            )
        raise AssertionError(f"unexpected Compose call: {args}")

    identity = wait_for_replacement_coordinator(
        tmp_path,
        object(),
        timer,
        initial_instance_id="initial-instance",
        initial_singleton_epoch=11,
        env={},
        run_compose=compose,
        owner_probe=lambda *_args: {
            "instance_id": "replacement-instance",
            "fencing_epoch": 12,
            "status": "active",
        },
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert health_calls == 2
    assert identity["instance_id"] == "replacement-instance"


@pytest.mark.parametrize("stdout", ("{", "[]"))
def test_health_ready_rejects_malformed_or_non_object_json(stdout: str) -> None:
    assert not _health_is_ready(_result(stdout=stdout))


@pytest.mark.parametrize(
    "owner",
    (
        {"instance_id": "replacement", "fencing_epoch": True, "status": "active"},
        {"instance_id": "replacement", "fencing_epoch": 12, "status": "stopped"},
    ),
)
def test_new_owner_requires_integer_fence_and_active_status(owner: object) -> None:
    assert not _is_new_owner(
        owner,
        initial_instance_id="initial",
        initial_singleton_epoch=0,
    )


def test_owner_probe_failure_is_retained_as_bounded_diagnostic(tmp_path: Path) -> None:
    clock = _Clock()
    timer = _Timer(clock, available_seconds=7.0)

    def compose(_compose_dir, args, **_kwargs):
        if "coordinator-health" in args:
            return _result(stdout='{"result":"ready","health":{"status":"ready"}}')
        if args[:3] == ["ps", "--all", "--format"]:
            return _result(stdout=_running_ps())
        if args[:3] == ["logs", "--no-color", "--tail"]:
            return _result(stdout="replacement waiting")
        raise AssertionError(f"unexpected Compose call: {args}")

    with pytest.raises(SystemTestError) as raised:
        wait_for_replacement_coordinator(
            tmp_path,
            object(),
            timer,
            initial_instance_id="initial-instance",
            initial_singleton_epoch=11,
            env={},
            run_compose=compose,
            owner_probe=lambda *_args: (_ for _ in ()).throw(
                ValueError("password=private-value")
            ),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            diagnostic_reserve_seconds=4.0,
        )

    diagnostic = str(raised.value)
    assert "owner probe unavailable" in diagnostic
    assert "private-value" not in diagnostic
    assert "password=[REDACTED]" in diagnostic


def test_invalid_readiness_configuration_fails_before_polling(tmp_path: Path) -> None:
    clock = _Clock()
    with pytest.raises(ValueError, match="configuration is invalid"):
        wait_for_replacement_coordinator(
            tmp_path,
            object(),
            _Timer(clock, available_seconds=30.0),
            initial_instance_id="",
            initial_singleton_epoch=11,
            env={},
            run_compose=lambda *_args, **_kwargs: pytest.fail("must not poll"),
            owner_probe=lambda *_args: pytest.fail("must not probe"),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
