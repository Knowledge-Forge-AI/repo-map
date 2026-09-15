from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import scale28_preparation_worker_process as process_owner

import pytest

import scale28_preparation_worker as worker


def test_safety3_attempt_deadline_uses_pre_spawn_clock_origin() -> None:
    process_start_ns = 9_500_000_000

    deadline = worker._attempt_deadline_from_process_start(process_start_ns, 250)

    assert deadline == pytest.approx(9.75)


def test_safety3_post_spawn_delay_remains_preparation_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker.time, "monotonic", lambda: 9.751)

    with pytest.raises(worker.PreparationWorkerError) as raised:
        worker.PreparationWorkerAttempt._remaining_until(9.75)

    assert raised.value.category == "preparation_timeout"
    assert raised.value.boundary == "worker"


def test_safety3_spawn_failure_is_classified_and_closes_all_ipc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Endpoint:
        closed = False

        def close(self) -> None:
            self.closed = True

    class Process:
        closed = False

        def start(self) -> None:
            raise AssertionError("injected spawn owner must fail first")

        def close(self) -> None:
            self.closed = True

    endpoints = tuple(Endpoint() for _ in range(10))
    process = Process()
    monkeypatch.setattr(
        worker,
        "_start_without_ambient_parent_main",
        lambda _process: (_ for _ in ()).throw(RuntimeError("spawn failed")),
    )

    with pytest.raises(worker.PreparationWorkerError) as raised:
        worker._start_preparation_process(process, endpoints)

    assert raised.value.category == "worker_failed"
    assert raised.value.boundary == "worker"
    assert all(endpoint.closed for endpoint in endpoints)
    assert process.closed is True


def test_safety3_preparation_child_bytecode_policy_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker.os, "environ", {"PATH": "/bin", "NOISE": "value"})

    worker._retain_minimal_worker_environment(dont_write_bytecode=True)

    assert worker.os.environ == {
        "PATH": "/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def test_safety3_does_not_add_startup_failure_vocabulary() -> None:
    source = worker.__file__
    assert source is not None
    text = Path(source).read_text(encoding="utf-8")

    assert "preparation_startup_failed" not in text
    assert "worker_startup" not in text
    assert "_await_worker_ready" not in text


def test_facade_deadline_receives_spawn_origin_after_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    origin = 9_500_000_123

    class DeadlineObserved(Exception):
        pass

    class Endpoint:
        def close(self) -> None:
            pass

    class Process:
        def start(self) -> None:
            events.append("start")

        def close(self) -> None:
            pass

    class Context:
        def Pipe(self, *, duplex: bool) -> tuple[Endpoint, Endpoint]:
            assert duplex is False
            return Endpoint(), Endpoint()

        def Event(self) -> object:
            return object()

        def Process(self, **_kwargs: object) -> Process:
            return Process()

    def start(process: Process) -> int:
        events.append("clock")
        process.start()
        return origin

    def deadline(started_ns: int, timeout_ms: int) -> float:
        assert events == ["clock", "start"]
        assert started_ns == origin
        assert timeout_ms == 250
        events.append("deadline")
        # Deadline construction is before run's settlement try block. Stop here
        # without introducing a fake successful IPC or settlement sequence.
        raise DeadlineObserved

    class Request:
        def to_bytes(self) -> bytes:
            return b"request"

    attempt = object.__new__(worker.PreparationWorkerAttempt)
    monkeypatch.setattr(attempt, "_request", Request(), raising=False)
    monkeypatch.setattr(attempt, "_specification", object(), raising=False)
    monkeypatch.setattr(attempt, "_preparer", object(), raising=False)
    monkeypatch.setattr(attempt, "_policy", SimpleNamespace(
        attempt_timeout_ms=250, acknowledgement_timeout_ms=150,
    ), raising=False)
    monkeypatch.setattr(worker, "get_context", lambda method: Context())
    monkeypatch.setattr(worker, "_start_without_ambient_parent_main", start)
    monkeypatch.setattr(worker, "_attempt_deadline_from_process_start", deadline)

    with pytest.raises(DeadlineObserved):
        attempt.run()
    assert events == ["clock", "start", "deadline"]


@pytest.mark.parametrize("ambient", [False, True])
def test_actual_spawn_failure_preserves_clock_cleanup_and_main(
    monkeypatch: pytest.MonkeyPatch, ambient: bool,
) -> None:
    events: list[str] = []
    main = ModuleType("__main__")
    main.__file__ = "synthetic-main.py"
    original_spec = main.__spec__
    if ambient:
        monkeypatch.setitem(sys.modules, "__main__", main)
    else:
        monkeypatch.delitem(sys.modules, "__main__", raising=False)

    def clock() -> int:
        events.append("clock")
        return 123

    class Endpoint:
        closed = False

        def close(self) -> None:
            self.closed = True

    class Process(Endpoint):
        def start(self) -> None:
            events.append("start")
            assert events == ["clock", "start"]
            if ambient:
                assert not hasattr(main, "__file__")
                assert main.__spec__ is None
            raise RuntimeError("synthetic spawn failure")

    endpoints = tuple(Endpoint() for _ in range(10))
    process = Process()
    monkeypatch.setattr(process_owner.time, "monotonic_ns", clock)
    with pytest.raises(worker.PreparationWorkerError) as raised:
        worker._start_preparation_process(process, endpoints)
    assert events == ["clock", "start"]
    assert raised.value.category == "worker_failed"
    assert raised.value.boundary == "worker"
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert all(endpoint.closed for endpoint in endpoints)
    assert process.closed
    if ambient:
        assert main.__file__ == "synthetic-main.py"
        assert main.__spec__ is original_spec
