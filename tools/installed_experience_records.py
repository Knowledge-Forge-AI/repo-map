"""Strict codecs for the installed intent, observation, index, verdict and projection records.

Each codec accepts only its schema's closed keys and domains and re-encodes to
identical canonical bytes, within the tighter installed bounds of contract
section 10.1. Row-level fact rules live in ``installed_experience_validation``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from installed_experience_domains import (
    CATEGORIES, CLEANUP_STATES, ENV_CLASSES, EXPECTATIONS, FACT_KEY, FACT_SOURCES, FAILURE_CODES,
    FAMILIES, INTENT_NAME, MAX_BUNDLE_FILES, MAX_FACTS, MAX_INDEX_BYTES,
    MAX_INTENT_BYTES, MAX_OBSERVATION_BYTES, MAX_OWNER_OBSERVATIONS, MAX_PROJECTION_BYTES,
    MAX_VERDICT_BYTES, OBSERVATION_NAME, ORIGIN_CLASSES, OUTCOMES, OWNERS, SCENARIO_ID,
    SCHEMA_INDEX, SCHEMA_INTENT, SCHEMA_OBSERVATION, SCHEMA_PROJECTION, SCHEMA_VERDICT,
    STDERR_CLASSES, STORAGE_SCENARIO, VERDICT_OUTCOMES,
)
from installed_experience_encoding import (
    closed, decode, encode, is_count, is_hex32, is_hex64, is_scalar, require,
)
from installed_experience_pins import MESSAGE_PATH, MESSAGE_SHA256

INTENT_KEYS = (
    "candidate_census_sha256", "candidate_input_count", "candidate_input_sha256", "env_classes",
    "fixture_census_sha256", "incumbent_wheel_sha256", "inventory_sha256", "message_path",
    "message_sha256", "owner", "platform",
    "projection", "python", "recipe_digest", "scenarios", "schema", "storage_scenario",
    "wheel_bytes", "wheel_member_count", "wheel_sha256",
)
INTENT_SCENARIO_KEYS = ("action", "env_class", "expectation", "expected", "family", "id")
PROJECTION_CONSTANT_KEYS = ("module_sha256", "record_sha256")
OBSERVATION_KEYS = (
    "attempt", "cleanup", "env_class", "exit", "facts", "failure_code", "family", "intent",
    "origin_classes", "outcome", "owner", "projection", "scenario", "schema", "seq",
    "stderr_class",
)
FACT_KEYS = ("source", "value")
PROJECTION_KEYS = (
    "bytecode_omitted", "hashed_count", "license_count", "member_count", "module_sha256",
    "name", "record_sha256", "schema", "source_class", "version",
)
INDEX_KEYS = ("attempt", "intent", "members", "owner", "schema")
VERDICT_KEYS = ("attempt", "categories", "counts", "index_sha256", "intent", "outcome", "owner", "schema")
PLATFORMS = ("aarch64", "arm64", "x86_64", "amd64")


def _text(value: object, limit: int = 64) -> bool:
    return type(value) is str and 0 < len(value) <= limit and value.isprintable()


def decode_intent(data: bytes) -> dict[str, Any]:
    payload = closed(decode(data, MAX_INTENT_BYTES), INTENT_KEYS)
    require(payload["schema"] == SCHEMA_INTENT and payload["owner"] in OWNERS)
    require(payload["storage_scenario"] == STORAGE_SCENARIO[payload["owner"]])
    for key in ("candidate_census_sha256", "candidate_input_sha256", "fixture_census_sha256",
                "inventory_sha256", "recipe_digest", "wheel_sha256"):
        require(is_hex64(payload[key]))
    incumbent = payload["incumbent_wheel_sha256"]
    require(incumbent is None or is_hex64(incumbent))
    require((incumbent is not None) == (payload["owner"] == "migration"))
    require(payload["message_path"] == MESSAGE_PATH and is_hex64(payload["message_sha256"]))
    require(payload["message_sha256"] == MESSAGE_SHA256)
    for key in ("candidate_input_count", "wheel_bytes", "wheel_member_count"):
        require(is_count(payload[key]) and payload[key] > 0)
    projection = closed(payload["projection"], PROJECTION_CONSTANT_KEYS)
    require(all(is_hex64(value) for value in projection.values()))
    require(_text(payload["python"], 16) and payload["platform"] in PLATFORMS)
    classes = payload["env_classes"]
    require(type(classes) is list and all(type(item) is str for item in classes))
    require(classes == sorted(set(classes)))
    require(all(item in ENV_CLASSES for item in classes))
    scenarios = payload["scenarios"]
    require(type(scenarios) is list and 0 < len(scenarios) <= MAX_OWNER_OBSERVATIONS)
    for row in scenarios:
        item = closed(row, INTENT_SCENARIO_KEYS)
        require(type(item["id"]) is str and SCENARIO_ID.fullmatch(item["id"]) is not None)
        require(_text(item["action"], 48) and item["family"] in FAMILIES)
        require(item["env_class"] in ENV_CLASSES and item["expectation"] in EXPECTATIONS)
        expected = item["expected"]
        require(type(expected) is dict and 0 < len(expected) <= MAX_FACTS)
        require(all(FACT_KEY.fullmatch(key) and is_scalar(value) for key, value in expected.items()))
    ids = [row["id"] for row in scenarios]
    require(len(ids) == len(set(ids)), "duplicate")
    return payload


def encode_intent(payload: Mapping[str, Any]) -> bytes:
    data = encode(payload, MAX_INTENT_BYTES)
    decode_intent(data)
    return data


def check_projection(raw: object) -> dict[str, Any]:
    record = closed(raw, PROJECTION_KEYS)
    require(record["schema"] == SCHEMA_PROJECTION and record["source_class"] == "sdk-installed-record")
    require(_text(record["name"]) and _text(record["version"], 32))
    for key in ("bytecode_omitted", "hashed_count", "license_count", "member_count"):
        require(is_count(record[key]))
    require(record["hashed_count"] <= record["member_count"] and record["license_count"] >= 1)
    require(is_hex64(record["module_sha256"]) and is_hex64(record["record_sha256"]))
    require(len(encode(record, MAX_PROJECTION_BYTES)) <= MAX_PROJECTION_BYTES, "bound-exceeded")
    return record


def _facts(raw: object) -> dict[str, Any]:
    require(type(raw) is dict and len(raw) <= MAX_FACTS)
    assert isinstance(raw, dict)
    for key, item in raw.items():
        require(FACT_KEY.fullmatch(key) is not None)
        fact = closed(item, FACT_KEYS)
        require(is_scalar(fact["value"]) and fact["source"] in FACT_SOURCES)
    return raw


def decode_observation(data: bytes) -> dict[str, Any]:
    payload = closed(decode(data, MAX_OBSERVATION_BYTES), OBSERVATION_KEYS)
    require(payload["schema"] == SCHEMA_OBSERVATION and payload["owner"] in OWNERS)
    require(is_hex32(payload["attempt"]) and is_hex64(payload["intent"]))
    require(type(payload["scenario"]) is str and SCENARIO_ID.fullmatch(payload["scenario"]) is not None)
    require(is_count(payload["seq"]) and 1 <= payload["seq"] <= MAX_OWNER_OBSERVATIONS)
    require(payload["env_class"] in ENV_CLASSES and payload["family"] in FAMILIES)
    require(payload["exit"] is None or is_count(payload["exit"]))
    require(payload["outcome"] in OUTCOMES and payload["stderr_class"] in STDERR_CLASSES)
    require(payload["cleanup"] in CLEANUP_STATES)
    failure = payload["failure_code"]
    require(failure is None or failure in FAILURE_CODES)
    require((failure is None) == (payload["outcome"] in ("passed", "expected-refusal", "not-reached")))
    _facts(payload["facts"])
    origins = payload["origin_classes"]
    if origins is not None:
        require(type(origins) is dict and set(origins) <= set(ORIGIN_CLASSES))
        require(all(is_count(value) for value in origins.values()))
    if payload["projection"] is not None:
        check_projection(payload["projection"])
    return payload


def encode_observation(payload: Mapping[str, Any]) -> bytes:
    data = encode(payload, MAX_OBSERVATION_BYTES)
    decode_observation(data)
    return data


def _member(name: object) -> bool:
    return type(name) is str and (name == INTENT_NAME or OBSERVATION_NAME.fullmatch(name) is not None)


def decode_index(data: bytes) -> dict[str, Any]:
    payload = closed(decode(data, MAX_INDEX_BYTES), INDEX_KEYS)
    require(payload["schema"] == SCHEMA_INDEX and payload["owner"] in OWNERS)
    require(is_hex32(payload["attempt"]) and is_hex64(payload["intent"]))
    rows = payload["members"]
    require(type(rows) is list and 0 < len(rows) <= MAX_BUNDLE_FILES - 2, "bound-exceeded")
    for row in rows:
        require(type(row) is list and len(row) == 3)
        require(_member(row[0]) and is_hex64(row[1]) and is_count(row[2]))
    names = [row[0] for row in rows]
    require(names == sorted(set(names)), "duplicate")
    return payload


def index_payload(owner: str, attempt: str, intent: str, members: Sequence[Sequence[Any]]) -> dict[str, Any]:
    return {"schema": SCHEMA_INDEX, "owner": owner, "attempt": attempt, "intent": intent,
            "members": sorted([list(row) for row in members])}


def encode_index(payload: Mapping[str, Any]) -> bytes:
    data = encode(payload, MAX_INDEX_BYTES)
    decode_index(data)
    return data


def verdict_payload(
    *, owner: str | None, attempt: str | None, intent: str | None, outcome: str,
    counts: Mapping[str, int], categories: Sequence[str], index_sha256: str | None,
) -> dict[str, Any]:
    return {"schema": SCHEMA_VERDICT, "owner": owner, "attempt": attempt, "intent": intent,
            "outcome": outcome, "counts": {key: counts.get(key, 0) for key in OUTCOMES},
            "categories": sorted(set(categories)), "index_sha256": index_sha256}


def decode_verdict(data: bytes) -> dict[str, Any]:
    payload = closed(decode(data, MAX_VERDICT_BYTES), VERDICT_KEYS)
    require(payload["schema"] == SCHEMA_VERDICT and payload["outcome"] in VERDICT_OUTCOMES)
    require(payload["owner"] is None or payload["owner"] in OWNERS)
    require(payload["attempt"] is None or is_hex32(payload["attempt"]))
    require(payload["intent"] is None or is_hex64(payload["intent"]))
    require(payload["index_sha256"] is None or is_hex64(payload["index_sha256"]))
    counts = closed(payload["counts"], OUTCOMES)
    require(all(is_count(value) for value in counts.values()))
    categories = payload["categories"]
    require(type(categories) is list and all(item in CATEGORIES for item in categories))
    require(categories == sorted(set(categories)))
    return payload


def encode_verdict(payload: Mapping[str, Any]) -> bytes:
    data = encode(payload, MAX_VERDICT_BYTES)
    decode_verdict(data)
    return data


__all__ = [
    "FACT_KEYS", "INDEX_KEYS", "INTENT_KEYS", "INTENT_SCENARIO_KEYS", "OBSERVATION_KEYS",
    "PROJECTION_KEYS", "VERDICT_KEYS", "check_projection", "decode_index", "decode_intent",
    "decode_observation", "decode_verdict", "encode_index", "encode_intent",
    "encode_observation", "encode_verdict", "index_payload", "verdict_payload",
]
