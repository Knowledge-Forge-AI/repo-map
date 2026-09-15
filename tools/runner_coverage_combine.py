"""Coverage combine warning attribution and owned data settlement."""

from __future__ import annotations

import json
from pathlib import Path
import tracemalloc
from typing import Any, Callable
import warnings


def close_owned_runners(runners: tuple[Any, ...]) -> None:
    """Attempt every owned close while preserving the first failure."""
    failure: BaseException | None = None
    for runner in runners:
        try:
            close_runner_data(runner)
        except BaseException as error:
            if failure is None:
                failure = error
            else:
                failure.add_note(f"additional owned data cleanup failed: {error}")
    if failure is not None:
        raise failure


def close_runner_data(runner: Any) -> None:
    """Close a caller-stopped owned runner; refuse the current collector.

    Callers must stop all owned collectors first, including suspended ones.
    This guard does not inspect the ambient collector stack.
    """
    if runner is None or not callable(getattr(runner, "get_data", None)):
        return
    import coverage

    if runner is coverage.Coverage.current():
        raise RuntimeError("cannot settle an active owned coverage collector")
    data = runner.get_data()
    if callable(getattr(data, "close", None)):
        data.close(force=True)


def combine_and_reload(accumulator: Any, combine: Callable[[], None]) -> None:
    """Retain a successful accumulator for reporting; settle failed attempts."""
    try:
        combine()
        accumulator.save()
        accumulator.load()
    except BaseException as failure:
        try:
            close_runner_data(accumulator)
        except Exception as cleanup_error:
            failure.add_note(f"owned accumulator cleanup failed: {cleanup_error}")
            raise failure from cleanup_error
        raise


def _warning_evidence(warning: warnings.WarningMessage) -> str:
    source = warning.source
    trace = tracemalloc.get_object_traceback(source) if source is not None else None
    return json.dumps({
        "category": warning.category.__name__, "message": str(warning.message),
        "filename": warning.filename, "lineno": warning.lineno,
        "source_type": type(source).__name__ if source is not None else None,
        "tracemalloc_enabled": tracemalloc.is_tracing(),
        "allocation_trace": trace.format() if trace is not None else None,
        "allocation_origin": "trace_available" if trace is not None else "unknown",
    }, sort_keys=True)


def execute_shard_combine(
    accumulator: Any, shard_paths: list[str], cov_mod: Any,
    snapshot_fn: Callable[..., Any], record_fn: Callable[[Any], None],
) -> None:
    """Reject coverage-invalidating warnings, preserving other caller policies."""
    from coverage.exceptions import CoverageWarning

    failure: BaseException | None = None
    with warnings.catch_warnings(record=True) as captured:
        # Only CoverageWarning overrides caller filters. Other warnings obey
        # the original filters at emission, including immediate error policy.
        warnings.simplefilter("always", CoverageWarning)
        try:
            accumulator.combine(data_paths=shard_paths, keep=False)
        except BaseException as error:
            failure = error

    coverage_warnings = []
    for warning in captured:
        if issubclass(warning.category, CoverageWarning):
            coverage_warnings.append(warning)
            record_fn(snapshot_fn(
                shard_name="batch", file_type="combine_warning", size_bytes=-1,
                sha256=None, reader_status=_warning_evidence(warning), stage="combine",
                cov_mod=cov_mod, termination_outcome="combine_warning",
            ))
        else:
            record_fn(snapshot_fn(
                shard_name="batch", file_type="noncoverage_warning", size_bytes=-1,
                sha256=None, reader_status=_warning_evidence(warning), stage="combine",
                cov_mod=cov_mod, termination_outcome="warning_origin_unattributed",
            ))
            # Eligibility was decided by the caller's original filter above.
            # Forward once with the original location and allocation object.
            with warnings.catch_warnings():
                warnings.simplefilter("always", warning.category)
                warnings.warn_explicit(
                    warning.message, warning.category, warning.filename,
                    warning.lineno, source=warning.source,
                )

    if failure is not None:
        if isinstance(failure, Warning) or not isinstance(failure, Exception):
            raise failure
        record_fn(snapshot_fn(
            shard_name="batch", file_type="combine_error", size_bytes=-1,
            sha256=None, reader_status=f"combine_error: {failure}", stage="combine",
            cov_mod=cov_mod, termination_outcome="combine_exception",
        ))
        raise RuntimeError(f"coverage shard combine failed: {failure}") from failure
    if coverage_warnings:
        message = str(coverage_warnings[0].message)
        raise RuntimeError(f"coverage shard combine rejected: {message}")
    unconsumed = [path for path in shard_paths if Path(path).exists()]
    if unconsumed:
        path = Path(unconsumed[0])
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        record_fn(snapshot_fn(
            shard_name=path.name, file_type="unconsumed", size_bytes=size,
            sha256=None, reader_status="unconsumed_after_combine", stage="post_combine",
            cov_mod=cov_mod, termination_outcome="unconsumed_after_combine",
        ))
        raise RuntimeError(f"coverage shard {path} is empty or unreadable: unconsumed during combine")
