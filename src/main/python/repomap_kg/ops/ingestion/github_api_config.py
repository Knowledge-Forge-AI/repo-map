"""GitHub API source configuration validation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from repomap_kg.ops.ingestion.github_api_helpers import (
    ALLOWED_ACQUISITION_TRANSPORTS,
    ALLOWED_CREDENTIAL_MODES,
    ALLOWED_CREDENTIAL_REF_PREFIXES,
    ALLOWED_ENDPOINT_PATHS,
    ALLOWED_GITHUB_API_SOURCE_CLASSES,
    ALLOWED_POLICY_STATUSES,
    ALLOWED_REPOSITORY_VISIBILITIES,
    ALLOWED_SOURCE_TYPES,
    DEFAULT_GITHUB_API_BASE_URL,
    DEFAULT_GITHUB_USER_AGENT,
    OWNER_RE,
    REPOSITORY_RE,
    GitHubApiPolicyError,
    ensure_contained,
    optional_bool,
    optional_positive_int,
    optional_string,
    required_positive_int,
    required_string,
)
from repomap_kg.ops.ingestion.github_api_records import GitHubApiSourceConfig, GitHubEndpointConfig


def validate_source_identity(
    *,
    source_type: str,
    api_source_class: str,
    provider_name: str,
    provider_product: str,
    policy_status: str,
    owner: str,
    repository: str,
    repository_visibility: str,
    read_only: bool,
    mutation_allowed: bool,
    credential_mode: str,
) -> None:
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise GitHubApiPolicyError(f"unsupported source_type: {source_type}")
    if api_source_class not in ALLOWED_GITHUB_API_SOURCE_CLASSES:
        raise GitHubApiPolicyError(f"unsupported api_source_class: {api_source_class}")
    if provider_name != "GitHub":
        raise GitHubApiPolicyError("source.provider_name must be GitHub")
    if provider_product != "GitHub REST API":
        raise GitHubApiPolicyError("source.provider_product must be GitHub REST API")
    if policy_status not in ALLOWED_POLICY_STATUSES:
        raise GitHubApiPolicyError(
            f"source policy status is not allowed: {policy_status}"
        )
    if not owner or not OWNER_RE.fullmatch(owner):
        raise GitHubApiPolicyError("source.owner must be a safe GitHub owner")
    if not repository or not REPOSITORY_RE.fullmatch(repository):
        raise GitHubApiPolicyError(
            "source.repository must be a safe GitHub repository"
        )
    if repository_visibility not in ALLOWED_REPOSITORY_VISIBILITIES:
        raise GitHubApiPolicyError(
            "source.repository_visibility must be public, private, or internal"
        )
    if not read_only:
        raise GitHubApiPolicyError("source.read_only must be true")
    if mutation_allowed:
        raise GitHubApiPolicyError("source.mutation_allowed must be false")
    if credential_mode not in ALLOWED_CREDENTIAL_MODES:
        raise GitHubApiPolicyError(f"unsupported credential_mode: {credential_mode}")
    if credential_mode == "none_public_readonly" and repository_visibility != "public":
        raise GitHubApiPolicyError(
            "credential_mode none_public_readonly is allowed only for public repositories"
        )


def acquisition_config_from_payload(
    payload: Mapping[str, Any],
    *,
    credential_mode: str,
    repository_visibility: str,
) -> tuple[str, str, int, bool, str]:
    acquisition = payload.get("acquisition")
    if acquisition is None:
        return ("fixture", DEFAULT_GITHUB_API_BASE_URL, 10, False, DEFAULT_GITHUB_USER_AGENT)
    if not isinstance(acquisition, Mapping):
        raise GitHubApiPolicyError("acquisition table is required when present")
    transport = str(acquisition.get("transport") or "fixture")
    if transport not in ALLOWED_ACQUISITION_TRANSPORTS:
        raise GitHubApiPolicyError(f"unsupported acquisition.transport: {transport}")
    base_url = str(acquisition.get("base_url") or DEFAULT_GITHUB_API_BASE_URL).rstrip("/")
    timeout_seconds = optional_positive_int(acquisition, "timeout_seconds", default=10)
    follow_redirects = optional_bool(acquisition, "follow_redirects", default=False)
    user_agent = str(acquisition.get("user_agent") or DEFAULT_GITHUB_USER_AGENT)
    if not user_agent or "\n" in user_agent or "\r" in user_agent:
        raise GitHubApiPolicyError("acquisition.user_agent must be a safe header value")
    if transport == "github_public_rest":
        if repository_visibility != "public":
            raise GitHubApiPolicyError("github_public_rest requires a public repository")
        if credential_mode != "none_public_readonly":
            raise GitHubApiPolicyError(
                "github_public_rest requires credential_mode none_public_readonly"
            )
        if base_url != DEFAULT_GITHUB_API_BASE_URL:
            raise GitHubApiPolicyError("acquisition.base_url must be https://api.github.com")
        if follow_redirects:
            raise GitHubApiPolicyError("github_public_rest must not follow redirects")
    return (transport, base_url, timeout_seconds, follow_redirects, user_agent)


def credentials_ref_from_payload(
    payload: Mapping[str, Any],
    *,
    credential_mode: str,
    repository_visibility: str,
    acquisition_transport: str,
) -> str | None:
    credentials = payload.get("credentials")
    if acquisition_transport == "github_public_rest" and credentials is not None:
        raise GitHubApiPolicyError(
            "credentials table is not allowed for github_public_rest"
        )
    if credential_mode == "none_public_readonly":
        if repository_visibility != "public":
            raise GitHubApiPolicyError("public unauthenticated mode requires public repo")
        return None
    if not isinstance(credentials, Mapping):
        raise GitHubApiPolicyError("credentials.credentials_ref is required")
    credentials_ref = required_string(credentials, "credentials_ref")
    validate_credential_ref(credentials_ref)
    return credentials_ref


def validate_credential_ref(credentials_ref: str) -> None:
    if not any(
        credentials_ref.startswith(prefix)
        and len(credentials_ref) > len(prefix)
        and not credentials_ref[len(prefix) :].isspace()
        for prefix in ALLOWED_CREDENTIAL_REF_PREFIXES
    ):
        raise GitHubApiPolicyError("credentials_ref must be an opaque local ref")


def validate_consent(
    *,
    consent_ref: str,
    authorized_operations: tuple[str, ...],
    authorized_data_classes: tuple[str, ...],
    consent_revoked: bool,
    consent_mutation_allowed: bool,
) -> None:
    if not consent_ref:
        raise GitHubApiPolicyError("consent_ref is required")
    if consent_revoked:
        raise GitHubApiPolicyError("consent is revoked")
    if consent_mutation_allowed:
        raise GitHubApiPolicyError("consent mutation_allowed must be false")
    if authorized_operations != ("read",):
        raise GitHubApiPolicyError("consent authorized_operations must be read-only")
    if not authorized_data_classes:
        raise GitHubApiPolicyError("consent authorized_data_classes is required")


def validate_limits(
    *,
    max_requests_per_run: int,
    endpoint_count: int,
    max_pages_per_endpoint: int,
    max_concurrent_requests: int,
    max_retries: int,
) -> None:
    if max_requests_per_run < endpoint_count:
        raise GitHubApiPolicyError("max_requests_per_run is below endpoint count")
    if max_pages_per_endpoint != 1:
        raise GitHubApiPolicyError("max_pages_per_endpoint must be 1 in GITHUB_API1")
    if max_concurrent_requests != 1:
        raise GitHubApiPolicyError("max_concurrent_requests must be 1 in GITHUB_API1")
    if max_retries != 0:
        raise GitHubApiPolicyError("max_retries must be 0 in GITHUB_API1")


def validate_retention_and_redaction(
    *,
    retention_policy: str,
    raw_response_retention: str,
    redacted_response_retention: str,
    redaction_profile: str,
    sensitivity: str,
) -> None:
    if retention_policy != "local_user_controlled":
        raise GitHubApiPolicyError("retention.policy must be local_user_controlled")
    if raw_response_retention != "minimized":
        raise GitHubApiPolicyError("retention.raw_response_retention must be minimized")
    if redacted_response_retention != "retain":
        raise GitHubApiPolicyError(
            "retention.redacted_response_retention must be retain"
        )
    if redaction_profile != "strict":
        raise GitHubApiPolicyError("redaction.profile must be strict")
    if not sensitivity:
        raise GitHubApiPolicyError("redaction.sensitivity is required")


def parse_github_endpoint(
    payload: Mapping[str, Any],
    *,
    owner: str,
    repository: str,
    authorized_data_classes: tuple[str, ...],
    acquisition_transport: str,
) -> GitHubEndpointConfig:
    name = required_string(payload, "name")
    method = required_string(payload, "method").upper()
    path = required_string(payload, "path")
    purpose = required_string(payload, "purpose")
    response_type = required_string(payload, "response_type")
    max_page_size = required_positive_int(payload, "max_page_size")
    pagination = required_string(payload, "pagination")
    downstream_route = required_string(payload, "downstream_route")
    fixture_response_path = optional_string(payload, "fixture_response_path")
    if method != "GET":
        raise GitHubApiPolicyError("GITHUB_API1 only allows GET endpoints")
    if not path.startswith("/") or "://" in path:
        raise GitHubApiPolicyError("endpoint path must be a relative API path")
    if path not in ALLOWED_ENDPOINT_PATHS:
        if path.startswith("/repos/") and "/contents" in path:
            raise GitHubApiPolicyError("endpoint path is not allowlisted")
        raise GitHubApiPolicyError("endpoint path must remain under owner/repository")
    if "{owner}" not in path or "{repo}" not in path:
        raise GitHubApiPolicyError("endpoint path must remain under owner/repository")
    if owner in path or repository in path:
        raise GitHubApiPolicyError("endpoint path must use owner/repo placeholders")
    if pagination != "none":
        raise GitHubApiPolicyError(
            "GitHub API acquisition only supports pagination = none in this phase"
        )
    if downstream_route != "config":
        raise GitHubApiPolicyError(
            "GitHub API acquisition only supports downstream_route = config"
        )
    if response_type != "application/json":
        raise GitHubApiPolicyError("GitHub API acquisition only supports JSON responses")
    if acquisition_transport == "fixture":
        if fixture_response_path is None:
            raise GitHubApiPolicyError("fixture_response_path is required for fixture transport")
        validate_fixture_response_path(fixture_response_path)
    elif fixture_response_path is not None:
        validate_fixture_response_path(fixture_response_path)
    data_class = ALLOWED_ENDPOINT_PATHS[path]
    if data_class not in authorized_data_classes:
        raise GitHubApiPolicyError(f"endpoint data class is not authorized: {data_class}")
    return GitHubEndpointConfig(
        name=name,
        method=method,
        path=path,
        purpose=purpose,
        response_type=response_type,
        max_page_size=max_page_size,
        pagination=pagination,
        downstream_route=downstream_route,
        fixture_response_path=fixture_response_path,
        data_class=data_class,
    )


def validate_fixture_response_path(fixture_response_path: str) -> None:
    path = Path(fixture_response_path)
    if (
        path.is_absolute()
        or ".." in path.parts
        or "://" in fixture_response_path
        or not fixture_response_path
    ):
        raise GitHubApiPolicyError(
            "fixture_response_path must be a contained relative path"
        )


def resolve_fixture_response_path(
    config: GitHubApiSourceConfig,
    endpoint: GitHubEndpointConfig,
) -> Path:
    if endpoint.fixture_response_path is None:
        raise GitHubApiPolicyError("fixture_response_path is required for fixture transport")
    config_dir = config.config_path.parent
    response_path = (config_dir / endpoint.fixture_response_path).resolve()
    ensure_contained(response_path, config_dir, "fixture_response_path")
    if not response_path.is_file():
        raise GitHubApiPolicyError(
            f"fixture response does not exist: {endpoint.fixture_response_path}"
        )
    return response_path
