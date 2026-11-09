"""State machine, scoped spans/CPU, cleanup registry and bundle custody (section 7).

Each recipe row moves ``pending -> preparing -> calling -> observing -> cleaning
-> recorded``. Preparation, the cataloged owner call(s), witnesses and owned
cleanup are timed separately with ``time.monotonic_ns``; parent-process CPU is
``time.process_time_ns`` and waited-descendant CPU is the ``RUSAGE_CHILDREN``
delta over the call span (all descendants reaped in it). Nothing is retried.
After a required failure the remaining rows are recorded once as
``unavailable``/``not_reached``. ``KeyboardInterrupt``/``SystemExit`` run only
the registered cleanup and propagate unchanged, so no verdict is written.
"""

from __future__ import annotations

import os
import resource
import secrets
import stat
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from first_use_workload_bundle import BundleWriter, read_bundle
from first_use_workload_census import Census
from first_use_workload_domains import (
    REFUSAL_CODES, SCHEMA_OBSERVATION, WorkloadError, observation_name,
)
from first_use_workload_integrity import member_rows, sha256_hex
from first_use_workload_reconcile import Verdict, reconcile
from first_use_workload_recipe import RECIPE, scenario_steps
from first_use_workload_recipe_shapes import Recipe, RecipeStep
from first_use_workload_records import encode_index, encode_observation, index_payload
from first_use_workload_validation import check_location_bound, fact_objects
from repomap_test_support.first_use_workload_cleanup import (
    CleanupFailure, CleanupRegistry, cleanup_labels, run_terminal_cleanup,
)

BUNDLE_CHILD = "first-use-workload"
Clock = Callable[[], int]


class StaleInput(Exception):
    """The materialized input differs from the frozen census; refuse before execution."""


class RuntimeUnavailable(Exception):
    """A required runtime is absent; the row is ``skipped/runtime_unavailable``."""


class Unbounded(Exception):
    """Observed public refs exceed the closed bound; nothing is truncated."""


class UnsafeBundleBase(RuntimeError):
    """An existing inner report root is unsafe; never fall back silently."""


@dataclass(frozen=True)
class CallOutcome:
    """What the cataloged call returned: ``refusal`` is a closed owner code or a raw label."""

    refusal: str | None = None
    detail: Any = None


@dataclass(frozen=True)
class Observed:
    facts: dict[str, Any] | None
    members: dict[str, bytes] = field(default_factory=dict)


def _nothing() -> None:
    return None


@dataclass(frozen=True)
class StepPlan:
    prepare: Callable[[], None]
    call: Callable[[], CallOutcome]
    observe: Callable[[CallOutcome], Observed]
    cleanup: Callable[[], None] = _nothing


def children_cpu_ns() -> int:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return round((usage.ru_utime + usage.ru_stime) * 1_000_000_000)


@dataclass(frozen=True)
class Clocks:
    wall: Clock = time.monotonic_ns
    process: Clock = time.process_time_ns
    children: Clock = children_cpu_ns


def _delta(start: int, end: int) -> int | None:
    return end - start if end >= start else None


@dataclass
class ScenarioRun:
    scenario: str
    attempt: str
    intent: bytes
    observations: list[tuple[str, bytes]] = field(default_factory=list)
    members: dict[str, bytes] = field(default_factory=dict)
    primary: Exception | None = None
    cleanup_errors: list[str] = field(default_factory=list)


def _classify(step: RecipeStep, outcome: CallOutcome) -> tuple[str, str | None, str | None]:
    code = outcome.refusal
    closed = code if code in REFUSAL_CODES else None
    if step.expectation == "pass":
        return ("pass", None, None) if code is None else ("failure", closed, "unexpected_refusal")
    if code is not None and code in step.refusal_codes:
        return "expected_refusal", code, None
    if code is None:
        return "failure", None, "unexpected_return"
    return "failure", closed, "unexpected_refusal"


def _failure_reason(error: Exception, default: str) -> tuple[str, str]:
    if isinstance(error, CleanupFailure):
        return "failure", "cleanup_failed"
    if isinstance(error, StaleInput):
        return "failure", "stale_input"
    if isinstance(error, Unbounded):
        return "failure", "unbounded"
    if isinstance(error, RuntimeUnavailable):
        return "skipped", "runtime_unavailable"
    return "failure", default


class _UnexpectedOutcome(Exception):
    """The call returned a non-matching outcome; recorded, never retried."""


