"""Record types for GitHub API ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion.acquisition_contracts import NonPublicationResult


@dataclass(frozen=True)
class GitHubEndpointConfig:
    name: str
    method: str
    path: str
    purpose: str
    response_type: str
    max_page_size: int
    pagination: str
    downstream_route: str
    fixture_response_path: str | None
    data_class: str

    def plan_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "method": self.method,
            "path": self.path,
            "purpose": self.purpose,
            "response_type": self.response_type,
            "max_page_size": self.max_page_size,
            "pagination": self.pagination,
            "downstream_route": self.downstream_route,
            "data_class": self.data_class,
        }


@dataclass(frozen=True)
class GitHubApiSourceConfig:
    config_path: Path
    acquisition_transport: str
    base_url: str
    timeout_seconds: int
    follow_redirects: bool
    user_agent: str
    source_id: str
    source_type: str
    api_source_class: str
    provider_name: str
    provider_product: str
    policy_status: str
    owner: str
    repository: str
    repository_visibility: str
    read_only: bool
    mutation_allowed: bool
    credential_mode: str
    credentials_ref: str | None
    consent_ref: str
    authorized_operations: tuple[str, ...]
    authorized_data_classes: tuple[str, ...]
    consent_revoked: bool
    consent_mutation_allowed: bool
    max_requests_per_run: int
    max_requests_per_minute: int
    max_pages_per_endpoint: int
    max_items_per_endpoint: int
    max_bytes_per_run: int
    max_concurrent_requests: int
    max_retries: int
    retention_policy: str
    raw_response_retention: str
    redacted_response_retention: str
    redaction_profile: str
    sensitivity: str
    endpoints: tuple[GitHubEndpointConfig, ...]


@dataclass(frozen=True)
class GitHubRequestPlan:
    endpoint_name: str
    method: str
    path: str
    response_type: str
    downstream_route: str
    data_class: str
    request_id: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "endpoint_name": self.endpoint_name,
            "method": self.method,
            "path": self.path,
            "response_type": self.response_type,
            "downstream_route": self.downstream_route,
            "data_class": self.data_class,
            "request_id": self.request_id,
        }


@dataclass(frozen=True)
class GitHubApiPlanManifest:
    source_id: str
    source_type: str
    api_source_class: str
    provider_name: str
    provider_product: str
    policy_status: str
    owner: str
    repository: str
    repository_visibility: str
    transport: str
    credential_mode: str
    api_run_id: str
    api_manifest_id: str
    requests: tuple[GitHubRequestPlan, ...]
    max_requests_per_run: int
    max_requests_per_minute: int
    max_pages_per_endpoint: int
    max_items_per_endpoint: int
    max_bytes_per_run: int
    max_concurrent_requests: int
    max_retries: int
    retention_policy: str
    redaction_profile: str
    sensitivity: str
    manifest_sha256: str = ""
    network_capable: bool = False
    no_network: bool = True
    no_mutation: bool = True
    no_credentials_resolved: bool = True
    no_scheduler: bool = True
    fixture_transport_only: bool = True

    @property
    def request_count(self) -> int:
        return len(self.requests)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "api_run_id": self.api_run_id,
            "api_manifest_id": self.api_manifest_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "api_source_class": self.api_source_class,
            "provider_name": self.provider_name,
            "provider_product": self.provider_product,
            "policy_status": self.policy_status,
            "owner": self.owner,
            "repository": self.repository,
            "repository_visibility": self.repository_visibility,
            "transport": self.transport,
            "credential_mode": self.credential_mode,
            "request_count": self.request_count,
            "requests": [request.to_jsonable() for request in self.requests],
            "limits": {
                "max_requests_per_run": self.max_requests_per_run,
                "max_requests_per_minute": self.max_requests_per_minute,
                "max_pages_per_endpoint": self.max_pages_per_endpoint,
                "max_items_per_endpoint": self.max_items_per_endpoint,
                "max_bytes_per_run": self.max_bytes_per_run,
                "max_concurrent_requests": self.max_concurrent_requests,
                "max_retries": self.max_retries,
            },
            "retention_policy": self.retention_policy,
            "redaction_profile": self.redaction_profile,
            "sensitivity": self.sensitivity,
            "manifest_sha256": self.manifest_sha256,
            "network_capable": self.network_capable,
            "no_network": self.no_network,
            "no_mutation": self.no_mutation,
            "no_credentials_resolved": self.no_credentials_resolved,
            "no_scheduler": self.no_scheduler,
            "fixture_transport_only": self.fixture_transport_only,
        }


@dataclass(frozen=True)
class GitHubTransportResponse:
    status_code: int
    body: bytes
    response_type: str = "application/json"
    headers: Mapping[str, str] = field(default_factory=dict)
    rate_limit: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GitHubResponseRecord:
    endpoint_name: str
    method: str
    path_template: str
    response_type: str
    data_class: str
    status_code: int
    response_byte_count: int
    response_sha256: str
    artifact_path: str
    transport: str
    redacted: bool
    redaction_profile: str
    retention_policy: str
    downstream_route: str
    rate_limit: Mapping[str, str] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "endpoint_name": self.endpoint_name,
            "method": self.method,
            "path_template": self.path_template,
            "response_type": self.response_type,
            "data_class": self.data_class,
            "status_code": self.status_code,
            "response_byte_count": self.response_byte_count,
            "response_sha256": self.response_sha256,
            "artifact_path": self.artifact_path,
            "transport": self.transport,
            "redacted": self.redacted,
            "redaction_profile": self.redaction_profile,
            "retention_policy": self.retention_policy,
            "downstream_route": self.downstream_route,
            "rate_limit": dict(self.rate_limit),
        }


@dataclass(frozen=True)
class GitHubApiAcquireSummary:
    source_id: str
    source_type: str
    api_source_class: str
    provider_name: str
    provider_product: str
    policy_status: str
    owner: str
    repository: str
    repository_visibility: str
    transport: str
    credential_mode: str
    api_run_id: str
    api_manifest_id: str
    requests: int
    responses: int
    observations: int
    raw_observations: tuple[RawObservation, ...]
    output_path: Path
    output_path_summary: str
    manifest: GitHubApiPlanManifest
    response_records: tuple[GitHubResponseRecord, ...]
    publication: NonPublicationResult
    no_network: bool = True
    no_mutation: bool = True
    no_credentials_resolved: bool = True
    no_scheduler: bool = True
    network_capable: bool = False
    fixture_transport_only: bool = True

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "api_source_class": self.api_source_class,
            "provider_name": self.provider_name,
            "provider_product": self.provider_product,
            "policy_status": self.policy_status,
            "owner": self.owner,
            "repository": self.repository,
            "repository_visibility": self.repository_visibility,
            "transport": self.transport,
            "credential_mode": self.credential_mode,
            "api_run_id": self.api_run_id,
            "api_manifest_id": self.api_manifest_id,
            "requests": self.requests,
            "responses": self.responses,
            "observations": self.observations,
            "output_path": self.output_path_summary,
            "publication": self.publication.to_jsonable(),
            "response_records": [
                record.to_jsonable() for record in self.response_records
            ],
            "no_network": self.no_network,
            "no_mutation": self.no_mutation,
            "no_credentials_resolved": self.no_credentials_resolved,
            "no_scheduler": self.no_scheduler,
            "network_capable": self.network_capable,
            "fixture_transport_only": self.fixture_transport_only,
        }
