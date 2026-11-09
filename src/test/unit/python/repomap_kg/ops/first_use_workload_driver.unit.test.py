"""Driver state machine with fakes: precedence, interrupts, not_reached, no retry, custody."""

from __future__ import annotations

import itertools
import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from first_use_workload_bundle import read_bundle
from first_use_workload_census import Census, load_census
from first_use_workload_records import decode_observation
from repomap_test_support.first_use_workload_driver import (
    BUNDLE_CHILD, CallOutcome, CleanupFailure, CleanupRegistry, Clocks, Observed, RuntimeUnavailable,
    ScenarioRun,
    StaleInput, StepPlan, Unbounded, UnsafeBundleBase, run_rows, select_bundle_base, write_bundle,
)
from repomap_test_support.first_use_workload_samples import (
    ATTEMPT, SAMPLE_RECIPE, pack_fact, sample_facts, sample_intent,
)

Key = tuple[int, int]


@pytest.fixture(scope="module")
def census() -> Census:
    return load_census()


def _clocks() -> Clocks:
    ticks = itertools.count(0, 10)
    return Clocks(wall=lambda: next(ticks), process=lambda: 5, children=lambda: 7)


class Calls:
    def __init__(self) -> None:
        self.log: list[str] = []

    def plan(self, key: Key, facts: Any, *, call: Callable[[], CallOutcome] | None = None,
             cleanup: Callable[[], None] | None = None) -> StepPlan:
        def prepare() -> None:
            self.log.append(f"prepare{key[0]}")

        def default_call() -> CallOutcome:
            self.log.append(f"call{key[0]}")
            return CallOutcome(refusal="sealing-budget-exceeded:planned_read_bytes" if key == (3, 0) else None)

        def observe(_outcome: CallOutcome) -> Observed:
            self.log.append(f"observe{key[0]}")
            return Observed(facts)

        def default_cleanup() -> None:
            self.log.append(f"cleanup{key[0]}")

        return StepPlan(prepare, call or default_call, observe, cleanup or default_cleanup)


def _plans(census: Census, calls: Calls, **custom: dict[str, Any]) -> dict[Key, StepPlan]:
    facts = sample_facts(census)
    plans = {step.key: calls.plan(step.key, facts[step.key]) for step in SAMPLE_RECIPE}
    for name, options in custom.items():
        key = (int(name[1:]), 0)
        plans[key] = calls.plan(key, facts[key], **options)
    return plans


def _run(census: Census, plans: dict[Key, StepPlan], registry: CleanupRegistry | None = None) -> ScenarioRun:
    run = ScenarioRun("local", ATTEMPT, sample_intent(census))
    return run_rows(run, plans, registry or CleanupRegistry(), recipe=SAMPLE_RECIPE, clocks=_clocks())


def _rows(run: ScenarioRun) -> list[dict[str, Any]]:
    return [decode_observation(data) for _name, data in run.observations]


def test_rows_run_once_in_order_with_scoped_spans(census: Census) -> None:
    calls = Calls()
    run = _run(census, _plans(census, calls))
    assert run.primary is None
    assert calls.log == [
        *(f"{phase}{step}" for step in range(1, 5)
          for phase in ("prepare", "call", "observe", "cleanup")),
        "prepare5", "call5", "cleanup5", "observe5",
    ]
    rows = _rows(run)
    assert [row["result"] for row in rows] == ["pass", "pass", "expected_refusal", "pass", "pass"]
    assert rows[0]["spans"] == {"prepare_ns": 10, "call_ns": 10, "observe_ns": 10, "cleanup_ns": 10}
    assert rows[0]["cpu"] == {"parent_process_ns": 0, "waited_descendants_ns": 0}
    assert rows[2]["refusal"] == "sealing-budget-exceeded:planned_read_bytes"


