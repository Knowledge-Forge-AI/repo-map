from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest

from repomap_kg.storage.staged_ingestion import (
    _install_connection_signal_handlers,
    _restore_connection_signal_handlers,
)


class FakeConnection:
    def __init__(self, *, cancel_safe_error: Exception | None = None) -> None:
        self.cancel_safe_error = cancel_safe_error
        self.cancel_safe_calls: list[float] = []
        self.cancel_calls = 0

    def cancel_safe(self, *, timeout: float) -> None:
        self.cancel_safe_calls.append(timeout)
        if self.cancel_safe_error is not None:
            raise self.cancel_safe_error

    def cancel(self) -> None:
        self.cancel_calls += 1


def test_signal_handlers_request_bounded_database_cancellation() -> None:
    connection = FakeConnection()
    installed: dict[object, Callable[..., Any]] = {}

    def install(signal_number: object, handler: Callable[..., Any]) -> None:
        installed[signal_number] = handler

    with patch(
        "repomap_kg.storage.staged_ingestion.signal.getsignal",
        return_value="previous",
    ), patch(
        "repomap_kg.storage.staged_ingestion.signal.signal",
        side_effect=install,
    ):
        previous = _install_connection_signal_handlers(connection)

    assert len(installed) == 2
    assert set(previous.values()) == {"previous"}
    for handler in installed.values():
        with pytest.raises(KeyboardInterrupt):
            handler(2, None)
    assert connection.cancel_safe_calls == [1.0, 1.0]
    assert connection.cancel_calls == 0


def test_signal_handler_falls_back_to_legacy_cancel_api() -> None:
    connection = FakeConnection(cancel_safe_error=RuntimeError("unsupported"))
    installed: dict[object, Callable[..., Any]] = {}

    with patch(
        "repomap_kg.storage.staged_ingestion.signal.getsignal",
        return_value="previous",
    ), patch(
        "repomap_kg.storage.staged_ingestion.signal.signal",
        side_effect=lambda signal_number, handler: installed.__setitem__(
            signal_number, handler
        ),
    ):
        previous = _install_connection_signal_handlers(connection)
        with pytest.raises(KeyboardInterrupt):
            next(iter(installed.values()))(15, None)
        _restore_connection_signal_handlers(previous)

    assert connection.cancel_calls == 1
