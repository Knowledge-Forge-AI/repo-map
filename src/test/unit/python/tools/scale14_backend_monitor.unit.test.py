from __future__ import annotations

import os
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from actual_refresh_failure_causality import FailureCausalityAuthority
import scale14_backend_monitor as backend_monitor_module
from scale14_backend_monitor import BackendMonitorError, BackendOwnershipMonitor


class _Connection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _Observer:
    def __init__(self, summaries):
        self.summaries = iter(summaries)
        self.registered = []
        self.events = []

    def register_connection(self, connection):
        self.registered.append(connection)

    def consume_pipe_event(self, event, connection, ack_fd):
        self.events.append((event, connection, ack_fd))

    def public_summary(self, connection):
        return next(self.summaries)


class _EventReader:
    def __init__(self, *events):
        self.events = iter(events)
        self.allow_eof = Event()

    def __call__(self, _stream, *, readiness=None):
        if readiness is not None:
            readiness()
        try:
            return next(self.events)
        except StopIteration:
            self.allow_eof.wait(1.0)
            return None


def test_backend_start_rejects_closed_acknowledgement_descriptor() -> None:
    read_descriptor, write_descriptor = os.pipe()
    os.close(write_descriptor)
    connections = []
    monitor = BackendOwnershipMonitor(
        connection_factory=lambda: connections.append(_Connection()),
        event_reader=_EventReader(),
        event_stream=object(),
        acknowledgement_fd=write_descriptor,
        observer_factory=lambda: _Observer([{"observer": 1}]),
        descriptor_closer=lambda _fd: None,
    )
    try:
        with pytest.raises(BackendMonitorError, match="acknowledgement"):
            monitor.start()
        assert connections == []
    finally:
        os.close(read_descriptor)
        monitor.close()


def test_backend_thread_start_failure_is_typed_and_close_safe(monkeypatch) -> None:
    class _UnstartedThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("thread unavailable")

        def join(self, _timeout) -> None:
            raise AssertionError("unstarted thread must not be joined")

    connection = _Connection()
    monitor = BackendOwnershipMonitor(
        connection_factory=lambda: connection,
        event_reader=_EventReader(),
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: _Observer([{"observer": 1}]),
        descriptor_closer=lambda _fd: None,
    )
    monkeypatch.setattr(backend_monitor_module, "Thread", _UnstartedThread)

    with pytest.raises(BackendMonitorError, match="consumer could not start"):
        monitor.start()
    monitor.close()

    assert connection.closed is True


def test_backend_registration_failure_closes_unowned_connection() -> None:
    class _RejectingObserver(_Observer):
        def register_connection(self, connection):
            del connection
            raise RuntimeError("registration unavailable")

    connection = _Connection()
    monitor = BackendOwnershipMonitor(
        connection_factory=lambda: connection,
        event_reader=_EventReader(),
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: _RejectingObserver([]),
        descriptor_closer=lambda _fd: None,
    )

    with pytest.raises(BackendMonitorError, match="registration failed"):
        monitor.start()
    monitor.close()

    assert connection.closed is True


def test_backend_registration_retries_once_before_child_release() -> None:
    connections = [_Connection(), _Connection()]
    attempts = 0

    def connection_factory():
        nonlocal attempts
        connection = connections[attempts]
        attempts += 1
        if attempts == 1:
            raise OSError("transient observer connection failure")
        return connection

    reader = _EventReader()
    monitor = BackendOwnershipMonitor(
        connection_factory=connection_factory,
        event_reader=reader,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: _Observer([{"observer": 1}]),
        descriptor_closer=lambda _fd: None,
    )

    monitor.start()
    reader.allow_eof.set()
    assert monitor.wait_quiescent(1.0) == {"observer": 1}
    monitor.close()

    assert attempts == 2
    assert connections[1].closed is True


def test_backend_monitor_registers_consumes_and_waits_for_quiescence() -> None:
    connection = _Connection()
    observer = _Observer(
        [
            {"observer": 1, "direct_client": 1},
            {"observer": 1, "postgres_internal": 2},
        ]
    )
    events = _EventReader(SimpleNamespace(event="ready"))
    monitor = BackendOwnershipMonitor(
        connection_factory=lambda: connection,
        event_reader=events,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: observer,
        descriptor_closer=lambda _fd: None,
    )

    monitor.start()
    active = monitor.summary()
    events.allow_eof.set()
    settled = monitor.wait_quiescent(1.0)
    monitor.close()

    assert observer.registered == [connection]
    assert len(observer.events) == 1
    assert active == {"observer": 1, "direct_client": 1}
    assert settled == {"observer": 1, "postgres_internal": 2}
    assert connection.closed is True


def test_backend_monitor_surfaces_telemetry_failure() -> None:
    observer = _Observer([{"observer": 1}])
    causality = FailureCausalityAuthority()

    def fail(_stream, *, readiness=None):
        if readiness is not None:
            readiness()
        raise OSError("private detail")

    monitor = BackendOwnershipMonitor(
        connection_factory=_Connection,
        event_reader=fail,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: observer,
        descriptor_closer=lambda _fd: None,
        failure_causality=causality,
        child_released=lambda: False,
    )
    with pytest.raises(BackendMonitorError, match="telemetry"):
        monitor.start()

    monitor.close()
    candidates = causality.freeze().candidates
    assert len(candidates) == 1
    assert candidates[0].code == "backend_telemetry_failed"
    assert candidates[0].existed_before_child_release is True


def test_backend_monitor_allows_bounded_ready_handoff_before_ambient_failure() -> None:
    observer = _Observer(
        [
            {"observer": 1, "ambient_client": 1},
            {"observer": 1, "direct_owned_client": 1},
        ]
    )
    events = _EventReader(SimpleNamespace(event="ready"))
    monitor = BackendOwnershipMonitor(
        connection_factory=_Connection,
        event_reader=events,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: observer,
        descriptor_closer=lambda _fd: None,
    )

    monitor.start()
    summary = monitor.summary()
    events.allow_eof.set()
    monitor.close()

    assert summary == {"observer": 1, "direct_owned_client": 1}


def test_backend_start_waits_for_consumer_readiness_not_thread_creation() -> None:
    observer = _Observer([{"observer": 1}, {"observer": 1}])
    allow_consumer = Event()
    allow_eof = Event()
    start_returned = Event()

    def controlled_reader(_stream, *, readiness=None):
        allow_consumer.wait(1.0)
        if readiness is not None:
            readiness()
        allow_eof.wait(1.0)
        return None

    monitor = BackendOwnershipMonitor(
        connection_factory=_Connection,
        event_reader=controlled_reader,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: observer,
        descriptor_closer=lambda _fd: None,
    )
    def start_monitor() -> None:
        monitor.start()
        start_returned.set()

    starter = Thread(target=start_monitor)
    starter.start()
    try:
        assert start_returned.wait(0.05) is False
        allow_consumer.set()
        assert start_returned.wait(1.0) is True
        assert monitor.startup_summary() == {"observer": 1}
    finally:
        allow_consumer.set()
        allow_eof.set()
        starter.join(timeout=1.0)
        monitor.close()
