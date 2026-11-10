"""Row-level judgment of one decoded observation against its intent row (section 10.4).

Pure functions over decoded records. An expected fact is matched only by an
observed fact with the same value and a non-intent source; a value copied from
the intent (source ``intent``) is ``witness-missing``. Closure counts of
origin-witness rows are rejudged with the shared section-6 rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from installed_experience_domains import OBSERVED_SOURCES
from installed_experience_rules import path_violations

CLOSURE_SCENARIOS = frozenset({"A03", "L00", "M00", "R00", "S01"})


def fact_categories(expected: Mapping[str, Any], facts: Mapping[str, Any]) -> set[str]:
    categories: set[str] = set()
    for key, value in expected.items():
        fact = facts.get(key)
        if fact is None:
            categories.add("witness-missing")
            continue
        if fact["source"] not in OBSERVED_SOURCES:
            categories.add("witness-missing")
            continue
        observed = fact["value"]
        if type(observed) is not type(value) or observed != value:
            categories.add("fact-mismatch")
    if set(facts) - set(expected):
        categories.add("malformed")
    return categories


def outcome_categories(expectation: str, outcome: str) -> set[str]:
    if outcome in ("not-reached", "unknown"):
        return {"incomplete-step"}
    if expectation == "pass" and outcome == "passed":
        return set()
    if expectation == "refusal" and outcome == "expected-refusal":
        return set()
    return {"unexpected-outcome"}


def closure_categories(row: Mapping[str, Any], observation: Mapping[str, Any]) -> set[str]:
    """Origin rows carry isolated counts; the witness already checked both probes."""
    if row["id"] not in CLOSURE_SCENARIOS or observation["outcome"] != "passed":
        return set()
    counts = observation["origin_classes"]
    if counts is None:
        return {"witness-missing"}
    if row["env_class"] != observation["env_class"]:
        return {"class-mismatch"}
    if path_violations(row["env_class"], counts, isolated=True):
        return {"class-mismatch"}
    return set()


def exit_holds(row: Mapping[str, Any], exit_code: int | None) -> bool:
    """Frozen command exits: context-pack alone permits bounded-partial code 3."""
    accepted = (None, 0, 1) if row["expectation"] == "refusal" else (None, 0)
    if row["id"] == "L06" and row["expectation"] == "pass":
        accepted = (None, 0, 3)
    return exit_code in accepted


def cleanup_categories(row: Mapping[str, Any], observation: Mapping[str, Any]) -> set[str]:
    if row["id"] != "X01":
        return set()
    if observation["cleanup"] == "not-applicable":
        return {"cleanup-missing"}
    if observation["cleanup"] == "retained-reported":
        return {"unexpected-outcome"}
    return set()


def judge_row(
    row: Mapping[str, Any], observation: Mapping[str, Any], *, owner: str, attempt: str, intent: str,
) -> set[str]:
    """Every category that one observation contributes; empty means the row holds."""
    categories: set[str] = set()
    if (observation["owner"], observation["attempt"], observation["intent"]) != (owner, attempt, intent):
        categories.add("binding-mismatch")
    if observation["env_class"] != row["env_class"] or observation["family"] != row["family"]:
        categories.add("class-mismatch")
    categories |= outcome_categories(row["expectation"], observation["outcome"])
    if observation["outcome"] in ("passed", "expected-refusal"):
        if not exit_holds(row, observation["exit"]):
            categories.add("unexpected-outcome")
        categories |= fact_categories(row["expected"], observation["facts"])
        categories |= closure_categories(row, observation)
    categories |= cleanup_categories(row, observation)
    return categories


__all__ = [
    "CLOSURE_SCENARIOS", "cleanup_categories", "closure_categories", "fact_categories",
    "exit_holds", "judge_row", "outcome_categories",
]
