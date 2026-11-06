"""Lifecycle and failure semantics for the call-owned resource observer."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
import threading

import pytest

from common_lore_index.ops.resource_view import (
    ResourceObserver, begin, end_stage, finish_local, mark, note_manifest,
    note_validated, observer_kwargs,
)


class _Clock:
    def __init__(self, *values: int) -> None:
        self.values = iter(values)

    def __call__(self) -> int:
        return next(self.values)


def _observer() -> ResourceObserver:
    return ResourceObserver(
        _monotonic_ns=_Clock(0, 10, 20, 30, 40, 50, 60, 70, 80),
        _process_time_ns=_Clock(0, 5),
    )


def _validated() -> SimpleNamespace:
    return SimpleNamespace(
        family_summaries=(
            SimpleNamespace(record_count=3, byte_length=40),
            SimpleNamespace(record_count=2, byte_length=12),
        )
    )


def test_absent_observer_is_inert_and_finish_returns_same_object() -> None:
    result = object()
    begin(None, "local_refresh", "sqlite")
    mark(None, "capture")
    assert finish_local(None, result) is result
    assert observer_kwargs(None) == {}


def test_local_success_records_stages_totals_and_reuses_frozen_report() -> None:
    observer = _observer()
    begin(observer, "local_refresh", "sqlite")
    mark(observer, "lock_and_reconcile")
    end_stage(observer, "lock_and_reconcile")
    mark(observer, "capture")
    note_manifest(observer, SimpleNamespace(total_files=2, total_bytes=52))
    end_stage(observer, "capture")
    mark(observer, "validation")
    end_stage(observer, "validation")
    note_validated(observer, _validated())
    mark(observer, "publication")
    result = SimpleNamespace(reconciled=False)
    assert finish_local(observer, result) is result

    report = observer.report()
    assert observer.report() is report
    assert report.outcome == "published"
    assert report.instrumentation == "complete"
    values = {metric.name: metric.value for metric in report.metrics}
    assert values["sealed_manifest_files"] == 2
    assert values["sealed_manifest_bytes"] == 52
    assert values["validated_bundle_records"] == 5
    assert values["validated_bundle_bytes"] == 52
    assert values["operation_elapsed"] == 80
    assert values["operation_process_cpu"] == 5


def test_replay_omits_worker_and_capture_rows_are_not_fabricated() -> None:
    observer = ResourceObserver(_monotonic_ns=_Clock(4, 9), _process_time_ns=_Clock(2, 3))
    begin(observer, "local_refresh", "sqlite")
    assert finish_local(observer, SimpleNamespace(reconciled=True)) is not None
    report = observer.report()
    assert report.outcome == "reconciled_replay"
    metrics = {metric.name: metric for metric in report.metrics}
    assert metrics["worker_cpu"].reason == "not_started"
    assert metrics["capture_elapsed"].reason == "not_started"


def test_ordinary_observer_error_degrades_and_stops_recording() -> None:
    observer = ResourceObserver(_monotonic_ns=_Clock(0, 1), _process_time_ns=_Clock(0, 1))
    begin(observer, "local_refresh", "sqlite")
    mark(observer, "not-a-stage")
    mark(observer, "capture")
    report = observer.report()
    assert report.instrumentation == "degraded"
    assert report.metrics
    assert all(metric.availability == "unavailable" for metric in report.metrics)
    assert all(metric.reason == "observer_failed" for metric in report.metrics)
    rows = {metric.name: metric for metric in report.metrics}
    assert rows["operation_process_cpu"].basis == "process_clock_inclusive"
    assert rows["sealed_manifest_files"].basis == "accepted_manifest_total"
    assert rows["validated_bundle_bytes"].basis == "parent_validated_total"
    assert rows["worker_cpu"].basis is None and rows["worker_peak_rss"].basis is None


def test_reuse_discards_the_previous_outcome_before_report_is_sealed() -> None:
    observer = ResourceObserver(_monotonic_ns=_Clock(0, 1), _process_time_ns=_Clock(0, 1))
    begin(observer, "local_refresh", "sqlite")
    first = SimpleNamespace(reconciled=False)
    assert finish_local(observer, first) is first
    begin(observer, "local_refresh", "sqlite")
    second = SimpleNamespace(reconciled=True)
    assert finish_local(observer, second) is second
    report = observer.report()
    assert report.instrumentation == "degraded"
    assert report.outcome == "not_recorded"
    assert all(metric.value is None for metric in report.metrics)
    assert all(limit.applies_this_call is None for limit in report.limits)


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_base_exception_from_private_clock_is_not_caught(error_type: type[BaseException]) -> None:
    interrupt = error_type("clock interrupt")

    def clock() -> int:
        raise interrupt

    observer = ResourceObserver(_monotonic_ns=clock, _process_time_ns=lambda: 0)
    with pytest.raises(error_type) as caught:
        begin(observer, "local_refresh", "sqlite")
    assert caught.value is interrupt


def test_cross_thread_hook_degrades_without_calling_business_refusal() -> None:
    observer = ResourceObserver(_monotonic_ns=_Clock(0), _process_time_ns=_Clock(0))
    begin(observer, "local_refresh", "sqlite")
    thread = threading.Thread(target=lambda: mark(observer, "capture"))
    thread.start()
    thread.join()
    assert observer.report().instrumentation == "degraded"


def test_wrong_type_observer_methods_are_not_invoked() -> None:
    class Wrong:
        def __getattr__(self, _name: str) -> object:
            raise AssertionError("wrong-type observer was invoked")

    wrong = Wrong()
    begin(wrong, "local_refresh", "sqlite")
    mark(wrong, "capture")
    assert observer_kwargs(cast(Any, wrong)) == {}


def test_report_seals_observer_and_later_hooks_are_ignored() -> None:
    observer = _observer()
    begin(observer, "local_refresh", "sqlite")
    report = observer.report()
    mark(observer, "capture")
    note_manifest(observer, SimpleNamespace(total_files=1, total_bytes=2))
    assert finish_local(observer, SimpleNamespace(reconciled=False)) is not None
    assert observer.report() is report
    assert report.outcome == "not_recorded"
    assert all(metric.availability == "unavailable" for metric in report.metrics)
