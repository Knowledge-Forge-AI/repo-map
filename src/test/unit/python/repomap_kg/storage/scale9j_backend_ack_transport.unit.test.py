from __future__ import annotations

import os
from dataclasses import replace
from threading import Event, Thread
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from repomap_kg.storage.backend_connection_telemetry import BackendTelemetry
from repomap_kg.storage.backend_ownership import ConnectionRole
from repomap_kg.storage.backend_telemetry_events import (
    ConnectionTelemetryError,
    ConnectionTelemetryEvent,
    TelemetryEventKind,
    read_telemetry_event,
    telemetry_from_inherited_fds,
    write_telemetry_ready_ack,
)


class _Connection:
    def __init__(self) -> None:
        self.info = SimpleNamespace(backend_pid=1001)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_acknowledged_transport_blocks_source_until_matching_ready_ack() -> None:
    event_read_fd, event_write_fd = os.pipe()
    ack_read_fd, ack_write_fd = os.pipe()
    connection = _Connection()
    returned = Event()
    result: list[Any] = []
    errors: list[BaseException] = []
    try:
        telemetry = telemetry_from_inherited_fds(
            event_write_fd,
            ack_read_fd,
            ready_ack_timeout_seconds=1.0,
            monotonic_ns=lambda: 123,
        )

        def track_connection() -> None:
            try:
                result.append(
                    telemetry.track(connection, ConnectionRole.DIRECT_STAGED_REFRESH)
                )
            except BaseException as error:
                errors.append(error)
            finally:
                returned.set()

        source = Thread(target=track_connection)
        source.start()
        with os.fdopen(event_read_fd, "rb", closefd=False) as events:
            opened = read_telemetry_event(events)
            ready = read_telemetry_event(events)

            assert opened is not None
            assert ready is not None
            assert opened.event is TelemetryEventKind.CONNECTION_OPENED
            assert ready.event is TelemetryEventKind.CONNECTION_READY
            assert not returned.wait(timeout=0.05)

            write_telemetry_ready_ack(ack_write_fd, ready)

            assert returned.wait(timeout=1.0)
            source.join(timeout=1.0)
            assert not source.is_alive()
            assert errors == []

            tracked = result[0]
            tracked.close()
            closed = read_telemetry_event(events)

    finally:
        for fd in (event_read_fd, event_write_fd, ack_read_fd, ack_write_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    assert connection.closed is True
    assert closed is not None
    assert closed.event is TelemetryEventKind.CONNECTION_CLOSED


def test_closed_acknowledgement_channel_fails_closed_and_reports_terminal_event() -> None:
    event_read_fd, event_write_fd = os.pipe()
    ack_read_fd, ack_write_fd = os.pipe()
    connection = _Connection()
    try:
        os.close(ack_write_fd)
        ack_write_fd = -1
        telemetry = telemetry_from_inherited_fds(
            event_write_fd,
            ack_read_fd,
            ready_ack_timeout_seconds=1.0,
            monotonic_ns=lambda: 123,
        )

        with pytest.raises(ConnectionTelemetryError, match="acknowledgement"):
            telemetry.track(connection, ConnectionRole.DIRECT_STAGED_REFRESH)

        with os.fdopen(event_read_fd, "rb", closefd=False) as events:
            observed = [
                read_telemetry_event(events),
                read_telemetry_event(events),
                read_telemetry_event(events),
            ]
    finally:
        for fd in (event_read_fd, event_write_fd, ack_read_fd, ack_write_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass

    assert connection.closed is True
    assert [event.event for event in observed if event is not None] == [
        TelemetryEventKind.CONNECTION_OPENED,
        TelemetryEventKind.CONNECTION_READY,
        TelemetryEventKind.CONNECTION_FAILED,
    ]


def test_mismatched_acknowledgement_fails_closed_without_releasing_source() -> None:
    event_read_fd, event_write_fd = os.pipe()
    ack_read_fd, ack_write_fd = os.pipe()
    connection = _Connection()
    returned = Event()
    errors: list[BaseException] = []
    try:
        telemetry = telemetry_from_inherited_fds(
            event_write_fd,
            ack_read_fd,
            ready_ack_timeout_seconds=1.0,
            monotonic_ns=lambda: 123,
        )

        def track_connection() -> None:
            try:
                telemetry.track(connection, ConnectionRole.DIRECT_STAGED_REFRESH)
            except BaseException as error:
                errors.append(error)
            finally:
                returned.set()

        source = Thread(target=track_connection)
        source.start()
        with os.fdopen(event_read_fd, "rb", closefd=False) as events:
            assert read_telemetry_event(events) is not None
            ready = read_telemetry_event(events)
            assert ready is not None
            write_telemetry_ready_ack(
                ack_write_fd,
                replace(
                    ready,
                    connection_generation=ready.connection_generation + 1,
                ),
            )

            assert returned.wait(timeout=1.0)
            source.join(timeout=1.0)
            assert not source.is_alive()
            failed = read_telemetry_event(events)
    finally:
        for fd in (event_read_fd, event_write_fd, ack_read_fd, ack_write_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    assert connection.closed is True
    assert len(errors) == 1
    assert isinstance(errors[0], ConnectionTelemetryError)
    assert failed is not None
    assert failed.event is TelemetryEventKind.CONNECTION_FAILED


def test_prior_instance_acknowledgement_cannot_release_a_new_instance() -> None:
    event_read_fd, event_write_fd = os.pipe()
    ack_read_fd, ack_write_fd = os.pipe()
    prior_events: list[ConnectionTelemetryEvent] = []
    source_connection = _Connection()
    try:
        with patch(
            "repomap_kg.storage.backend_connection_telemetry.secrets.randbits",
            side_effect=(10, 20),
        ):
            prior = BackendTelemetry(prior_events.append, monotonic_ns=lambda: 123)
            prior_connection = _Connection()
            prior_tracked = prior.track(
                prior_connection,
                ConnectionRole.DIRECT_STAGED_REFRESH,
            )
            prior_tracked.close()
            prior_ready = next(
                event
                for event in prior_events
                if event.event is TelemetryEventKind.CONNECTION_READY
            )
            write_telemetry_ready_ack(ack_write_fd, prior_ready)

            telemetry = telemetry_from_inherited_fds(
                event_write_fd,
                ack_read_fd,
                ready_ack_timeout_seconds=1.0,
                monotonic_ns=lambda: 123,
            )
            with pytest.raises(ConnectionTelemetryError, match="acknowledgement"):
                telemetry.track(source_connection, ConnectionRole.DIRECT_STAGED_REFRESH)

        with os.fdopen(event_read_fd, "rb", closefd=False) as events:
            assert read_telemetry_event(events) is not None
            ready = read_telemetry_event(events)
            failed = read_telemetry_event(events)
    finally:
        for fd in (event_read_fd, event_write_fd, ack_read_fd, ack_write_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    assert prior_ready.connection_sequence == 11
    assert ready is not None
    assert ready.connection_sequence == 21
    assert failed is not None
    assert failed.event is TelemetryEventKind.CONNECTION_FAILED
    assert source_connection.closed is True


def test_acknowledged_transport_requires_opposite_fifo_directions() -> None:
    event_read_fd, event_write_fd = os.pipe()
    ack_read_fd, ack_write_fd = os.pipe()
    try:
        with pytest.raises(ConnectionTelemetryError, match="telemetry channel"):
            telemetry_from_inherited_fds(event_read_fd, ack_read_fd)
        with pytest.raises(ConnectionTelemetryError, match="telemetry channel"):
            telemetry_from_inherited_fds(event_write_fd, ack_write_fd)
    finally:
        for fd in (event_read_fd, event_write_fd, ack_read_fd, ack_write_fd):
            try:
                os.close(fd)
            except OSError:
                pass
