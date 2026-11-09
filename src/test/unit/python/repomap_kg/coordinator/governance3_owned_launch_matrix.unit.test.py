"""Native-provenance factory matrix: positive canonical rows and each negative cell.

Real children here are T0 development wiring checks; the maintained-worker M
fixtures in ``governance3_*`` integration owners prove actual behavior.
"""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest

import common_lore_index.coordinator._launch_custody as custody
import common_lore_index.coordinator._protocol_execution as execution
import common_lore_index.coordinator.process_supervision as supervision
from common_lore_index.coordinator import protocol
from common_lore_index.coordinator._protocol_core import ProtocolError
from common_lore_index.coordinator._worker_launch import WorkerLaunchSpec

_LIMITS = SimpleNamespace(hello_deadline_seconds=20.0, process_termination_grace_seconds=0.5,
                          cancel_deadline_seconds=0.5)
_IDENTITY = {"job_id": "job-matrix", "attempt": 1}
_SLEEPER = (sys.executable, "-c", "import time; time.sleep(30)")
_HELLO_THEN_BLOCK = (sys.executable, "-c", (
    "import json, time\n"
    "print(json.dumps(dict(schema_version=1, message_type='worker_hello', protocol_versions=[1],"
    " capabilities=['refresh_graph'], worker_generation='wg1:fixture', process_nonce='fixture')),"
    " flush=True)\n"
    "time.sleep(30)\n"
))
_EXTRA_KEY_CONTEXT = {"graph_id": "g", "source_generation": "sg1:x", "config_generation": "cg1:x",
                      "unexpected": "extra"}


def _capture_launches(monkeypatch) -> list[Any]:
    captured: list[Any] = []
    real = supervision._launch_posix

    def spy(*args: Any, **kwargs: Any) -> Any:
        managed = real(*args, **kwargs)
        captured.append(managed)
        return managed

    monkeypatch.setattr(supervision, "_launch_posix", spy)  # delegated; launch stays canonical
    return captured


def _capture_outcomes(monkeypatch) -> list[Any]:
    outcomes: list[Any] = []
    real = custody.settle_abnormal_exit

    def spy(*args: Any, **kwargs: Any) -> Any:
        outcome = real(*args, **kwargs)
        outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(custody, "settle_abnormal_exit", spy)
    return outcomes


def _assert_native_settled(process: Any, outcome: Any) -> None:
    assert process.native and process.closed and process.reap_state() == "reaped"
    assert outcome.proven and outcome.reason is None and outcome.returncode == process.returncode == -9
    assert outcome.status_known and outcome.group_empty and outcome.released
    assert outcome.readers_joined and outcome.streams_closed
    assert all(getattr(process, name).closed for name in ("stdin", "stdout", "stderr"))
    with pytest.raises(ProcessLookupError):
        os.killpg(process.pid, 0)


def _cleanup(launched: list[Any]) -> None:
    for process in launched:
        if not process.closed:
            process.kill_tree()
            process.cleanup(0.1, 2.0)
        for name in ("stdin", "stdout", "stderr"):
            getattr(process, name).close()


def test_predicates_require_the_captured_original_and_recorded_native_provenance() -> None:
    assert custody.is_canonical_launch(supervision.launch_managed_process)
    assert not custody.is_canonical_launch(lambda *a, **k: None)
    fake = SimpleNamespace(native=True)  # a claimed fact is not provenance
    assert not custody.has_native_custody(fake, True)


def test_default_explicit_none_row_settles_a_real_child_through_the_shared_outcome(
    monkeypatch, tmp_path: Path,
) -> None:
    launched, outcomes = _capture_launches(monkeypatch), _capture_outcomes(monkeypatch)
    original = KeyboardInterrupt()

    def probe() -> bool:
        raise original

    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            execution._run_protocol_worker(
                _SLEEPER, dict(os.environ), tmp_path, False, _IDENTITY, _LIMITS,
                job_context=None, cancel_event=None, _timeout_probe=probe,
            )
        assert raised.value is original and len(outcomes) == 1
        (process,) = launched
        _assert_native_settled(process, outcomes[0])
        assert process.resource_usage is None
    finally:
        _cleanup(launched)


