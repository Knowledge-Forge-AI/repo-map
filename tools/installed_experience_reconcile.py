"""Pure reconciliation of one installed-experience bundle into a verdict (section 10.4).

``reconcile`` accepts only when the owner's scenarios appear exactly once in
recipe order, every expected fact is independently witnessed, closure rows hold,
every row has its declared outcome, cleanup is recorded and the index binds the
written bytes. A ``not-reached`` or ``unknown`` row is ``incomplete``; a skip is
never accepted. ``check_bundle`` additionally binds the current recipe and the
hosted candidate source identity.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from installed_experience_domains import (
    INDEX_NAME, INTENT_NAME, MAX_BUNDLE_BYTES, MAX_BUNDLE_FILES, OBSERVATION_NAME, VERDICT_NAME,
    InstalledError, outcome_for,
)
from installed_experience_records import (
    decode_index, decode_intent, decode_observation, decode_verdict, encode_verdict,
    verdict_payload,
)
from installed_experience_recipe import RECIPE, SOURCE, Scenario, owner_scenarios, recipe_digest
from installed_experience_validation import judge_row


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Verdict:
    owner: str | None
    attempt: str | None
    intent: str | None
    outcome: str
    categories: tuple[str, ...]
    counts: dict[str, int] = field(default_factory=dict)
    index_sha256: str | None = None
    rows: tuple[dict[str, Any], ...] = ()

    def encoded(self) -> bytes:
        return encode_verdict(verdict_payload(
            owner=self.owner, attempt=self.attempt, intent=self.intent, outcome=self.outcome,
            counts=self.counts, categories=self.categories, index_sha256=self.index_sha256,
        ))


def _refused(category: str) -> Verdict:
    return Verdict(None, None, None, "rejected", (category,))


def _catalog_categories(intent: Mapping[str, Any], recipe: tuple[Scenario, ...]) -> set[str]:
    """The intent's rows must be exactly the recipe's rows for that owner, in order."""
    rows = owner_scenarios(intent["owner"], recipe)
    declared = [(item["id"], item["action"], item["env_class"], item["family"], item["expectation"],
                 sorted(item["expected"])) for item in intent["scenarios"]]
    frozen = [(row.id, row.action, row.env_class, row.family, row.expectation,
               sorted(key for key, _value in row.expected)) for row in rows]
    if declared != frozen:
        return {"binding-mismatch"}
    for item, row in zip(intent["scenarios"], rows):
        for key, value in row.expected:
            if value is SOURCE:
                continue
            if item["expected"][key] != value:
                return {"binding-mismatch"}
    return set()


def _observations(files: Mapping[str, bytes]) -> tuple[list[dict[str, Any]], set[str]]:
    categories: set[str] = set()
    decoded: list[dict[str, Any]] = []
    names = sorted(name for name in files if OBSERVATION_NAME.fullmatch(name))
    for position, name in enumerate(names, start=1):
        try:
            observation = decode_observation(files[name])
        except InstalledError as error:
            categories.add("bound-exceeded" if error.category == "bound-exceeded" else "malformed")
            continue
        match = OBSERVATION_NAME.fullmatch(name)
        assert match is not None
        if observation["seq"] != int(match.group(1)) or observation["seq"] != position:
            categories.add("order-violation")
        decoded.append(observation)
    return decoded, categories


def _index_categories(files: Mapping[str, bytes], intent_sha: str, owner: str,
                      attempt: str | None) -> tuple[set[str], str | None]:
    data = files.get(INDEX_NAME)
    if data is None:
        return {"incomplete-step"}, None
    try:
        index = decode_index(data)
    except InstalledError:
        return {"malformed"}, sha256_hex(data)
    payload = {name: body for name, body in files.items() if name not in (INDEX_NAME, VERDICT_NAME)}
    rows = sorted([name, sha256_hex(body), len(body)] for name, body in payload.items())
    categories: set[str] = set()
    if index["members"] != rows or index["intent"] != intent_sha or index["owner"] != owner:
        categories.add("binding-mismatch")
    if attempt is not None and index["attempt"] != attempt:
        categories.add("binding-mismatch")
    return categories, sha256_hex(data)


def reconcile(files: Mapping[str, bytes], recipe: tuple[Scenario, ...] = RECIPE) -> Verdict:
    """Recompute the verdict of one bundle's written members; never raises on content."""
    if len(files) > MAX_BUNDLE_FILES or sum(len(body) for body in files.values()) > MAX_BUNDLE_BYTES:
        return _refused("bound-exceeded")
    unknown = set(files) - {INTENT_NAME, INDEX_NAME, VERDICT_NAME} - {
        name for name in files if OBSERVATION_NAME.fullmatch(name)}
    if unknown:
        return _refused("unsafe-member")
    raw_intent = files.get(INTENT_NAME)
    if raw_intent is None:
        return _refused("binding-mismatch")
    try:
        intent = decode_intent(raw_intent)
    except InstalledError as error:
        return _refused("bound-exceeded" if error.category == "bound-exceeded" else "malformed")
    owner, intent_sha = intent["owner"], sha256_hex(raw_intent)
    categories = _catalog_categories(intent, recipe)
    if intent["recipe_digest"] != recipe_digest(recipe):
        categories.add("binding-mismatch")
    observations, decode_categories = _observations(files)
    categories |= decode_categories
    attempt = observations[0]["attempt"] if observations else None
    rows = intent["scenarios"]
    seen = [item["scenario"] for item in observations]
    if len(seen) != len(set(seen)):
        categories.add("duplicate")
    if seen != [row["id"] for row in rows][:len(seen)]:
        categories.add("order-violation")
    if len(seen) < len(rows):
        categories.add("incomplete-step")
    if not seen or seen[-1:] != ["X01"]:
        categories.add("cleanup-missing")
    counts: dict[str, int] = {}
    judged: list[dict[str, Any]] = []
    by_id = {row["id"]: row for row in rows}
    for observation in observations:
        counts[observation["outcome"]] = counts.get(observation["outcome"], 0) + 1
        row = by_id.get(observation["scenario"])
        if row is None:
            categories.add("order-violation")
            continue
        row_categories = judge_row(row, observation, owner=owner, attempt=attempt or "",
                                   intent=intent_sha)
        categories |= row_categories
        judged.append({"scenario": observation["scenario"], "seq": observation["seq"],
                       "outcome": observation["outcome"], "env_class": observation["env_class"],
                       "family": observation["family"], "cleanup": observation["cleanup"],
                       "failure_code": observation["failure_code"],
                       "categories": sorted(row_categories)})
    index_categories, index_sha = _index_categories(files, intent_sha, owner, attempt)
    categories |= index_categories
    return Verdict(owner, attempt, intent_sha, outcome_for(categories), tuple(sorted(categories)),
                   counts, index_sha, tuple(judged))


def check_bundle(
    files: Mapping[str, bytes], *, candidate_source_sha256: str,
    recipe: tuple[Scenario, ...] = RECIPE,
) -> Verdict:
    """Host check: recompute, then bind the stored verdict and the hosted candidate."""
    verdict = reconcile(files, recipe)
    categories = set(verdict.categories)
    raw_intent = files.get(INTENT_NAME)
    if raw_intent is not None and verdict.intent is not None:
        if decode_intent(raw_intent)["candidate_census_sha256"] != candidate_source_sha256:
            categories.add("binding-mismatch")
    stored = files.get(VERDICT_NAME)
    if stored is None:
        categories.add("incomplete-step")
    else:
        try:
            decode_verdict(stored)
        except InstalledError:
            categories.add("malformed")
        else:
            if stored != verdict.encoded():
                categories.add("binding-mismatch")
    return Verdict(verdict.owner, verdict.attempt, verdict.intent, outcome_for(categories),
                   tuple(sorted(categories)), verdict.counts, verdict.index_sha256, verdict.rows)


__all__ = ["Verdict", "check_bundle", "reconcile", "sha256_hex"]
