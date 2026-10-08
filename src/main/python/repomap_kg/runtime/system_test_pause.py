"""Shared producer/consumer pause-window contract for disabled test hooks."""

from __future__ import annotations

SYSTEM_TEST_PRODUCER_PAUSE_SECONDS: float = 90.0
SYSTEM_TEST_CONSUMER_DEADLINE_SECONDS: float = 20.0
SYSTEM_TEST_CONSUMER_EXEC_TIMEOUT_SECONDS: float = 25.0
SYSTEM_TEST_STATUS_TIMEOUT_SECONDS: float = 5.0
SYSTEM_TEST_CONTROL_READBACK_TIMEOUT_SECONDS: float = 5.0
SYSTEM_TEST_SUBMISSION_REAP_TIMEOUT_SECONDS: float = 3.0
SYSTEM_TEST_INTERRUPTION_TIMEOUT_SECONDS: float = 10.0
SYSTEM_TEST_PAUSE_SAFETY_MARGIN_SECONDS: float = 10.0


def validate_pause_window_contract(
    producer_pause: float | None = None,
    consumer_deadline: float | None = None,
    consumer_exec_timeout: float | None = None,
    safety_margin: float | None = None,
    *,
    status_timeout: float | None = None,
    control_readback_timeout: float | None = None,
    submission_reap_timeout: float | None = None,
    interruption_timeout: float | None = None,
) -> None:
    """Bound every operation through the interruption while the producer pauses."""
    import math
    pause = SYSTEM_TEST_PRODUCER_PAUSE_SECONDS if producer_pause is None else producer_pause
    deadline = SYSTEM_TEST_CONSUMER_DEADLINE_SECONDS if consumer_deadline is None else consumer_deadline
    execution = SYSTEM_TEST_CONSUMER_EXEC_TIMEOUT_SECONDS if consumer_exec_timeout is None else consumer_exec_timeout
    margin = SYSTEM_TEST_PAUSE_SAFETY_MARGIN_SECONDS if safety_margin is None else safety_margin
    bounds = (
        execution,
        SYSTEM_TEST_STATUS_TIMEOUT_SECONDS if status_timeout is None else status_timeout,
        SYSTEM_TEST_CONTROL_READBACK_TIMEOUT_SECONDS if control_readback_timeout is None else control_readback_timeout,
        SYSTEM_TEST_SUBMISSION_REAP_TIMEOUT_SECONDS if submission_reap_timeout is None else submission_reap_timeout,
        SYSTEM_TEST_INTERRUPTION_TIMEOUT_SECONDS if interruption_timeout is None else interruption_timeout,
    )
    if any(not math.isfinite(value) or value <= 0 for value in (pause, deadline, margin, *bounds)):
        raise ValueError("Pause window bounds must be finite and positive")
    if execution <= deadline:
        raise ValueError("Consumer execution timeout must exceed consumer deadline")
    # Marker deadline is nested within its execution bound. Reap can require
    # both a graceful wait and a kill wait, so account for it twice.
    protected = bounds[0] + bounds[1] + bounds[2] + 2 * bounds[3] + bounds[4] + margin
    if protected >= pause:
        raise ValueError("Total window budget must be strictly less than producer pause")

