"""Parent-owned final handoff for hybrid startup preparation."""

from __future__ import annotations

import time
from typing import Callable, Mapping

from actual_refresh_startup import StartupReadinessError


def validate_startup_summary(backend_monitor, summary, validator) -> None:
    """Validate startup ownership inside the live observer session."""

    validate = getattr(backend_monitor, "validate_summary", None)
    if callable(validate):
        validate(summary, validator)
    else:
        validator(summary)


def prepare_startup_resources(
    preparation_authority,
    resource_sampler,
    validator,
):
    """Prepare, validate, accept, and settle startup resource authority."""

    sample = (
        preparation_authority.prepare()
        if preparation_authority is not None
        else resource_sampler.capture(force=False)
    )
    if sample is None:
        raise StartupReadinessError(
            "startup resource authorities are unavailable"
        )
    validator(sample)
    if preparation_authority is not None:
        accept = getattr(resource_sampler, "accept_preparation_baseline", None)
        if not callable(accept):
            raise StartupReadinessError(
                "prepared resource authority is unavailable"
            )
        accept(sample.baseline)
    else:
        settle = getattr(resource_sampler, "settle_startup", None)
        if callable(settle):
            settle()
    return sample


def prepare_parent_startup_authorities(
    startup,
    backend_monitor,
    resource_sampler,
    preparation_authority,
    event_pump,
    failure_collector,
    *,
    event_receiver_timeout_seconds: float,
    summary_validator,
    resource_validator,
) -> None:
    """Ready the parent observers, resources, and failure receivers."""

    startup_timeout = getattr(
        preparation_authority,
        "startup_handoff_timeout_seconds",
        None,
    )
    startup_summary = (
        backend_monitor.startup_summary()
        if startup_timeout is None
        else backend_monitor.startup_summary(
            timeout_seconds=startup_timeout,
        )
    )
    validate_startup_summary(
        backend_monitor,
        startup_summary,
        summary_validator,
    )
    startup.mark_backend_observer_ready()
    prepare_startup_resources(
        preparation_authority,
        resource_sampler,
        resource_validator,
    )
    startup.mark_resource_authorities_ready()
    if event_pump is None:
        raise StartupReadinessError("startup event receiver is unavailable")
    event_pump.start(timeout_seconds=event_receiver_timeout_seconds)
    startup.mark_event_receiver_ready()
    if not callable(failure_collector):
        raise StartupReadinessError("startup failure collector is unavailable")
    startup.mark_failure_collector_ready()


def release_prepared_child(
    preparation_authority,
    backend_monitor,
    startup,
    summary_validator: Callable[[Mapping[str, int]], None],
) -> None:
    """Prove final readiness and atomically release one blocked child."""

    preparation_authority.open_final_readiness()
    remaining = preparation_authority.final_release_remaining_seconds
    transient_summary = backend_monitor.pre_release_summary(
        timeout_seconds=remaining,
    )
    validate_summary = getattr(backend_monitor, "validate_summary", None)
    if callable(validate_summary):
        validate_summary(
            transient_summary,
            summary_validator,
            timeout_seconds=(
                preparation_authority.final_release_remaining_seconds
            ),
        )
    else:
        summary_validator(transient_summary)
    initial_stable_sample_ns = time.monotonic_ns()
    preparation_authority.mark_transient_ownership_clear()

    def release() -> None:
        startup.release()
        preparation_authority.mark_child_released()

    release_arguments = {
        "stable_samples": preparation_authority.mark_stable_samples,
        "before_release": preparation_authority.mark_ready_to_release,
        "initial_stable_sample_ns": initial_stable_sample_ns,
    }
    remaining = preparation_authority.final_release_remaining_seconds
    if isinstance(remaining, (int, float)):
        release_arguments["timeout_seconds"] = remaining
    backend_monitor.release_when_ready(
        release,
        summary_validator,
        **release_arguments,
    )


__all__ = [
    "prepare_parent_startup_authorities",
    "prepare_startup_resources",
    "release_prepared_child",
    "validate_startup_summary",
]
