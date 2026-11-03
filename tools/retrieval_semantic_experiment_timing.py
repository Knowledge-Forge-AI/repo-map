"""Exclusive query-work timing for the optional semantic experiment."""

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from time import perf_counter_ns
from typing import Protocol


class QueryTimingLedger(Protocol):
    """Mutable cost fields required by :func:`measure_query_work`."""

    query_ns: int
    index_ns: int
    ann_cleanup_ns: int


class CleanupTimingLedger(Protocol):
    """Mutable cleanup field required by campaign-cost attribution."""

    cleanup_ns: int | None


class QueryTimingError(ValueError):
    """Raised when a clock or subphase cost cannot produce a safe duration."""


def _counter(name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise QueryTimingError(f"{name} must be a non-negative integer")
    return value


def _exclusive_elapsed(
    costs: QueryTimingLedger,
    *,
    started_ns: int,
    index_started_ns: int,
    ann_cleanup_started_ns: int,
    clock_ns: Callable[[], int],
) -> None:
    finished_ns = _counter("clock reading", clock_ns())
    if finished_ns < started_ns:
        raise QueryTimingError("clock moved backwards")
    index_finished_ns = _counter("index_ns", costs.index_ns)
    ann_cleanup_finished_ns = _counter("ann_cleanup_ns", costs.ann_cleanup_ns)
    index_delta_ns = index_finished_ns - index_started_ns
    ann_cleanup_delta_ns = ann_cleanup_finished_ns - ann_cleanup_started_ns
    if index_delta_ns < 0 or ann_cleanup_delta_ns < 0:
        raise QueryTimingError("subphase cost moved backwards")
    elapsed_ns = finished_ns - started_ns
    exclusive_ns = elapsed_ns - index_delta_ns - ann_cleanup_delta_ns
    if exclusive_ns < 0:
        raise QueryTimingError("subphase costs exceed elapsed query work")
    costs.query_ns = exclusive_ns


@contextmanager
def measure_query_work(
    costs: QueryTimingLedger,
    *,
    clock_ns: Callable[[], int] = perf_counter_ns,
) -> Iterator[None]:
    """Record wall query work after subtracting nested index/ANN cleanup.

    The measurement is finalized on both normal and exceptional exits. When
    the clock and cost fields are valid, an exception raised by the measured
    body is re-raised unchanged after the query cost is recorded.
    """
    started_ns = _counter("clock reading", clock_ns())
    index_started_ns = _counter("index_ns", costs.index_ns)
    ann_cleanup_started_ns = _counter("ann_cleanup_ns", costs.ann_cleanup_ns)
    try:
        yield
    except BaseException as body_error:
        try:
            _exclusive_elapsed(
                costs,
                started_ns=started_ns,
                index_started_ns=index_started_ns,
                ann_cleanup_started_ns=ann_cleanup_started_ns,
                clock_ns=clock_ns,
            )
        except BaseException as timing_error:
            raise timing_error from body_error
        raise
    else:
        _exclusive_elapsed(
            costs,
            started_ns=started_ns,
            index_started_ns=index_started_ns,
            ann_cleanup_started_ns=ann_cleanup_started_ns,
            clock_ns=clock_ns,
        )


def assign_campaign_cleanup_cost(
    ledgers: Sequence[CleanupTimingLedger],
    cleanup_ns: object,
) -> None:
    """Assign one shared cleanup duration to the last retained ledger.

    A campaign cleanup is performed once after the retained generations have
    run. Earlier reports keep a numeric zero share so their existing totals
    remain schema-compatible; the final retained report owns the measured
    duration.
    """
    duration = _counter("cleanup duration", cleanup_ns)
    if not ledgers:
        return
    owner_index = len(ledgers) - 1
    for index, ledger in enumerate(ledgers):
        ledger.cleanup_ns = duration if index == owner_index else 0


__all__ = [
    "CleanupTimingLedger",
    "QueryTimingError",
    "QueryTimingLedger",
    "assign_campaign_cleanup_cost",
    "measure_query_work",
]
