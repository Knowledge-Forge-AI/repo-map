"""Explicit-policy-gated documented REST API acquisition skeleton."""

from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

from repomap_kg.ops.ingestion._api_helpers import (
    ALLOWED_API_SOURCE_CLASSES,
    ALLOWED_CREDENTIAL_REF_PREFIXES,
    ALLOWED_POLICY_STATUSES,
    ALLOWED_SOURCE_TYPES,
    SECRET_MARKERS,
    count_response_items,
    deterministic_api_run_id,
    endpoint_by_name,
    ensure_contained,
    is_contained,
    is_secret_key,
    literal_type,
    manifest_digest,
    parse_endpoint,
    parse_json_response,
    redact_value,
    required_bool,
    required_endpoint_list,
    required_nonnegative_int,
    required_positive_int,
    required_string,
    required_table,
    resolve_fixture_response_path,
    safe_artifact_name,
    sha256_bytes,
    sha256_json,
    sha256_text,
    string_tuple,
    validate_credential_ref,
    validate_fixture_response_path,
    write_json,
    write_jsonl,
)
from repomap_kg.ops.ingestion._api_observations import (
    EXTRACTOR,
    EXTRACTOR_VERSION,
    annotate_observation,
    api_observations_from_records,
    api_provenance_observations,
    write_api_run_files,
)
from repomap_kg.ops.ingestion.acquisition_contracts import non_publication_result
from repomap_kg.ops.ingestion.api_records import (
    ApiAcquireSummary,
    ApiEndpointConfig,
    ApiPlanManifest,
    ApiPolicyError,
    ApiRequestPlan,
    ApiResponseRecord,
    ApiSourceConfig,
    ApiTransportResponse,
)


class FixtureApiTransport:
    """Fixture-only API transport for API1; performs no network I/O."""

    def fetch(
        self,
        config: ApiSourceConfig,
        request: ApiRequestPlan,
    ) -> ApiTransportResponse:
        endpoint = endpoint_by_name(config, request.endpoint_name)
        response_path = resolve_fixture_response_path(
            config.config_path,
            endpoint.fixture_response_path,
        )
        try:
            body = response_path.read_bytes()
        except OSError as error:
            raise ApiPolicyError(
                f"fixture response is not readable for endpoint {endpoint.name}: {error}"
            ) from error
        return ApiTransportResponse(
            status_code=200,
            body=body,
            response_type=endpoint.response_type,
        )


