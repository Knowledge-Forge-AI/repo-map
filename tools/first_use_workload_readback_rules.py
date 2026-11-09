"""Readback rules: census projection, initialization, packs, lexical, snapshot, cleanup.

Presence of manual expected locations, absence of forbidden ones and alias
scope are computed here from observed public refs and recipe constants; no
producer boolean is trusted for those predicates. Canary absence,
initialization and cleanup are explicit driver witnesses: a value here proves
only that the witness was recorded and agrees with the recipe.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from first_use_workload_census import Census, inventory_digest, selected_rows
from first_use_workload_domains import UNRESOLVED_ALIAS
from first_use_workload_recipe import MAX_PACK_BYTES
from first_use_workload_recipe_shapes import Location, RecipeStep
from first_use_workload_report_rules import metric_value


def _witness(value: object, expected: object) -> set[str]:
    if value is None:
        return {"witness_missing"}
    return set() if value == expected else {"witness_mismatch"}


def projection_digest(census: Census, generation: int, aliases: Iterable[str]) -> str:
    return inventory_digest(selected_rows(census.generation(generation).entries, tuple(aliases)))


def census_rules(step: RecipeStep, facts: Mapping[str, Any], census: Census) -> set[str]:
    """Exact equality with the committed census projection, else ``stale_input``."""
    generation = step.generation or 0
    if any(facts[key] is None for key in ("C", "S", "files", "generation", "inventory_sha256")):
        return {"witness_missing"}
    projection = census.generation(generation).projection(step.aliases)
    found = (
        facts["generation"] == generation
        and (facts["S"], facts["C"], facts["files"]) == (projection.S, projection.C, projection.files)
        and facts["inventory_sha256"] == projection_digest(census, generation, step.aliases)
    )
    return set() if found else {"stale_input"}


def init_rules(step: RecipeStep, facts: Mapping[str, Any]) -> set[str]:
    categories = _witness(facts["initialized"], True)
    if facts["backend"] != step.backend:
        categories.add("cross_backend")
    return categories


def _scope_ok(refs: Iterable[Location], aliases: Iterable[str]) -> bool:
    allowed = set(aliases)
    return all(alias != UNRESOLVED_ALIAS and alias in allowed for alias, _rel in refs)


def _census_locations(census: Census, generation: int | None,
                     aliases: Iterable[str]) -> set[Location]:
    allowed = set(aliases)
    generations = (generation,) if generation is not None else (1, 2)
    return {
        (alias, rel)
        for number in generations
        for alias, rel, _digest, _size, selected in census.generation(number).entries
        if selected and alias in allowed
    }


def _locations(refs: set[Location], expected: Iterable[Location], forbidden: Iterable[Location],
               aliases: Iterable[str], census: Census, generation: int | None) -> set[str]:
    ok = (
        set(expected) <= refs
        and not (set(forbidden) & refs)
        and _scope_ok(refs, aliases)
        and refs <= _census_locations(census, generation, aliases)
    )
    return set() if ok else {"witness_mismatch"}


def pack_rules(step: RecipeStep, facts: Mapping[str, Any], census: Census) -> set[str]:
    categories: set[str] = set()
    status = {item[0]: item[1] for item in facts["status"]}
    reason = {item[0]: item[1] for item in facts["reason"]}
    encoded = {item[0]: item[1] for item in facts["encoded_bytes"]}
    categories |= _witness(facts["canary_free"], True)
    categories |= _witness(facts["max_bytes"], MAX_PACK_BYTES)
    investigating = any(spec.investigation for spec in step.packs)
    if investigating:
        categories |= _witness(facts["investigation_supported"], True)
    elif facts["investigation_supported"] is not None:
        categories.add("witness_mismatch")
    for spec in step.packs:
        if spec.tag not in status or spec.tag not in encoded or spec.tag not in reason:
            categories.add("witness_missing")
            continue
        if status[spec.tag] not in spec.statuses:
            categories.add("witness_mismatch")
        if spec.reason is not None and reason[spec.tag] != spec.reason:
            categories.add("witness_mismatch")
        size = encoded[spec.tag]
        if facts["max_bytes"] is not None and size > facts["max_bytes"]:
            categories.add("witness_mismatch")
        refs = {(alias, rel) for tag, alias, rel in facts["observed_locations"] if tag == spec.tag}
        categories |= _locations(
            refs, spec.expected, spec.forbidden, step.aliases, census, step.generation,
        )
    return categories


def lexical_rules(step: RecipeStep, facts: Mapping[str, Any], census: Census) -> set[str]:
    spec = step.lexical
    if spec is None:
        return {"witness_mismatch"}
    if facts["result"] is None:
        return {"witness_missing"}
    categories: set[str] = set()
    if facts["result"] not in spec.results:
        categories.add("witness_mismatch")
    refs = {(alias, rel) for alias, rel in facts["observed_locations"]}
    if step.action == "lexical_build":
        idle = (facts["hits"], facts["revoked_generations"], facts["unavailable_reason"])
        if idle != (None, None, None) or refs:
            categories.add("witness_mismatch")
    elif step.action == "lexical_query":
        hits = facts["hits"]
        if hits is None:
            return categories | {"witness_missing"}
        if (hits == 0) != (not refs) or facts["unavailable_reason"] is not None:
            categories.add("witness_mismatch")
        if facts["revoked_generations"] is not None:
            categories.add("witness_mismatch")
        categories |= _locations(
            refs, spec.expected, spec.forbidden, spec.query_aliases, census, step.generation,
        )
    else:
        revoked = facts["revoked_generations"]
        if revoked is None or facts["unavailable_reason"] is None:
            return categories | {"witness_missing"}
        if revoked < 1 or facts["unavailable_reason"] != spec.unavailable_reason or refs:
            categories.add("witness_mismatch")
    return categories


def lexical_report_rules(step: RecipeStep, facts: Mapping[str, Any], payload: Mapping[str, Any]) -> set[str]:
    """The decoded report counts the same returned envelope the facts project."""
    if step.action == "lexical_query":
        ok = metric_value(payload, "query_hits_returned") == facts["hits"]
        ok = ok and payload.get("outcome") == facts["result"]
    elif step.action == "lexical_revoke":
        ok = metric_value(payload, "revoked_generations") == facts["revoked_generations"]
    else:
        ok = payload.get("outcome") == facts["result"]
    return set() if ok else {"report_mismatch"}


def snapshot_rules(step: RecipeStep, backend: str | None, facts: Mapping[str, Any],
                   census: Census) -> set[str]:
    if any(facts[key] is None for key in (
        "incumbent_snapshot_sha256", "inventory_sha256", "manifest_snapshot_sha256",
    )):
        return {"witness_missing"}
    categories: set[str] = set()
    if facts["backend"] != backend:
        categories.add("cross_backend")
    if facts["inventory_sha256"] != projection_digest(census, step.generation or 0, step.aliases):
        categories.add("witness_mismatch")
    if facts["manifest_snapshot_sha256"] != facts["incumbent_snapshot_sha256"]:
        categories.add("witness_mismatch")
    return categories


def cleanup_rules(step: RecipeStep, facts: Mapping[str, Any]) -> set[str]:
    categories: set[str] = set()
    if facts["leftovers"]:
        categories.add("witness_mismatch")
    for key in ("forbidden_events", "shim_invocations"):
        if step.harness_cleanup:
            categories |= _witness(facts[key], 0)
        elif facts[key] is not None:
            categories.add("witness_mismatch")
    return categories


__all__ = [
    "census_rules", "cleanup_rules", "init_rules", "lexical_report_rules", "lexical_rules",
    "pack_rules", "projection_digest", "snapshot_rules",
]
