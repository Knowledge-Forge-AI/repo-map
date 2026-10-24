"""Failure custody for the D12 candidate owner's cleanup (ADR 0087 D12-A, ADR 0089 D10).

The owner's cleanup steps and its cleanup report must never replace the
initiating failure. ``run_candidate_cleanup`` is the one rule the owner uses
and the unit owner exercises without any build:

* a cleanup failure with a primary failure annotates the primary, which the
  caller then re-raises;
* a cleanup failure without a primary is raised after the report is written;
* a report write failure annotates the primary or cleanup failure, and is
  raised only when there is neither.
"""

from __future__ import annotations

from typing import Callable

CleanupSteps = Callable[[dict[str, object]], None]
ReportWriter = Callable[[str, dict[str, object]], object]


def run_candidate_cleanup(
    primary: BaseException | None, steps: CleanupSteps, write_report: ReportWriter
) -> dict[str, object]:
    """Run ``steps`` into one cleanup record, write it, and preserve every failure."""
    record: dict[str, object] = {}
    cleanup_failure: BaseException | None = None
    try:
        steps(record)
    except BaseException as error:
        record["error"] = f"{type(error).__name__}: {error}"
        if primary is None:
            cleanup_failure = error
        else:
            primary.add_note("D12 candidate cleanup also failed; see cleanup report")
    record["primary"] = None if primary is None else f"{type(primary).__name__}: {primary}"[:4000]
    try:
        write_report("cleanup", record)
    except Exception as write_error:
        initiating = primary or cleanup_failure
        if initiating is None:
            raise
        initiating.add_note(f"D12 cleanup report could not be written ({type(write_error).__name__})")
    if cleanup_failure is not None:
        raise cleanup_failure
    return record


__all__ = ["run_candidate_cleanup"]
