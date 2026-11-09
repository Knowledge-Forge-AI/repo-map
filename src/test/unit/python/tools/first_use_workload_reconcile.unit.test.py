"""Pure reconciliation: every closed category, skip visibility and stored-verdict distrust."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.ops.resource_view._canonical import canonical_bytes
from first_use_workload_bundle import BundleWriter, read_bundle
from first_use_workload_census import Census, load_census
from first_use_workload_domains import WorkloadError, plan_name
from first_use_workload_integrity import member_row, member_rows, sha256_hex
from first_use_workload_recipe_shapes import RecipeStep
from first_use_workload_reconcile import check_bundle, reconcile
from first_use_workload_records import encode_index, index_payload
from repomap_test_support.first_use_workload_samples import (
    ATTEMPT, CANDIDATE, OTHER_ATTEMPT, SAMPLE_RECIPE, census_fact, pack_fact, pin, plan_payload,
    sample_facts, sample_files, sample_intent,
)


@pytest.fixture(scope="module")
def census() -> Census:
    return load_census()


@pytest.fixture(scope="module")
def intent(census: Census) -> bytes:
    return sample_intent(census)


def _verdict(census: Census, intent: bytes, files: dict[str, bytes]) -> Any:
    return reconcile(intent, files, census, SAMPLE_RECIPE)


def _reindex(files: dict[str, bytes]) -> dict[str, bytes]:
    payload = {name: data for name, data in files.items() if name not in ("index.json", "verdict.json")}
    files["index.json"] = encode_index(index_payload(
        "local", ATTEMPT, sha256_hex(files["intent.json"]), member_rows(payload),
    ))
    return files


def _with(census: Census, **kwargs: Any) -> dict[str, bytes]:
    return sample_files(census, **kwargs)


def _categories(census: Census, intent: bytes, files: dict[str, bytes]) -> set[str]:
    return set(_verdict(census, intent, files).categories)


def _recipe_categories(census: Census, recipe: tuple[RecipeStep, ...],
                       files: dict[str, bytes]) -> set[str]:
    intent = sample_intent(census, recipe=recipe)
    return set(reconcile(intent, files, census, recipe).categories)


def _pin_recipe(scenario: str, backend: str) -> tuple[RecipeStep, ...]:
    aliases = SAMPLE_RECIPE[0].aliases
    return (
        RecipeStep(scenario, 1, "refresh_cold", backend, aliases, generation=1,
                   pin_relation="cold"),
        RecipeStep(scenario, 2, "refresh_repeat", backend, aliases, generation=1,
                   pin_relation="increment"),
        RecipeStep(scenario, 3, "planned_refusal", backend, aliases, generation=1,
                   expectation="expected_refusal", refusal_codes=("resource_budget_exceeded",),
                   pin_relation="preserve"),
        RecipeStep(scenario, 4, "replay_refresh", backend, aliases, generation=1,
                   pin_relation="replay"),
    )


def _refresh_facts(census: Census, before: dict[str, Any] | None,
                   after: dict[str, Any], *,
                   preparation: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "attempt_root_fresh": True, "inventory_sha256": census_fact(census)["inventory_sha256"],
        "manifest_bytes": 1, "outcome": "published", "pin_after": after,
        "pin_before": before, "preparation_pin": preparation,
    }


def _continuity_facts(census: Census) -> dict[tuple[int, int], Any]:
    first, second, replay = pin(1), pin(2), pin(3)
    return {
        (1, 0): _refresh_facts(census, None, first),
        (2, 0): _refresh_facts(census, first, second),
        (3, 0): {"code": "resource_budget_exceeded", "pin_before": second,
                 "pin_after": second},
        (4, 0): _refresh_facts(census, second, replay, preparation=replay),
    }


def _mixed_pin_recipe() -> tuple[RecipeStep, ...]:
    aliases = SAMPLE_RECIPE[0].aliases
    return (
        RecipeStep("mixed", 1, "sqlite_initial", "sqlite", aliases, generation=1,
                   pin_relation="cold"),
        RecipeStep("mixed", 2, "postgres_initial", "postgresql", aliases, generation=1,
                   pin_relation="cold"),
        RecipeStep(
            "mixed", 3, "privacy_refusal", "mixed", aliases,
            expectation="expected_refusal", refusal_codes=("graph_privacy_not_authorized",),
            pin_relation="preserve", fact_backends=("sqlite", "postgresql"),
        ),
    )


def test_complete_sample_is_accepted_with_separate_counts(census: Census, intent: bytes) -> None:
    verdict = _verdict(census, intent, _with(census))
    assert (verdict.outcome, verdict.categories) == ("accepted", ())
    assert verdict.counts == {"pass": 4, "expected_refusal": 1}
    assert verdict.payload()["counts"]["failure"] == 0


@pytest.mark.parametrize(("mutate", "category"), [
    (lambda data: data[:-1] + b" \n", "not_canonical"),
    (lambda data: b"{" + data, "malformed"),
    (lambda data: data.replace(b'"result":"pass"', b'"result":"done"'), "invalid_domain"),
    (lambda data: data[:-2] + b"," + b'"pad":"' + b"x" * 9000 + b'"}\n', "too_large"),
])
def test_decoding_categories(census: Census, intent: bytes, mutate: Any, category: str) -> None:
    files = _with(census)
    files["observation-02-0.json"] = mutate(files["observation-02-0.json"])
    # An oversized member cannot be re-indexed by the strict writer.
    # Keep its old index: semantic decoding must still classify the bytes.
    indexed = files if category == "too_large" else _reindex(files)
    found = _categories(census, intent, indexed)
    assert category in found and "missing_step" in found


def test_stale_census_projection_is_stale_input(census: Census, intent: bytes) -> None:
    facts = {**sample_facts(census), (1, 0): {**census_fact(census), "S": 1}}
    assert _categories(census, intent, _with(census, facts=facts)) == {"stale_input"}
    failed = {(1, 0): {"result": "failure", "reason": "stale_input", "facts": None}}
    found = _categories(census, intent, _with(census, overrides=failed))
    assert {"stale_input", "unexpected_failure"} <= found


def test_intent_and_candidate_mismatch(census: Census, intent: bytes) -> None:
    other_candidate = sample_intent(census, candidate="c" * 64)
    files = _with(census, intent=other_candidate)
    assert "candidate_mismatch" in _categories(census, intent, files)
    other_product = sample_intent(census, product="d" * 64)
    assert "candidate_mismatch" in _categories(census, intent, _with(census, intent=other_product))
    shorter = sample_intent(census, recipe=SAMPLE_RECIPE[:4])
    found = _categories(census, intent, _with(census, intent=shorter))
    assert "intent_mismatch" in found and "candidate_mismatch" not in found
    assert CANDIDATE != "c" * 64


def test_cross_attempt_and_cross_backend(census: Census, intent: bytes) -> None:
    attempt = {(2, 0): {"attempt": OTHER_ATTEMPT}}
    assert "cross_attempt" in _categories(census, intent, _with(census, overrides=attempt))
    backend = {(2, 0): {"backend": "postgresql"}}
    assert "cross_backend" in _categories(census, intent, _with(census, overrides=backend))


def test_rolling_pin_continuity_rejects_disconnected_local_publish(census: Census) -> None:
    recipe = _pin_recipe("local", "sqlite")
    facts = _continuity_facts(census)
    facts[(2, 0)] = _refresh_facts(census, pin(7), pin(8))
    facts[(3, 0)] = {"code": "resource_budget_exceeded", "pin_before": pin(8),
                     "pin_after": pin(8)}
    facts[(4, 0)] = _refresh_facts(census, pin(8), pin(9), preparation=pin(9))
    files = sample_files(census, recipe=recipe, facts=facts)
    assert _recipe_categories(census, recipe, files) == {"witness_mismatch"}


def test_rolling_pin_continuity_rejects_disconnected_server_refusal(census: Census) -> None:
    recipe = _pin_recipe("server", "postgresql")
    facts = _continuity_facts(census)
    facts[(3, 0)] = {"code": "resource_budget_exceeded", "pin_before": pin(7),
                     "pin_after": pin(7)}
    facts[(4, 0)] = _refresh_facts(census, pin(7), pin(8), preparation=pin(8))
    files = sample_files(census, recipe=recipe, facts=facts)
    assert _recipe_categories(census, recipe, files) == {"witness_mismatch"}


def test_rolling_pin_continuity_rejects_only_disconnected_mixed_backend(census: Census) -> None:
    recipe = _mixed_pin_recipe()
    sqlite_pin = pin(1, salt="sqlite")
    postgres_pin = pin(1, salt="postgres")
    disconnected = pin(8, salt="postgres")
    facts = {
        (1, 0): _refresh_facts(census, None, sqlite_pin),
        (2, 0): _refresh_facts(census, None, postgres_pin),
        (3, 0): {
            "sqlite": {"code": "graph_privacy_not_authorized", "pin_before": sqlite_pin,
                        "pin_after": sqlite_pin},
            "postgresql": {"code": "graph_privacy_not_authorized", "pin_before": disconnected,
                            "pin_after": disconnected},
        },
    }
    files = sample_files(census, recipe=recipe, facts=facts)
    assert _recipe_categories(census, recipe, files) == {"witness_mismatch"}


def test_rolling_pin_continuity_accepts_coherent_replay_and_keeps_cold_baseline(
    census: Census,
) -> None:
    recipe = _pin_recipe("local", "sqlite")
    facts = _continuity_facts(census)
    files = sample_files(census, recipe=recipe, facts=facts)
    intent = sample_intent(census, recipe=recipe)
    assert reconcile(intent, files, census, recipe).outcome == "accepted"

    bad_cold = dict(facts)
    bad_cold[(1, 0)] = _refresh_facts(census, pin(9), pin(1))
    bad_files = sample_files(census, recipe=recipe, facts=bad_cold)
    assert _recipe_categories(census, recipe, bad_files) == {"witness_mismatch"}


def test_out_of_order_and_missing_step(census: Census, intent: bytes) -> None:
    files = _with(census)
    files["observation-02-0.json"], files["observation-04-0.json"] = (
        files["observation-04-0.json"], files["observation-02-0.json"],
    )
    assert "out_of_order" in _categories(census, intent, _reindex(files))
    found = _categories(census, intent, _with(census, omit=((4, 0),)))
    assert found == {"missing_step"}
    assert _verdict(census, intent, _with(census, omit=((4, 0),))).outcome == "incomplete"


def test_partial_and_tampered_members(census: Census, intent: bytes) -> None:
    files = _with(census)
    del files["observation-03-0.json"]
    assert {"partial_bundle", "missing_step"} <= _categories(census, intent, files)
    files = _with(census)
    files["observation-03-0.json"] = files["observation-03-0.json"].replace(b'"call_ns":20', b'"call_ns":21')
    assert "tampered_member" in _categories(census, intent, files)
    files = _with(census)
    files["plans/plan-09-0.json"] = b"{}\n"
    assert "tampered_member" in _categories(census, intent, files)
    files = _with(census)
    del files["index.json"]
    assert "partial_bundle" in _categories(census, intent, files)
    assert "intent_mismatch" not in _categories(census, intent, files)
    assert _verdict(census, intent, files).outcome == "incomplete"


def test_unbounded_refs_and_witness_rules(census: Census, intent: bytes) -> None:
    many = [["implementation", "core", f"pkg/m{index:02d}.py"] for index in range(33)]
    facts = {**sample_facts(census), (4, 0): pack_fact(observed_locations=many)}
    assert "unbounded" in _categories(census, intent, _with(census, facts=facts))
    facts = {**sample_facts(census), (2, 0): {"backend": "sqlite", "initialized": False}}
    assert _categories(census, intent, _with(census, facts=facts)) == {"witness_mismatch"}
    moved = {"code": "sealing-budget-exceeded:planned_read_bytes", "pin_before": pin(3), "pin_after": pin(4)}
    facts = {**sample_facts(census), (3, 0): moved}
    assert _categories(census, intent, _with(census, facts=facts)) == {"pin_not_preserved"}


def test_expected_values_copied_without_witnesses_are_witness_missing(census: Census, intent: bytes) -> None:
    copied = {
        (1, 0): {**census_fact(census), "inventory_sha256": None},
        (2, 0): {"backend": "sqlite", "initialized": None},
        (3, 0): {"code": "sealing-budget-exceeded:planned_read_bytes", "pin_before": None,
                 "pin_after": None},
        (4, 0): pack_fact(canary_free=None),
        (5, 0): {"leftovers": [], "forbidden_events": None, "shim_invocations": None},
    }
    verdict = _verdict(census, intent, _with(census, facts=copied))
    assert verdict.categories == ("witness_missing",) and verdict.outcome == "incomplete"
    no_facts = _with(census, facts={})
    assert set(_verdict(census, intent, no_facts).categories) == {"witness_missing"}
    unspanned = {(2, 0): {"spans": {"prepare_ns": 1, "call_ns": None, "observe_ns": 1, "cleanup_ns": 1}}}
    assert _categories(census, intent, _with(census, overrides=unspanned)) == {"witness_missing"}


def test_failure_and_skip_stay_visible_and_separate(census: Census, intent: bytes) -> None:
    failed = {(2, 0): {"result": "failure", "reason": "call_failed", "facts": None}}
    verdict = _verdict(census, intent, _with(census, overrides=failed))
    assert "unexpected_failure" in verdict.categories and verdict.outcome == "rejected"
    assert verdict.counts["failure"] == 1
    skipped = {(4, 0): {"result": "skipped", "reason": "runtime_unavailable", "facts": None}}
    verdict = _verdict(census, intent, _with(census, overrides=skipped))
    assert (verdict.outcome, verdict.categories) == ("incomplete", ("missing_step",))
    assert verdict.counts["skipped"] == 1
    refused_pass = {(2, 0): {"result": "expected_refusal",
                             "refusal": "sealing-budget-exceeded:planned_read_bytes"}}
    assert "unexpected_failure" in _categories(census, intent, _with(census, overrides=refused_pass))


def test_report_mismatch_from_a_plan_member(census: Census) -> None:
    plan_step = RecipeStep("local", 2, "sealing_plan", "sqlite", SAMPLE_RECIPE[0].aliases,
                           generation=1, plan=True)
    recipe = (SAMPLE_RECIPE[0], plan_step)
    intent = sample_intent(census, recipe=recipe)
    projection = census.generation(1).projection(plan_step.aliases)
    plan_bytes = canonical_bytes(plan_payload(projection.S, projection.files), 4096) + b"\n"
    name = plan_name(2, 0)
    facts = {(1, 0): census_fact(census),
             (2, 0): {"inventory_bytes": projection.S, "inventory_files": projection.files,
                      "planned_min_read_bytes": 4 * projection.S + 1}}
    overrides = {(2, 0): {"members": [member_row(name, plan_bytes)]}}
    files = sample_files(census, recipe=recipe, facts=facts, overrides=overrides, intent=intent)
    files[name] = plan_bytes
    _reindex(files)
    assert reconcile(intent, files, census, recipe).outcome == "accepted"
    bad = canonical_bytes(plan_payload(projection.S, projection.files, planned_min_read_bytes_basis="x"),
                          4096) + b"\n"
    overrides = {(2, 0): {"members": [member_row(name, bad)]}}
    files = sample_files(census, recipe=recipe, facts=facts, overrides=overrides, intent=intent)
    files[name] = bad
    assert "report_mismatch" in reconcile(intent, _reindex(files), census, recipe).categories


def test_stored_verdict_never_supplies_acceptance(census: Census, intent: bytes) -> None:
    files = _with(census)
    good = _verdict(census, intent, files).encoded()
    assert check_bundle(intent, {**files, "verdict.json": good}, census, SAMPLE_RECIPE).outcome == "accepted"
    payload = json.loads(good)
    payload["counts"]["pass"] = 5
    forged = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    forged_verdict = check_bundle(intent, {**files, "verdict.json": forged}, census, SAMPLE_RECIPE)
    assert forged_verdict.outcome == "rejected" and "tampered_member" in forged_verdict.categories
    missing = check_bundle(intent, files, census, SAMPLE_RECIPE)
    assert (missing.outcome, missing.categories) == ("incomplete", ("partial_bundle",))


def test_verdict_only_bundle_is_not_accepted(census: Census, intent: bytes) -> None:
    good = _verdict(census, intent, _with(census)).encoded()
    verdict = check_bundle(intent, {"verdict.json": good}, census, SAMPLE_RECIPE)
    assert verdict.outcome != "accepted" and "partial_bundle" in verdict.categories


def test_semantic_categories_survive_a_stale_verdict(census: Census, intent: bytes) -> None:
    files = _with(census, overrides={(2, 0): {"attempt": OTHER_ATTEMPT}})
    stale = _verdict(census, intent, _with(census)).encoded()
    verdict = check_bundle(intent, {**files, "verdict.json": stale}, census, SAMPLE_RECIPE)
    assert {"cross_attempt", "tampered_member"} <= set(verdict.categories)


def test_written_bundle_round_trips_through_the_reader(tmp_path: Path, census: Census, intent: bytes) -> None:
    files = _with(census)
    writer = BundleWriter(tmp_path, "local", ATTEMPT)
    for name in sorted(name for name in files if name != "index.json"):
        writer.write(name, files[name])
    writer.write("index.json", files["index.json"])
    verdict = reconcile(intent, read_bundle(writer.root), census, SAMPLE_RECIPE)
    writer.write("verdict.json", verdict.encoded())
    stored = read_bundle(writer.root)
    assert check_bundle(intent, stored, census, SAMPLE_RECIPE).outcome == "accepted"
    with pytest.raises(WorkloadError):
        read_bundle(tmp_path / "missing")
