"""GitHub documented REST API acquisition for fixture and public REST modes."""

from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

from repomap_kg.ops.ingestion._github_api_transport import (
    FixtureGitHubApiTransport,
    PublicGitHubRestTransport,
    _NoRedirectHandler,
    deterministic_github_api_run_id,
    endpoint_by_name,
    github_public_rest_url,
    github_transport_for_config,
    manifest_digest,
    validate_transport_response,
    write_github_api_run_files,
)
from repomap_kg.ops.ingestion.acquisition_contracts import non_publication_result
from repomap_kg.ops.ingestion.github_api_config import (
    acquisition_config_from_payload,
    credentials_ref_from_payload,
    parse_github_endpoint,
    validate_consent,
    validate_limits,
    validate_retention_and_redaction,
    validate_source_identity,
)
from repomap_kg.ops.ingestion.github_api_helpers import (
    GitHubApiPolicyError,
    content_type_from_headers,
    count_response_items,
    header_mapping,
    literal_type,
    optional_bool,
    optional_positive_int,
    optional_string,
    parse_json_response,
    rate_limit_headers,
    redact_github_value,
    required_bool,
    required_endpoint_list,
    required_nonnegative_int,
    required_positive_int,
    required_string,
    required_table,
    sha256_json,
    sha256_text,
    string_tuple,
    validate_no_auth_headers,
)
from repomap_kg.ops.ingestion.github_api_observations import (
    github_api_observations_from_records,
)
from repomap_kg.ops.ingestion.github_api_records import (
    GitHubApiAcquireSummary,
    GitHubApiPlanManifest,
    GitHubApiSourceConfig,
    GitHubEndpointConfig,
    GitHubRequestPlan,
    GitHubResponseRecord,
    GitHubTransportResponse,
)


