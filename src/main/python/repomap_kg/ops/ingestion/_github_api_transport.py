"""Transport implementations and run-file persistence for GitHub API ingestion."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from repomap_kg.ops.ingestion.github_api_config import resolve_fixture_response_path
from repomap_kg.ops.ingestion.github_api_helpers import (
    DEFAULT_GITHUB_API_BASE_URL,
    GitHubApiPolicyError,
    content_type_from_headers,
    ensure_contained,
    github_artifact_name,
    header_mapping,
    rate_limit_headers,
    redact_github_value,
    sha256_bytes,
    sha256_json,
    validate_no_auth_headers,
    write_json,
    write_jsonl,
)
from repomap_kg.ops.ingestion.github_api_records import (
    GitHubApiPlanManifest,
    GitHubApiSourceConfig,
    GitHubEndpointConfig,
    GitHubRequestPlan,
    GitHubResponseRecord,
    GitHubTransportResponse,
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: Any,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class FixtureGitHubApiTransport:
    """Fixture-only GitHub transport that reads local response files."""

    def fetch(
        self,
        config: GitHubApiSourceConfig,
        request: GitHubRequestPlan,
    ) -> GitHubTransportResponse:
        endpoint = endpoint_by_name(config, request.endpoint_name)
        response_path = resolve_fixture_response_path(config, endpoint)
        body = response_path.read_bytes()
        return GitHubTransportResponse(
            status_code=200,
            body=body,
            response_type=endpoint.response_type,
        )


class PublicGitHubRestTransport:
    """Unauthenticated public GitHub REST transport for planned GET requests."""

    def __init__(self, *, opener: Any | None = None) -> None:
        self.opener = opener or urllib.request.build_opener(_NoRedirectHandler())

    def fetch(
        self,
        config: GitHubApiSourceConfig,
        request: GitHubRequestPlan,
    ) -> GitHubTransportResponse:
        if config.acquisition_transport != "github_public_rest":
            raise GitHubApiPolicyError("PublicGitHubRestTransport requires github_public_rest")
        if request.method != "GET":
            raise GitHubApiPolicyError("GitHub REST transport only allows GET")
        url = github_public_rest_url(config, request)
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": config.user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        validate_no_auth_headers(headers)
        http_request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            response = self.opener.open(
                http_request,
                timeout=config.timeout_seconds,
            )
        except urllib.error.HTTPError as error:
            headers_map = header_mapping(error.headers)
            body = error.read(config.max_bytes_per_run + 1)
            return GitHubTransportResponse(
                status_code=error.code,
                body=body,
                response_type=content_type_from_headers(headers_map),
                headers=headers_map,
                rate_limit=rate_limit_headers(headers_map),
            )
        except urllib.error.URLError as error:
            raise GitHubApiPolicyError(
                f"GitHub REST acquisition failed: {error.reason}"
            ) from error
        headers_map = header_mapping(getattr(response, "headers", {}))
        body = response.read(config.max_bytes_per_run + 1)
        return GitHubTransportResponse(
            status_code=int(getattr(response, "status", response.getcode())),
            body=body,
            response_type=content_type_from_headers(headers_map),
            headers=headers_map,
            rate_limit=rate_limit_headers(headers_map),
        )


def write_github_api_run_files(
    config: GitHubApiSourceConfig,
    manifest: GitHubApiPlanManifest,
    *,
    fetched: Sequence[tuple[GitHubRequestPlan, GitHubTransportResponse, Any]],
    repository_root: Path,
) -> tuple[Path, tuple[GitHubResponseRecord, ...], dict[str, Any]]:
    output_path = (
        repository_root
        / ".repomap"
        / "api-runs"
        / config.source_id
        / manifest.api_run_id
    ).resolve()
    ensure_contained(output_path, repository_root, "GitHub API output path")
    artifacts_path = output_path / "artifacts"
    artifacts_path.mkdir(parents=True, exist_ok=True)
    records: list[GitHubResponseRecord] = []
    redacted_payloads: dict[str, Any] = {}
    for request, response, parsed in fetched:
        redacted_payload = redact_github_value(parsed)
        redacted_payloads[request.endpoint_name] = redacted_payload
        artifact_name = github_artifact_name(request.endpoint_name)
        artifact_path = artifacts_path / artifact_name
        write_json(artifact_path, redacted_payload)
        relative_artifact = artifact_path.relative_to(output_path).as_posix()
        records.append(
            GitHubResponseRecord(
                endpoint_name=request.endpoint_name,
                method=request.method,
                path_template=request.path,
                response_type=request.response_type,
                data_class=request.data_class,
                status_code=response.status_code,
                response_byte_count=len(response.body),
                response_sha256=sha256_bytes(response.body),
                artifact_path=relative_artifact,
                transport=config.acquisition_transport,
                redacted=True,
                redaction_profile=config.redaction_profile,
                retention_policy=config.retention_policy,
                downstream_route=request.downstream_route,
                rate_limit=dict(response.rate_limit),
            )
        )
    write_json(output_path / "plan.json", manifest.to_jsonable())
    write_json(
        output_path / "manifest.json",
        {
            **manifest.to_jsonable(),
            "responses": [record.to_jsonable() for record in records],
        },
    )
    write_jsonl(
        output_path / "requests.jsonl",
        [request.to_jsonable() for request in manifest.requests],
    )
    write_jsonl(
        output_path / "redacted-responses.jsonl",
        [record.to_jsonable() for record in records],
    )
    write_jsonl(output_path / "diagnostics.jsonl", [])
    return output_path, tuple(records), redacted_payloads


def github_public_rest_url(
    config: GitHubApiSourceConfig,
    request: GitHubRequestPlan,
) -> str:
    if config.base_url != DEFAULT_GITHUB_API_BASE_URL:
        raise GitHubApiPolicyError("acquisition.base_url must be https://api.github.com")
    if not request.path.startswith("/") or "://" in request.path:
        raise GitHubApiPolicyError("endpoint path must be a relative API path")
    owner = urllib.parse.quote(config.owner, safe="")
    repository = urllib.parse.quote(config.repository, safe="")
    path = request.path.replace("{owner}", owner).replace("{repo}", repository)
    parsed = urllib.parse.urlsplit(f"{config.base_url}{path}")
    if parsed.scheme != "https" or parsed.netloc != "api.github.com":
        raise GitHubApiPolicyError("GitHub REST URL must stay under api.github.com")
    if parsed.query or parsed.fragment:
        raise GitHubApiPolicyError("GitHub REST URL must not include raw query data")
    repo_prefix = f"/repos/{owner}/{repository}"
    if not parsed.path.startswith(repo_prefix):
        raise GitHubApiPolicyError("GitHub REST URL must stay under owner/repository")
    return urllib.parse.urlunsplit(parsed)


def endpoint_by_name(
    config: GitHubApiSourceConfig,
    endpoint_name: str,
) -> GitHubEndpointConfig:
    for endpoint in config.endpoints:
        if endpoint.name == endpoint_name:
            return endpoint
    raise GitHubApiPolicyError(f"unknown endpoint: {endpoint_name}")


def github_transport_for_config(config: GitHubApiSourceConfig) -> Any:
    if config.acquisition_transport == "fixture":
        return FixtureGitHubApiTransport()
    if config.acquisition_transport == "github_public_rest":
        return PublicGitHubRestTransport()
    raise GitHubApiPolicyError(
        f"unsupported acquisition.transport: {config.acquisition_transport}"
    )


def validate_transport_response(
    config: GitHubApiSourceConfig,
    request: GitHubRequestPlan,
    response: GitHubTransportResponse,
) -> None:
    if 300 <= response.status_code < 400:
        raise GitHubApiPolicyError(
            f"endpoint {request.endpoint_name} returned redirect status "
            f"{response.status_code}; redirects are not followed"
        )
    if response.rate_limit.get("x-ratelimit-remaining") == "0":
        raise GitHubApiPolicyError(
            f"endpoint {request.endpoint_name} hit GitHub API rate limit"
        )
    if response.status_code < 200 or response.status_code >= 300:
        raise GitHubApiPolicyError(
            f"endpoint {request.endpoint_name} returned HTTP status "
            f"{response.status_code}"
        )
    if "json" not in response.response_type.lower():
        raise GitHubApiPolicyError(
            f"endpoint {request.endpoint_name} did not return a JSON response"
        )
    if len(response.body) > config.max_bytes_per_run:
        raise GitHubApiPolicyError("response bytes exceed max_bytes_per_run")


def deterministic_github_api_run_id(
    config: GitHubApiSourceConfig,
    requests: Sequence[GitHubRequestPlan],
) -> str:
    digest = sha256_json(
        {
            "source_id": config.source_id,
            "owner": config.owner,
            "repository": config.repository,
            "transport": config.acquisition_transport,
            "policy_status": config.policy_status,
            "credential_mode": config.credential_mode,
            "endpoints": [request.to_jsonable() for request in requests],
            "limits": {
                "max_requests_per_run": config.max_requests_per_run,
                "max_requests_per_minute": config.max_requests_per_minute,
                "max_pages_per_endpoint": config.max_pages_per_endpoint,
                "max_items_per_endpoint": config.max_items_per_endpoint,
                "max_bytes_per_run": config.max_bytes_per_run,
                "max_concurrent_requests": config.max_concurrent_requests,
                "max_retries": config.max_retries,
            },
        }
    )[:24]
    return f"github-api-{digest}"


def manifest_digest(manifest: GitHubApiPlanManifest) -> str:
    payload = dict(manifest.to_jsonable())
    payload.pop("manifest_sha256", None)
    return sha256_json(payload)