def test_required_failure_records_remaining_rows_not_reached_without_retry(census: Census) -> None:
    calls = Calls()
    attempts: list[int] = []

    def failing() -> CallOutcome:
        attempts.append(1)
        raise RuntimeError("boom")

    run = _run(census, _plans(census, calls, s2={"call": failing}))
    rows = _rows(run)
    assert attempts == [1] and isinstance(run.primary, RuntimeError)
    assert (rows[1]["result"], rows[1]["reason"], rows[1]["facts"]) == ("failure", "call_failed", None)
    assert [(row["result"], row["reason"]) for row in rows[2:4]] == [("unavailable", "not_reached")] * 2
    assert rows[4]["result"] == "pass"
    assert all(value is not None for value in rows[4]["spans"].values())
    assert not any(entry.startswith(phase) and entry.endswith(step)
                   for step in ("3", "4") for phase in ("prepare", "call", "observe", "cleanup")
                   for entry in calls.log)
    assert "cleanup2" in calls.log and "cleanup5" in calls.log


def test_primary_failure_outranks_cleanup_failure(census: Census) -> None:
    primary = RuntimeError("primary")
    secondary = OSError("secondary")

    def call() -> CallOutcome:
        raise primary

    def cleanup() -> None:
        raise secondary

    run = _run(census, _plans(census, Calls(), s2={"call": call, "cleanup": cleanup}))
    assert run.primary is primary and run.cleanup_errors == ["cleanup_failed"]
    assert _rows(run)[1]["reason"] == "call_failed"


def test_cleanup_failure_alone_fails_its_row(census: Census) -> None:
    def cleanup() -> None:
        raise OSError("cleanup")

    run = _run(census, _plans(census, Calls(), s4={"cleanup": cleanup}))
    row = _rows(run)[3]
    assert (row["result"], row["reason"]) == ("failure", "cleanup_failed")
    assert row["facts"] is not None


def test_failed_release_keeps_operation_primary_and_records_label(census: Census) -> None:
    primary = RuntimeError("primary")
    registry = CleanupRegistry()

    def failed_release() -> None:
        raise OSError("cleanup")

    registry.register("hidden", failed_release)
    calls = Calls()

    def call() -> CallOutcome:
        try:
            raise primary
        except BaseException as error:
            registry.release("hidden")
            raise error

    run = _run(census, _plans(census, calls, s2={"call": call}), registry)
    assert run.primary is primary
    assert run.cleanup_errors == ["cleanup_failed"]
    assert registry.pending() == ()


@pytest.mark.parametrize("cleanup_interrupt", [KeyboardInterrupt(), SystemExit(4)])
def test_cleanup_control_does_not_replace_operation_interrupt(
    census: Census, cleanup_interrupt: BaseException,
) -> None:
    original = KeyboardInterrupt()
    registry = CleanupRegistry()
    registry.register(
        "cleanup-control",
        lambda: (_ for _ in ()).throw(cleanup_interrupt),
    )

    def call() -> CallOutcome:
        raise original

    with pytest.raises(BaseException) as caught:
        _run(census, _plans(census, Calls(), s2={"call": call}), registry)
    assert caught.value is original
    assert registry.pending() == ()


def test_registry_attempts_all_callbacks_once_in_reverse_order() -> None:
    order: list[str] = []
    registry = CleanupRegistry()

    def callback(name: str, *, fail: bool = False) -> Callable[[], None]:
        def run() -> None:
            order.append(name)
            if fail:
                raise OSError("cleanup")
        return run

    registry.register("a", callback("a"))
    registry.register("b", callback("b", fail=True))
    registry.register("c", callback("c", fail=True))
    assert registry.unwind() == ["cleanup_failed", "cleanup_failed"]
    assert order == ["c", "b", "a"]
    assert registry.pending() == ()
    assert registry.unwind() == []


def test_failed_terminal_cleanup_is_recorded_and_bundle_is_not_accepted(
    tmp_path: Path, census: Census,
) -> None:
    registry = CleanupRegistry()

    def failed_cleanup() -> None:
        raise OSError("post-row-cleanup")

    registry.register("post-row", failed_cleanup)
    run = _run(census, _plans(census, Calls()), registry)
    row = _rows(run)[-1]
    assert (row["result"], row["reason"]) == ("failure", "cleanup_failed")
    assert row["facts"] is not None and row["spans"]["cleanup_ns"] == 10
    _root, verdict = write_bundle(
        tmp_path, run, sample_intent(census), census, recipe=SAMPLE_RECIPE,
    )
    assert verdict.outcome != "accepted"


