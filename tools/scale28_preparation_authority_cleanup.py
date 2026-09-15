"""Cleanup, timing, and detached snapshot helpers for preparation authority."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from scale28_preparation_values import (
    PreparationState,
    ResourceBaseline,
)


class PreparationAuthorityError(RuntimeError):
    """One bounded fail-closed parent-authority result."""


def ceil_milliseconds(elapsed_ns: int) -> int:
    """Convert elapsed nanoseconds to milliseconds, ceiling-rounded."""
    if elapsed_ns < 0:
        raise PreparationAuthorityError("preparation timing is invalid")
    return (elapsed_ns + 999_999) // 1_000_000


def compute_final_release_elapsed_ms(
    final_deadline_ns: int | None,
    final_release_timeout_ms: int,
    clock_ns: Callable[[], int],
    *,
    ceil_milliseconds_fn: Callable[[int], int] = ceil_milliseconds,
) -> int | None:
    """Calculate elapsed milliseconds for the final release window."""
    if final_deadline_ns is None:
        return None
    final_started_ns = (
        final_deadline_ns - final_release_timeout_ms * 1_000_000
    )
    return ceil_milliseconds_fn(clock_ns() - final_started_ns)


@dataclass(frozen=True, slots=True)
class PreparationAuthoritySnapshot:
    """Point-in-time snapshot of authority state and timing facts."""

    state: PreparationState
    state_history: tuple[PreparationState, ...]
    attempt_failures: tuple[tuple[str, str], ...]
    refusal: str | None
    worker_observation_elapsed_ms: int | None
    parent_protocol_elapsed_ms: int | None
    acknowledgement_to_receipt_elapsed_ms: int | None
    process_settlement_elapsed_ms: int | None
    attempt_elapsed_ms: int | None
    final_release_elapsed_ms: int | None


@dataclass(frozen=True, slots=True)
class PreparedStartupResourceSample:
    """Detached launch-control projection of accepted immutable evidence."""

    baseline: ResourceBaseline = field(repr=False)

    @property
    def values(self) -> dict[str, int]:
        return {
            "client_peak_rss_bytes": self.baseline.client_peak_rss_bytes,
            "postgresql_container_rss_upper_bound": (
                self.baseline.postgresql_container_rss_upper_bound
            ),
            "temporary_byte_upper_bound_delta": (
                self.baseline.temporary_byte_upper_bound_delta
            ),
            "wal_upper_bound_delta": self.baseline.wal_upper_bound_delta,
            "concurrent_profiles": 1,
            "postgresql_pgdata_allocated_delta": (
                self.baseline.allocated_delta_bytes
            ),
            "postgresql_pgdata_backing_free_bytes": (
                self.baseline.backing_free_bytes
            ),
            "postgresql_pgdata_reader_elapsed_ns": (
                self.baseline.pgdata_reader_elapsed_ns
            ),
        }

    @property
    def availability(self) -> dict[str, str]:
        return {name: self.baseline.availability for name in self.values}


__all__ = [
    "PreparationAuthorityError",
    "PreparationAuthoritySnapshot",
    "PreparedStartupResourceSample",
    "ceil_milliseconds",
    "compute_final_release_elapsed_ms",
]
