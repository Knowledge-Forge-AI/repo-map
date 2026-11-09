"""Pure synthetic first-use evidence for unit owners (no product runtime, no I/O but census).

``SAMPLE_RECIPE`` is a five-row Local recipe whose rows need no report member,
so a complete, accepted bundle can be built from constants and the committed
census alone. Report and plan rules are exercised separately on payload dicts.
These samples are fixtures for the pure tools; they are never workload evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from first_use_workload_census import Census
from first_use_workload_domains import SCHEMA_OBSERVATION, observation_name
from first_use_workload_integrity import member_rows, sha256_hex
from first_use_workload_readback_rules import projection_digest
from first_use_workload_recipe import (
    ALL_ALIASES, LOCAL_BUDGET_CODE, MAX_PACK_BYTES, PIPELINE_LOCATION, PIPELINE_SYMBOL,
    recipe_digest,
)
from first_use_workload_recipe_shapes import PackSpec, Recipe, RecipeStep
from first_use_workload_records import (
    encode_index, encode_intent, encode_observation, index_payload, intent_payload,
)

ATTEMPT = "0123456789abcdef0123456789abcdef"
OTHER_ATTEMPT = "fedcba9876543210fedcba9876543210"
PRODUCT = "a" * 64
CANDIDATE = "b" * 64
PACK = PackSpec(
    tag="implementation", mode="ranked_discovery", query=PIPELINE_SYMBOL, intent="implementation",
    selection="pinned_current", statuses=("complete", "partial"), expected=(PIPELINE_LOCATION,),
)
SAMPLE_RECIPE: Recipe = (
    RecipeStep("local", 1, "census_verify", "sqlite", ALL_ALIASES, generation=1),
    RecipeStep("local", 2, "sqlite_init", "sqlite", ALL_ALIASES),
    RecipeStep("local", 3, "planned_refusal", "sqlite", ALL_ALIASES, generation=2,
               expectation="expected_refusal", refusal_codes=(LOCAL_BUDGET_CODE,),
               pin_relation="preserve"),
    RecipeStep("local", 4, "pack_current", "sqlite", ALL_ALIASES, packs=(PACK,)),
    RecipeStep("local", 5, "cleanup", "sqlite", ALL_ALIASES, harness_cleanup=True),
)


def pin(generation: int, salt: str = "p") -> dict[str, Any]:
    return {
        "generation": generation,
        "pin_sha256": hashlib.sha256(f"{salt}-pin-{generation}".encode()).hexdigest(),
        "manifest_sha256": hashlib.sha256(f"{salt}-manifest-{generation}".encode()).hexdigest(),
    }


def sample_intent(census: Census, *, recipe: Recipe = SAMPLE_RECIPE, product: str = PRODUCT,
                  candidate: str = CANDIDATE) -> bytes:
    return encode_intent(intent_payload(
        recipe=recipe, recipe_digest=recipe_digest(recipe), census_digest=census.digest,
        fixture_digest=census.fixture_digest, product_digest=product, candidate_census=candidate,
        declared_source_parent=None,
    ))


def census_fact(census: Census, generation: int = 1, aliases: tuple[str, ...] = ALL_ALIASES) -> dict[str, Any]:
    projection = census.generation(generation).projection(aliases)
    return {
        "generation": generation, "aliases": list(aliases), "S": projection.S, "C": projection.C,
        "files": projection.files, "inventory_sha256": projection_digest(census, generation, aliases),
    }


def pack_fact(**changes: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "status": [["implementation", "complete"]],
        "reason": [["implementation", None]],
        "encoded_bytes": [["implementation", 2048]],
        "observed_locations": [["implementation", "companion", "shared/status_codes.py"],
                               ["implementation", "core", "pkg/pipeline.py"]],
        "canary_free": True, "max_bytes": MAX_PACK_BYTES, "investigation_supported": None,
    }
    facts.update(changes)
    return facts


def sample_facts(census: Census) -> dict[tuple[int, int], dict[str, Any]]:
    return {
        (1, 0): census_fact(census),
        (2, 0): {"backend": "sqlite", "initialized": True},
        (3, 0): {"code": LOCAL_BUDGET_CODE, "pin_before": pin(3), "pin_after": pin(3)},
        (4, 0): pack_fact(),
        (5, 0): {"leftovers": [], "forbidden_events": 0, "shim_invocations": 0},
    }


def observation(step: RecipeStep, intent: bytes, facts: Any, *, attempt: str = ATTEMPT,
                **changes: Any) -> dict[str, Any]:
    refused = step.expectation == "expected_refusal"
    payload: dict[str, Any] = {
        "schema": SCHEMA_OBSERVATION, "attempt": attempt, "intent": sha256_hex(intent),
        "scenario": step.scenario, "backend": step.backend, "step": step.step, "sub": step.sub,
        "action": step.action, "expectation": step.expectation,
        "result": step.expectation, "refusal": step.refusal_codes[0] if refused else None,
        "reason": None,
        "spans": {"prepare_ns": 10, "call_ns": 20, "observe_ns": 5, "cleanup_ns": 1},
        "cpu": {"parent_process_ns": 7, "waited_descendants_ns": None},
        "facts": facts, "members": [],
    }
    payload.update(changes)
    return payload


def sample_files(
    census: Census,
    *,
    recipe: Recipe = SAMPLE_RECIPE,
    facts: Mapping[tuple[int, int], Any] | None = None,
    overrides: Mapping[tuple[int, int], Mapping[str, Any]] | None = None,
    omit: tuple[tuple[int, int], ...] = (),
    intent: bytes | None = None,
) -> dict[str, bytes]:
    """intent + observations + index; the verdict is added by the caller when wanted."""
    intent_bytes = sample_intent(census, recipe=recipe) if intent is None else intent
    all_facts = sample_facts(census) if facts is None else facts
    files: dict[str, bytes] = {"intent.json": intent_bytes}
    for step in recipe:
        if step.key in omit:
            continue
        values = dict((overrides or {}).get(step.key, {}))
        facts_for_row = values.pop("facts", all_facts.get(step.key))
        payload = observation(step, intent_bytes, facts_for_row, **values)
        files[observation_name(step.step, step.sub)] = encode_observation(payload)
    files["index.json"] = encode_index(index_payload(
        recipe[0].scenario, ATTEMPT, sha256_hex(intent_bytes), member_rows(files),
    ))
    return files


def metric(name: str, value: int | None, basis: str | None = "call_meter_exact") -> dict[str, Any]:
    return {"name": name, "value": value, "unit": "bytes", "availability": "measured",
            "basis": basis, "reason": None}


def publish_payload(S: int, C: int, m: int, **overrides: int) -> dict[str, Any]:
    """A v2-shaped payload dict (rules input only; never passed to the product codec)."""
    values = {
        "sealed_manifest_bytes": S, "sealing_read_bytes": 4 * S + C + m,
        "sealing_copy_read_bytes": S, "sealing_capture_read_bytes": 2 * S,
        "sealing_store_read_bytes": S + C + m, "sealing_write_bytes": S + m,
        "sealing_discovery_read_bytes": 0, "sealing_classification_read_bytes": 0,
    }
    values.update(overrides)
    return {
        "schema": "cloe-resource-view-v2", "operation": "local_refresh", "backend": "sqlite",
        "outcome": "published", "instrumentation": "complete",
        "metrics": [metric(name, value) for name, value in values.items()],
        "limits": [{"name": "classification_max_retained_chars", "value": None, "unit": "chars",
                    "enforcement": "not_applicable", "applies_this_call": False}],
    }


def refusal_payload(S: int, **overrides: int) -> dict[str, Any]:
    values = {"planned_inventory_bytes": S, "planned_min_read_bytes": 4 * S + 1, "worker_launches": 0}
    for name in ("sealing_read_bytes", "sealing_copy_read_bytes", "sealing_capture_read_bytes",
                 "sealing_store_read_bytes", "sealing_discovery_read_bytes",
                 "sealing_classification_read_bytes"):
        values[name] = 0
    values.update(overrides)
    return {
        "schema": "cloe-resource-view-v2", "operation": "local_refresh", "backend": "sqlite",
        "outcome": "refused", "instrumentation": "incomplete",
        "metrics": [metric(name, value) for name, value in values.items()],
        "limits": [
            {"name": "sealing_max_read_bytes", "value": overrides.get("limit", 4 * S),
             "unit": "bytes", "enforcement": "enforced", "applies_this_call": True},
            {"name": "classification_max_retained_chars", "value": None, "unit": "chars",
             "enforcement": "not_applicable", "applies_this_call": False},
        ],
    }


def plan_payload(S: int, files: int, **changes: Any) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "schema": "cloe-sealing-plan-v1", "instrumentation": "complete", "refusal": None,
        "bindings": 4, "inventory_files": files, "inventory_bytes": S,
        "inventory_symlinked_files": 0, "directory_entries": 40, "opens": 12,
        "planned_min_read_bytes": 4 * S + 1, "planned_min_read_bytes_basis": "derived_lower_bound",
        "planned_min_write_bytes": S,
        "factors": {"full_body_reads_per_file": 4, "collision_extra_reads_per_file": 1,
                    "stable_capture_max_attempts": 2},
        "effective_max_directory_entries": 100000, "projected_directory_entries": 120,
        "projection_basis": "three_walks_of_unchanged_metadata_tree_estimate",
    }
    plan.update(changes)
    return plan


__all__ = [
    "ATTEMPT", "CANDIDATE", "OTHER_ATTEMPT", "PACK", "PRODUCT", "SAMPLE_RECIPE", "census_fact",
    "metric", "observation", "pack_fact", "pin", "plan_payload", "publish_payload",
    "refusal_payload", "sample_facts", "sample_files", "sample_intent",
]
