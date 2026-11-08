"""Budget validation and monotone, admit-before-act meter semantics (ADR 0173 A1-A4)."""

from __future__ import annotations

import threading
from typing import Any, cast

import pytest

from common_lore_index.artifacts._sealing_meter import (
    SealingMeter,
    SealingMeterMisuse,
    SealingPlanFacts,
    meter_kwargs,
)
from common_lore_index.artifacts.sealing_governance import (
    BUDGET_LIMITS,
    GOVERNED_DEFAULT_MAX_DIRECTORY_ENTRIES,
    MAX_COUNTER,
    MAX_ELAPSED_MS,
    SealingBudget,
    SealingBudgetExceeded,
    effective_max_directory_entries,
    governance_kwargs,
    normalize_budget,
    planned_min_read_bytes,
)


@pytest.mark.parametrize("value", [True, False, -1, 1.0, "1", MAX_COUNTER + 1, object()])
def test_budget_refuses_non_integer_bool_and_out_of_range_values(value: object) -> None:
    with pytest.raises(ValueError, match="^invalid sealing budget$"):
        SealingBudget(max_read_bytes=cast(Any, value))


def test_budget_ranges_and_normalization() -> None:
    assert SealingBudget(max_read_bytes=MAX_COUNTER, max_elapsed_ms=MAX_ELAPSED_MS).max_read_bytes == MAX_COUNTER
    with pytest.raises(ValueError):
        SealingBudget(max_elapsed_ms=MAX_ELAPSED_MS + 1)
    assert normalize_budget(None) is None
    assert normalize_budget(SealingBudget()) is None
    assert governance_kwargs(SealingBudget()) == {}
    budget = SealingBudget(max_opens=0)
    assert governance_kwargs(budget) == {"sealing_budget": budget}
    with pytest.raises(ValueError, match="invalid sealing budget"):
        normalize_budget({"max_opens": 1})
    assert effective_max_directory_entries(None) == GOVERNED_DEFAULT_MAX_DIRECTORY_ENTRIES == 100_000
    assert effective_max_directory_entries(SealingBudget(max_directory_entries=7)) == 7
    assert planned_min_read_bytes(10) == 61


@pytest.mark.parametrize("limit", BUDGET_LIMITS)
def test_refusal_messages_are_path_free_closed_and_bounded(limit: str) -> None:
    error = SealingBudgetExceeded(limit)
    assert str(error) == f"sealing budget exceeded: {limit}"
    assert len(str(error).encode()) <= 64 and error.category == "resource_budget_exceeded"
    assert isinstance(error, ValueError) and error.limit == limit
    with pytest.raises(ValueError):
        SealingBudgetExceeded("disk")


def test_a_budget_requires_governed_mode_and_kwargs_forward_only_meters() -> None:
    with pytest.raises(ValueError):
        SealingMeter(SealingBudget(max_opens=1), governed=False)
    meter = SealingMeter(None, governed=False)
    assert meter_kwargs(None) == {} and meter_kwargs(meter) == {"io_meter": meter}
    assert meter.snapshot().effective_max_directory_entries is None


@pytest.mark.parametrize(
    ("budget", "admit", "limit"),
    [
        (SealingBudget(max_read_bytes=0), lambda m: m.admit_read(1), "read_bytes"),
        (SealingBudget(max_write_bytes=0), lambda m: m.admit_write(1), "write_bytes"),
        (SealingBudget(max_opens=0), lambda m: m.admit_open(), "opens"),
        (SealingBudget(max_directory_entries=0), lambda m: m.admit_entry(), "directory_entries"),
        (SealingBudget(max_elapsed_ms=0), lambda m: m.admit_fsync(), "elapsed_ms"),
    ],
)
def test_zero_budgets_refuse_the_first_admission(budget: SealingBudget, admit, limit: str) -> None:
    meter = SealingMeter(budget, governed=True)
    with pytest.raises(SealingBudgetExceeded) as raised:
        admit(meter)
    assert raised.value.limit == meter.refused_limit == limit
    snapshot = meter.snapshot()
    assert (snapshot.read_bytes, snapshot.write_bytes, snapshot.opens, snapshot.directory_entries) == (0, 0, 0, 0)


def test_exact_need_passes_and_one_more_unit_refuses_for_every_counter() -> None:
    meter = SealingMeter(
        SealingBudget(max_read_bytes=5, max_write_bytes=4, max_opens=2, max_directory_entries=3),
        governed=True,
    )
    meter.admit_read(5)
    meter.charge_read("capture", 5, 5)
    meter.admit_write(4)
    meter.charge_write(4, 4)
    meter.admit_open()
    meter.admit_open()
    for _ in range(3):
        meter.admit_entry()
    for admit, limit in (
        (lambda: meter.admit_read(1), "read_bytes"), (lambda: meter.admit_write(1), "write_bytes"),
        (meter.admit_open, "opens"), (meter.admit_entry, "directory_entries"),
    ):
        with pytest.raises(SealingBudgetExceeded, match=limit):
            admit()
    snapshot = meter.snapshot()
    assert (snapshot.read_bytes, snapshot.write_bytes, snapshot.opens, snapshot.directory_entries) == (5, 4, 2, 3)
    assert meter.refused_limit == "read_bytes", "the first refusal is retained"