def load_github_api_source_config(path: Path | str) -> GitHubApiSourceConfig:
    config_path = Path(path).resolve()
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise GitHubApiPolicyError(f"invalid GitHub API config: {error}") from error

    source = required_table(payload, "source")
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
    owner = required_string(source, "owner")
    repository = required_string(source, "repository")
    repository_visibility = required_string(source, "repository_visibility")
    read_only = required_bool(source, "read_only")
    mutation_allowed = required_bool(source, "mutation_allowed")
    credential_mode = required_string(source, "credential_mode")

    validate_source_identity(
        source_type=source_type,
        api_source_class=api_source_class,
        provider_name=provider_name,
        provider_product=provider_product,
        policy_status=policy_status,
        owner=owner,
        repository=repository,
        repository_visibility=repository_visibility,
        read_only=read_only,
        mutation_allowed=mutation_allowed,
        credential_mode=credential_mode,
    )
    (
        acquisition_transport,
        base_url,
        timeout_seconds,
        follow_redirects,
        user_agent,
    ) = acquisition_config_from_payload(
        payload,
        credential_mode=credential_mode,
        repository_visibility=repository_visibility,
    )
    credentials_ref = credentials_ref_from_payload(
        payload,
        credential_mode=credential_mode,
        repository_visibility=repository_visibility,
        acquisition_transport=acquisition_transport,
    )

    consent_ref = required_string(consent, "consent_ref")
    authorized_operations = string_tuple(consent.get("authorized_operations"))
    authorized_data_classes = string_tuple(consent.get("authorized_data_classes"))
    consent_revoked = required_bool(consent, "revoked")
    consent_mutation_allowed = required_bool(consent, "mutation_allowed")
    validate_consent(
        consent_ref=consent_ref,
        authorized_operations=authorized_operations,
        authorized_data_classes=authorized_data_classes,
        consent_revoked=consent_revoked,
        consent_mutation_allowed=consent_mutation_allowed,
    )

    max_requests_per_run = required_positive_int(limits, "max_requests_per_run")
    max_requests_per_minute = required_positive_int(
        limits,
        "max_requests_per_minute",
    )
    max_pages_per_endpoint = required_positive_int(limits, "max_pages_per_endpoint")
    max_items_per_endpoint = required_positive_int(limits, "max_items_per_endpoint")
    max_bytes_per_run = required_positive_int(limits, "max_bytes_per_run")
    max_concurrent_requests = required_positive_int(limits, "max_concurrent_requests")
    max_retries = required_nonnegative_int(limits, "max_retries")
    validate_limits(
        max_requests_per_run=max_requests_per_run,
        endpoint_count=len(endpoints),
        max_pages_per_endpoint=max_pages_per_endpoint,
        max_concurrent_requests=max_concurrent_requests,
        max_retries=max_retries,
    )

    retention_policy = required_string(retention, "policy")
    raw_response_retention = required_string(retention, "raw_response_retention")
    redacted_response_retention = required_string(
        retention,
        "redacted_response_retention",
    )
    redaction_profile = required_string(redaction, "profile")
    sensitivity = required_string(redaction, "sensitivity")
    validate_retention_and_redaction(
        retention_policy=retention_policy,
        raw_response_retention=raw_response_retention,
        redacted_response_retention=redacted_response_retention,
        redaction_profile=redaction_profile,
        sensitivity=sensitivity,
    )

    parsed_endpoints = tuple(
        parse_github_endpoint(
            endpoint,
            owner=owner,
            repository=repository,
            authorized_data_classes=authorized_data_classes,
            acquisition_transport=acquisition_transport,
        )
        for endpoint in endpoints
    )
    return GitHubApiSourceConfig(
        config_path=config_path,
        acquisition_transport=acquisition_transport,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        follow_redirects=follow_redirects,
        user_agent=user_agent,
        source_id=source_id,
        source_type=source_type,
        api_source_class=api_source_class,
        provider_name=provider_name,
        provider_product=provider_product,
        policy_status=policy_status,
        owner=owner,
        repository=repository,
        repository_visibility=repository_visibility,
        read_only=read_only,
        mutation_allowed=mutation_allowed,
        credential_mode=credential_mode,
        credentials_ref=credentials_ref,
        consent_ref=consent_ref,
        authorized_operations=authorized_operations,
        authorized_data_classes=authorized_data_classes,
        consent_revoked=consent_revoked,
        consent_mutation_allowed=consent_mutation_allowed,
        max_requests_per_run=max_requests_per_run,
        max_requests_per_minute=max_requests_per_minute,
        max_pages_per_endpoint=max_pages_per_endpoint,
        max_items_per_endpoint=max_items_per_endpoint,
        max_bytes_per_run=max_bytes_per_run,
        max_concurrent_requests=max_concurrent_requests,
        max_retries=max_retries,
        retention_policy=retention_policy,
        raw_response_retention=raw_response_retention,
        redacted_response_retention=redacted_response_retention,
        redaction_profile=redaction_profile,
        sensitivity=sensitivity,
        endpoints=parsed_endpoints,
    )


def build_github_api_plan_from_config(config_path: Path | str) -> GitHubApiPlanManifest:
    return build_github_api_plan(load_github_api_source_config(config_path))


def build_github_api_plan(config: GitHubApiSourceConfig) -> GitHubApiPlanManifest:
    requests = tuple(
        GitHubRequestPlan(
            endpoint_name=endpoint.name,
            method=endpoint.method,
            path=endpoint.path,
            response_type=endpoint.response_type,
            downstream_route=endpoint.downstream_route,
            data_class=endpoint.data_class,
            request_id=sha256_json(
                {
                    "source_id": config.source_id,
                    "owner": config.owner,
                    "repository": config.repository,
                    "transport": config.acquisition_transport,
                    "endpoint": endpoint.plan_payload(),
                }
            )[:24],
        )
        for endpoint in config.endpoints
    )
    run_id = deterministic_github_api_run_id(config, requests)
    manifest_id = sha256_text(f"{config.source_id}:{run_id}")[:24]
    manifest = GitHubApiPlanManifest(
        source_id=config.source_id,
        source_type=config.source_type,
        api_source_class=config.api_source_class,
        provider_name=config.provider_name,
        provider_product=config.provider_product,
        policy_status=config.policy_status,
        owner=config.owner,
        repository=config.repository,
        repository_visibility=config.repository_visibility,
        transport=config.acquisition_transport,
        credential_mode=config.credential_mode,
        api_run_id=run_id,
        api_manifest_id=manifest_id,
        requests=requests,
        max_requests_per_run=config.max_requests_per_run,
        max_requests_per_minute=config.max_requests_per_minute,
        max_pages_per_endpoint=config.max_pages_per_endpoint,
        max_items_per_endpoint=config.max_items_per_endpoint,
        max_bytes_per_run=config.max_bytes_per_run,
        max_concurrent_requests=config.max_concurrent_requests,
        max_retries=config.max_retries,
        retention_policy=config.retention_policy,
        redaction_profile=config.redaction_profile,
        sensitivity=config.sensitivity,
        network_capable=config.acquisition_transport == "github_public_rest",
        no_network=config.acquisition_transport == "fixture",
        fixture_transport_only=config.acquisition_transport == "fixture",
    )
    return replace(manifest, manifest_sha256=manifest_digest(manifest))


