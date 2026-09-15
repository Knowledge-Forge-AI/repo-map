"""Structurally test-only acknowledged event blocking for SCALE14."""

from __future__ import annotations

from threading import Event
from typing import Callable

from repomap_kg.storage.staging_operation_contracts import (
    STAGING_OPERATION_DESCRIPTORS,
)
from repomap_kg.storage.staging_phase_events import STAGING_PHASE_CODES


_CONTROL_CODES = frozenset((*STAGING_PHASE_CODES, *STAGING_OPERATION_DESCRIPTORS))


class TestEventControlChannel:
    """Proxy one product channel and block test execution after its normal ack."""

    __test__ = False

    def __init__(
        self,
        channel,
        *,
        selected_code: str,
        wait_seconds: float,
        blocker: Callable[[float], object] | None = None,
        blocker_entered: Callable[[], object] | None = None,
    ) -> None:
        if selected_code not in _CONTROL_CODES:
            raise ValueError("test event control code is invalid")
        if (
            isinstance(wait_seconds, bool)
            or not isinstance(wait_seconds, (int, float))
            or not 0 < wait_seconds <= 60
        ):
            raise ValueError("test event control wait is invalid")
        self._channel = channel
        self._selected_code = selected_code
        self._wait_seconds = float(wait_seconds)
        self._blocker = blocker or Event().wait
        self._blocker_entered = blocker_entered or (lambda: None)

    def send(self, category: str, payload: dict[str, object]) -> None:
        """Send and acknowledge first, then block only at the selected start."""

        self._channel.send(category, payload)
        code = payload.get("phase_code") or payload.get("operation_code")
        if payload.get("event_category") == "started" and code == self._selected_code:
            self._blocker_entered()
            self._blocker(self._wait_seconds)

    def close(self) -> None:
        """Close the underlying product channel exactly once."""

        self._channel.close()


__all__ = ["TestEventControlChannel"]
