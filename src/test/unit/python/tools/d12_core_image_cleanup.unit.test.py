"""ADR 0089 D10: the D12 owner's cleanup never replaces the initiating failure (no build)."""

from __future__ import annotations

import pytest

from repomap_test_support.d12_core_image_cleanup import run_candidate_cleanup


class Reports:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.written: list[tuple[str, dict[str, object]]] = []

    def __call__(self, name: str, record: dict[str, object]) -> None:
        if self.failure is not None:
            raise self.failure
        self.written.append((name, dict(record)))


def _steps(error: BaseException | None = None):
    def steps(record: dict[str, object]) -> None:
        record["image"] = "removed"
        if error is not None:
            raise error
    return steps


def test_clean_cleanup_writes_one_record_and_returns_it():
    reports = Reports()
    record = run_candidate_cleanup(None, _steps(), reports)
    assert reports.written == [("cleanup", {"image": "removed", "primary": None})], reports.written
    assert record == {"image": "removed", "primary": None}, record


def test_cleanup_failure_without_primary_is_raised_after_the_report():
    reports, failure = Reports(), RuntimeError("baseline differs")
    with pytest.raises(RuntimeError) as raised:
        run_candidate_cleanup(None, _steps(failure), reports)
    assert raised.value is failure, raised.value
    assert reports.written[0][1]["error"] == "RuntimeError: baseline differs", reports.written


def test_cleanup_failure_with_primary_annotates_and_never_replaces_it():
    reports, primary = Reports(), AssertionError("round trip differs")
    record = run_candidate_cleanup(primary, _steps(OSError("busy")), reports)
    assert record["error"] == "OSError: busy" and record["primary"] == "AssertionError: round trip differs", record
    assert primary.__notes__ == ["D12 candidate cleanup also failed; see cleanup report"], primary.__notes__


@pytest.mark.parametrize("write_failure", [OSError("disk full"), ValueError("report ceiling")])
def test_report_write_failure_annotates_the_primary(write_failure):
    primary = AssertionError("build failed")
    run_candidate_cleanup(primary, _steps(), Reports(write_failure))
    assert primary.__notes__ == [
        f"D12 cleanup report could not be written ({type(write_failure).__name__})"
    ], primary.__notes__


def test_report_write_failure_annotates_a_cleanup_failure_that_is_still_raised():
    failure = RuntimeError("tag left for operator")
    with pytest.raises(RuntimeError) as raised:
        run_candidate_cleanup(None, _steps(failure), Reports(OSError("disk full")))
    assert raised.value is failure, raised.value
    assert failure.__notes__ == ["D12 cleanup report could not be written (OSError)"], failure.__notes__


def test_report_write_failure_alone_is_raised():
    failure = OSError("disk full")
    with pytest.raises(OSError) as raised:
        run_candidate_cleanup(None, _steps(), Reports(failure))
    assert raised.value is failure, raised.value


def test_interrupt_during_cleanup_is_preserved_after_the_report():
    reports = Reports()
    with pytest.raises(KeyboardInterrupt):
        run_candidate_cleanup(None, _steps(KeyboardInterrupt()), reports)
    assert reports.written[0][1]["error"] == "KeyboardInterrupt: ", reports.written
