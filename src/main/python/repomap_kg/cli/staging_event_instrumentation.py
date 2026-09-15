"""Private actual-refresh event instrumentation construction."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator

from repomap_kg.storage.staging_event_transport import (
    StagingEventChannel,
    staging_event_channel_from_inherited_fd,
)
from repomap_kg.storage.staging_observability import StagingMeasurements


@contextmanager
def staging_event_instrumentation(
    event_fd: int | None,
    *,
    channel_factory: Callable[[int], StagingEventChannel] = (
        staging_event_channel_from_inherited_fd
    ),
    measurements_factory=StagingMeasurements,
) -> Iterator[StagingMeasurements | None]:
    """Build and close one hidden event channel around an actual refresh."""

    if event_fd is None:
        yield None
        return
    channel = channel_factory(event_fd)

    def send(category, event) -> None:
        channel.send(category, event.to_payload())

    try:
        yield measurements_factory(
            lambda event: send("measurement", event),
            operation_sink=lambda event: send("operation", event),
            phase_sink=lambda event: send("phase", event),
            authority_sink=lambda event: send("authority", event),
        )
    finally:
        channel.close()


__all__ = ["staging_event_instrumentation"]
