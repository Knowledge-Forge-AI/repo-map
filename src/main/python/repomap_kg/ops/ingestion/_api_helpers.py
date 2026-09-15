"""Helper utilities and validation for documented REST API ingestion."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from repomap_kg.ops.ingestion.api_records import (
    ApiEndpointConfig,
    ApiPlanManifest,
    ApiPolicyError,
    ApiRequestPlan,
    ApiSourceConfig,
)

ALLOWED_SOURCE_TYPES = frozenset({"api.rest"})
ALLOWED_API_SOURCE_CLASSES = frozenset({"api.custom_documented_api"})
ALLOWED_POLICY_STATUSES = frozenset({"allowed", "allowed_with_limits"})
ALLOWED_CREDENTIAL_REF_PREFIXES = (
    "local_secret_ref:",
    "os_keychain_ref:",
    "env_ref:",
)
SECRET_MARKERS = frozenset(
    {
        "token",
        "secret",
        "password",
        "passwd",
        "api_key",
        "apikey",
        "credential",
        "private_key",
        "access_key",
        "refresh_token",
        "bearer",
        "auth",
        "client_secret",
        "secret_key",
        "access_token",
        "id_token",
        "session",
        "cookie",
        "connection_string",
        "authorization",
        "set-cookie",
    }
)


def parse_endpoint(payload: Mapping[str, Any]) -> ApiEndpointConfig:
    name = required_string(payload, "name")
    method = required_string(payload, "method").upper()
    path = required_string(payload, "path")
    purpose = required_string(payload, "purpose")
    response_type = required_string(payload, "response_type")
    max_page_size = required_positive_int(payload, "max_page_size")
    pagination = required_string(payload, "pagination")
    downstream_route = required_string(payload, "downstream_route")
    fixture_response_path = required_string(payload, "fixture_response_path")
    if method != "GET":
        raise ApiPolicyError("API1 only allows GET endpoints")
    if not path.startswith("/") or "://" in path:
        raise ApiPolicyError("endpoint path must be an allowlisted relative API path")
    if pagination != "none":
        raise ApiPolicyError("API1 only supports pagination = none")
    if downstream_route != "config":
        raise ApiPolicyError("API1 only supports downstream_route = config")
    validate_fixture_response_path(fixture_response_path)
    return ApiEndpointConfig(
        name=name,
        method=method,
        path=path,
        purpose=purpose,
        response_type=response_type,
        max_page_size=max_page_size,
        pagination=pagination,
        downstream_route=downstream_route,
        fixture_response_path=fixture_response_path,
    )


def required_endpoint_list(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    value = payload.get("endpoints")
    if not isinstance(value, list) or not value:
        raise ApiPolicyError("at least one [[endpoints]] entry is required")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ApiPolicyError("[[endpoints]] entries must be objects")
        result.append(item)
    return tuple(result)


def validate_credential_ref(value: str) -> None:
    if not any(value.startswith(prefix) for prefix in ALLOWED_CREDENTIAL_REF_PREFIXES):
        raise ApiPolicyError("credentials_ref must use an allowed opaque reference shape")
    _, _, name = value.partition(":")
    if not name.strip():
        raise ApiPolicyError("credentials_ref must include a non-empty opaque name")


def validate_fixture_response_path(value: str) -> None:
    path = Path(value)
    if path.is_absolute() or "://" in value:
        raise ApiPolicyError("fixture_response_path must be a local relative path")
    if ".." in path.parts:
        raise ApiPolicyError("fixture_response_path must not escape the config root")


def resolve_fixture_response_path(config_path: Path, configured: str) -> Path:
    path = (config_path.parent / configured).resolve()
    ensure_contained(path, config_path.parent.resolve(), "fixture response path")
    return path


def endpoint_by_name(config: ApiSourceConfig, name: str) -> ApiEndpointConfig:
    for endpoint in config.endpoints:
        if endpoint.name == name:
            return endpoint
    raise ApiPolicyError(f"request endpoint is not allowlisted: {name}")


def parse_json_response(body: bytes, endpoint_name: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ApiPolicyError(
            f"endpoint {endpoint_name} did not return safe JSON: {error}"
        ) from error


def count_response_items(payload: Any) -> int:
    if isinstance(payload, Mapping):
        items = payload.get("items")
        if isinstance(items, list):
            return len(items)
        return 1
    if isinstance(payload, list):
        return len(payload)
    return 1


def redact_value(value: Any, *, key_name: str | None = None) -> Any:
    if key_name and is_secret_key(key_name):
        return {
            "redacted": True,
            "redaction_reason": "secret-prone-key",
            "literal_type": literal_type(value),
        }
    if isinstance(value, Mapping):
        return {str(key): redact_value(item, key_name=str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def is_secret_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    return any(marker in normalized for marker in SECRET_MARKERS)


def literal_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return "unknown"


def deterministic_api_run_id(
    config: ApiSourceConfig,
    requests: Sequence[ApiRequestPlan],
) -> str:
    payload = {
        "source_id": config.source_id,
        "source_type": config.source_type,
        "api_source_class": config.api_source_class,
        "provider_name": config.provider_name,
        "provider_product": config.provider_product,
        "policy_status": config.policy_status,
        "limits": {
            "max_requests_per_run": config.max_requests_per_run,
            "max_requests_per_minute": config.max_requests_per_minute,
            "max_concurrent_requests": config.max_concurrent_requests,
            "max_bytes_per_run": config.max_bytes_per_run,
            "max_items_per_run": config.max_items_per_run,
            "max_retries": config.max_retries,
        },
        "retention": {
            "policy": config.retention_policy,
            "raw_response_retention": config.raw_response_retention,
            "redacted_response_retention": config.redacted_response_retention,
        },
        "redaction": {
            "profile": config.redaction_profile,
            "sensitivity": config.sensitivity,
        },
        "requests": [request.to_jsonable() for request in requests],
    }
    return "api-" + sha256_json(payload)[:24]


def manifest_digest(manifest: ApiPlanManifest) -> str:
    payload = manifest.to_jsonable()
    payload["manifest_sha256"] = ""
    return sha256_json(payload)


def safe_artifact_name(endpoint_name: str, response_type: str) -> str:
    suffix = ".json" if response_type == "application/json" else ".jsonl"
    safe = "".join(
        character if character.isalnum() or character in ("-", "_") else "-"
        for character in endpoint_name
    ).strip("-")
    return f"{safe or 'response'}{suffix}"


def required_table(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ApiPolicyError(f"{key} table is required")
    return value


def required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApiPolicyError(f"{key} is required")
    return value.strip()


def required_positive_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ApiPolicyError(f"{key} must be a positive integer")
    return value


def required_nonnegative_int(payload: Mapping[str, Any], key: str) -> int:
    if key not in payload:
        raise ApiPolicyError(f"{key} is required")
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ApiPolicyError(f"{key} must be a non-negative integer")
    return value


def required_bool(payload: Mapping[str, Any], key: str) -> bool:
    if key not in payload:
        raise ApiPolicyError(f"{key} is required")
    value = payload[key]
    if not isinstance(value, bool):
        raise ApiPolicyError(f"{key} must be a boolean")
    return value


def string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ApiPolicyError("consent list fields must be arrays")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ApiPolicyError("consent list values must be non-empty strings")
        result.append(item.strip())
    return tuple(result)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: object) -> str:
    return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))


def ensure_contained(path: Path, root: Path, name: str) -> None:
    if not is_contained(path, root):
        raise ApiPolicyError(f"{name} escapes repository root")


def is_contained(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
