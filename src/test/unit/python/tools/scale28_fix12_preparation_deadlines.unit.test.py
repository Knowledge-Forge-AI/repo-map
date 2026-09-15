from multiprocessing.connection import Connection

import pytest

import scale28_preparation_worker as worker
from scale28_preparation_ipc import (
    FAILURE_MESSAGE,
    OBSERVATION_MESSAGE,
    PreparationIpcError,
)
from scale28_preparation_policy import DEFAULT_PREPARATION_DEADLINE_POLICY


def _attempt() -> worker.PreparationWorkerAttempt:
    attempt = object.__new__(worker.PreparationWorkerAttempt)
    attempt._policy = DEFAULT_PREPARATION_DEADLINE_POLICY
    return attempt


def test_failure_read_recomputes_remaining_attempt_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver: Connection = object.__new__(Connection)
    failure_receiver: Connection = object.__new__(Connection)
    now = [9.0]
    received_timeouts: list[float] = []

    def wait_ready(connections: tuple[Connection, ...], *, timeout: float) -> set[Connection]:
        assert connections == (receiver, failure_receiver)
        assert timeout == pytest.approx(1.0)
        now[0] += 0.2
        return {failure_receiver}

    def receive_failure(
        connection: Connection,
        specification: object,
        *,
        timeout_seconds: float,
        settlement_timeout_seconds: float,
    ) -> bytes:
        assert connection is failure_receiver
        assert specification is FAILURE_MESSAGE
        assert settlement_timeout_seconds == pytest.approx(0.1)
        assert timeout_seconds + settlement_timeout_seconds <= 0.9 + 1e-9
        received_timeouts.append(timeout_seconds)
        raise PreparationIpcError("message_timeout", "transport_poll", "failure")

    monkeypatch.setattr(worker.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(worker, "wait", wait_ready)
    monkeypatch.setattr(worker, "receive_one_bounded", receive_failure)

    with pytest.raises(PreparationIpcError):
        _attempt()._receive_success_or_failure(
            receiver,
            OBSERVATION_MESSAGE,
            failure_receiver,
            attempt_deadline=10.0,
        )

    assert received_timeouts == [pytest.approx(0.8)]


def test_sender_exit_fallback_wait_recomputes_remaining_attempt_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver: Connection = object.__new__(Connection)
    failure_receiver: Connection = object.__new__(Connection)
    now = [9.0]
    wait_timeouts: list[float] = []

    def wait_ready(connections: tuple[Connection, ...], *, timeout: float) -> set[Connection]:
        wait_timeouts.append(timeout)
        if len(wait_timeouts) == 1:
            now[0] += 0.2
            return {failure_receiver}
        assert connections == (receiver,)
        return set()

    def receive_failure(*_args: object, **_kwargs: object) -> bytes:
        now[0] += 0.3
        raise PreparationIpcError(
            "sender_exit_before_message",
            "transport_frame",
            "failure",
        )

    monkeypatch.setattr(worker.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(worker, "wait", wait_ready)
    monkeypatch.setattr(worker, "receive_one_bounded", receive_failure)

    with pytest.raises(worker.PreparationWorkerError, match="timed out"):
        _attempt()._receive_success_or_failure(
            receiver,
            OBSERVATION_MESSAGE,
            failure_receiver,
            attempt_deadline=10.0,
        )

    assert wait_timeouts == [pytest.approx(1.0), pytest.approx(0.5)]


def test_payload_read_recomputes_remaining_attempt_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver: Connection = object.__new__(Connection)
    failure_receiver: Connection = object.__new__(Connection)
    now = [9.0]
    received_timeouts: list[float] = []

    def wait_ready(_connections: tuple[Connection, ...], *, timeout: float) -> set[Connection]:
        assert timeout == pytest.approx(1.0)
        now[0] += 0.2
        return {receiver}

    def receive_payload(
        connection: Connection,
        specification: object,
        *,
        timeout_seconds: float,
        settlement_timeout_seconds: float,
    ) -> bytes:
        assert connection is receiver
        assert specification is OBSERVATION_MESSAGE
        assert settlement_timeout_seconds == pytest.approx(0.1)
        assert timeout_seconds + settlement_timeout_seconds <= 0.9 + 1e-9
        received_timeouts.append(timeout_seconds)
        return b"payload"

    monkeypatch.setattr(worker.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(worker, "wait", wait_ready)
    monkeypatch.setattr(worker, "receive_one_bounded", receive_payload)

    assert (
        _attempt()._receive_success_or_failure(
            receiver,
            OBSERVATION_MESSAGE,
            failure_receiver,
            attempt_deadline=10.0,
        )
        == b"payload"
    )
    assert received_timeouts == [pytest.approx(0.8)]


def test_failed_process_sigterm_join_uses_named_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    joins: list[float] = []

    class Process:
        pid = 321
        alive = True

        def is_alive(self) -> bool:
            return self.alive

        def join(self, timeout: float | None = None) -> None:
            if timeout is not None:
                joins.append(timeout)
            self.alive = False

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            pass

    process = Process()
    monkeypatch.setattr(worker, "SIGTERM_JOIN_MS", 275, raising=False)
    monkeypatch.setattr(worker.os, "killpg", lambda _pid, _signal: None)
    monkeypatch.setattr(worker, "_process_group_exists", lambda _pid: False)
    monkeypatch.setattr(
        worker,
        "_wait_process_group_settled",
        lambda _pid, _seconds: True,
    )

    _attempt()._settle_failed_process(process)

    assert joins[0] == pytest.approx(0.275)


def test_failed_process_cleanup_limitation_prohibits_retry_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Process:
        pid = 321

        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float | None = None) -> None:
            assert timeout == 0.0

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            pass

    monkeypatch.setattr(
        worker.os,
        "killpg",
        lambda _pid, _signal: (_ for _ in ()).throw(PermissionError()),
    )
    monkeypatch.setattr(worker, "_process_group_exists", lambda _pid: True)

    with pytest.raises(worker.PreparationWorkerError) as raised:
        _attempt()._settle_failed_process(Process())

    assert raised.value.category == "cleanup_limitation"
    assert raised.value.boundary == "process_settlement"


def test_settle_failed_process_natural_settlement_grace_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed: list[int] = []

    class CleanExitingProcess:
        pid = 456
        alive = True

        def is_alive(self) -> bool:
            return self.alive

        def join(self, timeout: float | None = None) -> None:
            self.alive = False

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            pass

    monkeypatch.setattr(worker.os, "killpg", lambda _pid, sig: killed.append(sig))
    monkeypatch.setattr(worker, "_process_group_exists", lambda _pid: False)

    proc = CleanExitingProcess()
    _attempt()._settle_failed_process(proc, natural_settlement_grace_seconds=0.1)
    assert not proc.alive
    assert killed == []  # No SIGTERM sent because child settled naturally


def test_settle_failed_process_natural_settlement_grace_still_alive_escalates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed: list[int] = []

    class StuckProcess:
        pid = 457
        alive = True

        def is_alive(self) -> bool:
            return self.alive

        def join(self, timeout: float | None = None) -> None:
            if 9 in killed:
                self.alive = False

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            self.alive = False

    monkeypatch.setattr(worker.os, "killpg", lambda _pid, sig: killed.append(sig))
    monkeypatch.setattr(worker, "_process_group_exists", lambda _pid: False)
    monkeypatch.setattr(worker, "_wait_process_group_settled", lambda _pid, _sec: True)

    proc = StuckProcess()
    _attempt()._settle_failed_process(proc, natural_settlement_grace_seconds=0.05)
    import signal
    assert signal.SIGTERM in killed


def test_remaining_seconds_non_raising_past_deadline() -> None:
    past_deadline = worker.time.monotonic() - 5.0
    grace = worker.PreparationWorkerAttempt._remaining_seconds(past_deadline)
    assert grace == 0.0
