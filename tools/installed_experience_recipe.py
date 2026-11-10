"""Frozen installed-experience scenario catalog and recipe digest (contract section 9).

Each row names its owner, environment class, launch family, expectation and the
closed expected facts. A fact is either a recipe constant or ``SOURCE``: a value
the test process computes from current source before any scenario child runs
and records in the owner's intent. Nothing here is learned from a run.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from installed_experience_domains import (
    ACTION, ENV_CLASSES, EXPECTATIONS, FACT_KEY, FAMILIES, MAX_FACTS, MAX_OWNER_OBSERVATIONS,
    MAX_RECIPE_OBSERVATIONS, OWNERS, SCENARIO_ID, InstalledError,
)
from installed_experience_encoding import encode, is_scalar
from installed_experience_pins import (
    CODE_KIND, CODE_PATH, DOCS_PATH, GRAPH_ID, PSYCOPG_IMPL, PSYCOPG_VERSION, TE_MODULE_SHA256,
    TE_RECORD_SHA256,
)


class _Source:
    """Marker for an expected value computed from current source before execution."""

    def __repr__(self) -> str:
        return "SOURCE"


SOURCE: Any = _Source()


@dataclass(frozen=True)
class Scenario:
    id: str
    owner: str
    env_class: str
    family: str
    action: str
    expectation: str
    expected: tuple[tuple[str, Any], ...]

    def source_keys(self) -> tuple[str, ...]:
        return tuple(key for key, value in self.expected if value is SOURCE)

    def catalog_row(self) -> list[Any]:
        facts = [[key, "source" if value is SOURCE else value] for key, value in self.expected]
        return [self.id, self.owner, self.env_class, self.family, self.action, self.expectation, facts]


def _row(sid: str, owner: str, env: str, family: str, action: str, expectation: str,
         **facts: Any) -> Scenario:
    return Scenario(sid, owner, env, family, action, expectation, tuple(facts.items()))


P, I, N, S = "pure-local", "incumbent-local", "none", "provisioned-server"
PIP, PROBE = "arch7f_pip", "arch7f_probe"

RECIPE: tuple[Scenario, ...] = (
    _row("A01", "environment", N, PIP, "candidate-assembly", "pass", inventory_sha256=SOURCE,
         entry_points_sha256=SOURCE, requires_dist=SOURCE, record_hashes_valid=True,
         license_members=SOURCE, pth_members=0),
    _row("A02", "environment", P, PIP, "install-project-check", "pass", install_exit=0,
         projection_module_sha256=TE_MODULE_SHA256, projection_record_sha256=TE_RECORD_SHA256,
         pip_check_exit=0, include_system_site_packages=False),
    _row("A03", "environment", P, PROBE, "origin-closure", "pass", closure_holds=True,
         product_origin="env-purelib", facade_origin="env-purelib",
         dependency_origin="env-purelib", resource_root="env-data", absent_families=True,
         distributions=SOURCE, graph_migrations=SOURCE, control_migrations=SOURCE,
         base_has_product=False),
    _row("A04", "environment", P, PROBE, "installation-check", "pass",
         ownership_state="single-owner", exit=0),
    _row("A05", "environment", "shared-site", PROBE, "class-refusal", "refusal",
         observed_class="provisioned", refusal="environment-class-mismatch"),
    _row("A06", "environment", P, PROBE, "checkout-injection", "refusal",
         checkout_entries=True, refusal="origin-checkout"),
    _row("A07", "environment", N, "none", "projection-refusals", "refusal",
         hash_refusal="projection-hash-mismatch", symlink_refusal="projection-entry-unsafe",
         unknown_refusal="projection-unknown-entry", target_unchanged=True),
    _row("X01", "environment", N, "none", "owner-cleanup", "pass", cleanup="removed"),
    _row("L00", "local", P, PROBE, "origin-witness", "pass", closure_holds=True,
         product_origin="env-purelib", facade_origin="env-purelib",
         dependency_origin="env-purelib", resource_root="env-data", absent_families=True,
         distributions=SOURCE, graph_migrations=SOURCE, control_migrations=SOURCE,
         base_has_product=False, pyvenv_system_site=False,
         wrappers_hold=True),
    _row("L01", "local", P, PROBE, "wrapper-versions", "pass", cloe_stdout=SOURCE,
         long_stdout=SOURCE, legacy_stdout=SOURCE, cloe_stderr="empty", long_stderr="empty",
         legacy_stderr="legacy-command-notice"),
    _row("L02", "local", P, PROBE, "config-and-graphs", "pass", valid=True, graph_ids=GRAPH_ID,
         storage_backend="sqlite", public_paths_owned=True),
    _row("L03", "local", P, PROBE, "sqlite-init", "pass", init_exit=0, db_state="current",
         published=False),
    _row("L04", "local", P, PROBE, "guarded-refresh", "pass", preflight_exit=0,
         accepted_generation=1, forbidden_events=0, blocker_probe="import-blocked",
         probe_checkout_root_absent=True, probe_python_path_absent=True),
    _row("L05", "local", P, PROBE, "useful-question", "pass", code_kind=CODE_KIND,
         code_path=CODE_PATH, code_line=SOURCE, docs_path=DOCS_PATH, message_metadata_present=True),
    _row("L06", "local", P, PROBE, "context-select-pack", "pass", pin_generation=1,
         pack_within_bound=True, pack_has_code_location=True),
    _row("L07", "local", P, PROBE, "sqlite-backup", "pass", backup_result="created",
         backup_files=2, manifest_graph=GRAPH_ID, manifest_generation=1),
    _row("L08", "local", P, PROBE, "source-blind-readback", "pass", digests_equal=True,
         material_absent=True),
    _row("L09", "local", P, PROBE, "restore-readback", "pass", restore_result="restored",
         schema_state="current", generation=1, digests_equal=True, material_absent=True),
    _row("L10", "local", P, PROBE, "restore-existing", "refusal", exit=1,
         refusal="sqlite-restore-target-exists", database_unchanged=True),
    _row("L11", "local", P, PROBE, "postgres-home-driverless", "refusal", exit=1,
         refusal="postgresql-driver-unavailable", psycopg_absent=True),
    _row("X01", "local", N, "none", "owner-cleanup", "pass", cleanup="removed"),
    _row("M00", "mcp", P, PROBE, "origin-witness", "pass", closure_holds=True,
         product_origin="env-purelib", facade_origin="env-purelib",
         dependency_origin="env-purelib", resource_root="env-data", absent_families=True,
         distributions=SOURCE, graph_migrations=SOURCE, control_migrations=SOURCE,
         base_has_product=False, pyvenv_system_site=False,
         wrappers_hold=True),
    _row("M01", "mcp", P, PROBE, "canonical-serve", "pass", protocol_version=SOURCE,
         tools_sha256=SOURCE, stderr_class="empty", useful_member_found=True),
    _row("M02", "mcp", P, PROBE, "canonical-module", "pass", tools_sha256=SOURCE,
         digests_equal=True, stderr_class="empty"),
    _row("M03", "mcp", P, PROBE, "legacy-module", "pass", stderr_line=SOURCE,
         digests_equal=True),
    _row("M04", "mcp", P, PROBE, "legacy-command", "pass", stderr_line=SOURCE,
         digests_equal=True),
    _row("M05", "mcp", P, PROBE, "legacy-module-version", "pass", stdout=SOURCE,
         stderr_line=SOURCE),
    _row("M06", "mcp", P, PROBE, "adverse-requests", "pass", unknown_tool_error=True,
         invalid_limit_error=True, malformed_code="-32700", malformed_id_null=True,
         valid_call_ok=True),
    _row("M07", "mcp", P, PROBE, "read-only-witness", "pass", database_unchanged=True,
         attempts_unchanged=True),
    _row("X01", "mcp", N, "none", "owner-cleanup", "pass", cleanup="removed"),
    _row("R00", "migration", P, PROBE, "origin-witness", "pass", closure_holds=True,
         product_origin="env-purelib", facade_origin="env-purelib",
         dependency_origin="env-purelib", resource_root="env-data", absent_families=True,
         distributions=SOURCE, graph_migrations=SOURCE, control_migrations=SOURCE,
         base_has_product=False, pyvenv_system_site=False,
         wrappers_hold=True),
    _row("R01", "migration", P, PROBE, "legacy-home-publish", "pass", accepted_generation=1),
    _row("R02", "migration", I, PROBE, "incumbent-check", "pass", incumbent_stdout=SOURCE,
         valid=True, dependency_pin=SOURCE, incumbent_closure_holds=True),
    _row("R03", "migration", P, PROBE, "apply-dry-run", "pass", result="would-apply",
         writes=0, home_unchanged=True),
    _row("R04", "migration", P, PROBE, "apply-confirmed", "pass", result="applied",
         rollback_available=True, valid=True, identity_unchanged=True, mcp_unchanged=True),
    _row("R05", "migration", P, PROBE, "legacy-rollback", "pass", result="rolled-back",
         names_bytes_restored=True, incumbent_valid=True, identity_unchanged=True),
    _row("R06", "migration", P, PROBE, "apply-finalize-rollback", "pass", apply="applied",
         finalize="finalized", operation_retained=False, rollback="nothing-to-recover",
         rollback_writes=0),
    _row("R07", "migration", P, PROBE, "migration-refusals", "refusal",
         none_refusal="repo-map-home-required", unconfirmed_refusal="confirmation-required",
         symlink_refusal="config-entry-unsafe", writes=0, home_unchanged=True),
    _row("R08", "migration", P, PROBE, "env-selector", "pass", selector_equal=True),
    _row("X01", "migration", N, "none", "owner-cleanup", "pass", cleanup="removed"),
    _row("S01", "server", S, PROBE, "provisioned-origin", "pass", closure_holds=True,
         product_origin="env-purelib", facade_origin="env-purelib", dependency_origin="system-site",
         resource_root="env-data", psycopg_origin="system-site", psycopg_version=PSYCOPG_VERSION,
         psycopg_impl=PSYCOPG_IMPL, label="provisioned-server"),
    _row("S02", "server", S, PROBE, "catalog-discovery", "pass", graph_catalog_sha256=SOURCE,
         control_catalog_sha256=SOURCE),
    _row("S03", "server", S, PROBE, "server-refresh", "pass", refresh_result="success",
         publication_state="committed", function_present=True, accepted_generation=1),
    _row("S04", "server", S, PROBE, "server-mcp", "pass", tools_sha256=SOURCE,
         useful_member_found=True),
    _row("X01", "server", N, "none", "owner-cleanup", "pass", cleanup="removed"),
)


def owner_scenarios(owner: str, recipe: tuple[Scenario, ...] = RECIPE) -> tuple[Scenario, ...]:
    if owner not in OWNERS:
        raise InstalledError("malformed")
    return tuple(item for item in recipe if item.owner == owner)


def validate_recipe(recipe: tuple[Scenario, ...] = RECIPE) -> None:
    """Static shape of the frozen catalog; a violation is a source defect."""
    if len(recipe) > MAX_RECIPE_OBSERVATIONS:
        raise InstalledError("bound-exceeded")
    for owner in OWNERS:
        rows = owner_scenarios(owner, recipe)
        ids = [row.id for row in rows]
        if not rows or len(ids) != len(set(ids)) or len(rows) > MAX_OWNER_OBSERVATIONS:
            raise InstalledError("malformed")
        if rows[-1].id != "X01":
            raise InstalledError("cleanup-missing")
    for row in recipe:
        if SCENARIO_ID.fullmatch(row.id) is None or ACTION.fullmatch(row.action) is None:
            raise InstalledError("malformed")
        if row.env_class not in ENV_CLASSES or row.family not in FAMILIES:
            raise InstalledError("malformed")
        if row.expectation not in EXPECTATIONS or not 0 < len(row.expected) <= MAX_FACTS:
            raise InstalledError("malformed")
        keys = [key for key, _value in row.expected]
        if len(keys) != len(set(keys)) or any(FACT_KEY.fullmatch(key) is None for key in keys):
            raise InstalledError("malformed")
        if any(value is not SOURCE and not is_scalar(value) for _key, value in row.expected):
            raise InstalledError("malformed")


def catalog(recipe: tuple[Scenario, ...] = RECIPE) -> list[list[Any]]:
    return [row.catalog_row() for row in recipe]


def recipe_digest(recipe: tuple[Scenario, ...] = RECIPE) -> str:
    validate_recipe(recipe)
    data = encode({"catalog": catalog(recipe)}, 64 * 1024)
    return hashlib.sha256(data).hexdigest()


def resolve_expected(
    scenario: Scenario, source_values: Mapping[str, Any],
) -> dict[str, Any]:
    """Expected facts of one row; every ``SOURCE`` key needs a source-computed value."""
    resolved: dict[str, Any] = {}
    for key, value in scenario.expected:
        if value is SOURCE:
            if key not in source_values or not is_scalar(source_values[key]):
                raise InstalledError("witness-missing")
            resolved[key] = source_values[key]
        else:
            resolved[key] = value
    return resolved


__all__ = [
    "RECIPE", "SOURCE", "Scenario", "catalog", "owner_scenarios", "recipe_digest",
    "resolve_expected", "validate_recipe",
]
