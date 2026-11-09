"""Witness arithmetic, m_c/r gating, report identity, plan, pin, pack, lexical and cleanup rules."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

import first_use_workload_rules as rules
from common_lore_index.ops.resource_view._canonical import canonical_bytes
from first_use_workload_census import Census, load_census
from first_use_workload_domains import WorkloadError, report_name
from first_use_workload_integrity import member_row
from first_use_workload_pins import advanced_by_one, preserved
from first_use_workload_readback_rules import (
    cleanup_rules, lexical_rules, pack_rules, projection_digest,
)
from first_use_workload_recipe import RECIPE, find_step
from first_use_workload_recipe_shapes import RecipeStep, ReportSpec
from first_use_workload_report_rules import (
    decode_plan_member, plan_rules, planned_refusal_formula, publish_formula, report_identity,
)
from repomap_test_support.first_use_workload_samples import (
    SAMPLE_RECIPE, pack_fact, pin, plan_payload, publish_payload, refusal_payload,
)
from repomap_test_support.first_use_workload_witness import packet_refs
from repomap_test_support.retrieval_evaluation_fixture import binding_id_for_alias

S, C, M = 1000, 200, 300


@pytest.fixture(scope="module")
def census() -> Census:
    return load_census()


def _step(scenario: str, step: int, sub: int = 0) -> RecipeStep:
    found = find_step(scenario, step, sub, RECIPE)
    assert found is not None
    return found


def test_publish_formula_accepts_exact_terms_with_nonzero_collisions() -> None:
    assert publish_formula(publish_payload(S, C, M), S=S, C=C, m=M) == set()


@pytest.mark.parametrize("name", [
    "sealed_manifest_bytes", "sealing_read_bytes", "sealing_copy_read_bytes",
    "sealing_capture_read_bytes", "sealing_store_read_bytes", "sealing_write_bytes",
    "sealing_discovery_read_bytes", "sealing_classification_read_bytes",
])
def test_each_publish_term_mismatch_is_a_report_mismatch(name: str) -> None:
    good = publish_payload(S, C, M)
    value = next(item["value"] for item in good["metrics"] if item["name"] == name)
    assert publish_formula(publish_payload(S, C, M, **{name: value + 1}), S=S, C=C, m=M) == {
        "report_mismatch"
    }


def test_a_retry_or_collided_manifest_term_is_not_absorbed() -> None:
    # m_c and r are zero only under witnessed conditions; any extra read is a mismatch.
    retried = publish_payload(S, C, M, sealing_read_bytes=4 * S + C + M + M)
    assert publish_formula(retried, S=S, C=C, m=M) == {"report_mismatch"}
    assert publish_formula(publish_payload(S, 0, M), S=S, C=C, m=M) == {"report_mismatch"}


def test_exact_basis_and_classification_limit_are_required() -> None:
    payload = publish_payload(S, C, M)
    for item in payload["metrics"]:
        if item["name"] == "sealing_discovery_read_bytes":
            item["basis"] = "derived_lower_bound"
    assert publish_formula(payload, S=S, C=C, m=M) == {"report_mismatch"}
    payload = publish_payload(S, C, M)
    payload["limits"][0]["applies_this_call"] = True
    assert publish_formula(payload, S=S, C=C, m=M) == {"report_mismatch"}


def test_planned_refusal_formula() -> None:
    assert planned_refusal_formula(refusal_payload(S), S=S, multiplier=4) == set()
    for change in ({"worker_launches": 1}, {"sealing_copy_read_bytes": 5},
                   {"planned_min_read_bytes": 4 * S}, {"limit": 4 * S + 1}):
        assert planned_refusal_formula(refusal_payload(S, **change), S=S, multiplier=4) == {
            "report_mismatch"
        }, change


def test_report_identity_checks_labels_schema_and_canary_text() -> None:
    spec = ReportSpec(2, "local_refresh", "sqlite", ("published",), "complete")
    payload = publish_payload(S, C, M)
    assert report_identity(spec, payload, b"{}\n") == set()
    assert report_identity(spec, payload, b'{"x":"mixed-v1"}\n') == {"report_mismatch"}
    for key, value in (("operation", "server_refresh"), ("backend", "postgresql"),
                       ("outcome", "refused"), ("instrumentation", "incomplete"),
                       ("schema", "cloe-resource-view-v1")):
        assert report_identity(spec, {**payload, key: value}, b"{}\n") == {"report_mismatch"}, key
    assert report_identity(dataclasses.replace(spec, instrumentation=None),
                           {**payload, "instrumentation": "incomplete"}, b"{}\n") == set()


def _plan_bytes(payload: dict[str, Any]) -> bytes:
    return canonical_bytes(payload, 4096) + b"\n"


def test_plan_member_codec_and_rules(census: Census) -> None:
    projection = census.generation(1).projection(_step("local", 3).aliases)
    plan = decode_plan_member(_plan_bytes(plan_payload(projection.S, projection.files)))
    facts = {key: plan[key] for key in ("inventory_bytes", "inventory_files", "planned_min_read_bytes")}
    assert plan_rules(plan, facts, S=projection.S) == set()
    assert plan_rules(plan, {**facts, "inventory_bytes": None}, S=projection.S) == {"witness_missing"}
    assert plan_rules(plan, {**facts, "inventory_files": 1}, S=projection.S) == {"report_mismatch"}
    assert "witness_mismatch" in plan_rules(plan, facts, S=projection.S + 1)
    refused = decode_plan_member(_plan_bytes(plan_payload(1, 1, refusal="directory_entries")))
    assert "report_mismatch" in plan_rules(refused, facts, S=1)
    with pytest.raises(WorkloadError) as error:
        decode_plan_member(_plan_bytes({**plan_payload(1, 1), "extra": 1}))
    assert error.value.category == "report_mismatch"
    with pytest.raises(WorkloadError):
        decode_plan_member(_plan_bytes(plan_payload(1, 1)).replace(b",", b", ", 1))


def test_pin_relations() -> None:
    assert advanced_by_one(None, pin(1)) and not advanced_by_one(None, pin(2))
    assert advanced_by_one(pin(1), pin(2)) and not advanced_by_one(pin(1), pin(3))
    same_map = dict(pin(2), pin_sha256=pin(1)["pin_sha256"])
    assert not advanced_by_one(pin(1), same_map)
    assert preserved(pin(3), pin(3)) and not preserved(pin(3), pin(3, salt="q"))
    assert not preserved(None, None)


def _refresh_files(step: RecipeStep) -> dict[str, bytes]:
    return {report_name(step.step, step.sub): b"report-bytes\n"}


def _refresh_observation(step: RecipeStep, census: Census, **changes: Any) -> dict[str, Any]:
    facts = {
        "outcome": "published", "pin_before": pin(1), "pin_after": pin(2), "preparation_pin": None,
        "attempt_root_fresh": True, "manifest_bytes": M,
        "inventory_sha256": projection_digest(census, step.generation or 0, step.aliases),
    }
    facts.update(changes)
    data = _refresh_files(step)[report_name(step.step, step.sub)]
    return {"facts": facts, "refusal": None, "members": [member_row(report_name(step.step, step.sub), data)]}


def test_refresh_gating_requires_a_fresh_attempt_before_m_c_is_zero(
    census: Census, monkeypatch: pytest.MonkeyPatch,
) -> None:
    step = _step("local", 6)
    projection = census.generation(1).projection(step.aliases)
    monkeypatch.setattr(rules, "decode_report_member",
                        lambda _data: publish_payload(projection.S, projection.C, M))
    files = _refresh_files(step)
    assert rules.row_categories(step, _refresh_observation(step, census), files, census) == set()
    unknown = _refresh_observation(step, census, attempt_root_fresh=None)
    assert rules.row_categories(step, unknown, files, census) == {"witness_missing"}
    reused = _refresh_observation(step, census, attempt_root_fresh=False)
    assert rules.row_categories(step, reused, files, census) == {"witness_mismatch"}
    wrong_m = _refresh_observation(step, census, manifest_bytes=M + 1)
    assert rules.row_categories(step, wrong_m, files, census) == {"report_mismatch"}
    skipped = _refresh_observation(step, census, pin_after=pin(3))
    assert rules.row_categories(step, skipped, files, census) == {"witness_mismatch"}
    drifted = _refresh_observation(step, census, inventory_sha256="0" * 64)
    assert rules.row_categories(step, drifted, files, census) == {"witness_mismatch"}


def test_replay_requires_preparation_increment_and_unchanged_pin(
    census: Census, monkeypatch: pytest.MonkeyPatch,
) -> None:
    step = _step("local", 12)
    monkeypatch.setattr(rules, "decode_report_member", lambda _data: {
        "schema": "cloe-resource-view-v1", "operation": "local_refresh", "backend": "sqlite",
        "outcome": "reconciled_replay", "instrumentation": "complete", "metrics": [], "limits": [],
    })
    files = _refresh_files(step)
    good = _refresh_observation(step, census, outcome="reconciled_replay", pin_before=pin(4),
                                preparation_pin=pin(5), pin_after=pin(5), attempt_root_fresh=None)
    assert rules.row_categories(step, good, files, census) == set()
    moved = dict(good, facts={**good["facts"], "pin_after": pin(6)})
    assert rules.row_categories(step, moved, files, census) == {"pin_not_preserved"}
    missing = dict(good, facts={**good["facts"], "preparation_pin": None})
    assert rules.row_categories(step, missing, files, census) == {"witness_missing"}


def test_refusal_keeps_the_complete_pin_digest(census: Census) -> None:
    step = SAMPLE_RECIPE[2]
    observation: dict[str, Any] = {"facts": {"code": step.refusal_codes[0], "pin_before": pin(3), "pin_after": pin(3)},
                   "refusal": step.refusal_codes[0], "members": []}
    assert rules.row_categories(step, observation, {}, census) == set()
    changed = dict(observation, facts={**observation["facts"], "pin_after": pin(3, salt="other")})
    assert rules.row_categories(step, changed, {}, census) == {"pin_not_preserved"}
    copied = dict(observation, facts={**observation["facts"], "pin_before": None, "pin_after": None})
    assert rules.row_categories(step, copied, {}, census) == {"witness_missing"}


def test_plan_member_rejects_canary_text_in_a_string_metadata_field() -> None:
    data = _plan_bytes(plan_payload(1, 1, projection_basis="mixed-v1"))
    with pytest.raises(WorkloadError) as failure:
        decode_plan_member(data)
    assert failure.value.category == "report_mismatch"


def test_pack_rules_compute_presence_absence_and_scope_from_refs(census: Census) -> None:
    step = SAMPLE_RECIPE[3]
    assert pack_rules(step, pack_fact(), census) == set()
    assert pack_rules(step, pack_fact(observed_locations=[]), census) == {"witness_mismatch"}
    unresolved = [["implementation", "core", "pkg/pipeline.py"], ["implementation", "unresolved", "x.py"]]
    assert pack_rules(step, pack_fact(observed_locations=unresolved), census) == {"witness_mismatch"}
    subset = dataclasses.replace(step, aliases=("core",))
    assert pack_rules(subset, pack_fact(), census) == {"witness_mismatch"}
    assert pack_rules(step, pack_fact(encoded_bytes=[["implementation", 16385]]), census) == {"witness_mismatch"}
    assert pack_rules(step, pack_fact(canary_free=None), census) == {"witness_missing"}
    assert pack_rules(step, pack_fact(status=[["implementation", "stale"]]), census) == {"witness_mismatch"}
    assert pack_rules(step, pack_fact(investigation_supported=True), census) == {"witness_mismatch"}


def test_location_refs_must_be_selected_census_members(census: Census) -> None:
    step = SAMPLE_RECIPE[3]
    unknown = pack_fact(observed_locations=sorted([
        ["implementation", "core", "pkg/pipeline.py"],
        ["implementation", "core", "pkg/not-in-census.py"],
    ]))
    assert rules.row_categories(
        step, {"facts": unknown, "refusal": None, "members": []}, {}, census,
    ) == {"witness_mismatch"}
    excluded = pack_fact(observed_locations=sorted([
        ["implementation", "core", "pkg/pipeline.py"],
        ["implementation", "companion", "excluded_cache/unselected_scratch.txt"],
    ]))
    assert rules.row_categories(
        step, {"facts": excluded, "refusal": None, "members": []}, {}, census,
    ) == {"witness_mismatch"}
    malformed = pack_fact(observed_locations=[["implementation", "core", None]])
    assert rules.row_categories(
        step, {"facts": malformed, "refusal": None, "members": []}, {}, census,
    ) == {"invalid_domain"}


def test_packet_refs_preserve_alias_qualified_duplicate_relative_paths() -> None:
    path = "shared/status_codes.py"
    packet = {"items": [{"locations": [
        {"source_binding_id": binding_id_for_alias("core"), "source_relative_path": path},
        {"source_binding_id": binding_id_for_alias("companion"), "source_relative_path": path},
    ]}]}
    assert packet_refs(packet, "implementation") == [
        ["implementation", "companion", path], ["implementation", "core", path],
    ]


def test_packet_refs_reject_nonstring_relative_paths_before_normalization() -> None:
    packet = {"items": [{"locations": [{
        "source_binding_id": binding_id_for_alias("core"), "source_relative_path": None,
    }]}]}
    with pytest.raises(ValueError, match="first-use-location-invalid"):
        packet_refs(packet, "implementation")


def test_lexical_rules(census: Census) -> None:
    query = _step("server", 11, 0)
    facts = {"result": "available", "hits": 2, "observed_locations": [["core", "pkg/pipeline.py"]],
             "revoked_generations": None, "unavailable_reason": None}
    assert lexical_rules(query, facts, census) == set()
    assert lexical_rules(query, {**facts, "hits": 0}, census) == {"witness_mismatch"}
    assert lexical_rules(query, {**facts, "observed_locations": [["companion", "x.md"]]}, census) == {
        "witness_mismatch"
    }
    absent = _step("server", 11, 2)
    leaked = {**facts, "observed_locations": [["core", "pkg/legacy_deprecated.py"]]}
    assert lexical_rules(absent, leaked, census) == {"witness_mismatch"}
    assert lexical_rules(absent, {**facts, "hits": 0, "observed_locations": []}, census) == set()
    revoke = _step("server", 12)
    revoked: dict[str, Any] = {"result": "revoked", "hits": None, "observed_locations": [], "revoked_generations": 1,
               "unavailable_reason": "projection_absent"}
    assert lexical_rules(revoke, revoked, census) == set()
    assert lexical_rules(revoke, {**revoked, "unavailable_reason": "capability_available"}, census) == {
        "witness_mismatch"
    }
    assert lexical_rules(revoke, {**revoked, "revoked_generations": None}, census) == {"witness_missing"}


def test_cleanup_rules_distinguish_harness_scenarios() -> None:
    local, server = _step("local", 13), _step("server", 13)
    clean = {"leftovers": [], "forbidden_events": 0, "shim_invocations": 0}
    assert cleanup_rules(local, clean) == set()
    assert cleanup_rules(local, {**clean, "leftovers": [".cloe-resource-report-x"]}) == {"witness_mismatch"}
    assert cleanup_rules(local, {**clean, "shim_invocations": None}) == {"witness_missing"}
    assert cleanup_rules(server, {**clean, "forbidden_events": None, "shim_invocations": None}) == set()
    assert cleanup_rules(server, clean) == {"witness_mismatch"}


def test_fact_shapes_are_closed_and_refs_bounded(census: Census) -> None:
    step = SAMPLE_RECIPE[3]
    many = [["implementation", "core", f"pkg/m{index:02d}.py"] for index in range(33)]
    observation: dict[str, Any] = {"facts": pack_fact(observed_locations=many), "refusal": None, "members": []}
    assert rules.row_categories(step, observation, {}, census) == {"unbounded"}
    extra: dict[str, Any] = {"facts": {**pack_fact(), "note": 1}, "refusal": None, "members": []}
    assert rules.row_categories(step, extra, {}, census) == {"malformed"}
    unsorted: dict[str, Any] = {"facts": pack_fact(observed_locations=list(reversed(pack_fact()["observed_locations"]))),
                "refusal": None, "members": []}
    assert rules.row_categories(step, unsorted, {}, census) == {"not_canonical"}
    stray = {"facts": pack_fact(), "refusal": None, "members": [["reports/report-04-0.json", "0" * 64, 1]]}
    assert rules.row_categories(step, stray, {}, census) == {"tampered_member", "partial_bundle"}