def test_ignored_release_failure_reaches_terminal_cleanup(tmp_path: Path, census: Census) -> None:
    registry = CleanupRegistry()

    def ignored_release() -> CallOutcome:
        registry.release("ignored")
        return CallOutcome()

    registry.register("ignored", lambda: (_ for _ in ()).throw(OSError("release")))
    run = _run(census, _plans(census, Calls(), s2={"call": ignored_release}), registry)
    row = _rows(run)[-1]
    assert (row["result"], row["reason"]) == ("failure", "cleanup_failed")
    _root, verdict = write_bundle(
        tmp_path, run, sample_intent(census), census, recipe=SAMPLE_RECIPE,
    )
    assert verdict.outcome != "accepted"


def test_failed_callback_registered_during_terminal_observe_is_rejected(census: Census) -> None:
    registry = CleanupRegistry()
    plans = _plans(census, Calls())
    original = plans[(5, 0)]

    def observe(outcome: CallOutcome) -> Observed:
        registry.register("late", lambda: (_ for _ in ()).throw(OSError("late")))
        return original.observe(outcome)

    plans[(5, 0)] = StepPlan(original.prepare, original.call, observe, original.cleanup)
    with pytest.raises(CleanupFailure):
        _run(census, plans, registry)


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt(), SystemExit(3)])
def test_interrupts_run_registered_cleanup_and_keep_identity(census: Census, interrupt: BaseException) -> None:
    released: list[str] = []
    registry = CleanupRegistry()
    registry.register("root", lambda: released.append("root"))
    registry.register("postgres", lambda: released.append("postgres"))

    def call() -> CallOutcome:
        raise interrupt

    calls = Calls()
    with pytest.raises(BaseException) as caught:
        _run(census, _plans(census, calls, s3={"call": call}), registry)
    assert caught.value is interrupt
    assert released == ["postgres", "root"] and registry.pending() == ()
    assert "cleanup3" not in calls.log


def test_outcome_classification_is_exact(census: Census) -> None:
    def refuses() -> CallOutcome:
        return CallOutcome(refusal="local_value_error")

    def returns() -> CallOutcome:
        return CallOutcome()

    def raw() -> CallOutcome:
        return CallOutcome(refusal="ERROR: something else")

    rows = _rows(_run(census, _plans(census, Calls(), s2={"call": refuses})))
    assert (rows[1]["result"], rows[1]["refusal"], rows[1]["reason"]) == (
        "failure", "local_value_error", "unexpected_refusal")
    rows = _rows(_run(census, _plans(census, Calls(), s3={"call": returns})))
    assert (rows[2]["result"], rows[2]["reason"]) == ("failure", "unexpected_return")
    rows = _rows(_run(census, _plans(census, Calls(), s3={"call": raw})))
    assert (rows[2]["result"], rows[2]["refusal"], rows[2]["reason"]) == (
        "failure", None, "unexpected_refusal")


def test_stale_input_unbounded_and_runtime_skip_reasons(census: Census) -> None:
    def stale() -> CallOutcome:
        raise StaleInput("stale")

    def missing_runtime() -> CallOutcome:
        raise RuntimeUnavailable("pg")

    rows = _rows(_run(census, _plans(census, Calls(), s1={"call": stale})))
    assert (rows[0]["result"], rows[0]["reason"]) == ("failure", "stale_input")
    rows = _rows(_run(census, _plans(census, Calls(), s4={"call": missing_runtime})))
    assert (rows[3]["result"], rows[3]["reason"]) == ("skipped", "runtime_unavailable")
    many = [["implementation", "core", f"pkg/m{index:02d}.py"] for index in range(33)]
    calls = Calls()
    plans = _plans(census, calls)
    plans[(4, 0)] = calls.plan((4, 0), pack_fact(observed_locations=many))
    rows = _rows(_run(census, plans))
    assert (rows[3]["result"], rows[3]["reason"], rows[3]["facts"]) == ("failure", "unbounded", None)
    assert issubclass(Unbounded, Exception)


