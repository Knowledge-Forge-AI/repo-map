"""Maintained refresh_worker M proof for native default and canonical facade custody.

Each case launches the existing nine-argument ``refresh_worker`` command with a
valid sealed capability over disposable refresh/PostgreSQL fixtures. The real
``ManagedProcess`` is captured by a delegated ``_launch_posix`` spy, so the
effective launch callable stays the canonical original.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import sys
from typing import Any

import pytest

import common_lore_index.coordinator._launch_custody as custody
import common_lore_index.coordinator._protocol_execution as execution
import common_lore_index.coordinator.process_supervision as supervision
from common_lore_index.coordinator import protocol
from common_lore_index.coordinator._protocol_core import ProtocolError
from common_lore_index.coordinator._worker_launch import WorkerLaunchSpec
from common_lore_index.coordinator.refresh_adapter import RefreshCapability, create_refresh_capability
from common_lore_index.ops.config import load_ops_config
from common_lore_index.runtime.postgres_route import effective_postgres_route
from repomap_test_support.startup_recovery_scenarios import (
    _make_refresh_fixture,
    _refresh_harness,
    _search_path,
)

_LIMITS = {
    "process_deadline_seconds": 60, "heartbeat_seconds": 30, "hello_deadline_seconds": 30,
    "cancellation_after_seconds": 5, "cancel_deadline_seconds": 1,
    "process_termination_grace_seconds": 1, "max_diagnostic_bytes": 4096,
    "max_protocol_line_bytes": 1024 * 1024, "max_array_items": 32,
}
_ENV = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[6] / "src/main/python")}


@contextmanager
def _maintained_worker(job_id: str) -> Iterator[tuple[tuple[str, ...], dict[str, object], dict[str, object], Path]]:
    with _refresh_harness() as (_store, cap_dir, _connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        route = effective_postgres_route(load_ops_config(config))
        capability = RefreshCapability(
            schema_version=1, job_id=job_id, attempt=1, graph_id="synthetic-g1",
            config_path=config, psql_path=Path(postgres.psql_command), postgres_user=postgres.user,
            postgres_host=route.host, postgres_port=route.port, postgres_route_kind=route.kind,
            postgres_password=postgres.password, executable_search_path=_search_path(),
            source_generation=sg, config_generation=cg, extractor_generation=eg, canonicalizer_generation=kg,
            coordinator_instance_id="governance3-native", singleton_fencing_epoch=1, graph_lease_fencing_epoch=1,
        )
        sealed = create_refresh_capability(cap_dir, capability)
        argv = (sys.executable, "-m", "common_lore_index.coordinator.refresh_worker", "--capability",
                str(sealed), "--job-id", job_id, "--attempt", "1")
        context: dict[str, object] = {"graph_id": "synthetic-g1", "source_generation": sg, "config_generation": cg}
        yield argv, {"job_id": job_id, "attempt": 1}, context, cap_dir


def _spies(monkeypatch) -> tuple[list[Any], list[Any], list[str]]:
    launched: list[Any] = []
    outcomes: list[Any] = []
    sent: list[str] = []
    real_launch, real_settle = supervision._launch_posix, custody.settle_abnormal_exit
    real_send = execution._send_coordinator

    def launch(*args: Any, **kwargs: Any) -> Any:
        launched.append(real_launch(*args, **kwargs))
        return launched[-1]

    def settle(*args: Any, **kwargs: Any) -> Any:
        outcomes.append(real_settle(*args, **kwargs))
        return outcomes[-1]

    def send(process: Any, session: Any, lock: Any, message: Any, *following: Any) -> bool:
        sent.append(str(message["message_type"]))
        return real_send(process, session, lock, message, *following)

    monkeypatch.setattr(supervision, "_launch_posix", launch)
    monkeypatch.setattr(custody, "settle_abnormal_exit", settle)
    monkeypatch.setattr(execution, "_send_coordinator", send)
    return launched, outcomes, sent


def _assert_native_settled(process: Any, outcome: Any, returncode: int) -> None:
    assert process.native and process.closed, "native boundary released"
    assert process.reap_state() == "reaped" and process.returncode == returncode
    assert outcome.proven and outcome.reason is None and outcome.returncode == returncode
    assert outcome.status_known and outcome.group_empty and outcome.released
    assert outcome.readers_joined and outcome.streams_closed
    assert all(getattr(process, name).closed for name in ("stdin", "stdout", "stderr"))
    with pytest.raises(ProcessLookupError):
        os.killpg(process.pid, 0)  # exact owned group: ESRCH


def _exact_cleanup(launched: list[Any]) -> None:
    for process in launched:
        if not process.closed:
            process.kill_tree()
            assert process.cleanup(0.1, 5.0)
        for name in ("stdin", "stdout", "stderr"):
            getattr(process, name).close()
        with pytest.raises(ProcessLookupError):
            os.killpg(process.pid, 0)


def _run(mode: str, argv: tuple[str, ...], identity: dict[str, object], context: dict[str, object],
         cwd: Path) -> Any:
    if mode == "facade":
        return protocol.run_worker_spec(WorkerLaunchSpec(argv, _ENV, cwd), identity, _LIMITS,
                                        job_context=context)
    return execution._run_protocol_worker(argv, _ENV, cwd, False, identity, _LIMITS,
                                          job_context=context, cancel_event=None)


@pytest.mark.parametrize("mode", ["default", "facade"])
def test_extra_job_context_key_after_real_hello_is_settled_before_job_start(monkeypatch, mode: str) -> None:
    with _maintained_worker(f"gov3-invalid-{mode}") as (argv, identity, context, cwd):
        launched, outcomes, sent = _spies(monkeypatch)
        try:
            with pytest.raises(ProtocolError, match="invalid_job_context"):
                _run(mode, argv, identity, {**context, "unexpected": "extra"}, cwd)
            assert sent == [], "job_start is never sent"
            (process,), (outcome,) = launched, outcomes
            _assert_native_settled(process, outcome, -9)
            assert process.resource_usage is None
        finally:
            _exact_cleanup(launched)


@pytest.mark.parametrize(("secondary", "note_error"), [
    (OSError, None), (SystemExit, None), (OSError, RuntimeError), (OSError, KeyboardInterrupt),
])
def test_primary_identity_survives_a_secondary_failure_at_a_parent_seam(
    monkeypatch, secondary: type[BaseException], note_error: type[BaseException] | None,
) -> None:
    with _maintained_worker(f"gov3-primary-{secondary.__name__.lower()}") as (argv, identity, context, cwd):
        launched, outcomes, _sent = _spies(monkeypatch)
        class NoNotes(KeyboardInterrupt):
            def add_note(self, note: str) -> None:
                assert note_error is not None
                raise note_error("diagnostic delivery unavailable")

        primary = NoNotes("primary") if note_error is not None else KeyboardInterrupt("primary")

        def interrupted_job_start(_identity: object, _context: object) -> dict[str, object]:
            raise primary  # Python BaseException at the established post-hello seam

        real_kill = supervision.ManagedProcess.kill_tree
        armed = [True]

        def failing_first_kill(self: Any) -> None:
            if armed[0]:
                armed[0] = False
                raise secondary("secondary")
            real_kill(self)

        monkeypatch.setattr(execution, "_job_start", interrupted_job_start)
        monkeypatch.setattr(supervision.ManagedProcess, "kill_tree", failing_first_kill)
        try:
            with pytest.raises(KeyboardInterrupt) as raised:
                _run("default", argv, identity, context, cwd)
            assert raised.value is primary
            if note_error is not None:
                assert not getattr(primary, "__notes__", [])
            else:
                assert primary.__notes__[0] == f"worker interrupt cleanup failure: {secondary.__name__}"
            (process,), (outcome,) = launched, outcomes
            if secondary is SystemExit or note_error is KeyboardInterrupt:
                # A guarded second interrupt, including note delivery, permits only closes.
                assert not outcome.proven and not outcome.group_empty
                assert outcome.reason == "interrupted" and not process.closed
                assert all(getattr(process, name).closed for name in ("stdin", "stdout", "stderr"))
            else:  # ordinary failure: later cleanup may prove the group if empty
                assert process.closed and process.reap_state() == "reaped"
                assert outcome.group_empty is process.group_empty_observed
                if outcome.group_empty:
                    assert outcome.proven and outcome.reason is None
                else:
                    assert not outcome.proven and outcome.reason == "group_not_proven"
        finally:
            _exact_cleanup(launched)


def test_worker_input_closed_is_the_real_closed_pipe_after_owned_termination(monkeypatch) -> None:
    with _maintained_worker("gov3-input-closed") as (argv, identity, context, cwd):
        launched, outcomes, sent = _spies(monkeypatch)
        real_job_start = execution._job_start
        owned: list[int] = []

        def terminate_then_start(job_identity: Any, job_context: Any) -> dict[str, object]:
            (process,) = launched
            process.kill_tree()  # owned group signal after real hello readiness
            owned.append(process.wait(timeout=10))  # the selected owner reaps it
            return real_job_start(job_identity, job_context)

        monkeypatch.setattr(execution, "_job_start", terminate_then_start)
        try:
            with pytest.raises(ProtocolError, match="worker_input_closed") as raised:
                _run("default", argv, identity, context, cwd)
            assert isinstance(raised.value.__cause__, BrokenPipeError), "actual closed-pipe write"
            assert owned == [-9] and sent == ["job_start"]
            (process,), (outcome,) = launched, outcomes
            _assert_native_settled(process, outcome, -9)
        finally:
            _exact_cleanup(launched)
