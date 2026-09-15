from __future__ import annotations

import io
import json
import os
import struct
from types import SimpleNamespace
from typing import Callable
from unittest.mock import patch

import pytest

from repomap_kg.storage.backend_connection_telemetry import BackendTelemetry
from repomap_kg.storage.backend_ownership import ConnectionRole
from repomap_kg.storage.backend_telemetry_events import (
    MAX_TELEMETRY_FRAME_BYTES,
    ConnectionTelemetryError,
    ConnectionTelemetryEvent,
    TelemetryEventKind,
    frame_telemetry_event,
    parse_telemetry_frame,
    read_telemetry_event,
    telemetry_from_inherited_fd,
)
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.staged_connection_telemetry import open_owned_connection


def _event(
    kind: TelemetryEventKind = TelemetryEventKind.CONNECTION_READY,
    *,
    schema_version: int = 1,
    connection_sequence: int = 1,
    connection_generation: int = 1,
    connection_role: ConnectionRole = ConnectionRole.DIRECT_STAGED_REFRESH,
    backend_pid: int | None = 1001,
    monotonic_ns: int = 123,
) -> ConnectionTelemetryEvent:
    return ConnectionTelemetryEvent(
        schema_version=schema_version,
        connection_sequence=connection_sequence,
        connection_generation=connection_generation,
        connection_role=connection_role,
        backend_pid=backend_pid,
        event=kind,
        monotonic_ns=monotonic_ns,
    )


class _Connection:
    def __init__(self, backend_pid: int = 1001, *, close_error: Exception | None = None) -> None:
        self.info = SimpleNamespace(backend_pid=backend_pid)
        self.close_error = close_error
        self.closed = False

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda: _event(schema_version=2), "schema version"),
        (lambda: _event(connection_sequence=0), "connection sequence"),
        (lambda: _event(connection_generation=0), "connection generation"),
        (lambda: _event(backend_pid=0), "backend PID"),
        (lambda: _event(backend_pid=None), "backend PID is required"),
        (lambda: _event(monotonic_ns=-1), "timestamp"),
    ],
)
def test_event_validation_rejects_invalid_lifecycle_fields(
    mutate: Callable[[], ConnectionTelemetryEvent],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        mutate()


def test_failed_connection_event_may_omit_a_backend_pid() -> None:
    event = _event(
        TelemetryEventKind.CONNECTION_FAILED,
        backend_pid=None,
    )

    assert event.backend_pid is None
    assert parse_telemetry_frame(frame_telemetry_event(event)) == event


def _frame_from_payload(payload: object) -> bytes:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return struct.pack("!I", len(encoded)) + encoded


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"unexpected": "field"},
        {**_event().to_payload(), "backend_pid": True},
        {**_event().to_payload(), "backend_pid": "not-an-int"},
        {**_event().to_payload(), "connection_role": 7},
        {**_event().to_payload(), "event": 7},
        {**_event().to_payload(), "monotonic_ns": True},
    ],
)
def test_parser_rejects_noncanonical_or_malformed_payloads(payload: object) -> None:
    with pytest.raises(ConnectionTelemetryError, match="telemetry frame"):
        parse_telemetry_frame(_frame_from_payload(payload))


def test_parser_and_reader_reject_truncated_or_oversized_input() -> None:
    with pytest.raises(ConnectionTelemetryError, match="telemetry frame"):
        parse_telemetry_frame(b"\x00\x00")
    with pytest.raises(ConnectionTelemetryError, match="telemetry frame"):
        parse_telemetry_frame(b"\x00\x00\x00\x02{")
    with pytest.raises(ConnectionTelemetryError, match="telemetry frame"):
        read_telemetry_event(
            io.BytesIO(struct.pack("!I", MAX_TELEMETRY_FRAME_BYTES + 1))
        )
    with pytest.raises(ConnectionTelemetryError, match="telemetry frame"):
        read_telemetry_event(io.BytesIO(b"\x00\x00"))