def load_api_source_config(path: Path | str) -> ApiSourceConfig:
    config_path = Path(path).resolve()
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ApiPolicyError(f"invalid API config: {error}") from error

    source = required_table(payload, "source")
    credentials = required_table(payload, "credentials")
    consent = required_table(payload, "consent")
    limits = required_table(payload, "limits")
    retention = required_table(payload, "retention")
    redaction = required_table(payload, "redaction")
    endpoints = required_endpoint_list(payload)

    source_id = required_string(source, "source_id")
    source_type = required_string(source, "source_type")
    api_source_class = required_string(source, "api_source_class")
    provider_name = required_string(source, "provider_name")
    provider_product = required_string(source, "provider_product")
    policy_status = required_string(source, "policy_status")
    read_only = required_bool(source, "read_only")
    mutation_allowed = required_bool(source, "mutation_allowed")

    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ApiPolicyError(f"unsupported source_type: {source_type}")
    if api_source_class not in ALLOWED_API_SOURCE_CLASSES:
        raise ApiPolicyError(f"unsupported api_source_class: {api_source_class}")
    if policy_status not in ALLOWED_POLICY_STATUSES:
        raise ApiPolicyError(f"source policy status is not allowed: {policy_status}")
    if not read_only:
        raise ApiPolicyError("source.read_only must be true")
    if mutation_allowed:
        raise ApiPolicyError("source.mutation_allowed must be false")

    credentials_ref = required_string(credentials, "credentials_ref")
    validate_credential_ref(credentials_ref)

    consent_ref = required_string(consent, "consent_ref")
    authorized_operations = string_tuple(consent.get("authorized_operations"))
    authorized_data_classes = string_tuple(consent.get("authorized_data_classes"))
    consent_revoked = required_bool(consent, "revoked")
    consent_mutation_allowed = required_bool(consent, "mutation_allowed")
    if consent_revoked:
        raise ApiPolicyError("consent is revoked")
    if consent_mutation_allowed:
        raise ApiPolicyError("consent mutation_allowed must be false")
    if authorized_operations != ("read",):
        raise ApiPolicyError("consent authorized_operations must be read-only")
    if not authorized_data_classes:
        raise ApiPolicyError("consent authorized_data_classes is required")

    max_requests_per_run = required_positive_int(limits, "max_requests_per_run")
    max_requests_per_minute = required_positive_int(limits, "max_requests_per_minute")
    max_concurrent_requests = required_positive_int(limits, "max_concurrent_requests")
    max_bytes_per_run = required_positive_int(limits, "max_bytes_per_run")
    max_items_per_run = required_positive_int(limits, "max_items_per_run")
    max_retries = required_nonnegative_int(limits, "max_retries")
    if max_concurrent_requests != 1:
        raise ApiPolicyError("max_concurrent_requests must be 1 in API1")
    if max_requests_per_run < len(endpoints):
        raise ApiPolicyError("max_requests_per_run is below endpoint count")

    retention_policy = required_string(retention, "policy")
    raw_response_retention = required_string(retention, "raw_response_retention")
    redacted_response_retention = required_string(
        retention,
        "redacted_response_retention",
    )
    redaction_profile = required_string(redaction, "profile")
    sensitivity = required_string(redaction, "sensitivity")

    parsed_endpoints = tuple(parse_endpoint(endpoint) for endpoint in endpoints)
    return ApiSourceConfig(
        config_path=config_path,
        source_id=source_id,
        source_type=source_type,
        api_source_class=api_source_class,
        provider_name=provider_name,
        provider_product=provider_product,
        policy_status=policy_status,
        read_only=read_only,
        mutation_allowed=mutation_allowed,
        credentials_ref=credentials_ref,
        consent_ref=consent_ref,
        authorized_operations=authorized_operations,
        authorized_data_classes=authorized_data_classes,
        consent_revoked=consent_revoked,
        consent_mutation_allowed=consent_mutation_allowed,
        max_requests_per_run=max_requests_per_run,
        max_requests_per_minute=max_requests_per_minute,
        max_concurrent_requests=max_concurrent_requests,
        max_bytes_per_run=max_bytes_per_run,
        max_items_per_run=max_items_per_run,
        max_retries=max_retries,
        retention_policy=retention_policy,
        raw_response_retention=raw_response_retention,
        redacted_response_retention=redacted_response_retention,
        redaction_profile=redaction_profile,
        sensitivity=sensitivity,
        endpoints=parsed_endpoints,
    )


def build_api_plan_from_config(config_path: Path | str) -> ApiPlanManifest:
    return build_api_plan(load_api_source_config(config_path))


def build_api_plan(config: ApiSourceConfig) -> ApiPlanManifest:
    requests = tuple(
        ApiRequestPlan(
            endpoint_name=endpoint.name,
            method=endpoint.method,
            path=endpoint.path,
            response_type=endpoint.response_type,
            downstream_route=endpoint.downstream_route,
            request_id=sha256_json(
                {
                    "source_id": config.source_id,
                    "endpoint": endpoint.plan_payload(),
                }
            )[:24],
        )
        for endpoint in config.endpoints
    )
    run_id = deterministic_api_run_id(config, requests)
    manifest_id = sha256_text(f"{config.source_id}:{run_id}")[:24]
    manifest = ApiPlanManifest(
        source_id=config.source_id,
        source_type=config.source_type,
        api_source_class=config.api_source_class,
        provider_name=config.provider_name,
        provider_product=config.provider_product,
        policy_status=config.policy_status,
        api_run_id=run_id,
        api_manifest_id=manifest_id,
        requests=requests,
        max_requests_per_run=config.max_requests_per_run,
        max_requests_per_minute=config.max_requests_per_minute,
        max_concurrent_requests=config.max_concurrent_requests,
        max_bytes_per_run=config.max_bytes_per_run,
        max_items_per_run=config.max_items_per_run,
        max_retries=config.max_retries,
        retention_policy=config.retention_policy,
        redaction_profile=config.redaction_profile,
        sensitivity=config.sensitivity,
    )
    return replace(manifest, manifest_sha256=manifest_digest(manifest))


