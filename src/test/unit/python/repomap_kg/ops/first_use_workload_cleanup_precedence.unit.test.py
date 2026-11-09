"""An originating operation error retains identity through secondary cleanup control."""

from __future__ import annotations

import pytest

from first_use_workload_recipe_shapes import RecipeStep
from first_use_workload_records import decode_observation
from repomap_test_support.first_use_workload_driver import (
    CallOutcome, Clocks, Observed, ScenarioRun, StepPlan, run_step,
)


@pytest.mark.parametrize("control", [KeyboardInterrupt(), SystemExit(4)])
def test_originating_operation_failure_precedes_secondary_cleanup_control(control: BaseException) -> None:
    primary = RuntimeError("operation failed")

    def call() -> CallOutcome:
        raise primary

    def cleanup() -> None:
        raise control

    run = ScenarioRun("local", "0" * 32, b"{}\n")
    step = RecipeStep("local", 1, "refresh_cold", "sqlite", ("core",), generation=1,
                      pin_relation="cold")
    plan = StepPlan(lambda: None, call, lambda _outcome: Observed(None), cleanup)
    failure = run_step(run, step, plan, Clocks())
    assert failure is primary
    assert run.cleanup_errors == ["cleanup_failed"]
    assert len(run.observations) == 1
    recorded = decode_observation(run.observations[0][1])
    assert recorded["result"] == "failure"
    assert recorded["reason"] == "call_failed"
