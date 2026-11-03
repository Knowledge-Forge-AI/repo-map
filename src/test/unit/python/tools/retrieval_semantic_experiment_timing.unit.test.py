"""Unit contracts for exclusive optional-experiment query timing."""

from dataclasses import dataclass
from typing import Callable, Iterator

import pytest

from retrieval_semantic_experiment_timing import (
    QueryTimingError,
    assign_campaign_cleanup_cost,
    measure_query_work,
)


@dataclass
class _Costs:
    query_ns: int = 0
    index_ns: int = 0
    ann_cleanup_ns: int = 0
    cleanup_ns: int | None = None
    status: str = "completed"


def _clock(values: tuple[int, ...]) -> Callable[[], int]:
    readings: Iterator[int] = iter(values)
    return lambda: next(readings)


def test_measure_query_work_records_only_exclusive_success_duration() -> None:
    costs = _Costs(index_ns=11, ann_cleanup_ns=7)

    with measure_query_work(costs, clock_ns=_clock((100, 140))):
        costs.index_ns += 9
        costs.ann_cleanup_ns += 6

    assert costs.query_ns == 25
    assert costs.index_ns == 20
    assert costs.ann_cleanup_ns == 13


def test_measure_query_work_records_failure_and_reraises_original_exception() -> None:
    costs = _Costs()
    failure = RuntimeError("query failed")

    with pytest.raises(RuntimeError, match="query failed") as captured:
        with measure_query_work(costs, clock_ns=_clock((10, 42))):
            costs.index_ns = 5
            costs.ann_cleanup_ns = 4
            raise failure

    assert captured.value is failure
    assert costs.query_ns == 23


@pytest.mark.parametrize("readings", [(-1,), (10, -1), (True, 10)])
def test_measure_query_work_refuses_invalid_clock_readings(readings: tuple[int, ...]) -> None:
    costs = _Costs()
    with pytest.raises(QueryTimingError):
        with measure_query_work(costs, clock_ns=_clock(readings)):
            pass


def test_measure_query_work_refuses_subphase_costs_larger_than_elapsed_time() -> None:
    costs = _Costs()
    with pytest.raises(QueryTimingError):
        with measure_query_work(costs, clock_ns=_clock((100, 110))):
            costs.index_ns = 8
            costs.ann_cleanup_ns = 4


def test_assign_campaign_cleanup_cost_uses_last_retained_ledger_only() -> None:
    first = _Costs(cleanup_ns=101)
    last = _Costs(cleanup_ns=102)

    assign_campaign_cleanup_cost((first, last), 23)

    assert first.cleanup_ns == 0
    assert last.cleanup_ns == 23


def test_assign_campaign_cleanup_cost_uses_last_retained_record_after_failure() -> None:
    failed_first = _Costs(cleanup_ns=7, status="failed")
    failed_last = _Costs(cleanup_ns=8, status="failed")

    assign_campaign_cleanup_cost((failed_first, failed_last), 19)

    assert failed_first.cleanup_ns == 0
    assert failed_last.cleanup_ns == 19
    assert failed_first.status == "failed"
    assert failed_last.status == "failed"


def test_assign_campaign_cleanup_cost_accepts_empty_and_zero_duration() -> None:
    ledger = _Costs()

    assign_campaign_cleanup_cost((), 0)
    assign_campaign_cleanup_cost((ledger,), 0)

    assert ledger.cleanup_ns == 0


@pytest.mark.parametrize("duration", [-1, True, 1.5, "3", None])
def test_assign_campaign_cleanup_cost_rejects_invalid_duration(duration: object) -> None:
    ledger = _Costs(cleanup_ns=11)

    with pytest.raises(QueryTimingError, match="cleanup duration"):
        assign_campaign_cleanup_cost((ledger,), duration)

    assert ledger.cleanup_ns == 11
