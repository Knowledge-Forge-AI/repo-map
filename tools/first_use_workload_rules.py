"""Per-action fact rules and witness arithmetic for one recorded row (section 8).

``row_categories`` is pure: it receives one decoded observation, its recipe row,
the referenced member bytes and the frozen census, and returns closed
categories. Pin relations are the predeclared ones of section 4; no expected
generation is taken from a returned result.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from first_use_workload_census import Census
from first_use_workload_domains import WorkloadError, plan_name, report_name
from first_use_workload_integrity import sha256_hex
from first_use_workload_pins import advanced_by_one, preserved
from first_use_workload_readback_rules import (
    census_rules, cleanup_rules, init_rules, lexical_report_rules, lexical_rules, pack_rules,
    projection_digest, snapshot_rules,
)
from first_use_workload_recipe_shapes import RecipeStep
from first_use_workload_report_rules import (
    decode_plan_member, decode_report_member, plan_rules, planned_refusal_formula,
    publish_formula, report_identity,
)
from first_use_workload_validation import check_location_bound, fact_class, fact_objects

ORDINARY_RELATIONS = frozenset({"cold", "increment"})


def expected_members(step: RecipeStep) -> set[str]:
    names: set[str] = set()
    if step.report is not None:
        names.add(report_name(step.step, step.sub))
    if step.plan:
        names.add(plan_name(step.step, step.sub))
    return names


def _member_categories(step: RecipeStep, observation: Mapping[str, Any],
                       files: Mapping[str, bytes]) -> set[str]:
    categories: set[str] = set()
    rows = {str(row[0]): row for row in observation["members"]}
    expected = expected_members(step)
    if expected - set(rows):
        categories.add("witness_missing")
    if set(rows) - expected:
        categories.add("tampered_member")
    for name, (_name, digest, size) in rows.items():
        data = files.get(name)
        if data is None:
            categories.add("partial_bundle")
        elif (sha256_hex(data), len(data)) != (digest, size):
            categories.add("tampered_member")
    return categories


def _report(step: RecipeStep, files: Mapping[str, bytes]) -> tuple[dict[str, Any], bytes] | None:
    data = files.get(report_name(step.step, step.sub))
    if step.report is None or data is None:
        return None
    return decode_report_member(data), data


def _pin_rules(step: RecipeStep, facts: Mapping[str, Any]) -> set[str]:
    before, after = facts["pin_before"], facts["pin_after"]
    relation = step.pin_relation
    if relation == "cold":
        ok = before is None and facts["preparation_pin"] is None and advanced_by_one(None, after)
        return set() if ok else {"witness_mismatch"}
    if before is None or after is None:
        return {"witness_missing"}
    if relation == "increment":
        ok = facts["preparation_pin"] is None and advanced_by_one(before, after)
        return set() if ok else {"witness_mismatch"}
    preparation = facts["preparation_pin"]
    if preparation is None:
        return {"witness_missing"}
    categories = set() if advanced_by_one(before, preparation) else {"witness_mismatch"}
    if not preserved(preparation, after):
        categories.add("pin_not_preserved")
    return categories


def _refresh(step: RecipeStep, facts: Mapping[str, Any], files: Mapping[str, bytes],
             census: Census) -> set[str]:
    if facts["outcome"] is None or facts["manifest_bytes"] is None or facts["inventory_sha256"] is None:
        return {"witness_missing"}
    generation = step.generation or 0
    categories = _pin_rules(step, facts)
    if step.report is not None and facts["outcome"] not in step.report.outcomes:
        categories.add("witness_mismatch")
    if facts["inventory_sha256"] != projection_digest(census, generation, step.aliases):
        categories.add("witness_mismatch")
    if step.report is None:
        return categories
    report = _report(step, files)
    if report is None:
        return categories | {"witness_missing"}
    payload, data = report
    assert step.report is not None
    categories |= report_identity(step.report, payload, data)
    if payload.get("outcome") != facts["outcome"]:
        categories.add("report_mismatch")
    if step.pin_relation in ORDINARY_RELATIONS:
        fresh = facts["attempt_root_fresh"]
        if fresh is None:
            categories.add("witness_missing")
        elif fresh is not True:
            categories.add("witness_mismatch")
        elif step.report.schema == 2:
            projection = census.generation(generation).projection(step.aliases)
            categories |= publish_formula(
                payload, S=projection.S, C=projection.C, m=facts["manifest_bytes"],
            )
    return categories


def _refusal(step: RecipeStep, facts: Mapping[str, Any], files: Mapping[str, bytes],
             census: Census, refusal: object) -> set[str]:
    if facts["code"] is None:
        return {"witness_missing"}
    categories: set[str] = set()
    if facts["code"] not in step.refusal_codes or facts["code"] != refusal:
        categories.add("witness_mismatch")
    if facts["pin_before"] is None or facts["pin_after"] is None:
        categories.add("witness_missing")
    elif not preserved(facts["pin_before"], facts["pin_after"]):
        categories.add("pin_not_preserved")
    if step.report is None:
        return categories
    report = _report(step, files)
    if report is None:
        return categories | {"witness_missing"}
    payload, data = report
    assert step.report is not None
    categories |= report_identity(step.report, payload, data)
    if step.budget_multiplier is not None:
        projection = census.generation(step.generation or 0).projection(step.aliases)
        categories |= planned_refusal_formula(payload, S=projection.S, multiplier=step.budget_multiplier)
    return categories


def _plan(step: RecipeStep, facts: Mapping[str, Any], files: Mapping[str, bytes],
          census: Census) -> set[str]:
    data = files.get(plan_name(step.step, step.sub))
    if data is None:
        return {"witness_missing"}
    plan = decode_plan_member(data)
    projection = census.generation(step.generation or 0).projection(step.aliases)
    return plan_rules(plan, facts, S=projection.S)


def _lexical(step: RecipeStep, facts: Mapping[str, Any], files: Mapping[str, bytes],
             census: Census) -> set[str]:
    categories = lexical_rules(step, facts, census)
    if step.report is None:
        return categories
    report = _report(step, files)
    if report is None:
        return categories | {"witness_missing"}
    payload, data = report
    assert step.report is not None
    return categories | report_identity(step.report, payload, data) | lexical_report_rules(
        step, facts, payload,
    )


def _one(step: RecipeStep, backend: str | None, facts: Mapping[str, Any],
         files: Mapping[str, bytes], census: Census, refusal: object) -> set[str]:
    kind = fact_class(step.action)
    if kind == "census":
        return census_rules(step, facts, census)
    if kind == "init":
        return init_rules(step, facts)
    if kind == "plan":
        return _plan(step, facts, files, census)
    if kind == "refresh":
        return _refresh(step, facts, files, census)
    if kind == "refusal":
        return _refusal(step, facts, files, census, refusal)
    if kind == "pack":
        return pack_rules(step, facts, census)
    if kind == "lexical":
        return _lexical(step, facts, files, census)
    if kind == "snapshot":
        return snapshot_rules(step, backend, facts, census)
    return cleanup_rules(step, facts)


def row_categories(step: RecipeStep, observation: Mapping[str, Any],
                   files: Mapping[str, bytes], census: Census) -> set[str]:
    """Categories for one ``pass`` or ``expected_refusal`` row."""
    categories = _member_categories(step, observation, files)
    if observation["facts"] is None:
        return categories | {"witness_missing"}
    try:
        pairs = fact_objects(step, observation["facts"])
        check_location_bound(pairs)
        for backend, facts in pairs:
            categories |= _one(step, backend, facts, files, census, observation["refusal"])
    except WorkloadError as error:
        categories.add(error.category)
    return categories


__all__ = ["expected_members", "row_categories"]
