"""Pure documented-API plan, redaction, and endpoint-policy contracts."""

from dataclasses import replace
from pathlib import Path
import json

import pytest

from repomap_kg.ops.ingestion.api import (
    ApiPolicyError, ApiSourceConfig, build_api_plan, count_response_items,
    parse_endpoint, parse_json_response, redact_value,
)


def _endpoint_payload():
    return {
        "name": "items", "method": "get", "path": "/v1/items",
        "purpose": "Read fixture metadata", "response_type": "application/json",
        "max_page_size": 10, "pagination": "none", "downstream_route": "config",
        "fixture_response_path": "responses/items.json",
    }


def _config():
    return ApiSourceConfig(
        config_path=Path("fixture/api.toml"), source_id="fixture-api",
        source_type="api.rest", api_source_class="api.custom_documented_api",
        provider_name="Fixture", provider_product="Metadata", policy_status="allowed",
        read_only=True, mutation_allowed=False, credentials_ref="env_ref:FIXTURE_API",
        consent_ref="local_consent_ref:fixture", authorized_operations=("read",),
        authorized_data_classes=("metadata",), consent_revoked=False,
        consent_mutation_allowed=False, max_requests_per_run=2,
        max_requests_per_minute=10, max_concurrent_requests=1,
        max_bytes_per_run=1024, max_items_per_run=10, max_retries=0,
        retention_policy="local_user_controlled", raw_response_retention="minimized",
        redacted_response_retention="retain", redaction_profile="strict",
        sensitivity="private", endpoints=(parse_endpoint(_endpoint_payload()),),
    )


def test_plan_identity_excludes_physical_paths_and_opaque_credentials():
    config = _config()
    first = build_api_plan(config)
    relocated = replace(
        config, config_path=Path("relocated/api.toml"), credentials_ref="os_keychain_ref:other",
        endpoints=(replace(config.endpoints[0], fixture_response_path="relocated/items.json"),),
    )
    assert build_api_plan(relocated) == first
    payload = first.to_jsonable()
    assert first.request_count == 1 and first.requests[0].method == "GET"
    assert first.requests[0].path == "/v1/items"
    assert all(payload[name] is True for name in (
        "no_network", "no_mutation", "no_credentials_resolved", "no_scheduler",
    ))
    serialized = json.dumps(payload)
    assert "FIXTURE_API" not in serialized and "api.toml" not in serialized
    assert len(first.manifest_sha256) == 64


@pytest.mark.parametrize("field,value", [
    ("max_bytes_per_run", 2048), ("max_items_per_run", 11), ("max_retries", 1),
    ("redaction_profile", "metadata"), ("raw_response_retention", "discard"),
    ("redacted_response_retention", "discard"),
])
def test_plan_identity_changes_with_acquisition_and_retention_policy(field, value):
    config = _config()
    original = build_api_plan(config)
    changed = build_api_plan(replace(config, **{field: value}))
    assert changed.api_run_id != original.api_run_id
    assert changed.api_manifest_id != original.api_manifest_id
    assert changed.manifest_sha256 != original.manifest_sha256
    assert changed.requests == original.requests


@pytest.mark.parametrize("field,value,message", [
    ("method", "POST", "only allows GET"),
    ("path", "v1/items", "relative API path"),
    ("path", "/https://example.invalid/items", "relative API path"),
    ("pagination", "cursor", "pagination = none"),
    ("downstream_route", "execute", "downstream_route = config"),
    ("fixture_response_path", "/responses/items.json", "local relative path"),
    ("fixture_response_path", "https://example.invalid/items", "local relative path"),
    ("fixture_response_path", "../items.json", "must not escape"),
    ("max_page_size", True, "positive integer"),
    ("max_page_size", 0, "positive integer"),
    ("name", " ", "name is required"),
])
def test_endpoint_policy_refuses_mutation_remote_fixtures_and_coerced_limits(field, value, message):
    payload = _endpoint_payload()
    payload[field] = value
    with pytest.raises(ApiPolicyError, match=message):
        parse_endpoint(payload)


@pytest.mark.parametrize("value,literal_type", [
    (None, "null"), (False, "boolean"), (3, "number"), (1.5, "number"),
    ("fixture-value", "string"), (["fixture-value"], "array"),
    ({"nested": "fixture-value"}, "object"),
])
def test_nested_api_redaction_keeps_shape_and_suppresses_secret_values(value, literal_type):
    original = {"items": [{"id": "public-item", "Access-Token": value}], "count": 1}
    snapshot = json.loads(json.dumps(original))
    redacted = redact_value(original)
    assert redacted == {
        "items": [{"id": "public-item", "Access-Token": {
            "redacted": True, "redaction_reason": "secret-prone-key",
            "literal_type": literal_type,
        }}], "count": 1,
    }
    assert original == snapshot
    assert "fixture-value" not in json.dumps(redacted)


@pytest.mark.parametrize("body,count", [
    (b'{"items":[{"id":1},{"id":2}]}', 2), (b'[1,2,3]', 3),
    (b'{"items":"single-value"}', 1), (b'null', 1), (b'42', 1),
])
def test_response_count_matches_items_contract_before_redaction(body, count):
    parsed = parse_json_response(body, "items")
    assert count_response_items(parsed) == count


@pytest.mark.parametrize("body", [b'\xff', b'{"items":'])
def test_non_json_api_responses_refuse_before_any_artifact_processing(body):
    with pytest.raises(ApiPolicyError, match="endpoint items did not return safe JSON"):
        parse_json_response(body, "items")
