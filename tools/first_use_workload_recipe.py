"""The frozen, code-owned first-use recipe (contract section 4).

Thirteen Local, fifteen Server and eight mixed rows, in order. Expected codes,
labels and manual locations are literal constants from current owner contracts
and the public mixed-v1 fixture text; none is copied from current output. Only
the planned-refusal rows pass an explicit limit (``4S``, ``S`` from the census).
"""

from __future__ import annotations

import hashlib
from typing import Any

from common_lore_index.ops.resource_view._canonical import canonical_bytes
from first_use_workload_recipe_shapes import (
    LexicalSpec, PackSpec, Recipe, RecipeStep, ReportSpec,
)

ALL_ALIASES = ("core", "companion", "feeds", "mailbox")
SERVER_ALIASES = ("core", "companion")
PIPELINE_SYMBOL = "RetrievalExecutionPipeline"
GEN2_MARKER = "GEN2_EXTENSION_ACTIVE_MARKER_2026"
LEGACY_TOKEN = "LEGACY_DEPRECATED_PIPELINE_V0_ONLY_TOKEN"
INVESTIGATION_KEY = "py:pkg.pipeline.RetrievalExecutionPipeline"
PIPELINE_LOCATION = ("core", "pkg/pipeline.py")
GEN2_LOCATION = ("core", "pkg/gen2_extension.py")
LEGACY_LOCATION = ("core", "pkg/legacy_deprecated.py")
STALE_REASON = "selection_publication_advanced"
LOCAL_BUDGET_CODE = "sealing-budget-exceeded:planned_read_bytes"
SERVER_BUDGET_CODE = "resource_budget_exceeded"
MISSING_ROOT_CODE = "local_value_error"
PRIVACY_CODES = ("graph_privacy_not_authorized", "retention_not_authorized")
PACK_STATUSES = ("complete", "partial")
QUERY_RESULTS = ("available", "partial")
MAX_PACK_BYTES = 16384

_LOCAL_PUBLISH = ReportSpec(2, "local_refresh", "sqlite", ("published",), "complete")
_SERVER_COMMIT = ReportSpec(2, "server_refresh", "postgresql", ("committed",), "complete")


def _implementation(selection: str, *, expected: bool = True) -> PackSpec:
    return PackSpec(
        tag="implementation", mode="ranked_discovery", query=PIPELINE_SYMBOL,
        intent="implementation", selection=selection, statuses=PACK_STATUSES,
        expected=(PIPELINE_LOCATION,) if expected else (),
    )


def _stale(selection: str) -> PackSpec:
    return PackSpec(
        tag="stale", mode="ranked_discovery", query=PIPELINE_SYMBOL, intent="implementation",
        selection=selection, statuses=("stale",), reason=STALE_REASON,
    )


def _local() -> Recipe:
    def row(step: int, action: str, **extra: Any) -> RecipeStep:
        return RecipeStep("local", step, action, "sqlite", ALL_ALIASES, **extra)

    return (
        row(1, "census_verify", generation=1, calls=("materialize_g1", "compare_census")),
        row(2, "sqlite_init", calls=("cli_sqlite_init",)),
        row(3, "sealing_plan", generation=1, plan=True, calls=("cli_sealing_plan",)),
        row(4, "refresh_cold", generation=1, report=_LOCAL_PUBLISH, pin_relation="cold",
            calls=("cli_refresh_report_v2",)),
        row(5, "pack_current", packs=(_implementation("pinned_current"),),
            calls=("cli_select_pinned", "hide_sources", "cli_pack", "restore_sources")),
        row(6, "refresh_repeat", generation=1, report=_LOCAL_PUBLISH, pin_relation="increment",
            calls=("cli_refresh_report_v2",)),
        row(7, "refresh_generation", generation=2, report=_LOCAL_PUBLISH,
            pin_relation="increment", calls=("cli_refresh_report_v2",)),
        row(8, "pack_stale", packs=(_stale("pinned_first"),), calls=("cli_pack",)),
        row(9, "planned_refusal", generation=2, expectation="expected_refusal",
            refusal_codes=(LOCAL_BUDGET_CODE,), budget_multiplier=4, pin_relation="preserve",
            report=ReportSpec(2, "local_refresh", "sqlite", ("refused",), "incomplete"),
            calls=("cli_refresh_budget_4s",)),
        row(10, "missing_refusal", generation=2, expectation="expected_refusal",
            refusal_codes=(MISSING_ROOT_CODE,), pin_relation="preserve",
            report=ReportSpec(1, "local_refresh", "sqlite", ("not_recorded",), "incomplete"),
            calls=("inprocess_refresh",)),
        row(11, "refresh_recovery", generation=2, report=_LOCAL_PUBLISH,
            pin_relation="increment", calls=("cli_refresh_report_v2",)),
        row(12, "replay_refresh", generation=2, pin_relation="replay",
            report=ReportSpec(1, "local_refresh", "sqlite", ("reconciled_replay",), None),
            calls=("inprocess_refresh",)),
        row(13, "cleanup", harness_cleanup=True, calls=("verify_cleanup",)),
    )


