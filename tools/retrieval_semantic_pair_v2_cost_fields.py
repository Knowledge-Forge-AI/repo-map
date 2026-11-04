"""Closed numeric and byte-field helpers for the W5 V2 cost projection."""

from __future__ import annotations

from collections.abc import Mapping
import math

from retrieval_semantic_pair_artifacts import refuse


GENERATION_COST = frozenset(
    {
        "preparation_ns", "installation_ns", "request_ns", "component_ns", "import_ns",
        "index_ns", "ann_cleanup_ns", "query_ns", "cleanup_ns", "failures", "total_ns",
    }
)
COMPONENT_COST = frozenset(
    {
        "inference_seconds", "input_bytes", "input_records", "load_seconds", "model_input_bytes",
        "overflow_chunks", "token_count_before_limit", "token_count_used", "total_seconds",
        "truncated_records",
    }
)
OBSERVATION_BYTES = frozenset(
    {
        "agent_completion_cost_usd", "artifact_store_bytes_read", "internal_source_io_bytes",
        "model_tokens_spent", "observed_output_payload_bytes",
    }
)
RESULT_BYTES = frozenset(
    {
        "schema_version", "correspondence_verification_ns", "correspondence_verification_bytes_read",
        "decoded_candidate_count",
        "direct_selected_text_bytes", "native_process_stdout_cap_bytes", "observed_output_payload_bytes",
        "raw_process_stdout_bytes", "returned_hit_count", "serialized_envelope_bytes",
    }
)
CORRESPONDENCE_COST = frozenset(
    {
        "correspondence_verification_ns", "correspondence_verification_bytes_read",
        "correspondence_failures", "known_artifact_bytes_read", "known_materialized_bytes_read",
    }
)
GENERATION_INTEGER = GENERATION_COST
COMPONENT_INTEGER = COMPONENT_COST - frozenset(
    {"inference_seconds", "load_seconds", "total_seconds"}
)
OBSERVATION_INTEGER = OBSERVATION_BYTES - frozenset({"agent_completion_cost_usd"})
RESULT_INTEGER = RESULT_BYTES - frozenset({"schema_version"})
CORRESPONDENCE_INTEGER = CORRESPONDENCE_COST


def mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise refuse(code)
    return value


def number(value: object, code: str, *, integer: bool = False) -> int | float | None:
    if value is None:
        return None
    if integer:
        if type(value) is not int or value < 0:
            raise refuse(code)
        return value
    if type(value) is bool:
        raise refuse(code)
    if not isinstance(value, (int, float)):
        raise refuse(code)
    if isinstance(value, float) and not math.isfinite(value):
        raise refuse(code)
    if value < 0:
        raise refuse(code)
    return value


def byte_value(
    value: object, code: str, *, integer: bool = False, schema: bool = False
) -> int | float | str | None:
    if schema:
        if type(value) is not str or value != "cloe-w5-byte-accounting-v1":
            raise refuse(code)
        return value
    return number(value, code, integer=integer)


def byte_map(
    value: object, fields: frozenset[str], integer_fields: frozenset[str], code: str
) -> dict[str, object] | None:
    if value is None:
        return None
    source = mapping(value, code)
    if any(key not in fields for key in source):
        raise refuse(code)
    return {
        key: byte_value(
            source[key], code, integer=key in integer_fields, schema=key == "schema_version"
        )
        for key in sorted(source)
    }


def numeric_map(
    value: object, fields: frozenset[str], code: str, integer_fields: frozenset[str]
) -> dict[str, object] | None:
    if value is None:
        return None
    source = mapping(value, code)
    if any(key not in fields for key in source):
        raise refuse(code)
    return {
        key: number(source[key], code, integer=key in integer_fields)
        for key in sorted(source)
    }


def validate_numeric_map(
    value: object, fields: frozenset[str], code: str, integer_fields: frozenset[str]
) -> None:
    if value is None:
        return
    source = mapping(value, code)
    if any(key not in fields for key in source):
        raise refuse(code)
    for key, item in source.items():
        number(item, code, integer=key in integer_fields)


def validate_byte_map(
    value: object, fields: frozenset[str], integer_fields: frozenset[str], code: str
) -> None:
    if value is None:
        return
    source = mapping(value, code)
    if any(key not in fields for key in source):
        raise refuse(code)
    for key, item in source.items():
        byte_value(item, code, integer=key in integer_fields, schema=key == "schema_version")


__all__ = [
    "COMPONENT_COST", "COMPONENT_INTEGER", "CORRESPONDENCE_COST", "CORRESPONDENCE_INTEGER",
    "GENERATION_COST", "GENERATION_INTEGER", "OBSERVATION_BYTES", "OBSERVATION_INTEGER",
    "RESULT_BYTES", "RESULT_INTEGER", "byte_map", "byte_value", "mapping", "number", "numeric_map",
    "validate_byte_map", "validate_numeric_map",
]
