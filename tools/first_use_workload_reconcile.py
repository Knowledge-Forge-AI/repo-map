"""Pure reconciliation of one bundle against the current intent (section 9).

``reconcile`` decodes every record, checks index digests against member bytes,
requires one attempt and one intent, matches scenario and backend to the
intent, requires the complete and strictly ordered ``(step, sub)`` catalog, then
applies the expectation/result rules and the section 8 fact rules. Expected
refusals, actual failures and skips stay separate. ``check_bundle`` additionally
compares a stored verdict with the recomputed one; a stored verdict never
supplies acceptance.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from first_use_workload_census import Census
from first_use_workload_domains import (
    INTENT_NAME, MAX_OBSERVATIONS, OBSERVATION_NAME, WorkloadError, outcome_for,
)
from first_use_workload_integrity import compare_index, referenced_members, sha256_hex
from first_use_workload_recipe import RECIPE, find_step, scenario_steps
from first_use_workload_recipe_shapes import Recipe
from first_use_workload_records import (
    IDENTITY_FIELDS, decode_index, decode_intent, decode_observation, encode_verdict,
    verdict_payload,
)
from first_use_workload_rules import row_categories
from first_use_workload_validation import fact_objects

IGNORED_INTENT_FIELDS = frozenset({"declared_source_parent"})


@dataclass
class Verdict:
    outcome: str
    categories: tuple[str, ...]
    counts: dict[str, int]
    scenario: str | None
    attempt: str | None
    intent: str | None
    index_sha256: str | None
    observations: list[dict[str, Any]] = field(default_factory=list, compare=False)

    def payload(self) -> dict[str, Any]:
        return verdict_payload(
            scenario=self.scenario, attempt=self.attempt, intent=self.intent, outcome=self.outcome,
            counts=self.counts, categories=self.categories, index_sha256=self.index_sha256,
        )

    def encoded(self) -> bytes:
        return encode_verdict(self.payload())


def _intent_categories(stored: bytes | None, current: bytes, index: Mapping[str, Any] | None) -> set[str]:
    if stored is None:
        return {"partial_bundle"}
    try:
        bundle = decode_intent(stored)
    except WorkloadError as error:
        return {error.category}
    now = decode_intent(current)
    categories: set[str] = set()
    for key in now:
        if key in IGNORED_INTENT_FIELDS or bundle[key] == now[key]:
            continue
        categories.add("candidate_mismatch" if key in IDENTITY_FIELDS else "intent_mismatch")
    if index is not None and index["intent"] != sha256_hex(stored):
        categories.add("intent_mismatch")
    return categories


def _decode_index(files: Mapping[str, bytes]) -> tuple[dict[str, Any] | None, set[str]]:
    data = files.get("index.json")
    if data is None:
        return None, {"partial_bundle"}
    try:
        index = decode_index(data)
    except WorkloadError as error:
        return None, {error.category}
    return index, compare_index(index["members"], files)


def _observations(files: Mapping[str, bytes], categories: set[str]) -> list[dict[str, Any]]:
    decoded: list[dict[str, Any]] = []
    for name in sorted(item for item in files if OBSERVATION_NAME.fullmatch(item)):
        match = OBSERVATION_NAME.fullmatch(name)
        assert match is not None
        try:
            observation = decode_observation(files[name])
        except WorkloadError as error:
            categories.add(error.category)
            continue
        if (observation["step"], observation["sub"]) != (int(match.group(1)), int(match.group(2))):
            categories.add("out_of_order")
            continue
        decoded.append(observation)
    if len(decoded) > MAX_OBSERVATIONS:
        categories.add("unbounded")
    keys = [(item["step"], item["sub"]) for item in decoded]
    if keys != sorted(set(keys)):
        categories.add("out_of_order")
    return decoded


def _result_categories(observation: Mapping[str, Any]) -> set[str]:
    result, expectation = observation["result"], observation["expectation"]
    if result == "failure":
        extra = {observation["reason"]} & {"stale_input", "unbounded"}
        return {"unexpected_failure", *extra}
    if result in ("skipped", "unavailable"):
        return {"missing_step"}
    if result != expectation:
        return {"unexpected_failure"}
    if (result == "pass") != (observation["refusal"] is None) or observation["reason"] is not None:
        return {"witness_mismatch"}
    if any(value is None for value in observation["spans"].values()):
        return {"witness_missing"}
    return set()


def _pin_continuity(observations: list[dict[str, Any]], recipe: Recipe) -> set[str]:
    """Require each backend's next pin witness to start at its prior after-state."""
    previous: dict[str, dict[str, Any] | None] = {}
    categories: set[str] = set()
    for observation in observations:
        step = find_step(observation["scenario"], observation["step"], observation["sub"], recipe)
        if step is None or step.pin_relation is None:
            continue
        facts = observation["facts"]
        keys = step.fact_backends or (step.backend,)
        if facts is None:
            for key in keys:
                previous[key] = None
            continue
        try:
            pairs = fact_objects(step, facts)
        except WorkloadError:
            for key in keys:
                previous[key] = None
            continue
        for backend, pair in pairs:
            key = step.backend if backend is None else backend
            before = pair.get("pin_before")
            after = pair.get("pin_after")
            if before is not None and previous.get(key) is not None and before != previous[key]:
                categories.add("witness_mismatch")
            previous[key] = after
    return categories