def _query(sub: int, query: str, **extra: Any) -> RecipeStep:
    return RecipeStep(
        "server", 11, "lexical_query", "postgresql", SERVER_ALIASES, sub=sub,
        report=ReportSpec(1, "lexical_query", "postgresql", QUERY_RESULTS, "complete"),
        lexical=LexicalSpec(results=QUERY_RESULTS, query=query, query_aliases=("core",), **extra),
        calls=("lexical_query",),
    )


def _server() -> Recipe:
    def row(step: int, action: str, **extra: Any) -> RecipeStep:
        return RecipeStep("server", step, action, "postgresql", SERVER_ALIASES, **extra)

    return (
        row(1, "census_verify", generation=1, calls=("materialize_g1", "compare_census")),
        row(2, "migrate", calls=("apply_migrations",)),
        row(3, "sealing_plan", generation=1, plan=True, calls=("build_sealing_plan",)),
        row(4, "refresh_cold", generation=1, report=_SERVER_COMMIT, pin_relation="cold",
            calls=("refresh_graph_v2",)),
        row(5, "pack_current", packs=(_implementation("pinned_current"),),
            calls=("select_pinned", "pack")),
        row(6, "refresh_repeat", generation=1, report=_SERVER_COMMIT, pin_relation="increment",
            calls=("refresh_graph_v2",)),
        row(7, "refresh_generation", generation=2, report=_SERVER_COMMIT,
            pin_relation="increment", calls=("refresh_graph_v2",)),
        row(8, "stale_investigation", packs=(
            _stale("pinned_first"),
            PackSpec(
                tag="investigation", mode="graph_investigation", query=None, intent=None,
                selection="unpinned_current", statuses=PACK_STATUSES,
                canonical_key=INVESTIGATION_KEY, investigation=True,
            ),
        ), calls=("pack_stale", "select_unpinned", "pack_investigation")),
        row(9, "planned_refusal", generation=2, expectation="expected_refusal",
            refusal_codes=(SERVER_BUDGET_CODE,), budget_multiplier=4, pin_relation="preserve",
            report=ReportSpec(2, "server_refresh", "postgresql", ("refused",), "incomplete"),
            calls=("refresh_graph_budget_4s",)),
        row(10, "lexical_build",
            report=ReportSpec(1, "lexical_build", "postgresql", ("published",), "complete"),
            lexical=LexicalSpec(results=("published",)), calls=("lexical_build",)),
        _query(0, PIPELINE_SYMBOL, expected=(PIPELINE_LOCATION,)),
        _query(1, GEN2_MARKER, expected=(GEN2_LOCATION,)),
        _query(2, LEGACY_TOKEN, forbidden=(LEGACY_LOCATION,)),
        row(12, "lexical_revoke",
            report=ReportSpec(1, "lexical_revoke", "postgresql", ("revoked",), "complete"),
            lexical=LexicalSpec(
                results=("revoked",), query=PIPELINE_SYMBOL, query_aliases=("core",),
                unavailable_reason="projection_absent",
            ), calls=("lexical_revoke", "lexical_query_absent")),
        row(13, "cleanup", calls=("verify_cleanup",)),
    )


