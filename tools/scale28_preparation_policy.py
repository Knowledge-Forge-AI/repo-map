"""Selected private production policy for hybrid startup preparation."""

from __future__ import annotations

from scale28_preparation_values import PreparationDeadlinePolicy


DEFAULT_PREPARATION_DEADLINE_POLICY = PreparationDeadlinePolicy(
    attempt_timeout_ms=3_400,
    total_timeout_ms=8_900,
    final_release_timeout_ms=600,
    observation_transfer_reserve_ms=100,
    acknowledgement_timeout_ms=150,
    receipt_timeout_ms=300,
    process_settlement_timeout_ms=300,
    freshness_lease_ms=800,
    maximum_attempts=2,
)


__all__ = ["DEFAULT_PREPARATION_DEADLINE_POLICY"]
