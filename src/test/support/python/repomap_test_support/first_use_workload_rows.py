"""Generic refresh, refusal, pack and cleanup rows shared by the three scenarios.

Pins are read independently of the operation's return value: before the call
in preparation, after it as a witness. Reports are kept as exact member bytes.
A row's call performs only its cataloged owner call(s), once.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from first_use_workload_domains import plan_name, report_name
from first_use_workload_recipe_shapes import PackSpec, RecipeStep
from repomap_test_support.first_use_workload_driver import CallOutcome, Observed, StepPlan
from repomap_test_support.first_use_workload_call_results import ReturnedPublication
from repomap_test_support.first_use_workload_session import Backend, ScenarioContext, pack_facts
from repomap_test_support.first_use_workload_witness import (
    attempt_roots, fresh_attempt, inventory_sha256, pin_witness,
)
from repomap_test_support.resource_report_cli_files import report_leftovers

Invoke = Callable[[], tuple[CallOutcome, bytes | None]]


def _nothing() -> None:
    return None


def _nest(step: RecipeStep, facts: dict[str, Any], backend: str) -> dict[str, Any]:
    return {backend: facts} if step.fact_backends else facts


def _members(step: RecipeStep, report: bytes | None) -> dict[str, bytes]:
    return {} if report is None else {report_name(step.step, step.sub): report}


def refresh_plan(
    context: ScenarioContext,
    step: RecipeStep,
    backend: Backend,
    invoke: Invoke,
    *,
    before: Callable[[], None] = _nothing,
    arm: Callable[[], None] | None = None,
) -> StepPlan:
    """Refresh-class row; ``arm`` prepares one retained after-commit attempt (replay)."""
    state: dict[str, Any] = {}

    def prepare() -> None:
        before()
        publication = None if step.pin_relation == "cold" else backend.publication(context, step.aliases)
        state["pin_before"], _length = pin_witness(backend.home, publication)
        state["roots"] = attempt_roots(backend.home)
        state["preparation_pin"] = None
        if arm is not None:
            arm()
            prepared = backend.publication(context, step.aliases)
            state["preparation_pin"], _length = pin_witness(backend.home, prepared)

    def call() -> CallOutcome:
        outcome, report = invoke()
        state["report"] = report
        return outcome

    def observe(outcome: CallOutcome) -> Observed:
        after = backend.publication(context, step.aliases)
        pin_after, length = pin_witness(backend.home, after)
        returned = outcome.detail
        if not isinstance(returned, ReturnedPublication):
            raise AssertionError("first-use-refresh-return-missing")
        if returned.generation is not None and (
            pin_after is None or returned.generation != pin_after["generation"]
        ):
            raise AssertionError("first-use-refresh-return-pin-mismatch")
        report = state["report"]
        fresh = None if arm is not None else fresh_attempt(state["roots"], attempt_roots(backend.home))
        facts = {
            "outcome": returned.outcome,
            "pin_before": state["pin_before"],
            "pin_after": pin_after,
            "preparation_pin": state["preparation_pin"],
            "attempt_root_fresh": fresh,
            "inventory_sha256": inventory_sha256(context.working_copy, step.aliases),
            "manifest_bytes": length,
        }
        return Observed(_nest(step, facts, backend.name), _members(step, report))

    return StepPlan(prepare, call, observe)


def refusal_plan(
    context: ScenarioContext,
    step: RecipeStep,
    backend: Backend,
    invoke: Invoke,
    *,
    before: Callable[[], None] = _nothing,
    pin_aliases: Sequence[str] | None = None,
) -> StepPlan:
    """Refusal-class row: the complete pin digest is read before and after the call."""
    aliases = tuple(step.aliases if pin_aliases is None else pin_aliases)
    state: dict[str, Any] = {}

    def prepare() -> None:
        publication = backend.publication(context, aliases)
        state["pin_before"], _length = pin_witness(backend.home, publication)
        before()

    def call() -> CallOutcome:
        outcome, report = invoke()
        state["report"] = report
        return outcome

    def observe(outcome: CallOutcome) -> Observed:
        after = backend.publication(context, aliases)
        pin_after, _length = pin_witness(backend.home, after)
        facts = {"code": outcome.refusal, "pin_before": state["pin_before"], "pin_after": pin_after}
        return Observed(_nest(step, facts, backend.name), _members(step, state["report"]))

    return StepPlan(prepare, call, observe)


SelectionFor = Callable[[Backend, PackSpec], Path]


def pack_plan(
    step: RecipeStep,
    backends: Sequence[Backend],
    selection_for: SelectionFor,
    *,
    prepare: Callable[[], None] = _nothing,
) -> StepPlan:
    """Pack-class row: each listed pack runs once per named backend, in order."""
    results: dict[str, list[tuple[PackSpec, dict[str, Any]]]] = {}

    def call() -> CallOutcome:
        for backend in backends:
            for spec in step.packs:
                selection = selection_for(backend, spec)
                results.setdefault(backend.name, []).append((spec, backend.pack(selection, spec)))
        return CallOutcome()

    def observe(_outcome: CallOutcome) -> Observed:
        if step.fact_backends:
            return Observed({name: pack_facts(results[name]) for name in step.fact_backends})
        return Observed(pack_facts(results[backends[0].name]))

    return StepPlan(prepare, call, observe)


def plan_member(step: RecipeStep, data: bytes) -> dict[str, bytes]:
    return {plan_name(step.step, step.sub): data}


def cleanup_plan(
    context: ScenarioContext,
    report_dirs: Sequence[Path],
    harness_counts: Callable[[], tuple[int | None, int | None]],
) -> StepPlan:
    """Final-row witnesses; the driver cleans the registry before observe."""

    def observe(_outcome: CallOutcome) -> Observed:
        leftovers = sorted(name for directory in report_dirs for name in report_leftovers(directory))
        forbidden, shims = harness_counts()
        return Observed({"leftovers": leftovers, "forbidden_events": forbidden, "shim_invocations": shims})

    return StepPlan(_nothing, CallOutcome, observe)


__all__ = ["Invoke", "SelectionFor", "cleanup_plan", "pack_plan", "plan_member", "refresh_plan",
           "refusal_plan"]
