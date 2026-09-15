"""Closed validation contracts for SCALE14 protected-launch supervision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from scale15_terminal_contracts import ControlFailure, ControlFailureCode


class Scale14SupervisorError(RuntimeError):
    """Raised when integrated actual-refresh supervision fails closed."""


@dataclass(frozen=True)
class ProtectedLaunchLimits:
    """Closed elapsed-time ceilings for one protected launch attempt."""

    attempt_seconds: int = 90 * 60
    phase_seconds: int = 30 * 60
    operation_seconds: int = 90
    final_transaction_seconds: int = 10 * 60

    def __post_init__(self) -> None:
        for value in (
            self.attempt_seconds,
            self.phase_seconds,
            self.operation_seconds,
            self.final_transaction_seconds,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("protected launch limit is invalid")


def validate_backend_summary(
    summary: Mapping[str, int],
    *,
    require_quiescent: bool = True,
) -> None:
    """Require bounded exact ownership and optional owned-backend quiescence."""

    if not isinstance(summary, Mapping) or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in summary.values()
    ):
        raise ControlFailure(ControlFailureCode.BACKEND_OWNERSHIP_UNKNOWN)
    if require_quiescent and (
        summary.get("direct_owned_client", 0)
        or summary.get("direct_owned_parallel_worker", 0)
    ):
        raise ControlFailure(ControlFailureCode.BACKEND_QUIESCENCE_TIMEOUT)
    if summary.get("ambient_client", 0):
        raise ControlFailure(ControlFailureCode.AMBIENT_CLIENT_DETECTED)
    if summary.get("unknown", 0):
        raise ControlFailure(ControlFailureCode.BACKEND_OWNERSHIP_UNKNOWN)


def validate_storage_baseline(sample) -> None:
    """Require the three exact storage authorities before supervision."""

    baseline_bytes = getattr(sample, "baseline_bytes", None)
    current_bytes = getattr(sample, "current_bytes", None)
    free_bytes = getattr(sample, "free_bytes", None)
    elapsed_ns = getattr(sample, "sampling_elapsed_ns", None)
    nonnegative_values = (baseline_bytes, current_bytes, free_bytes, elapsed_ns)
    if (
        getattr(sample, "metric_code", None)
        != "postgresql_pgdata_allocated_delta"
        or getattr(sample, "scope", None) != "owned_postgresql_pgdata"
        or getattr(sample, "availability", None) != "available"
        or getattr(sample, "delta_bytes", None) != 0
        or baseline_bytes != current_bytes
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in nonnegative_values
        )
    ):
        raise ControlFailure(ControlFailureCode.RESOURCE_READER_UNAVAILABLE)


def validate_required_resources(sample) -> None:
    """Fail closed when a required launch-control metric is unavailable."""

    required = {
        "client_peak_rss_bytes",
        "temporary_byte_upper_bound_delta",
        "wal_upper_bound_delta",
        "concurrent_profiles",
        "postgresql_pgdata_allocated_delta",
        "postgresql_pgdata_backing_free_bytes",
        "postgresql_pgdata_reader_elapsed_ns",
    }
    if any(sample.availability.get(code) != "available" for code in required):
        raise ControlFailure(ControlFailureCode.RESOURCE_READER_UNAVAILABLE)
    postgresql_rss = {
        "owned_postgresql_process_group_rss_bytes",
        "postgresql_container_rss_upper_bound",
    }
    if not any(
        sample.availability.get(code) == "available" for code in postgresql_rss
    ):
        raise ControlFailure(ControlFailureCode.RESOURCE_READER_UNAVAILABLE)


def validate_receipt_state(
    terminal_category: str,
    receipt_state: Mapping[str, object],
) -> None:
    """Require receipt-bearing success or fully reconciled cancellation."""

    if terminal_category == "completed":
        if receipt_state.get("receipt_complete") is not True:
            raise Scale14SupervisorError("completed refresh has no complete receipt")
        return
    if terminal_category == "cancelled" and (
        receipt_state.get("receipt_complete") is not False
        or receipt_state.get("final_row_count") != 0
    ):
        raise Scale14SupervisorError("cancelled refresh reconciliation is invalid")


__all__ = [
    "ProtectedLaunchLimits",
    "Scale14SupervisorError",
    "validate_backend_summary",
    "validate_receipt_state",
    "validate_required_resources",
    "validate_storage_baseline",
]
