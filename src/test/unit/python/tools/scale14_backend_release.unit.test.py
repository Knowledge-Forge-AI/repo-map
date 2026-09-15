from __future__ import annotations

from threading import Event

import pytest

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


def test_backend_startup_summary_requires_stable_quiescent_handoff() -> None:
    observer = _Observer(
        [
            {"observer": 1, "ambient_client": 1},
            {"observer": 1},
            {"observer": 1},
        ]
    )
    events = _EventReader()
    monitor = BackendOwnershipMonitor(
        connection_factory=_Connection,
        event_reader=events,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: observer,
        descriptor_closer=lambda _fd: None,
    )
    try:
        monitor.start()

        assert monitor.startup_summary() == {"observer": 1}
    finally:
        events.allow_eof.set()
        monitor.close()


def test_backend_startup_summary_timeout_fails_closed() -> None:
    class _PersistentObserver(_Observer):
        def public_summary(self, connection):
            del connection
            return {"observer": 1, "ambient_client": 1}

    events = _EventReader()
    monitor = BackendOwnershipMonitor(
        connection_factory=_Connection,
        event_reader=events,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: _PersistentObserver([]),
        descriptor_closer=lambda _fd: None,
    )
    try:
        monitor.start()

        with pytest.raises(BackendMonitorError) as captured:
            monitor.startup_summary()
        assert captured.value.category == "ambient_client_detected"
    finally:
        events.allow_eof.set()
        monitor.close()


def test_backend_startup_summary_rejects_persistent_owned_client() -> None:
    class _PersistentObserver(_Observer):
        def public_summary(self, connection):
            del connection
            return {"observer": 1, "direct_owned_client": 1}

    events = _EventReader()
    monitor = BackendOwnershipMonitor(
        connection_factory=_Connection,
        event_reader=events,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: _PersistentObserver([]),
        descriptor_closer=lambda _fd: None,
    )
    try:
        monitor.start()

        with pytest.raises(BackendMonitorError) as captured:
            monitor.startup_summary()
        assert captured.value.category == "backend_quiescence_timeout"
    finally:
        events.allow_eof.set()
        monitor.close()


def test_backend_startup_summary_refuses_below_floor_with_last_known_category(
    monkeypatch,
) -> None:
    observer = _Observer(
        [
            {"observer": 1, "ambient_client": 1},
            {"observer": 1},
        ]
    )
    events = _EventReader()
    monitor = BackendOwnershipMonitor(
        connection_factory=_Connection,
        event_reader=events,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: observer,
        descriptor_closer=lambda _fd: None,
    )
    moments = iter((0.0, 0.1, 0.2, 0.4, 0.6))
    monkeypatch.setattr(backend_monitor_module.time, "monotonic", moments.__next__)
    try:
        monitor.start()

        with pytest.raises(BackendMonitorError) as captured:
            monitor.startup_summary()
        assert captured.value.category == "ambient_client_detected"
    finally:
        events.allow_eof.set()
        monitor.close()


def test_backend_startup_summary_rejects_telemetry_eof_during_handoff() -> None:
    events = _EventReader()
    monitor = None

    class _EndingObserver(_Observer):
        def public_summary(self, connection):
            del connection
            events.allow_eof.set()
            return {"observer": 1, "ambient_client": 1}

    monitor = BackendOwnershipMonitor(
        connection_factory=_Connection,
        event_reader=events,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: _EndingObserver([]),
        descriptor_closer=lambda _fd: None,
    )
    try:
        monitor.start()

        with pytest.raises(BackendMonitorError) as captured:
            monitor.startup_summary()
        assert captured.value.category == "backend_telemetry_failed"
    finally:
        events.allow_eof.set()
        monitor.close()


