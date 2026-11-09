"""Strict first-use record codecs: duplicates, depth, numbers, booleans and canonical bytes."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest

import first_use_workload_recipe as recipe_module
from first_use_workload_census import Census, load_census
from first_use_workload_domains import MAX_COUNTER, WorkloadError
from first_use_workload_encoding import decode_record, encode_record
from first_use_workload_recipe import RECIPE, catalog, recipe_digest, scenario_steps
from first_use_workload_records import (
    decode_index, decode_intent, decode_observation, decode_verdict, encode_index,
    encode_observation, index_payload, verdict_payload,
)
from repomap_test_support.first_use_workload_samples import (
    ATTEMPT, SAMPLE_RECIPE, observation, sample_facts, sample_intent,
)


def _category(call: Callable[..., object], *args: Any) -> str:
    with pytest.raises(WorkloadError) as error:
        call(*args)
    return error.value.category


def _text(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


@pytest.fixture(scope="module")
def census() -> Census:
    return load_census()


@pytest.fixture()
def sample(census: Census) -> tuple[bytes, dict[str, Any]]:
    intent = sample_intent(census)
    step = SAMPLE_RECIPE[1]
    return intent, observation(step, intent, sample_facts(census)[step.key])


def test_observation_round_trips_to_identical_canonical_bytes(sample) -> None:
    _intent, payload = sample
    data = encode_observation(payload)
    assert data.endswith(b"\n") and data.count(b"\n") == 1
    assert decode_observation(data) == payload
    assert encode_observation(decode_observation(data)) == data


def test_duplicate_keys_are_malformed() -> None:
    assert _category(decode_record, b'{"a":1,"a":1}\n', 100) == "malformed"


@pytest.mark.parametrize("text", [b'{"a":1.0}\n', b'{"a":1e3}\n', b'{"a":NaN}\n', b'{"a":Infinity}\n'])
def test_floats_and_constants_are_refused(text: bytes) -> None:
    assert _category(decode_record, text, 100) == "malformed"


@pytest.mark.parametrize("text", [b'{"a":-1}\n', ('{"a":%d}\n' % (MAX_COUNTER + 1)).encode()])
def test_integers_outside_counter_range_are_invalid(text: bytes) -> None:
    assert _category(decode_record, text, 100) == "invalid_domain"


def test_booleans_never_stand_in_for_counters(sample) -> None:
    _intent, payload = sample
    for key in ("step", "sub"):
        bad = dict(payload, **{key: True})
        assert _category(decode_observation, _text(bad)) == "invalid_domain"
    spans = dict(payload["spans"], call_ns=False)
    assert _category(decode_observation, _text(dict(payload, spans=spans))) == "invalid_domain"


def test_depth_counts_the_root_as_one() -> None:
    six = {"a": [[[[[1]]]]]}
    assert decode_record(encode_record(six, 200), 200) == six
    seven = {"a": [[[[[[1]]]]]]}
    assert _category(encode_record, seven, 200) == "malformed"
    assert _category(decode_record, b'{"a":[[[[[[1]]]]]]}\n', 200) == "malformed"


def test_encoder_refuses_deep_objects_before_python_recursion_is_exhausted() -> None:
    root: dict[str, Any] = {}
    child = root
    for _ in range(2000):
        nested: dict[str, Any] = {}
        child["a"] = nested
        child = nested
    assert _category(encode_record, root, 200) == "malformed"


def test_encoder_refuses_a_cycle_with_the_closed_depth_category() -> None:
    cycle: list[Any] = []
    cycle.append(cycle)
    assert _category(encode_record, {"a": cycle}, 200) == "malformed"


@pytest.mark.parametrize("text", [
    b'{"b":1,"a":2}\n', b'{"a": 1}\n', b'{"a":1}', b'{"a":1}\n\n', b'{"a":"\\u00e9"}\n',
])
def test_noncanonical_bytes_are_refused(text: bytes) -> None:
    assert _category(decode_record, text, 100) == "not_canonical"


def test_bounds_include_the_final_lf() -> None:
    payload = {"a": "x" * 10}
    data = encode_record(payload, 100)
    assert decode_record(data, len(data)) == payload
    assert _category(decode_record, data, len(data) - 1) == "too_large"
    assert _category(encode_record, payload, len(data) - 1) == "too_large"


def test_encode_refuses_floats_and_negative_counters() -> None:
    assert _category(encode_record, {"a": 1.5}, 100) == "malformed"
    assert _category(encode_record, {"a": -2}, 100) == "invalid_domain"
    assert _category(encode_record, {1: 2}, 100) == "malformed"


def test_observation_closed_key_set_and_domains(sample) -> None:
    _intent, payload = sample
    assert _category(decode_observation, _text({**payload, "extra": 1})) == "malformed"
    missing = {key: value for key, value in payload.items() if key != "cpu"}
    assert _category(decode_observation, _text(missing)) == "malformed"
    for key, value in (("result", "ok"), ("reason", "because"), ("refusal", "any_code"),
                       ("attempt", "ABC"), ("backend", "oracle"), ("action", "deploy")):
        assert _category(decode_observation, _text({**payload, key: value})) == "invalid_domain", key


def test_observation_members_are_sorted_known_and_bounded(sample) -> None:
    _intent, payload = sample
    digest = "c" * 64
    good = [["plans/plan-03-0.json", digest, 10], ["reports/report-03-0.json", digest, 10]]
    assert decode_observation(_text({**payload, "members": good}))["members"] == good
    unsorted = list(reversed(good))
    assert _category(decode_observation, _text({**payload, "members": unsorted})) == "not_canonical"
    escaped = [["reports/../intent.json", digest, 1]]
    assert _category(decode_observation, _text({**payload, "members": escaped})) == "invalid_domain"
    oversize = [["plans/plan-03-0.json", digest, 4098]]
    assert _category(decode_observation, _text({**payload, "members": oversize})) == "invalid_domain"


def test_intent_codec_validates_catalog_and_declared_parent(census) -> None:
    payload = decode_intent(sample_intent(census))
    assert payload["steps"] == [step.catalog_row() for step in SAMPLE_RECIPE]
    bad_row = {**payload, "steps": [["local", "sqlite", 1, 0, "deploy", "pass"]]}
    assert _category(decode_intent, _text(bad_row)) == "invalid_domain"
    assert _category(decode_intent, _text({**payload, "declared_source_parent": "abc"})) == "invalid_domain"
    parent = {**payload, "declared_source_parent": "d" * 40}
    assert decode_intent(_text(parent))["declared_source_parent"] == "d" * 40


def test_index_rows_are_sorted_unique_payload_members() -> None:
    digest = "e" * 64
    rows = [["intent.json", digest, 5], ["observation-01-0.json", digest, 7]]
    data = encode_index(index_payload("local", ATTEMPT, digest, rows))
    assert decode_index(data)["members"] == rows
    assert _category(decode_index, _text({**decode_index(data), "members": rows[::-1]})) == "not_canonical"
    control = [*rows, ["verdict.json", digest, 3]]
    assert _category(decode_index, _text({**decode_index(data), "members": control})) == "invalid_domain"


def test_verdict_categories_are_closed_and_sorted() -> None:
    payload = verdict_payload(scenario="local", attempt=ATTEMPT, intent="f" * 64, outcome="rejected",
                              counts={"pass": 2}, categories=["tampered_member", "missing_step"],
                              index_sha256="0" * 64)
    assert payload["categories"] == ["missing_step", "tampered_member"]
    assert payload["counts"] == {"pass": 2, "expected_refusal": 0, "failure": 0, "skipped": 0,
                                 "unavailable": 0}
    assert decode_verdict(_text(payload)) == payload
    assert _category(decode_verdict, _text({**payload, "categories": ["made_up"]})) == "invalid_domain"
    reversed_payload = {**payload, "categories": ["tampered_member", "missing_step"]}
    assert _category(decode_verdict, _text(reversed_payload)) == "not_canonical"


def test_recipe_has_the_contract_row_counts_and_order() -> None:
    counts = {name: len(scenario_steps(name)) for name in ("local", "server", "mixed")}
    assert counts == {"local": 13, "server": 15, "mixed": 8}
    for name in counts:
        keys = [step.key for step in scenario_steps(name)]
        assert keys == sorted(set(keys))
    assert [step.sub for step in RECIPE if step.sub] == [1, 2]
    assert {step.backend for step in scenario_steps("local")} == {"sqlite"}
    assert {step.backend for step in scenario_steps("server")} == {"postgresql"}
    assert [step.backend for step in scenario_steps("mixed")] == [
        "mixed", "sqlite", "postgresql", "mixed", "mixed", "mixed", "mixed", "mixed",
    ]


def test_only_planned_refusals_carry_an_explicit_limit() -> None:
    limited = [(step.scenario, step.step) for step in RECIPE if step.budget_multiplier is not None]
    assert limited == [("local", 9), ("server", 9)]
    assert all(step.budget_multiplier == 4 for step in RECIPE if step.budget_multiplier)


def test_recipe_digest_binds_every_constant() -> None:
    assert recipe_digest() == recipe_digest(RECIPE)
    changed = (dataclasses.replace(RECIPE[0], aliases=("core",)), *RECIPE[1:])
    assert recipe_digest(changed) != recipe_digest()
    assert len(catalog()) == len(RECIPE) == 36
    assert recipe_module.SERVER_ALIASES == ("core", "companion")
