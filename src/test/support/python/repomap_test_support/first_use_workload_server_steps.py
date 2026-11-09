"""Server (PostgreSQL) first-use workload rows over ``temporary_postgres``.

The disposable cluster is entered in the migrate row's preparation and is
registered for exit, so it closes exactly once in the scenario's cleanup row.
Cluster host, port, database, user and password stay in memory and never reach
the evidence. Refresh, plan and lexical calls are the incumbent product calls.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from common_lore_index.artifacts.sealing_governance import SealingBudget
from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.lexical_service import (
    build_graph_lexical_generation,
    query_graph_lexical_generation,
    revoke_graph_lexical_generation,
)
from common_lore_index.ops.refresh import refresh_graph
from common_lore_index.ops.resource_reports._codec import encode_report
from common_lore_index.ops.resource_view import ResourceObserver
from common_lore_index.ops.sealing_plan import build_sealing_plan
from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
from common_lore_index.retrieval.query_contracts import CapabilityState
from common_lore_index.storage import apply_migrations, default_rdbms_root
from first_use_workload_domains import report_name
from first_use_workload_recipe import SERVER_BUDGET_CODE, scenario_steps
from first_use_workload_recipe_shapes import PackSpec, RecipeStep
from repomap_test_support.first_use_workflow import guard_first_use_root
from repomap_test_support.first_use_workload_call_results import (
    revocation_result, server_publication,
)
from repomap_test_support.first_use_workload_driver import (
    CallOutcome, Observed, RuntimeUnavailable, StepPlan,
)
from repomap_test_support.first_use_workload_local_steps import plan_row
from repomap_test_support.first_use_workload_rows import (
    cleanup_plan, pack_plan, refresh_plan, refusal_plan,
)
from repomap_test_support.first_use_workload_session import (
    Backend, ScenarioContext, census_plan, materialize,
)
from repomap_test_support.first_use_workload_witness import bounded, hit_refs
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, binding_id_for_alias, write_mixed_v1_postgres_home,
)

Key = tuple[int, int]
REVOKE_REASON = "first_use_workload"


class ServerSession:
    """One PostgreSQL home over a test-owned temporary cluster."""

    def __init__(self, context: ScenarioContext, aliases: Sequence[str]) -> None:
        self.context = context
        self.aliases = tuple(aliases)
        self.home = context.work / "postgres-home"
        self.backend = Backend("postgresql", self.home)
        self.postgres: Any = None
        self._config: OpsConfig | None = None

    def enter(self) -> None:
        """Enter the cluster (registered for exit) and write the home in preparation."""
        stack = ExitStack()
        try:
            self.postgres = stack.enter_context(temporary_postgres())
        except OSError as error:
            stack.close()
            raise RuntimeUnavailable("first-use-postgres-unavailable") from error
        self.context.registry.register("temporary-postgres", stack.close)
        home = guard_first_use_root(self.home, self.context.work)
        postgres = self.postgres
        write_mixed_v1_postgres_home(
            home, self.context.working_copy, host=postgres.host, port=postgres.port,
            database=postgres.database, user=postgres.user, password=postgres.password,
            declared_aliases=self.aliases,
        )
        config = load_graph_registry_config_home(home)
        if not isinstance(config, OpsConfig):
            raise AssertionError("first-use-server-config-invalid")
        self._config = config

    @property
    def config(self) -> OpsConfig:
        if self._config is None:
            raise AssertionError("first-use-server-not-prepared")
        return self._config

    def migrate(self) -> bool:
        apply_migrations(
            default_rdbms_root(), self.config.postgres.psql_args_for_database(self.postgres.database),
            psql_command=self.postgres.psql_command,
        )
        return True

    def refresh(self, max_read_bytes: int | None = None) -> tuple[CallOutcome, bytes]:
        observer = ResourceObserver(report_schema="cloe-resource-view-v2")
        budget = None if max_read_bytes is None else SealingBudget(max_read_bytes=max_read_bytes)
        extra: dict[str, Any] = {} if budget is None else {"sealing_budget": budget}
        result = refresh_graph(self.config, MIXED_V1_GRAPH_ID, psql_command=self.postgres.psql_command,
                               resource_observer=observer, **extra)
        triple = (result.result, result.error_category, result.publication_state)
        if (result.result, result.publication_state) == ("success", "committed"):
            outcome = CallOutcome(detail=server_publication(result))
        elif triple == ("failure", SERVER_BUDGET_CODE, "not_started"):
            outcome = CallOutcome(refusal=SERVER_BUDGET_CODE)
        else:
            raise AssertionError("first-use-server-refresh-unexpected")
        return outcome, encode_report(observer.report())

    def plan(self) -> tuple[dict[str, Any], bytes]:
        plan = build_sealing_plan(self.config, MIXED_V1_GRAPH_ID)
        return plan.to_payload(), plan.canonical_json() + b"\n"


def _lexical_facts(**values: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "result": None, "hits": None, "observed_locations": [], "revoked_generations": None,
        "unavailable_reason": None,
    }
    facts.update(values)
    return facts


def lexical_build_row(session: ServerSession, step: RecipeStep, aliases: Sequence[str]) -> StepPlan:
    def call() -> CallOutcome:
        observer = ResourceObserver()
        built = build_graph_lexical_generation(
            session.config, MIXED_V1_GRAPH_ID,
            selected_binding_ids=tuple(binding_id_for_alias(alias) for alias in aliases),
            authorize_body=True, resource_observer=observer,
        )
        return CallOutcome(detail=(built.result, encode_report(observer.report())))

    def observe(outcome: CallOutcome) -> Observed:
        result, report = outcome.detail
        return Observed(_lexical_facts(result=result), _report(step, report))

    return StepPlan(lambda: None, call, observe)


def _report(step: RecipeStep, data: bytes) -> dict[str, bytes]:
    return {report_name(step.step, step.sub): data}


def _query(session: ServerSession, step: RecipeStep, observer: ResourceObserver | None) -> Any:
    spec = step.lexical
    assert spec is not None and spec.query is not None
    request = LexicalQueryRequest(
        query=spec.query, query_style="ranked_terms",
        selected_binding_ids=tuple(binding_id_for_alias(alias) for alias in spec.query_aliases),
    )
    return query_graph_lexical_generation(
        session.config, MIXED_V1_GRAPH_ID, request, authorize_body=True,
        resource_observer=observer,
    )


def lexical_query_row(session: ServerSession, step: RecipeStep) -> StepPlan:
    def call() -> CallOutcome:
        observer = ResourceObserver()
        envelope = _query(session, step, observer)
        return CallOutcome(detail=(envelope, encode_report(observer.report())))

    def observe(outcome: CallOutcome) -> Observed:
        envelope, report = outcome.detail
        facts = _lexical_facts(
            result=envelope.capability_state.value, hits=len(envelope.hits),
            observed_locations=bounded(hit_refs(envelope.hits)),
            unavailable_reason=envelope.unavailable_reason,
        )
        return Observed(facts, _report(step, report))

    return StepPlan(lambda: None, call, observe)


def lexical_revoke_row(session: ServerSession, step: RecipeStep) -> StepPlan:
    def call() -> CallOutcome:
        observer = ResourceObserver()
        revoked = revoke_graph_lexical_generation(
            session.config, MIXED_V1_GRAPH_ID, reason=REVOKE_REASON, confirmed=True,
            resource_observer=observer,
        )
        report = encode_report(observer.report())
        after = _query(session, step, None)
        count = revoked.revoked_generation_count
        return CallOutcome(detail=(revocation_result(count), count, after, report))

    def observe(outcome: CallOutcome) -> Observed:
        result, count, after, report = outcome.detail
        state = after.capability_state
        absent = after.unavailable_reason if state == CapabilityState.UNAVAILABLE else f"capability_{state.value}"
        facts = _lexical_facts(
            result=result, revoked_generations=count,
            unavailable_reason=absent,
        )
        return Observed(facts, _report(step, report))

    return StepPlan(lambda: None, call, observe)


def build_server_plans(context: ScenarioContext) -> Mapping[Key, StepPlan]:
    steps = {step.key: step for step in scenario_steps("server")}
    session = ServerSession(context, steps[(1, 0)].aliases)
    backend = session.backend
    selections: dict[str, Path] = {}

    def selection_for(_backend: Backend, spec: PackSpec) -> Path:
        if spec.selection == "pinned_current":
            path = context.fresh_path("selection-first")
            backend.select(path, session.aliases, pin=True)
            selections["pinned_first"] = path
            return path
        if spec.selection == "unpinned_current":
            path = context.fresh_path("selection-current")
            backend.select(path, session.aliases, pin=False)
            return path
        return selections[spec.selection]

    budget = 4 * context.census.generation(2).projection(session.aliases).S
    return {
        (1, 0): census_plan(context, steps[(1, 0)]),
        (2, 0): StepPlan(
            session.enter, lambda: CallOutcome(detail=session.migrate()),
            lambda outcome: Observed({"backend": "postgresql", "initialized": outcome.detail}),
        ),
        (3, 0): plan_row(steps[(3, 0)], session.plan),
        (4, 0): refresh_plan(context, steps[(4, 0)], backend, session.refresh),
        (5, 0): pack_plan(steps[(5, 0)], [backend], selection_for),
        (6, 0): refresh_plan(context, steps[(6, 0)], backend, session.refresh),
        (7, 0): refresh_plan(context, steps[(7, 0)], backend, session.refresh,
                             before=lambda: _regenerate(context)),
        (8, 0): pack_plan(steps[(8, 0)], [backend], selection_for),
        (9, 0): refusal_plan(context, steps[(9, 0)], backend, lambda: session.refresh(budget)),
        (10, 0): lexical_build_row(session, steps[(10, 0)], session.aliases),
        (11, 0): lexical_query_row(session, steps[(11, 0)]),
        (11, 1): lexical_query_row(session, steps[(11, 1)]),
        (11, 2): lexical_query_row(session, steps[(11, 2)]),
        (12, 0): lexical_revoke_row(session, steps[(12, 0)]),
        (13, 0): cleanup_plan(context, [], lambda: (None, None)),
    }


def _regenerate(context: ScenarioContext) -> None:
    materialize(context, 2)


__all__ = [
    "REVOKE_REASON", "ServerSession", "build_server_plans", "lexical_build_row",
    "lexical_query_row", "lexical_revoke_row",
]