def acquire_api_source(
    config_path: Path | str,
    *,
    root_path: Path | str,
    transport: FixtureApiTransport | None = None,
) -> ApiAcquireSummary:
    config = load_api_source_config(config_path)
    repo_root = Path(root_path).resolve()
    manifest = build_api_plan(config)
    fixture_transport = transport or FixtureApiTransport()
    fetched: list[tuple[ApiRequestPlan, ApiTransportResponse, Any]] = []
    total_bytes = 0
    total_items = 0
    for request in manifest.requests:
        response = fixture_transport.fetch(config, request)
        if response.status_code < 200 or response.status_code >= 300:
            raise ApiPolicyError(
                f"endpoint {request.endpoint_name} returned status {response.status_code}"
            )
        total_bytes += len(response.body)
        if total_bytes > config.max_bytes_per_run:
            raise ApiPolicyError("response bytes exceed max_bytes_per_run")
        parsed = parse_json_response(response.body, request.endpoint_name)
        total_items += count_response_items(parsed)
        if total_items > config.max_items_per_run:
            raise ApiPolicyError("response items exceed max_items_per_run")
        fetched.append((request, response, parsed))

    output_path, records = write_api_run_files(
        config,
        manifest,
        fetched=fetched,
        repository_root=repo_root,
    )
    observations = api_observations_from_records(
        config,
        manifest,
        response_records=records,
        repository_root=repo_root,
        output_path=output_path,
    )
    return ApiAcquireSummary(
        source_id=config.source_id,
        source_type=config.source_type,
        api_source_class=config.api_source_class,
        provider_name=config.provider_name,
        provider_product=config.provider_product,
        policy_status=config.policy_status,
        api_run_id=manifest.api_run_id,
        api_manifest_id=manifest.api_manifest_id,
        requests=manifest.request_count,
        responses=len(records),
        observations=len(observations),
        raw_observations=tuple(observations),
        output_path=output_path,
        output_path_summary=output_path.relative_to(repo_root).as_posix(),
        manifest=manifest,
        response_records=tuple(records),
        publication=non_publication_result(),
    )


__all__ = [
    "ALLOWED_API_SOURCE_CLASSES",
    "ALLOWED_CREDENTIAL_REF_PREFIXES",
    "ALLOWED_POLICY_STATUSES",
    "ALLOWED_SOURCE_TYPES",
    "ApiAcquireSummary",
    "ApiEndpointConfig",
    "ApiPlanManifest",
    "ApiPolicyError",
    "ApiRequestPlan",
    "ApiResponseRecord",
    "ApiSourceConfig",
    "ApiTransportResponse",
    "EXTRACTOR",
    "EXTRACTOR_VERSION",
    "FixtureApiTransport",
    "SECRET_MARKERS",
    "acquire_api_source",
    "annotate_observation",
    "api_observations_from_records",
    "api_provenance_observations",
    "build_api_plan",
    "build_api_plan_from_config",
    "count_response_items",
    "deterministic_api_run_id",
    "endpoint_by_name",
    "ensure_contained",
    "is_contained",
    "is_secret_key",
    "literal_type",
    "load_api_source_config",
    "manifest_digest",
    "parse_endpoint",
    "parse_json_response",
    "redact_value",
    "required_bool",
    "required_endpoint_list",
    "required_nonnegative_int",
    "required_positive_int",
    "required_string",
    "required_table",
    "resolve_fixture_response_path",
    "safe_artifact_name",
    "sha256_bytes",
    "sha256_json",
    "sha256_text",
    "string_tuple",
    "validate_credential_ref",
    "validate_fixture_response_path",
    "write_api_run_files",
    "write_json",
    "write_jsonl",
]
