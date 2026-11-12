"""Frozen estimate algebra and source-bound transition observation gate."""

from __future__ import annotations

import math
from typing import cast

import pytest

from retrieval_public_text_preflight import (
    BASIS, PreflightRefusal, check_transition_observation, checked_counts, estimate_generation,
    transition_observation,
)

IDS = {name: "sha256:" + ch * 64 for name, ch in (
    ("q_source_closure_identity", "1"), ("task_pins_identity", "2"), ("selected_task_set_identity", "3"),
    ("artifact_profile_identity", "4"))}
G1 = {"v1.document": 80, "ptx.document": 80, "v1.query": 4, "ptx.query": 4}
G2 = {"v1.document": 80, "ptx.document": 80, "v1.query": 0, "ptx.query": 0}


def test_basis_is_the_frozen_original_raw_native_report() -> None:
    assert (BASIS[1].records, BASIS[1].before_limit_tokens) == (84, 4972)
    assert (BASIS[2].records, BASIS[2].before_limit_tokens) == (80, 4861)


def test_worst_case_estimates_match_the_disclosed_table() -> None:
    g1, g2 = estimate_generation(1, G1), estimate_generation(2, G2)
    g1_seconds = cast(float, g1["estimated_model_seconds"])
    g2_seconds = cast(float, g2["estimated_model_seconds"])
    assert math.isclose(g1_seconds, 473.6, abs_tol=0.5)
    assert math.isclose(g2_seconds, 442.4, abs_tol=0.5)
    assert math.isclose(cast(float, g1["policy_factor"]), 10.3075, abs_tol=1e-3)
    assert g1_seconds + 60 <= 550 and g2_seconds + 60 <= 550
    assert g1["estimate_gate_identity"] != g2["estimate_gate_identity"]
    assert estimate_generation(1, G1) == g1


@pytest.mark.parametrize("generation,counts,code", [
    (1, {**G1, "v1.query": True}, "preflight_count_type_or_bounds"),
    (1, {**G1, "v1.query": 4.0}, "preflight_count_type_or_bounds"),
    (1, {**G1, "extra": 1}, "preflight_count_fields"),
    (1, {**G1, "ptx.query": 0}, "preflight_query_floor_or_fixed_candidate_cap"),
    (1, {**G1, "v1.query": 5, "ptx.query": 5}, "preflight_query_floor_or_fixed_candidate_cap"),
    (1, {**G1, "ptx.query": 4, "v1.query": 3}, "preflight_query_floor_or_fixed_candidate_cap"),
    (1, {**G1, "ptx.document": 0}, "preflight_document_floor_or_request_cap"),
    (1, {**G1, "ptx.document": 81}, "preflight_document_floor_or_request_cap"),
    (2, {**G2, "v1.query": 1}, "preflight_generation_two_query_refused"),
    (3, G2, "preflight_generation"),
    (True, G1, "preflight_generation"),
    (1, {"v1.document": 300, "ptx.document": 200, "v1.query": 4, "ptx.query": 4},
     "preflight_document_floor_or_request_cap"),
])
def test_count_refusals(generation: object, counts: dict, code: str) -> None:
    with pytest.raises(PreflightRefusal) as raised:
        checked_counts(counts, generation)
    assert raised.value.code == code


def test_estimate_over_budget_or_changed_runtime_refuses() -> None:
    with pytest.raises(PreflightRefusal, match="over_budget"):
        estimate_generation(1, {"v1.document": 100, "ptx.document": 100, "v1.query": 4, "ptx.query": 4})
    with pytest.raises(PreflightRefusal, match="runtime_changed"):
        estimate_generation(1, G1, runtime_sha256="sha256:" + "9" * 64)


def _observation(interval: float = 200.0, **changes: object) -> dict:
    value = transition_observation(interval_seconds=interval, counts={"1": G1, "2": G2}, **IDS)
    value.update(changes)
    return value


def test_transition_gate_accepts_the_exact_functional_observation() -> None:
    gate = check_transition_observation(_observation(), actual_counts={"1": G1, "2": G2}, **IDS)
    assert gate["observed_interval_seconds"] == 200.0
    assert cast(str, gate["transition_gate_identity"]).startswith("sha256:")
    boundary = check_transition_observation(_observation(480.0), actual_counts={"1": G1, "2": G2}, **IDS)
    assert boundary["observed_interval_seconds"] == 480.0


@pytest.mark.parametrize("observation,code", [
    (None, "preflight_transition_fields"),
    (_observation(480.5), "preflight_transition_over_budget"),
    (_observation(interval_seconds=float("nan")), "preflight_transition_interval"),
    (_observation(interval_seconds=-1.0), "preflight_transition_interval"),
    (_observation(interval_seconds="1"), "preflight_transition_interval"),
    (_observation(functional_only=False), "preflight_transition_mode"),
    (_observation(schema="other"), "preflight_transition_mode"),
    (_observation(q_source_closure_identity="sha256:" + "9" * 64), "preflight_transition_source_or_task_changed"),
    (_observation(counts={"1": {**G1, "v1.document": 81}, "2": G2}), "preflight_transition_counts_changed"),
    (_observation(counts={"1": G1}), "preflight_transition_count_generations"),
    ({**_observation(), "extra": 1}, "preflight_transition_fields"),
])
def test_transition_gate_refuses_missing_stale_nonfinite_over_budget_or_mismatched(observation: object,
                                                                                   code: str) -> None:
    with pytest.raises(PreflightRefusal) as raised:
        check_transition_observation(observation, actual_counts={"1": G1, "2": G2}, **IDS)
    assert raised.value.code == code


def test_transition_gate_refuses_partial_expected_identities() -> None:
    partial = dict(IDS)
    partial.pop("artifact_profile_identity")
    with pytest.raises(PreflightRefusal):
        check_transition_observation(_observation(), actual_counts={"1": G1, "2": G2}, **partial)
