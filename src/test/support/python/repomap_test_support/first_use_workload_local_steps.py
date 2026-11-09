"""Local (SQLite) first-use workload rows over guarded ``LocalHarness`` children.

The replay row reuses the incumbent ``resource_view_local`` arming exactly:
``harness.start`` with ``paused_env("after_commit", barrier, abrupt=True)``,
``await_ready``, ``kill_paused_child`` and ``communicate`` in ``finally``. No new
environment key, runner flag, direct ``Popen`` or signal is introduced.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.ops.local_refresh import refresh_local_graph
from common_lore_index.ops.resource_reports._codec import encode_report
from common_lore_index.ops.resource_reports._files import read_report_file
from common_lore_index.ops.resource_view import ResourceObserver
from first_use_workload_domains import report_name
from first_use_workload_recipe import LOCAL_BUDGET_CODE, MISSING_ROOT_CODE, scenario_steps
from first_use_workload_recipe_shapes import PackSpec, RecipeStep
from repomap_test_support.first_use_workflow import guard_first_use_root
from repomap_test_support.first_use_workload_cleanup import CleanupFailure
from repomap_test_support.first_use_workload_call_results import (
    local_cli_publication, local_inprocess_publication,
)
from repomap_test_support.first_use_workload_driver import CallOutcome, Observed, StepPlan
from repomap_test_support.first_use_workload_rows import (
    cleanup_plan, pack_plan, plan_member, refresh_plan, refusal_plan,
)
from repomap_test_support.first_use_workload_session import (
    Backend, ScenarioContext, census_plan, materialize, pack_facts,
)
from repomap_test_support.resource_report_cli_files import private_directory
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, write_mixed_v1_sqlite_home,
)
from repomap_test_support.sqlite_local_harness import LocalHarness, await_ready, kill_paused_child

Key = tuple[int, int]


def harness_counts(harness: LocalHarness) -> tuple[int, int]:
    shims = [line for line in harness.shim_invocations().splitlines() if line.strip()]
    return len(harness.forbidden_events()), len(shims)


def delivered_report(path: Path, forbidden: tuple[object, ...]) -> bytes | None:
    """Custody of one delivered report: regular, 0600, effective owner, identity-free."""
    try:
        details = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o600 \
            or details.st_uid != os.geteuid():
        raise AssertionError("first-use-report-custody")
    data = read_report_file(path)
    text = data.decode("utf-8", "replace")
    if any(item and str(item) in text for item in forbidden):
        raise AssertionError("first-use-report-retained-identity")
    return data


class LocalSession:
    """One guarded SQLite home, its harness and its private report directory."""

    def __init__(self, context: ScenarioContext, name: str = "sqlite") -> None:
        self.context = context
        self.home = context.work / f"{name}-home"
        self.reports = context.work / f"{name}-reports"
        self.harness: LocalHarness | None = None
        self.backend = Backend("sqlite", self.home, self.require_harness)

    def setup(self) -> None:
        home = guard_first_use_root(self.home, self.context.work)
        write_mixed_v1_sqlite_home(home, self.context.working_copy)
        self.harness = LocalHarness(self.context.work / "guarded", block_psycopg=True)
        private_directory(self.reports)

    def require_harness(self) -> LocalHarness:
        if self.harness is None:
            raise AssertionError("first-use-harness-not-prepared")
        return self.harness

    def cli(self, *args: str) -> Any:
        return self.require_harness().run(*args)

    def init(self) -> bool:
        completed = self.cli("ops", "sqlite-init", "--repo-map-home", str(self.home),
                             "--graph", MIXED_V1_GRAPH_ID, "--json")
        if completed.returncode != 0:
            raise AssertionError("first-use-sqlite-init-failed")
        if completed.stderr:
            raise AssertionError("first-use-cli-stderr-unexpected")
        return bool(json.loads(completed.stdout).get("result") == "initialized")

    def refresh(self, step: RecipeStep, *extra: str) -> tuple[CallOutcome, bytes | None]:
        """One guarded CLI refresh delivering a v2 report to a new owner-only file."""
        report = self.reports / Path(report_name(step.step, step.sub)).name
        completed = self.cli(
            "ops", "refresh-graph", "--repo-map-home", str(self.home), "--graph", MIXED_V1_GRAPH_ID,
            "--json", *extra, "--resource-report", str(report), "--resource-report-schema", "2",
        )
        if completed.returncode == 0:
            if completed.stderr:
                raise AssertionError("first-use-cli-stderr-unexpected")
            payload = json.loads(completed.stdout)
            outcome = CallOutcome(detail=local_cli_publication(payload))
        elif (completed.returncode, completed.stdout, completed.stderr) == (
            1, "", f"ERROR: {LOCAL_BUDGET_CODE}\n",
        ):
            outcome = CallOutcome(refusal=LOCAL_BUDGET_CODE)
        else:
            raise AssertionError("first-use-refresh-child-failed")
        return outcome, delivered_report(report, (self.home, self.context.working_copy, "mixed-v1"))

    def config(self) -> LocalSqliteConfig:
        config = load_graph_registry_config_home(self.home)
        if not isinstance(config, LocalSqliteConfig):
            raise AssertionError("first-use-local-config-invalid")
        return config

    def plan(self) -> tuple[dict[str, Any], bytes]:
        """``ops sealing-plan --json`` through the guarded child; a canonical member."""
        completed = self.cli("ops", "sealing-plan", "--repo-map-home", str(self.home),
                             "--graph", MIXED_V1_GRAPH_ID, "--json")
        if completed.returncode != 0:
            raise AssertionError("first-use-sealing-plan-failed")
        if completed.stderr:
            raise AssertionError("first-use-cli-stderr-unexpected")
        plan = json.loads(completed.stdout)
        return plan, completed.stdout.encode("utf-8")


def inprocess_refresh(session: LocalSession) -> tuple[CallOutcome, bytes | None]:
    """One in-process Local refresh with a fresh v1 observer; ``ValueError`` is the refusal."""
    observer = ResourceObserver()
    try:
        result = refresh_local_graph(session.config(), MIXED_V1_GRAPH_ID, resource_observer=observer)
    except ValueError:
        return CallOutcome(refusal=MISSING_ROOT_CODE), encode_report(observer.report())
    return CallOutcome(detail=local_inprocess_publication(result)), encode_report(observer.report())


def arm_after_commit(session: LocalSession) -> None:
    """Commit one armed generation and settle the abrupt child (incumbent technique)."""
    harness = session.require_harness()
    barrier = session.context.work / "after-commit"
    child = harness.start(
        "ops", "refresh-graph", "--repo-map-home", str(session.home), "--graph", MIXED_V1_GRAPH_ID,
        "--json", extra_env=harness.paused_env("after_commit", barrier, abrupt=True),
    )
    try:
        await_ready(barrier, child)
        kill_paused_child(child)
    finally:
        child.communicate()


def rename_away(context: ScenarioContext, source: Path, name: str) -> None:
    """Move an owned root aside and register its restoration."""
    target = context.work / name
    source.rename(target)

    def restore() -> None:
        target.rename(source)

    context.registry.register(name, restore)


def _release_or_fail(context: ScenarioContext, key: str) -> None:
    failures = context.registry.release(key)
    if failures:
        raise CleanupFailure(tuple(failures))


def plan_row(step: RecipeStep, produce: Any) -> StepPlan:
    def call() -> CallOutcome:
        return CallOutcome(detail=produce())

    def observe(outcome: CallOutcome) -> Observed:
        plan, data = outcome.detail
        keys = ("inventory_bytes", "inventory_files", "planned_min_read_bytes")
        return Observed({key: plan.get(key) for key in keys}, plan_member(step, data))

    return StepPlan(lambda: None, call, observe)


def _pack_current(context: ScenarioContext, step: RecipeStep, session: LocalSession,
                  selections: dict[str, Path]) -> StepPlan:
    """Select the pinned publication, hide every source, pack, restore."""
    packets: list[tuple[PackSpec, dict[str, Any]]] = []

    def call() -> CallOutcome:
        selection = context.fresh_path("selection-first")
        session.backend.select(selection, step.aliases, pin=True)
        selections["pinned_first"] = selections["pinned_current"] = selection
        rename_away(context, context.working_copy, "working-copy-hidden")
        try:
            packets.extend((spec, session.backend.pack(selection, spec)) for spec in step.packs)
        except BaseException as primary:
            try:
                context.registry.release("working-copy-hidden")
            except BaseException:
                pass
            raise primary
        _release_or_fail(context, "working-copy-hidden")
        return CallOutcome()

    return StepPlan(lambda: None, call, lambda _outcome: Observed(pack_facts(packets)))


def build_local_plans(context: ScenarioContext) -> Mapping[Key, StepPlan]:
    steps = {step.key: step for step in scenario_steps("local")}
    session = LocalSession(context)
    backend = session.backend
    selections: dict[str, Path] = {}

    def cli_refresh(key: Key, *extra: str) -> Any:
        return lambda: session.refresh(steps[key], *extra)

    budget = 4 * context.census.generation(2).projection(steps[(9, 0)].aliases).S
    return {
        (1, 0): census_plan(context, steps[(1, 0)]),
        (2, 0): StepPlan(
            session.setup, lambda: CallOutcome(detail=session.init()),
            lambda outcome: Observed({"backend": "sqlite", "initialized": outcome.detail}),
        ),
        (3, 0): plan_row(steps[(3, 0)], session.plan),
        (4, 0): refresh_plan(context, steps[(4, 0)], backend, cli_refresh((4, 0))),
        (5, 0): _pack_current(context, steps[(5, 0)], session, selections),
        (6, 0): refresh_plan(context, steps[(6, 0)], backend, cli_refresh((6, 0))),
        (7, 0): refresh_plan(context, steps[(7, 0)], backend, cli_refresh((7, 0)),
                             before=lambda: _regenerate(context, 2)),
        (8, 0): pack_plan(steps[(8, 0)], [backend], lambda _backend, spec: selections[spec.selection]),
        (9, 0): refusal_plan(context, steps[(9, 0)], backend,
                             cli_refresh((9, 0), "--sealing-max-read-bytes", str(budget))),
        (10, 0): refusal_plan(
            context, steps[(10, 0)], backend, lambda: inprocess_refresh(session),
            before=lambda: rename_away(context, context.working_copy / "companion", "companion-missing"),
        ),
        (11, 0): refresh_plan(context, steps[(11, 0)], backend, cli_refresh((11, 0)),
                              before=lambda: _release_or_fail(context, "companion-missing")),
        (12, 0): refresh_plan(context, steps[(12, 0)], backend, lambda: inprocess_refresh(session),
                              arm=lambda: arm_after_commit(session)),
        (13, 0): cleanup_plan(context, [session.reports],
                              lambda: harness_counts(session.require_harness())),
    }


def _regenerate(context: ScenarioContext, generation: int) -> None:
    materialize(context, generation)


__all__ = [
    "LocalSession", "arm_after_commit", "build_local_plans", "delivered_report", "harness_counts",
    "inprocess_refresh", "plan_row", "rename_away",
]