def _payload(run: ScenarioRun, step: RecipeStep, **values: Any) -> dict[str, Any]:
    return {
        "schema": SCHEMA_OBSERVATION, "attempt": run.attempt, "intent": sha256_hex(run.intent),
        "scenario": step.scenario, "backend": step.backend, "step": step.step, "sub": step.sub,
        "action": step.action, "expectation": step.expectation, **values,
    }


def _empty_spans() -> dict[str, int | None]:
    return {"prepare_ns": None, "call_ns": None, "observe_ns": None, "cleanup_ns": None}


def _check_facts(step: RecipeStep, facts: dict[str, Any] | None) -> None:
    try:
        check_location_bound(fact_objects(step, facts))
    except WorkloadError as error:
        if error.category == "unbounded":
            raise Unbounded("first-use-refs-unbounded") from None
        raise


def run_step(
    run: ScenarioRun, step: RecipeStep, plan: StepPlan, clocks: Clocks, *,
    cleanup_before_observe: bool = False,
) -> Exception | None:
    """Record one row; terminal cleanup may precede its final witnesses."""
    spans = _empty_spans()
    cpu: dict[str, int | None] = {"parent_process_ns": None, "waited_descendants_ns": None}
    result, refusal, reason = "failure", None, None
    facts: dict[str, Any] | None = None
    members: dict[str, bytes] = {}
    error: Exception | None = None
    start = clocks.wall()
    try:
        plan.prepare()
    except Exception as failure:
        error = failure
        result, reason = _failure_reason(failure, "call_failed")
    spans["prepare_ns"] = _delta(start, clocks.wall())
    outcome = CallOutcome()
    if error is None:
        process0, children0, start = clocks.process(), clocks.children(), clocks.wall()
        try:
            outcome = plan.call()
        except Exception as failure:
            error = failure
            result, reason = _failure_reason(failure, "call_failed")
        finally:
            spans["call_ns"] = _delta(start, clocks.wall())
            cpu = {
                "parent_process_ns": _delta(process0, clocks.process()),
                "waited_descendants_ns": _delta(children0, clocks.children()),
            }
        if error is None:
            result, refusal, reason = _classify(step, outcome)
            if result == "failure":
                error = _UnexpectedOutcome(reason)

    cleanup_failed = False

    def cleanup_phase() -> None:
        nonlocal cleanup_failed, error, result, reason
        start = clocks.wall()
        try:
            plan.cleanup()
        except BaseException as failure:
            if not isinstance(failure, Exception):
                if error is None:
                    raise
                run.cleanup_errors.extend(cleanup_labels(failure))
            else:
                if not isinstance(failure, CleanupFailure):
                    run.cleanup_errors.extend(cleanup_labels(failure))
                if error is None:
                    error, result, reason = failure, "failure", "cleanup_failed"
                    cleanup_failed = True
        spans["cleanup_ns"] = _delta(start, clocks.wall())

    if cleanup_before_observe:
        cleanup_phase()
    if error is None or cleanup_failed:
        start = clocks.wall()
        try:
            observed = plan.observe(outcome)
            _check_facts(step, observed.facts)
            facts, members = observed.facts, dict(observed.members)
        except Exception as failure:
            if error is None:
                error = failure
                result, reason = _failure_reason(failure, "witness_failed")
                if result == "skipped":
                    result = "failure"
            elif not isinstance(failure, CleanupFailure):
                run.cleanup_errors.extend(cleanup_labels(failure))
        spans["observe_ns"] = _delta(start, clocks.wall())
    if not cleanup_before_observe:
        cleanup_phase()
    payload = _payload(run, step, result=result, refusal=refusal, reason=reason, spans=spans,
                       cpu=cpu, facts=facts, members=member_rows(members))
    try:
        encoded = encode_observation(payload)
    except WorkloadError as failure:
        unbounded = failure.category in {"too_large", "unbounded"}
        payload.update(result="failure", reason="unbounded" if unbounded else "witness_failed",
                       facts=None, members=[])
        encoded = encode_observation(payload)
        members = {}
        error = error or failure
    run.observations.append((observation_name(step.step, step.sub), encoded))
    run.members.update(members)
    return error


def _not_reached(run: ScenarioRun, step: RecipeStep) -> None:
    payload = _payload(run, step, result="unavailable", refusal=None, reason="not_reached",
                       spans=_empty_spans(), cpu={"parent_process_ns": None,
                                                  "waited_descendants_ns": None},
                       facts=None, members=[])
    run.observations.append((observation_name(step.step, step.sub), encode_observation(payload)))