def test_framing_rejects_payloads_larger_than_its_fixed_bound(monkeypatch) -> None:
    monkeypatch.setattr(
        "repomap_kg.storage.backend_telemetry_events.MAX_TELEMETRY_FRAME_BYTES",
        1,
    )

    with pytest.raises(ConnectionTelemetryError, match="telemetry frame"):
        frame_telemetry_event(_event())


class _ChunkedReader(io.BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self._content = content

    def read(self, size: int | None = -1) -> bytes:
        if not self._content:
            return b""
        result = self._content[:1]
        self._content = self._content[1:]
        return result


def test_reader_handles_clean_eof_and_chunked_frames() -> None:
    assert read_telemetry_event(io.BytesIO()) is None
    event = _event()

    assert read_telemetry_event(_ChunkedReader(frame_telemetry_event(event))) == event


def test_inherited_pipe_requires_a_writable_fifo_descriptor() -> None:
    read_fd, write_fd = os.pipe()
    try:
        with pytest.raises(ConnectionTelemetryError, match="telemetry channel"):
            telemetry_from_inherited_fd(read_fd)
        with pytest.raises(ConnectionTelemetryError, match="telemetry channel"):
            telemetry_from_inherited_fd(-1)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_inherited_pipe_rejects_a_non_fifo_descriptor() -> None:
    fd = os.open(__file__, os.O_RDONLY)
    try:
        with pytest.raises(ConnectionTelemetryError, match="telemetry channel"):
            telemetry_from_inherited_fd(fd)
    finally:
        os.close(fd)


def test_pipe_write_failures_close_the_source_connection() -> None:
    read_fd, write_fd = os.pipe()
    connection = _Connection()
    try:
        telemetry = telemetry_from_inherited_fd(write_fd, monotonic_ns=lambda: 123)
        with patch(
            "repomap_kg.storage.backend_telemetry_events.os.write",
            side_effect=OSError(),
        ):
            with pytest.raises(ConnectionTelemetryError, match="telemetry"):
                telemetry.track(connection, ConnectionRole.DIRECT_STAGED_REFRESH)
    finally:
        os.close(read_fd)
        os.close(write_fd)

    assert connection.closed is True


def test_partial_pipe_write_is_a_bounded_transport_failure() -> None:
    read_fd, write_fd = os.pipe()
    connection = _Connection()
    try:
        telemetry = telemetry_from_inherited_fd(write_fd, monotonic_ns=lambda: 123)
        with patch(
            "repomap_kg.storage.backend_telemetry_events.os.write",
            return_value=1,
        ):
            with pytest.raises(ConnectionTelemetryError, match="telemetry"):
                telemetry.track(connection, ConnectionRole.DIRECT_STAGED_REFRESH)
    finally:
        os.close(read_fd)
        os.close(write_fd)

    assert connection.closed is True


def test_terminal_telemetry_failure_is_visible_after_raw_connection_closes() -> None:
    events: list[ConnectionTelemetryEvent] = []

    def sink(event: ConnectionTelemetryEvent) -> None:
        if event.event is TelemetryEventKind.CONNECTION_CLOSED:
            raise OSError()
        events.append(event)

    connection = _Connection()
    tracked = BackendTelemetry(sink, monotonic_ns=lambda: 123).track(
        connection,
        ConnectionRole.DIRECT_STAGED_REFRESH,
    )

    with pytest.raises(ConnectionTelemetryError, match="telemetry channel"):
        tracked.close()

    assert connection.closed is True
    assert events[-1].event is TelemetryEventKind.CONNECTION_READY


def test_raw_close_failure_remains_visible_after_failure_event_attempt() -> None:
    events: list[ConnectionTelemetryEvent] = []
    connection = _Connection(close_error=RuntimeError("raw close failed"))
    tracked = BackendTelemetry(events.append, monotonic_ns=lambda: 123).track(
        connection,
        ConnectionRole.DIRECT_STAGED_REFRESH,
    )

    with pytest.raises(RuntimeError, match="raw close failed"):
        tracked.close()

    assert events[-1].event is TelemetryEventKind.CONNECTION_FAILED


def test_raw_close_error_is_not_masked_by_a_failed_terminal_notification() -> None:
    connection = _Connection(close_error=RuntimeError("raw close failed"))

    def sink(event: ConnectionTelemetryEvent) -> None:
        if event.event is TelemetryEventKind.CONNECTION_FAILED:
            raise OSError()

    telemetry = BackendTelemetry(
        sink,
        monotonic_ns=lambda: 123,
    )
    tracked = telemetry.track(
        connection,
        ConnectionRole.DIRECT_STAGED_REFRESH,
    )

    with pytest.raises(RuntimeError, match="raw close failed"):
        tracked.close()


@pytest.mark.parametrize("backend_pid", [True, 0])
def test_invalid_backend_pid_fails_closed_and_closes_best_effort(
    backend_pid: int | bool,
) -> None:
    connection = _Connection(close_error=RuntimeError("close failed"))
    connection.info.backend_pid = backend_pid

    with pytest.raises(ConnectionTelemetryError, match="connection is unavailable"):
        BackendTelemetry(lambda _event: None).track(
            connection,
            ConnectionRole.DIRECT_STAGED_REFRESH,
        )

    assert connection.closed is True


def test_tracked_connection_delegates_and_only_closes_once() -> None:
    events: list[ConnectionTelemetryEvent] = []
    connection = _Connection()
    tracked = BackendTelemetry(events.append, monotonic_ns=lambda: 123).track(
        connection,
        ConnectionRole.DIRECT_STAGED_REFRESH,
    )

    assert tracked.info.backend_pid == 1001
    tracked.close()
    tracked.close()

    assert connection.closed is True
    assert [event.event for event in events].count(
        TelemetryEventKind.CONNECTION_CLOSED
    ) == 1


def test_connection_factory_and_owner_acknowledgement_fail_closed() -> None:
    failing_telemetry = BackendTelemetry(
        lambda _event: (_ for _ in ()).throw(OSError()),
    )

    def failing_factory(**_params):
        raise RuntimeError("factory failed")

    with pytest.raises(StorageSchemaError, match="backend ownership telemetry"):
        open_owned_connection(
            failing_factory,
            {},
            role=ConnectionRole.DIRECT_STAGED_REFRESH,
            telemetry=failing_telemetry,
        )

    connection = _Connection()
    telemetry = BackendTelemetry(
        lambda _event: None,
        ownership_sink=lambda _event, _source: (_ for _ in ()).throw(OSError()),
    )
    with pytest.raises(ConnectionTelemetryError, match="ownership observer"):
        telemetry.track(connection, ConnectionRole.DIRECT_STAGED_REFRESH)

    assert connection.closed is True


def test_staged_connection_wraps_post_open_telemetry_failure() -> None:
    connection = _Connection()
    telemetry = BackendTelemetry(
        lambda _event: (_ for _ in ()).throw(OSError()),
    )

    with pytest.raises(StorageSchemaError, match="backend ownership telemetry"):
        open_owned_connection(
            lambda **_params: connection,
            {},
            role=ConnectionRole.DIRECT_STAGED_REFRESH,
            telemetry=telemetry,
        )

    assert connection.closed is True


def test_uninstrumented_factory_error_is_preserved() -> None:
    def failing_factory(**_params):
        raise RuntimeError("factory failed")

    with pytest.raises(RuntimeError, match="factory failed"):
        open_owned_connection(
            failing_factory,
            {},
            role=ConnectionRole.DIRECT_STAGED_REFRESH,
            telemetry=None,
        )


def test_uninstrumented_connection_factory_remains_unchanged() -> None:
    connection = _Connection()

    opened = open_owned_connection(
        lambda **_params: connection,
        {},
        role=ConnectionRole.DIRECT_STAGED_REFRESH,
        telemetry=None,
    )

    assert opened is connection
