"""Mixed first-use workload rows: one working copy, a SQLite and a PostgreSQL home.

Per-backend facts stay distinct objects. The privacy refusal moves the
metadata-only ``feeds`` and ``mailbox`` roots aside first, so an accidental
body read cannot make the refusal pass, then asks for a ``feeds`` lexical
build on PostgreSQL; the returned refusal and its policy code are the outcome.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from common_lore_index.ops.lexical_service import build_graph_lexical_generation
from common_lore_index.ops.resource_reports._codec import encode_report
from common_lore_index.ops.resource_view import ResourceObserver
from first_use_workload_recipe import ALL_ALIASES, scenario_steps
from first_use_workload_recipe_shapes import PackSpec, RecipeStep
from repomap_test_support.first_use_workload_driver import CallOutcome, Observed, StepPlan
from repomap_test_support.first_use_workload_local_steps import (
    LocalSession, harness_counts, rename_away,
)
from repomap_test_support.first_use_workload_rows import (
    cleanup_plan, pack_plan, refresh_plan, refusal_plan,
)
from repomap_test_support.first_use_workload_server_steps import ServerSession
from repomap_test_support.first_use_workload_session import (
    Backend, ScenarioContext, census_plan,
)
from repomap_test_support.first_use_workload_witness import snapshot_facts
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, binding_id_for_alias,
)

Key = tuple[int, int]
REFUSED_WITH_PLAN = "refused_with_plan"


def snapshot_row(context: ScenarioContext, step: RecipeStep, backends: tuple[Backend, ...]) -> StepPlan:
    """Each home's retained manifest against the incumbent multi-source scan."""
    publications: dict[str, dict[str, Any] | None] = {}
    facts: dict[str, Any] = {}

    def prepare() -> None:
        for backend in backends:
            publications[backend.name] = backend.publication(context, step.aliases)

    def call() -> CallOutcome:
        for backend in backends:
            publication = publications[backend.name]
            if publication is None:
                raise AssertionError("first-use-snapshot-publication-absent")
            facts[backend.name] = snapshot_facts(
                backend.name, backend.home, context.working_copy, publication, step.aliases,
            )
        return CallOutcome()

    return StepPlan(prepare, call, lambda _outcome: Observed(dict(facts)))


def privacy_call(server: ServerSession, step: RecipeStep) -> tuple[CallOutcome, bytes]:
    """One metadata-only lexical build; a returned refusal before body capture."""
    observer = ResourceObserver()
    refused = build_graph_lexical_generation(
        server.config, MIXED_V1_GRAPH_ID,
        selected_binding_ids=tuple(binding_id_for_alias(alias) for alias in step.aliases),
        authorize_body=True, resource_observer=observer,
    )
    report = encode_report(observer.report())
    if refused.result != "refused":
        return CallOutcome(), report
    if refused.plan is not None or refused.published is not None:
        return CallOutcome(refusal=REFUSED_WITH_PLAN), report
    return CallOutcome(refusal=refused.refusal_code), report


def _remove_metadata_roots(context: ScenarioContext) -> None:
    for alias in ("feeds", "mailbox"):
        rename_away(context, context.working_copy / alias, f"{alias}-removed")


def build_mixed_plans(context: ScenarioContext) -> Mapping[Key, StepPlan]:
    steps = {step.key: step for step in scenario_steps("mixed")}
    sqlite = LocalSession(context)
    server = ServerSession(context, ALL_ALIASES)
    backends = (sqlite.backend, server.backend)
    selections: dict[tuple[str, str], Path] = {}

    def selection_for(backend: Backend, spec: PackSpec) -> Path:
        key = (backend.name, spec.selection)
        if key not in selections:
            aliases = ("core",) if spec.selection == "pinned_subset" else ALL_ALIASES
            path = context.fresh_path(f"selection-{backend.name}-{spec.selection}")
            backend.select(path, aliases, pin=True)
            selections[key] = path
        return selections[key]

    def sqlite_initial() -> tuple[CallOutcome, bytes | None]:
        if not sqlite.init():
            raise AssertionError("first-use-sqlite-init-not-initialized")
        return sqlite.refresh(steps[(2, 0)])

    def postgres_initial() -> tuple[CallOutcome, bytes | None]:
        server.migrate()
        return server.refresh()

    return {
        (1, 0): census_plan(context, steps[(1, 0)]),
        (2, 0): refresh_plan(context, steps[(2, 0)], sqlite.backend, sqlite_initial,
                             before=sqlite.setup),
        (3, 0): refresh_plan(context, steps[(3, 0)], server.backend, postgres_initial,
                             before=server.enter),
        (4, 0): snapshot_row(context, steps[(4, 0)], backends),
        (5, 0): pack_plan(steps[(5, 0)], backends, selection_for),
        (6, 0): pack_plan(steps[(6, 0)], backends, selection_for),
        (7, 0): refusal_plan(
            context, steps[(7, 0)], server.backend, lambda: privacy_call(server, steps[(7, 0)]),
            before=lambda: _remove_metadata_roots(context), pin_aliases=ALL_ALIASES,
        ),
        (8, 0): cleanup_plan(context, [sqlite.reports], lambda: harness_counts(sqlite.require_harness())),
    }


__all__ = ["REFUSED_WITH_PLAN", "build_mixed_plans", "privacy_call", "snapshot_row"]
