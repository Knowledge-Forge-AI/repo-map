from __future__ import annotations

from typing import Callable

from repomap_kg.cli.staging_event_instrumentation import (
    staging_event_instrumentation,
)
from repomap_kg.storage.authority import AttemptNumber, JobId
from repomap_kg.storage.publication import RunPublicationAttempt
from repomap_kg.storage.staging_event_transport import StagingEventChannel


class _FakeChannel(StagingEventChannel):
    def __init__(
        self,
        on_send: Callable[[str, dict[str, object]], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self._on_send = on_send
        self._on_close = on_close

    def send(self, category: str, payload: dict[str, object]) -> None:
        if self._on_send is not None:
            self._on_send(category, payload)

    def close(self) -> None:
        if self._on_close is not None:
            self._on_close()


def test_scale13_staging_instrumentation_is_absent_without_descriptor() -> None:
    with staging_event_instrumentation(None) as measurements:
        assert measurements is None


def test_scale13_staging_instrumentation_sends_and_closes() -> None:
    frames: list[tuple[str, dict[str, object]]] = []
    closed: list[bool] = []
    channel = _FakeChannel(
        on_send=lambda category, payload: frames.append((category, payload)),
        on_close=lambda: closed.append(True),
    )
    with staging_event_instrumentation(
        9,
        channel_factory=lambda _fd: channel,
    ) as measurements:
        assert measurements is not None
        with measurements.phase("refresh.extraction"):
            pass

    assert [category for category, _payload in frames] == ["phase", "phase"]
    assert closed == [True]


def test_scale16_staging_instrumentation_sends_one_authority_event() -> None:
    frames: list[tuple[str, dict[str, object]]] = []
    channel = _FakeChannel(
        on_send=lambda category, payload: frames.append((category, payload)),
    )
    attempt = RunPublicationAttempt(JobId("direct-scale16"), AttemptNumber(1))

    with staging_event_instrumentation(
        9,
        channel_factory=lambda _fd: channel,
    ) as measurements:
        assert measurements is not None
        measurements.bind_direct_publication_attempt(attempt)

    assert [category for category, _payload in frames] == ["authority"]
    assert frames[0][1]["publication_identity"] == "direct-scale16"


def test_scale16_staging_instrumentation_rejects_duplicate_authority() -> None:
    channel = _FakeChannel()
    attempt = RunPublicationAttempt(JobId("direct-scale16"), AttemptNumber(1))

    with staging_event_instrumentation(
        9,
        channel_factory=lambda _fd: channel,
    ) as measurements:
        assert measurements is not None
        measurements.bind_direct_publication_attempt(attempt)
        try:
            measurements.bind_direct_publication_attempt(attempt)
        except ValueError as error:
            assert str(error) == "direct launch authority is already bound"
        else:
            raise AssertionError("duplicate authority was accepted")