def test_registry_releases_in_reverse_and_records_errors() -> None:
    order: list[str] = []
    registry = CleanupRegistry()
    registry.register("a", lambda: order.append("a"))
    registry.register("b", lambda: (_ for _ in ()).throw(OSError("b")))
    registry.register("c", lambda: order.append("c"))
    registry.release("a")
    with pytest.raises(ValueError):
        registry.register("c", lambda: None)
    failures = registry.unwind()
    assert order == ["a", "c"] and failures == ["cleanup_failed"]
    assert registry.errors == ["cleanup_failed"]
    assert registry.pending() == () and registry.unwind() == []


def test_bundle_base_uses_temporary_directory_when_not_sandboxed(tmp_path: Path) -> None:
    inner = tmp_path / "sandbox-report" / "report"
    inner.mkdir(parents=True, mode=0o700)
    (tmp_path / "pytest").mkdir()
    base = select_bundle_base(tmp_path / "pytest", sandbox_active=lambda: False, inner_root=inner)
    assert base == tmp_path / "pytest" / BUNDLE_CHILD
    assert os.listdir(inner) == []
    shutil.rmtree(tmp_path / "sandbox-report")
    assert not (tmp_path / "sandbox-report").exists()


def test_absent_inner_root_selects_temporary_directory_and_creates_nothing(tmp_path: Path) -> None:
    temporary = tmp_path / "pytest"
    temporary.mkdir()
    inner = tmp_path / "sandbox-report" / "report"
    base = select_bundle_base(temporary, sandbox_active=lambda: True, inner_root=inner)
    assert base == temporary / BUNDLE_CHILD and base.is_dir()
    assert not (tmp_path / "sandbox-report").exists()


def test_existing_owned_inner_root_receives_only_the_child(tmp_path: Path) -> None:
    inner = tmp_path / "sandbox-report" / "report"
    inner.mkdir(parents=True, mode=0o700)
    base = select_bundle_base(tmp_path / "pytest", sandbox_active=lambda: True, inner_root=inner)
    assert base == inner / BUNDLE_CHILD
    assert stat.S_IMODE(os.lstat(base).st_mode) & 0o077 == 0
    assert sorted(os.listdir(inner)) == [BUNDLE_CHILD]
    again = select_bundle_base(tmp_path / "pytest", sandbox_active=lambda: True, inner_root=inner)
    assert again == base
    assert not (tmp_path / "pytest").exists()


def test_unsafe_existing_inner_root_refuses_without_fallback(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "report-link"
    link.symlink_to(real)
    with pytest.raises(UnsafeBundleBase):
        select_bundle_base(tmp_path / "pytest", sandbox_active=lambda: True, inner_root=link)
    os.chmod(real, 0o777)
    try:
        with pytest.raises(UnsafeBundleBase):
            select_bundle_base(tmp_path / "pytest", sandbox_active=lambda: True, inner_root=real)
    finally:
        os.chmod(real, 0o700)
    assert not (tmp_path / "pytest").exists()


def test_written_bundle_is_reconciled_from_disk(tmp_path: Path, census: Census) -> None:
    run = _run(census, _plans(census, Calls()))
    intent = sample_intent(census)
    root, verdict = write_bundle(tmp_path, run, intent, census, recipe=SAMPLE_RECIPE)
    assert (verdict.outcome, verdict.categories) == ("accepted", ())
    files = read_bundle(root)
    assert set(files) == {"intent.json", "index.json", "verdict.json",
                          *(f"observation-0{step}-0.json" for step in range(1, 6))}
    assert files["verdict.json"] == verdict.encoded()


def test_identity_drift_during_the_run_rejects_the_evidence(tmp_path: Path, census: Census) -> None:
    drifted = sample_intent(census, candidate="e" * 64)
    _root, verdict = write_bundle(tmp_path, _run(census, _plans(census, Calls())), drifted, census,
                                  recipe=SAMPLE_RECIPE)
    assert verdict.outcome == "rejected" and "candidate_mismatch" in verdict.categories