def test_canonical_facade_row_settles_after_a_real_invalid_job_context(monkeypatch, tmp_path: Path) -> None:
    launched, outcomes = _capture_launches(monkeypatch), _capture_outcomes(monkeypatch)
    spec = WorkerLaunchSpec(_HELLO_THEN_BLOCK, dict(os.environ), tmp_path)
    try:
        with pytest.raises(ProtocolError, match="invalid_job_context"):
            protocol.run_worker_spec(spec, _IDENTITY, _LIMITS, job_context=_EXTRA_KEY_CONTEXT)
        (process,) = launched
        _assert_native_settled(process, outcomes[0])
    finally:
        _cleanup(launched)


def test_explicit_custom_callable_keeps_incumbent_injected_behavior(monkeypatch, tmp_path: Path) -> None:
    outcomes = _capture_outcomes(monkeypatch)
    launched: list[Any] = []

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        launched.append(supervision.launch_managed_process(*args, **kwargs))
        return launched[-1]

    def probe() -> bool:
        raise KeyboardInterrupt

    try:
        with pytest.raises(KeyboardInterrupt):
            execution._run_protocol_worker(
                _SLEEPER, dict(os.environ), tmp_path, False, _IDENTITY, _LIMITS,
                job_context=None, cancel_event=None, _launch_process=wrapper, _timeout_probe=probe,
            )
        assert outcomes == [] and not launched[0].closed and launched[0].poll() is None
    finally:
        _cleanup(launched)


class _FakePopen:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args, self.pid, self.returncode = args[0], 4343, None
        self.stdin, self.stdout, self.stderr = BytesIO(), BytesIO(), BytesIO()

    def poll(self) -> None:
        return None


def test_original_launch_with_patched_popen_gets_no_native_handler_or_real_signal(
    monkeypatch, tmp_path: Path,
) -> None:
    outcomes = _capture_outcomes(monkeypatch)
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)  # forwarded at runtime: no real child
    monkeypatch.setattr(supervision.os, "killpg", lambda *a: pytest.fail("no real group signal"))
    monkeypatch.setattr(supervision.os, "wait4", lambda *a: pytest.fail("no wait4 owner"))

    def probe() -> bool:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        execution._run_protocol_worker(
            ("worker",), {}, tmp_path, False, _IDENTITY, _LIMITS,
            job_context=None, cancel_event=None, _timeout_probe=probe,
        )
    assert outcomes == []


@pytest.mark.parametrize(("options", "error", "match"), [
    ({"_launch_process": lambda *a, **k: pytest.fail("launched"), "_launch_ticket": object()},
     PermissionError, "injected child factory"),
    ({"_launch_process": lambda *a, **k: pytest.fail("launched"), "collect_usage": True},
     ValueError, "owned launch"),
    ({"_launch_ticket": object(), "collect_usage": True}, ValueError, "owned launch"),
])
def test_usage_and_ticketed_rows_reject_explicit_factories_before_launch(
    tmp_path: Path, options: dict[str, Any], error: type[Exception], match: str,
) -> None:
    with pytest.raises(error, match=match):
        execution._run_protocol_worker(
            ("worker",), {}, tmp_path, False, _IDENTITY, _LIMITS,
            job_context=None, cancel_event=None, **options,
        )


def test_usage_with_a_fake_module_launch_stays_a_t0_shim_simulation(monkeypatch, tmp_path: Path) -> None:
    outcomes = _capture_outcomes(monkeypatch)
    calls: list[object] = []
    fake = SimpleNamespace(pid=7, stdin=BytesIO(), stdout=BytesIO(), stderr=BytesIO(),
                           poll=lambda: None, returncode=None)
    monkeypatch.setattr(execution, "launch_managed_process", lambda *a, **k: fake)
    monkeypatch.setattr(execution, "interrupt_cleanup", lambda *args: calls.append(args[0]))

    def probe() -> bool:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        execution._run_protocol_worker(
            ("worker",), {}, tmp_path, False, _IDENTITY, _LIMITS,
            job_context=None, cancel_event=None, _timeout_probe=probe, collect_usage=True,
        )
    assert calls == [fake] and outcomes == [], "the shim is called; no native outcome is minted"