def test_backend_release_rejects_eof_after_clean_startup_summary() -> None:
    observer = _Observer([{"observer": 1}, {"observer": 1}, {"observer": 1}])
    events = _EventReader()
    monitor = BackendOwnershipMonitor(
        connection_factory=_Connection,
        event_reader=events,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: observer,
        descriptor_closer=lambda _fd: None,
    )
    released = Event()
    try:
        monitor.start()
        assert monitor.startup_summary() == {"observer": 1}
        events.allow_eof.set()
        assert monitor._done.wait(1.0)

        with pytest.raises(BackendMonitorError) as captured:
            monitor.release_when_ready(released.set, lambda _summary: None)
        assert captured.value.category == "backend_telemetry_failed"
        assert not released.is_set()
    finally:
        events.allow_eof.set()
        monitor.close()


def test_backend_release_waits_for_stable_quiescent_summary() -> None:
    observer = _Observer(
        [
            {"observer": 1},
            {"observer": 1},
            {"observer": 1, "ambient_client": 1},
            {"observer": 1},
            {"observer": 1},
        ]
    )
    events = _EventReader()
    monitor = BackendOwnershipMonitor(
        connection_factory=_Connection,
        event_reader=events,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: observer,
        descriptor_closer=lambda _fd: None,
    )
    released = Event()

    def validate(summary) -> None:
        if summary.get("ambient_client", 0):
            raise ValueError("not quiescent")

    try:
        monitor.start()
        assert monitor.startup_summary() == {"observer": 1}

        assert monitor.release_when_ready(released.set, validate) == {
            "observer": 1
        }
        assert released.is_set()
    finally:
        events.allow_eof.set()
        monitor.close()


def test_backend_pre_release_summary_is_one_transient_sample() -> None:
    observer = _Observer(
        [
            {"observer": 1},
            {"observer": 1},
            {"observer": 1},
        ]
    )
    events = _EventReader()
    monitor = BackendOwnershipMonitor(
        connection_factory=_Connection,
        event_reader=events,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: observer,
        descriptor_closer=lambda _fd: None,
    )
    try:
        monitor.start()
        assert monitor.startup_summary() == {"observer": 1}

        assert monitor.pre_release_summary() == {"observer": 1}
    finally:
        events.allow_eof.set()
        monitor.close()


def test_backend_release_exposes_both_samples_and_final_atomic_boundary() -> None:
    observer = _Observer(
        [
            {"observer": 1},
            {"observer": 1},
            {"observer": 1},
            {"observer": 1},
            {"observer": 1},
        ]
    )
    events = _EventReader()
    monitor = BackendOwnershipMonitor(
        connection_factory=_Connection,
        event_reader=events,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: observer,
        descriptor_closer=lambda _fd: None,
    )
    order: list[str | tuple[str, bool]] = []
    try:
        monitor.start()
        assert monitor.startup_summary() == {"observer": 1}

        monitor.release_when_ready(
            lambda: order.append("release"),
            lambda _summary: None,
            stable_samples=lambda first, second: order.append(
                ("samples", first <= second)
            ),
            before_release=lambda: order.append("ready"),
        )

        assert order == [("samples", True), "ready", "release"]
    finally:
        events.allow_eof.set()
        monitor.close()


def test_backend_release_reuses_validated_pre_release_sample() -> None:
    observer = _Observer(
        [
            {"observer": 1},
            {"observer": 1},
            {"observer": 1},
            {"observer": 1},
        ]
    )
    events = _EventReader()
    monitor = BackendOwnershipMonitor(
        connection_factory=_Connection,
        event_reader=events,
        event_stream=object(),
        acknowledgement_fd=1,
        observer_factory=lambda: observer,
        descriptor_closer=lambda _fd: None,
    )
    samples = []
    released = Event()
    try:
        monitor.start()
        assert monitor.startup_summary() == {"observer": 1}
        assert monitor.pre_release_summary() == {"observer": 1}

        assert monitor.release_when_ready(
            released.set,
            lambda _summary: None,
            stable_samples=lambda first, second: samples.append(
                (first, second)
            ),
            initial_stable_sample_ns=1,
        ) == {"observer": 1}

        assert released.is_set()
        assert len(samples) == 1
        assert samples[0][0] == 1
        assert samples[0][1] > samples[0][0]
    finally:
        events.allow_eof.set()
        monitor.close()
