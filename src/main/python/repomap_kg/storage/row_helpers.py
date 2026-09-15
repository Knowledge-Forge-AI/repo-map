"""Pure storage row payload, metadata, hash, and JSON helpers."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.errors import StorageSchemaError

__all__ = (
    "raw_observation_payload_hash",
    "identity_metadata_hash",
    "optional_manifest_text",
    "manifest_int",
    "manifest_counter",
    "manifest_list",
    "payload_text",
    "payload_string",
    "payload_bool",
    "payload_optional_bool",
    "payload_string_tuple",
    "payload_json_object",
    "payload_count_map",
    "payload_required_count_map",
    "payload_required_bool_map",
    "payload_int",
    "payload_optional_int",
    "payload_optional_text",
    "clean_yaml_value",
    "metadata_text",
    "metadata_bool",
    "optional_text",
    "sha256_text",
    "canonical_json_text",
    "canonical_json_value",
)


def raw_observation_payload_hash(observation: RawObservation) -> str:
    return sha256_text(canonical_json_text(observation.to_dict()))


def identity_metadata_hash(metadata: Mapping[str, Any]) -> str:
    return sha256_text(canonical_json_text(metadata))


def optional_manifest_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def manifest_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key, 0)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def manifest_counter(value: Any) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not isinstance(value, Mapping):
        return counts
    for key, count in value.items():
        if not isinstance(key, str) or not key:
            continue
        try:
            normalized_count = int(count)
        except (TypeError, ValueError):
            continue
        if normalized_count > 0:
            counts[key] += normalized_count
    return counts


def manifest_list(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def payload_text(
    payload: dict[str, Any], key: str, *, label: str = "file record"
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return value


def payload_string(
    payload: dict[str, Any], key: str, *, label: str = "file record"
) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return value


def payload_bool(
    payload: dict[str, Any], key: str, *, label: str = "file record"
) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return value


def payload_optional_bool(
    payload: dict[str, Any], key: str, *, label: str = "file record"
) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return value


def payload_string_tuple(
    payload: dict[str, Any], key: str, *, label: str
) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    if any(not isinstance(item, str) for item in value):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return tuple(value)


def payload_json_object(
    payload: dict[str, Any], key: str, *, label: str
) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    normalized = canonical_json_value(value)
    if not isinstance(normalized, dict):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return normalized


def payload_count_map(
    payload: dict[str, Any], key: str, *, label: str
) -> dict[str, int]:
    value = payload_json_object(payload, key, label=label)
    counts: dict[str, int] = {}
    for count_key, count in value.items():
        if not isinstance(count_key, str) or not count_key:
            raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
        try:
            counts[count_key] = int(count)
        except (TypeError, ValueError) as error:
            raise StorageSchemaError(
                f"psql returned a malformed {label}: {key}"
            ) from error
    return dict(sorted(counts.items()))


def payload_required_count_map(
    payload: dict[str, Any],
    key: str,
    required_keys: Sequence[str],
    *,
    label: str,
) -> dict[str, int]:
    counts = payload_count_map(payload, key, label=label)
    missing_keys = [
        required_key for required_key in required_keys if required_key not in counts
    ]
    if missing_keys:
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return {required_key: counts[required_key] for required_key in required_keys}


def payload_required_bool_map(
    payload: dict[str, Any],
    key: str,
    required_keys: Sequence[str],
    *,
    label: str,
) -> dict[str, bool]:
    value = payload_json_object(payload, key, label=label)
    result: dict[str, bool] = {}
    for required_key in required_keys:
        item = value.get(required_key)
        if not isinstance(item, bool):
            raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
        result[required_key] = item
    return result


def payload_int(payload: dict[str, Any], key: str, *, label: str) -> int:
    value = payload.get(key)
    if value is None:
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}") from error


def payload_optional_int(
    payload: dict[str, Any], key: str, *, label: str
) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}") from error


def payload_optional_text(
    payload: dict[str, Any], key: str, *, label: str
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return value


def clean_yaml_value(value: str) -> str:
    return value.strip().strip("'\"")


def metadata_text(metadata: dict[str, Any], key: str, default: str) -> str:
    value = metadata.get(key, default)
    if not isinstance(value, str) or not value:
        return default
    return value


def metadata_bool(metadata: dict[str, Any], key: str) -> bool:
    value = metadata.get(key, False)
    return value if isinstance(value, bool) else False


def optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json_text(value: Any) -> str:
    return json.dumps(
        canonical_json_value(value),
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): canonical_json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, tuple | list):
        return [canonical_json_value(item) for item in value]
    return value