def acquire_github_api_source(
    config_path: Path | str,
    *,
    root_path: Path | str,
    transport: Any | None = None,
) -> GitHubApiAcquireSummary:
    config = load_github_api_source_config(config_path)
    repo_root = Path(root_path).resolve()
    manifest = build_github_api_plan(config)
    selected_transport = transport or github_transport_for_config(config)
    fetched: list[tuple[GitHubRequestPlan, GitHubTransportResponse, Any]] = []
    total_bytes = 0
    for request in manifest.requests:
        response = selected_transport.fetch(config, request)
        validate_transport_response(config, request, response)
        total_bytes += len(response.body)
        if total_bytes > config.max_bytes_per_run:
            raise GitHubApiPolicyError("response bytes exceed max_bytes_per_run")
        parsed = parse_json_response(response.body, request.endpoint_name)
        item_count = count_response_items(parsed)
        if item_count > config.max_items_per_endpoint:
            raise GitHubApiPolicyError("response items exceed max_items_per_endpoint")
        fetched.append((request, response, parsed))

    output_path, records, redacted_payloads = write_github_api_run_files(
        config,
        manifest,
        fetched=fetched,
        repository_root=repo_root,
    )
    observations = github_api_observations_from_records(
        config,
        manifest,
        response_records=records,
        redacted_payloads=redacted_payloads,
        repository_root=repo_root,
        output_path=output_path,
    )
    return GitHubApiAcquireSummary(
        source_id=config.source_id,
        source_type=config.source_type,
        api_source_class=config.api_source_class,
        provider_name=config.provider_name,
        provider_product=config.provider_product,
        policy_status=config.policy_status,
        owner=config.owner,
        repository=config.repository,
        repository_visibility=config.repository_visibility,
        transport=config.acquisition_transport,
        credential_mode=config.credential_mode,
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
        no_network=config.acquisition_transport == "fixture",
        network_capable=config.acquisition_transport == "github_public_rest",
        fixture_transport_only=config.acquisition_transport == "fixture",
    )


__all__ = [
    "FixtureGitHubApiTransport",
    "GitHubApiAcquireSummary",
    "GitHubApiPlanManifest",
    "GitHubApiPolicyError",
    "GitHubApiSourceConfig",
    "GitHubEndpointConfig",
    "GitHubRequestPlan",
    "GitHubResponseRecord",
    "GitHubTransportResponse",
    "PublicGitHubRestTransport",
    "_NoRedirectHandler",
    "acquire_github_api_source",
    "build_github_api_plan",
    "build_github_api_plan_from_config",
    "content_type_from_headers",
    "count_response_items",
    "deterministic_github_api_run_id",
    "endpoint_by_name",
    "github_public_rest_url",
    "github_transport_for_config",
    "header_mapping",
    "literal_type",
    "load_github_api_source_config",
    "manifest_digest",
    "optional_bool",
    "optional_positive_int",
    "optional_string",
    "parse_json_response",
    "rate_limit_headers",
    "redact_github_value",
    "required_bool",
    "required_endpoint_list",
    "required_nonnegative_int",
    "required_positive_int",
    "required_string",
    "required_table",
    "string_tuple",
    "validate_no_auth_headers",
    "validate_transport_response",
    "write_github_api_run_files",
]