def reconcile(
    current_intent: bytes,
    files: Mapping[str, bytes],
    census: Census,
    recipe: Recipe = RECIPE,
) -> Verdict:
    """Recompute the verdict from payload bytes, the current intent and the census."""
    index, categories = _decode_index(files)
    categories |= _intent_categories(files.get(INTENT_NAME), current_intent, index)
    observations = _observations(files, categories)
    counts: Counter[str] = Counter(item["result"] for item in observations)
    scenario = None if index is None else index["scenario"]
    attempt = None if index is None else index["attempt"]
    intent_digest = None if index is None else index["intent"]
    seen: set[tuple[int, int]] = set()
    for observation in observations:
        if attempt is not None and observation["attempt"] != attempt:
            categories.add("cross_attempt")
        if intent_digest is not None and observation["intent"] != intent_digest:
            categories.add("intent_mismatch")
        if scenario is None:
            continue
        if observation["scenario"] != scenario:
            categories.add("intent_mismatch")
            continue
        step = find_step(scenario, observation["step"], observation["sub"], recipe)
        if step is None:
            categories.add("intent_mismatch")
            continue
        seen.add(step.key)
        if observation["backend"] != step.backend:
            categories.add("cross_backend")
            continue
        if (observation["action"], observation["expectation"]) != (step.action, step.expectation):
            categories.add("intent_mismatch")
            continue
        row = _result_categories(observation)
        categories |= row
        if not row and observation["result"] in ("pass", "expected_refusal"):
            categories |= row_categories(step, observation, files, census)
    if scenario is not None:
        if any(step.key not in seen for step in scenario_steps(scenario, recipe)):
            categories.add("missing_step")
    else:
        categories.add("partial_bundle")
    categories |= _pin_continuity(observations, recipe)
    referenced = referenced_members(observations)
    evidence = {name for name in files if "/" in name}
    if evidence - set(referenced):
        categories.add("tampered_member")
    index_bytes = files.get("index.json")
    return Verdict(
        outcome=outcome_for(categories),
        categories=tuple(sorted(categories)),
        counts=dict(counts),
        scenario=scenario,
        attempt=attempt,
        intent=intent_digest,
        index_sha256=None if index_bytes is None else sha256_hex(index_bytes),
        observations=observations,
    )


def check_bundle(
    current_intent: bytes,
    files: Mapping[str, bytes],
    census: Census,
    recipe: Recipe = RECIPE,
) -> Verdict:
    """Recompute and compare with the stored verdict; categories stay collected."""
    verdict = reconcile(current_intent, files, census, recipe)
    stored = files.get("verdict.json")
    extra: set[str] = set()
    if stored is None:
        extra.add("partial_bundle")
    elif stored != verdict.encoded():
        extra.add("tampered_member")
    if not extra:
        return verdict
    categories = set(verdict.categories) | extra
    verdict.categories = tuple(sorted(categories))
    verdict.outcome = outcome_for(categories)
    return verdict


__all__ = ["Verdict", "check_bundle", "reconcile"]
