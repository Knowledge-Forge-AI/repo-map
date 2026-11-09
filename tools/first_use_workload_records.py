"""Strict codecs for the intent, observation, index and verdict records.

Each codec accepts only its schema's closed key set and value domains and
re-encodes to identical bytes. Facts are validated against their recipe row by
``first_use_workload_validation``; this module checks the record envelope.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from first_use_workload_domains import (
    ACTIONS, BACKENDS, CATEGORIES, EXPECTATIONS, HEX32, HEX40, INTENT_NAME, MAX_BUNDLE_MEMBERS,
    MAX_CONTROL_BYTES, MAX_OBSERVATION_BYTES, MAX_PLAN_MEMBER_BYTES, MAX_REPORT_MEMBER_BYTES,
    OBSERVATION_NAME, OUTCOMES, PLAN_NAME, PLANS_DIR, REASONS, REFUSAL_CODES, REPORT_NAME,
    REPORTS_DIR, RESULTS, SCENARIOS, SCHEMA_INDEX, SCHEMA_INTENT, SCHEMA_OBSERVATION,
    SCHEMA_VERDICT, WorkloadError,
)
from first_use_workload_encoding import (
    closed, decode_record, encode_record, is_count, is_hex64, require,
)
from first_use_workload_recipe_shapes import Recipe

INTENT_KEYS = (
    "candidate_census", "census_digest", "declared_source_parent", "fixture_digest",
    "product_digest", "recipe_digest", "schema", "steps",
)
OBSERVATION_KEYS = (
    "action", "attempt", "backend", "cpu", "expectation", "facts", "intent", "members",
    "reason", "refusal", "result", "scenario", "schema", "spans", "step", "sub",
)
SPAN_KEYS = ("call_ns", "cleanup_ns", "observe_ns", "prepare_ns")
CPU_KEYS = ("parent_process_ns", "waited_descendants_ns")
INDEX_KEYS = ("attempt", "intent", "members", "scenario", "schema")
VERDICT_KEYS = (
    "attempt", "categories", "counts", "index_sha256", "intent", "outcome", "scenario", "schema",
)
IDENTITY_FIELDS = ("candidate_census", "product_digest")
MemberRow = list[Any]


def intent_payload(
    *, recipe: Recipe, recipe_digest: str, census_digest: str, fixture_digest: str,
    product_digest: str, candidate_census: str, declared_source_parent: str | None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_INTENT,
        "recipe_digest": recipe_digest,
        "census_digest": census_digest,
        "fixture_digest": fixture_digest,
        "product_digest": product_digest,
        "candidate_census": candidate_census,
        "declared_source_parent": declared_source_parent,
        "steps": [item.catalog_row() for item in recipe],
    }


def _catalog_row(raw: object) -> None:
    require(type(raw) is list and len(raw) == 6, "malformed")
    assert isinstance(raw, list)
    scenario, backend, step, sub, action, expectation = raw
    require(scenario in SCENARIOS and backend in BACKENDS and action in ACTIONS)
    require(is_count(step) and 1 <= step <= 99 and is_count(sub) and sub <= 9)
    require(expectation in EXPECTATIONS)


def decode_intent(data: bytes) -> dict[str, Any]:
    payload = closed(decode_record(data, MAX_CONTROL_BYTES), INTENT_KEYS)
    require(payload["schema"] == SCHEMA_INTENT)
    for key in ("candidate_census", "census_digest", "fixture_digest", "product_digest", "recipe_digest"):
        require(is_hex64(payload[key]))
    parent = payload["declared_source_parent"]
    require(parent is None or (type(parent) is str and HEX40.fullmatch(parent) is not None))
    require(type(payload["steps"]) is list and bool(payload["steps"]), "malformed")
    for row in payload["steps"]:
        _catalog_row(row)
    return payload


def encode_intent(payload: Mapping[str, Any]) -> bytes:
    data = encode_record(dict(payload), MAX_CONTROL_BYTES)
    decode_intent(data)
    return data


def member_limit(name: str) -> int:
    if name == INTENT_NAME or name in ("index.json", "verdict.json"):
        return MAX_CONTROL_BYTES
    if OBSERVATION_NAME.fullmatch(name):
        return MAX_OBSERVATION_BYTES
    head, _sep, leaf = name.partition("/")
    if head == REPORTS_DIR and REPORT_NAME.fullmatch(leaf):
        return MAX_REPORT_MEMBER_BYTES
    if head == PLANS_DIR and PLAN_NAME.fullmatch(leaf):
        return MAX_PLAN_MEMBER_BYTES
    raise WorkloadError("unsafe_input")


def _member_rows(raw: object, *, allow: Any) -> list[MemberRow]:
    require(type(raw) is list, "malformed")
    assert isinstance(raw, list)
    for row in raw:
        require(type(row) is list and len(row) == 3, "malformed")
        name, digest, size = row
        require(type(name) is str and allow(name))
        require(is_hex64(digest) and is_count(size) and size <= member_limit(name))
    names = [row[0] for row in raw]
    require(names == sorted(set(names)), "not_canonical")
    return raw


def _is_evidence_member(name: str) -> bool:
    head, _sep, leaf = name.partition("/")
    return (head == REPORTS_DIR and REPORT_NAME.fullmatch(leaf) is not None) or (
        head == PLANS_DIR and PLAN_NAME.fullmatch(leaf) is not None
    )


def _nullable_count(raw: object) -> bool:
    return raw is None or is_count(raw)


def decode_observation(data: bytes) -> dict[str, Any]:
    payload = closed(decode_record(data, MAX_OBSERVATION_BYTES), OBSERVATION_KEYS)
    require(payload["schema"] == SCHEMA_OBSERVATION)
    require(type(payload["attempt"]) is str and HEX32.fullmatch(payload["attempt"]) is not None)
    require(is_hex64(payload["intent"]))
    require(payload["scenario"] in SCENARIOS and payload["backend"] in BACKENDS)
    require(payload["action"] in ACTIONS and payload["expectation"] in EXPECTATIONS)
    require(is_count(payload["step"]) and 1 <= payload["step"] <= 99)
    require(is_count(payload["sub"]) and payload["sub"] <= 9)
    require(payload["result"] in RESULTS)
    require(payload["refusal"] is None or payload["refusal"] in REFUSAL_CODES)
    require(payload["reason"] is None or payload["reason"] in REASONS)
    spans = closed(payload["spans"], SPAN_KEYS)
    cpu = closed(payload["cpu"], CPU_KEYS)
    require(all(_nullable_count(value) for value in (*spans.values(), *cpu.values())))
    _member_rows(payload["members"], allow=_is_evidence_member)
    facts = payload["facts"]
    require(facts is None or type(facts) is dict, "malformed")
    return payload


def encode_observation(payload: Mapping[str, Any]) -> bytes:
    data = encode_record(dict(payload), MAX_OBSERVATION_BYTES)
    decode_observation(data)
    return data


def _payload_member(name: str) -> bool:
    return name == INTENT_NAME or OBSERVATION_NAME.fullmatch(name) is not None or _is_evidence_member(name)


def decode_index(data: bytes) -> dict[str, Any]:
    payload = closed(decode_record(data, MAX_CONTROL_BYTES), INDEX_KEYS)
    require(payload["schema"] == SCHEMA_INDEX and payload["scenario"] in SCENARIOS)
    require(type(payload["attempt"]) is str and HEX32.fullmatch(payload["attempt"]) is not None)
    require(is_hex64(payload["intent"]))
    rows = _member_rows(payload["members"], allow=_payload_member)
    require(len(rows) <= MAX_BUNDLE_MEMBERS - 2, "unbounded")
    return payload


def index_payload(scenario: str, attempt: str, intent: str, members: Sequence[MemberRow]) -> dict[str, Any]:
    return {
        "schema": SCHEMA_INDEX, "scenario": scenario, "attempt": attempt, "intent": intent,
        "members": sorted(list(row) for row in members),
    }


def encode_index(payload: Mapping[str, Any]) -> bytes:
    data = encode_record(dict(payload), MAX_CONTROL_BYTES)
    decode_index(data)
    return data


def verdict_payload(
    *, scenario: str | None, attempt: str | None, intent: str | None, outcome: str,
    counts: Mapping[str, int], categories: Sequence[str], index_sha256: str | None,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERDICT, "scenario": scenario, "attempt": attempt, "intent": intent,
        "outcome": outcome, "counts": {key: counts.get(key, 0) for key in RESULTS},
        "categories": sorted(set(categories)), "index_sha256": index_sha256,
    }


def decode_verdict(data: bytes) -> dict[str, Any]:
    payload = closed(decode_record(data, MAX_CONTROL_BYTES), VERDICT_KEYS)
    require(payload["schema"] == SCHEMA_VERDICT and payload["outcome"] in OUTCOMES)
    require(payload["scenario"] is None or payload["scenario"] in SCENARIOS)
    attempt = payload["attempt"]
    require(attempt is None or (type(attempt) is str and HEX32.fullmatch(attempt) is not None))
    require(payload["intent"] is None or is_hex64(payload["intent"]))
    require(payload["index_sha256"] is None or is_hex64(payload["index_sha256"]))
    counts = closed(payload["counts"], RESULTS)
    require(all(is_count(value) for value in counts.values()))
    categories = payload["categories"]
    require(type(categories) is list and all(item in CATEGORIES for item in categories))
    require(categories == sorted(set(categories)), "not_canonical")
    return payload


def encode_verdict(payload: Mapping[str, Any]) -> bytes:
    data = encode_record(dict(payload), MAX_CONTROL_BYTES)
    decode_verdict(data)
    return data


__all__ = [
    "CPU_KEYS", "IDENTITY_FIELDS", "INDEX_KEYS", "INTENT_KEYS", "OBSERVATION_KEYS", "SPAN_KEYS",
    "VERDICT_KEYS", "decode_index", "decode_intent", "decode_observation", "decode_verdict",
    "encode_index", "encode_intent", "encode_observation", "encode_verdict", "index_payload",
    "intent_payload", "member_limit", "verdict_payload",
]