def run_rows(
    run: ScenarioRun,
    plans: Mapping[tuple[int, int], StepPlan],
    registry: CleanupRegistry,
    *,
    recipe: Recipe = RECIPE,
    clocks: Clocks | None = None,
) -> ScenarioRun:
    """Run every recipe row once; the terminal cleanup row always runs."""
    timing = Clocks() if clocks is None else clocks
    steps = scenario_steps(run.scenario, recipe)
    try:
        for position, step in enumerate(steps):
            terminal = position == len(steps) - 1 or step.harness_cleanup
            if run.primary is not None and not terminal:
                _not_reached(run, step)
                continue
            plan = plans[step.key]
            if terminal:
                action = plan.cleanup
                prior_failures = tuple(run.cleanup_errors)
                plan = StepPlan(
                    plan.prepare, plan.call, plan.observe,
                    partial(run_terminal_cleanup, action, registry, prior_failures),
                )
            failure = run_step(run, step, plan, timing, cleanup_before_observe=terminal)
            run.cleanup_errors.extend(registry.drain_errors())
            control = registry.take_control_error()
            if control is not None and run.primary is None and (
                    failure is None or isinstance(failure, CleanupFailure)):
                raise control
            if failure is not None and run.primary is None:
                run.primary = failure
        registry.unwind()
        post_failures = registry.drain_errors()
        run.cleanup_errors.extend(post_failures)
        control = registry.take_control_error()
        if control is not None and run.primary is None:
            raise control
        if post_failures and run.primary is None:
            raise CleanupFailure(tuple(post_failures))
    except BaseException:
        registry.unwind()
        run.cleanup_errors.extend(registry.drain_errors())
        registry.take_control_error()
        raise
    return run


def new_attempt() -> str:
    return secrets.token_hex(16)


def _owned_directory(path: Path) -> None:
    details = os.lstat(path)
    if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.geteuid() or details.st_mode & 0o022:
        raise UnsafeBundleBase("first-use-bundle-base-unsafe")


def select_bundle_base(
    temporary: Path, *, sandbox_active: Callable[[], bool], inner_root: Path,
) -> Path:
    """``INNER_REPORT_ROOT`` only when active and already safe; never create it."""
    if sandbox_active():
        try:
            os.lstat(inner_root)
        except FileNotFoundError:
            pass
        else:
            _owned_directory(inner_root)
            base = inner_root / BUNDLE_CHILD
            try:
                os.mkdir(base, 0o700)
            except FileExistsError:
                pass
            _owned_directory(base)
            return base
    base = temporary / BUNDLE_CHILD
    base.mkdir(mode=0o700, exist_ok=True)
    _owned_directory(base)
    return base


def default_bundle_base(temporary: Path) -> Path:
    from test_sandbox import INNER_REPORT_ROOT, active_sandbox

    return select_bundle_base(temporary, sandbox_active=active_sandbox, inner_root=INNER_REPORT_ROOT)


def write_bundle(base: Path, run: ScenarioRun, current_intent: bytes,
                 census: Census, *, recipe: Recipe = RECIPE) -> tuple[Path, Verdict]:
    """Payloads, then index, then the verdict reconciled from the written bytes."""
    writer = BundleWriter(base, run.scenario, run.attempt)
    writer.write("intent.json", run.intent)
    for name, data in run.observations:
        writer.write(name, data)
    for name in sorted(run.members):
        writer.write(name, run.members[name])
    rows = member_rows(writer.written)
    writer.write("index.json", encode_index(index_payload(
        run.scenario, run.attempt, sha256_hex(run.intent), rows,
    )))
    verdict = reconcile(current_intent, read_bundle(writer.root), census, recipe)
    writer.write("verdict.json", verdict.encoded())
    return writer.root, verdict


__all__ = [
    "BUNDLE_CHILD", "CallOutcome", "CleanupFailure", "CleanupRegistry", "Clocks", "Observed",
    "RuntimeUnavailable",
    "ScenarioRun", "StaleInput", "StepPlan", "Unbounded", "UnsafeBundleBase", "children_cpu_ns",
    "default_bundle_base", "new_attempt", "run_rows", "run_step", "select_bundle_base",
    "write_bundle",
]
