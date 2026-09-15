from __future__ import annotations

from types import SimpleNamespace

import pytest

from repomap_kg.storage.backend_connection_telemetry import BackendTelemetry
from repomap_kg.storage.backend_ownership import ConnectionRole
from repomap_kg.storage.staged_connection_telemetry import open_owned_connection


class _InterruptingConnection:
    def __init__(self) -> None:
        self.closed = False

    @property
    def info(self):
        raise KeyboardInterrupt

    def close(self) -> None:
        self.closed = True


class _Connection:
    def __init__(self) -> None:
        self.info = SimpleNamespace(backend_pid=1201)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_tracking_preserves_async_interruption_and_closes_connection() -> None:
    connection = _InterruptingConnection()
    telemetry = BackendTelemetry(lambda event: None)

    with pytest.raises(KeyboardInterrupt):
        telemetry.track(connection, ConnectionRole.DIRECT_STAGED_REFRESH)

    assert connection.closed is True


def test_factory_interruption_is_not_masked_by_telemetry_channel_failure() -> None:
    telemetry = BackendTelemetry(lambda event: (_ for _ in ()).throw(OSError()))

    def interrupting_factory(**params):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        open_owned_connection(
            interrupting_factory,
            {},
            role=ConnectionRole.DIRECT_STAGED_REFRESH,
            telemetry=telemetry,
        )


def test_terminal_telemetry_failure_does_not_mask_active_interruption() -> None:
    def sink(event) -> None:
        if event.event.value == "connection_closed":
            raise OSError()

    connection = _Connection()
    tracked = BackendTelemetry(sink).track(
        connection,
        ConnectionRole.DIRECT_STAGED_REFRESH,
    )

    def interrupt_and_close() -> None:
        try:
            raise KeyboardInterrupt
        finally:
            tracked.close()

    with pytest.raises(KeyboardInterrupt):
        interrupt_and_close()

    assert connection.closed is True