def _mixed() -> Recipe:
    both = ("sqlite", "postgresql")
    packs = (
        _implementation("pinned_current"),
        PackSpec(tag="docs", mode="ranked_discovery", query="architecture", intent="docs",
                 selection="pinned_current", statuses=PACK_STATUSES),
        PackSpec(tag="messages", mode="ranked_discovery", query="release", intent="messages",
                 selection="pinned_current", statuses=PACK_STATUSES),
    )
    return (
        RecipeStep("mixed", 1, "census_verify", "mixed", ALL_ALIASES, generation=1,
                   calls=("materialize_g1", "compare_census")),
        RecipeStep("mixed", 2, "sqlite_initial", "sqlite", ALL_ALIASES, generation=1,
                   report=_LOCAL_PUBLISH, pin_relation="cold",
                   calls=("cli_sqlite_init", "cli_refresh_report_v2")),
        RecipeStep("mixed", 3, "postgres_initial", "postgresql", ALL_ALIASES, generation=1,
                   report=_SERVER_COMMIT, pin_relation="cold",
                   calls=("apply_migrations", "refresh_graph_v2")),
        RecipeStep("mixed", 4, "snapshot_equivalence", "mixed", ALL_ALIASES, generation=1,
                   fact_backends=both, calls=("snapshot_equivalence_each_home",)),
        RecipeStep("mixed", 5, "pack_mixed", "mixed", ALL_ALIASES, fact_backends=both,
                   packs=packs, calls=("select_pinned_each_home", "pack_each_intent")),
        RecipeStep("mixed", 6, "pack_subset", "mixed", ("core",), fact_backends=both,
                   packs=(_implementation("pinned_subset"),),
                   calls=("select_core_each_home", "pack_each_home")),
        RecipeStep("mixed", 7, "privacy_refusal", "mixed", ("feeds",),
                   expectation="expected_refusal", refusal_codes=PRIVACY_CODES,
                   fact_backends=("postgresql",), pin_relation="preserve",
                   report=ReportSpec(1, "lexical_build", "postgresql", ("refused",), "complete"),
                   calls=("remove_feeds_mailbox_roots", "lexical_build_feeds")),
        RecipeStep("mixed", 8, "cleanup", "mixed", ALL_ALIASES, harness_cleanup=True,
                   calls=("verify_cleanup",)),
    )


RECIPE: Recipe = (*_local(), *_server(), *_mixed())


def scenario_steps(scenario: str, recipe: Recipe = RECIPE) -> Recipe:
    return tuple(step for step in recipe if step.scenario == scenario)


def find_step(scenario: str, step: int, sub: int, recipe: Recipe = RECIPE) -> RecipeStep | None:
    for item in recipe:
        if (item.scenario, item.step, item.sub) == (scenario, step, sub):
            return item
    return None


def recipe_digest(recipe: Recipe = RECIPE) -> str:
    """SHA-256 of the canonical recipe projection plus one LF."""
    payload = {"steps": [item.payload() for item in recipe]}
    return hashlib.sha256(canonical_bytes(payload, 1 << 20) + b"\n").hexdigest()


def catalog(recipe: Recipe = RECIPE) -> list[list[object]]:
    return [item.catalog_row() for item in recipe]


__all__ = [
    "ALL_ALIASES", "GEN2_LOCATION", "GEN2_MARKER", "INVESTIGATION_KEY", "LEGACY_LOCATION",
    "LEGACY_TOKEN", "LOCAL_BUDGET_CODE", "MAX_PACK_BYTES", "MISSING_ROOT_CODE",
    "PIPELINE_LOCATION", "PIPELINE_SYMBOL", "PRIVACY_CODES", "RECIPE", "SERVER_ALIASES",
    "SERVER_BUDGET_CODE", "STALE_REASON", "catalog", "find_step", "recipe_digest",
    "scenario_steps",
]