def test_short_reads_charge_actual_bytes_and_counters_never_reset() -> None:
    meter = SealingMeter(SealingBudget(max_read_bytes=10), governed=True)
    meter.admit_read(8)
    meter.charge_read("discovery", 3, 8)
    meter.admit_read(7)
    meter.charge_read("discovery", 0, 7)
    assert meter.remaining_read() == 7 and meter.snapshot().read_calls == 2
    assert meter.probe_length(1024) == 7
    with pytest.raises(SealingMeterMisuse):
        meter.charge_read("discovery", 9, 8)
    with pytest.raises(SealingMeterMisuse):
        meter.charge_read("nowhere", 1, 1)
    with pytest.raises(SealingMeterMisuse):
        meter.admit_read(0)
    meter.note_retry()
    meter.note_retry()
    assert meter.snapshot().capture_retries == 2
    assert meter.snapshot().reader("discovery") == 3


def test_probe_length_without_a_budget_is_the_reader_chunk() -> None:
    assert SealingMeter(None, governed=False).probe_length(65536) == 65536
    exhausted = SealingMeter(SealingBudget(max_read_bytes=0), governed=True)
    assert exhausted.probe_length(65536) == 1  # admission of that one byte then refuses


def test_pre_open_headroom_refuses_a_body_larger_than_the_remaining_budget() -> None:
    meter = SealingMeter(SealingBudget(max_read_bytes=10), governed=True)
    meter.require_read_headroom(10)
    with pytest.raises(SealingBudgetExceeded, match="read_bytes"):
        meter.require_read_headroom(11)
    assert meter.snapshot().read_bytes == 0 and meter.snapshot().read_calls == 0


def test_elapsed_is_checked_before_every_admission_with_an_injected_clock() -> None:
    now = [0]
    meter = SealingMeter(SealingBudget(max_elapsed_ms=2), governed=True, _monotonic_ns=lambda: now[0])
    now[0] = 1_999_999
    meter.admit_open()
    now[0] = 2_000_000
    with pytest.raises(SealingBudgetExceeded, match="elapsed_ms"):
        meter.admit_entry()
    assert meter.snapshot().opens == 1 and meter.snapshot().directory_entries == 0


def test_governed_entries_have_a_finite_default_ceiling_and_observe_only_has_none() -> None:
    governed = SealingMeter(SealingBudget(max_read_bytes=1), governed=True)
    assert governed.snapshot().effective_max_directory_entries == 100_000
    observe = SealingMeter(None, governed=False)
    for _ in range(3):
        observe.admit_entry()
    assert observe.snapshot().directory_entries == 3


def test_plan_facts_refuse_provable_planned_overruns() -> None:
    plan = SealingPlanFacts(bindings=1, inventory_files=2, inventory_bytes=10, inventory_symlinked_files=0)
    SealingMeter(SealingBudget(max_read_bytes=61, max_write_bytes=10), governed=True).note_plan(plan)
    with pytest.raises(SealingBudgetExceeded, match="planned_read_bytes"):
        SealingMeter(SealingBudget(max_read_bytes=60), governed=True).note_plan(plan)
    with pytest.raises(SealingBudgetExceeded, match="planned_write_bytes"):
        SealingMeter(SealingBudget(max_write_bytes=9), governed=True).note_plan(plan)
    with pytest.raises(SealingMeterMisuse):
        SealingMeter(None, governed=False).note_plan(plan)
    meter = SealingMeter(None, governed=True)
    meter.note_plan(plan)
    with pytest.raises(SealingMeterMisuse):
        meter.note_plan(plan)
    assert meter.snapshot().plan == plan


def test_retention_refusal_is_recorded_and_returned_for_raising() -> None:
    meter = SealingMeter(None, governed=True)
    error = meter.refuse_retention()
    assert isinstance(error, SealingBudgetExceeded) and error.limit == "classification_retention"
    assert meter.refused_limit == "classification_retention"


def test_cross_thread_use_and_use_after_close_are_misuse() -> None:
    meter = SealingMeter(None, governed=False)
    failures: list[BaseException] = []

    def other() -> None:
        try:
            meter.admit_open()
        except BaseException as error:  # recorded for the owning thread
            failures.append(error)
        try:
            meter.snapshot()
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=other)
    thread.start()
    thread.join()
    assert [type(item) for item in failures] == [SealingMeterMisuse, SealingMeterMisuse]
    assert meter.snapshot().opens == 0
    meter.close()
    assert meter.closed and meter.snapshot().complete
    with pytest.raises(SealingMeterMisuse):
        meter.admit_open()
