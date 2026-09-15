from threading import Event
from types import SimpleNamespace

import pytest

import scale14_backend_monitor as backend_monitor_module
from scale14_backend_monitor import BackendMonitorError, BackendOwnershipMonitor


class _Connection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Observer:
    def __init__(self, summary: dict[str, int]) -> None:
        self._summary = summary
        self.events: list[object] = []

    def register_connection(self, _connection) -> None:
        return None

    def consume_pipe_event(self, event, _connection, _acknowledgement_fd) -> None:
        self.events.append(event)

    def public_summary(self, _connection) -> dict[str, int]:
        return dict(self._summary)


class _ControlledReader:
    def __init__(self, first_event=None) -> None:
        self._first_event = first_event
        self._first_read = True
        self.release_eof = Event()
        self.eof_returned = Event()

    def __call__(self, _stream, *, readiness=None):
        if readiness is not None:
            readiness()
        if self._first_read and self._first_event is not None:
            self._first_read = False
            return self._first_event
        self._first_read = False
        self.release_eof.wait(1.0)
        self.eof_returned.set()
        return None


def _monitor(
    reader: _ControlledReader,
    observer: _Observer,
    *,
    child_is_live=None,
):
    connection = _Connection()
    monitor = BackendOwnershipMonitor(
        connection_factory=lambda: connection,
        event_reader=reader,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: observer,
        descriptor_closer=lambda _fd: None,
        child_is_live=child_is_live,
    )
    return monitor, connection


def test_static_interval_does_not_require_a_first_connection_frame(
    monkeypatch,
) -> None:
    monkeypatch.setattr(backend_monitor_module, "_STARTUP_TIMEOUT_SECONDS", 0.01)
    reader = _ControlledReader()
    observer = _Observer({"observer": 1})
    monitor, _connection = _monitor(reader, observer)

    try:
        monitor.start()
        assert monitor.summary() == {"observer": 1}
        assert observer.events == []
    finally:
        reader.release_eof.set()
        monitor.close()


def test_remote_eof_before_first_frame_fails_while_session_is_active() -> None:
    reader = _ControlledReader()
    monitor, _connection = _monitor(reader, _Observer({"observer": 1}))

    try:
        monitor.start()
        reader.release_eof.set()
        assert reader.eof_returned.wait(1.0)
        with pytest.raises(BackendMonitorError) as captured:
            monitor.summary()
        assert captured.value.category == "backend_telemetry_failed"
    finally:
        monitor.close()


def test_remote_eof_after_connection_frame_fails_while_session_is_active() -> None:
    reader = _ControlledReader(SimpleNamespace(event="ready"))
    monitor, _connection = _monitor(reader, _Observer({"observer": 1}))

    try:
        monitor.start()
        assert monitor.summary() == {"observer": 1}
        reader.release_eof.set()
        assert reader.eof_returned.wait(1.0)
        with pytest.raises(BackendMonitorError) as captured:
            monitor.summary()
        assert captured.value.category == "backend_telemetry_failed"
    finally:
        monitor.close()


def test_terminal_eof_without_connection_frames_returns_settled_summary() -> None:
    reader = _ControlledReader()
    observer = _Observer({"observer": 1, "postgres_internal": 2})
    monitor, connection = _monitor(reader, observer)

    monitor.start()
    reader.release_eof.set()
    assert monitor.wait_quiescent(1.0) == {
        "observer": 1,
        "postgres_internal": 2,
    }
    monitor.close()

    assert observer.events == []
    assert connection.closed is True


def test_terminal_wait_rejects_eof_observed_while_child_is_live() -> None:
    reader = _ControlledReader()
    monitor, _connection = _monitor(
        reader,
        _Observer({"observer": 1}),
        child_is_live=lambda: True,
    )

    monitor.start()
    reader.release_eof.set()
    with pytest.raises(BackendMonitorError) as captured:
        monitor.wait_quiescent(1.0)
    monitor.close()

    assert captured.value.category == "backend_telemetry_failed"
    assert _connection.closed is True


def test_terminal_wait_arbitrates_eof_against_settled_child_state() -> None:
    reader = _ControlledReader()
    child_live = True
    monitor, connection = _monitor(
        reader,
        _Observer({"observer": 1}),
        child_is_live=lambda: child_live,
    )

    monitor.start()
    reader.release_eof.set()
    assert reader.eof_returned.wait(1.0)
    child_live = False

    assert monitor.wait_quiescent(1.0) == {"observer": 1}
    assert connection.closed is True


def test_one_hundred_static_intervals_settle_without_first_frame_or_leak() -> None:
    connections = []
    for _index in range(100):
        reader = _ControlledReader()
        child_live = True
        monitor, connection = _monitor(
            reader,
            _Observer({"observer": 1}),
            child_is_live=lambda: child_live,
        )
        connections.append(connection)

        monitor.start()
        assert monitor.summary() == {"observer": 1}
        child_live = False
        reader.release_eof.set()
        assert monitor.wait_quiescent(1.0) == {"observer": 1}
        monitor.close()

    assert all(connection.closed for connection in connections)
