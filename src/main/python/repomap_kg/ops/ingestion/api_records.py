"""Documented API acquisition record and manifest contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion.acquisition_contracts import NonPublicationResult


class ApiPolicyError(ValueError):
    """Raised when an API source config is not explicitly allowed and bounded."""


@dataclass(frozen=True)
class ApiEndpointConfig:
    name: str
    method: str
    path: str
    purpose: str
    response_type: str
    max_page_size: int
    pagination: str
    downstream_route: str
    fixture_response_path: str

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
        }


@dataclass(frozen=True)
class ApiSourceConfig:
    config_path: Path
    source_id: str
    source_type: str
    api_source_class: str
    provider_name: str
    provider_product: str
    policy_status: str
    read_only: bool
    mutation_allowed: bool
    credentials_ref: str
    consent_ref: str
    authorized_operations: tuple[str, ...]
    authorized_data_classes: tuple[str, ...]
    consent_revoked: bool
    consent_mutation_allowed: bool
    max_requests_per_run: int
    max_requests_per_minute: int
    max_concurrent_requests: int
    max_bytes_per_run: int
    max_items_per_run: int
    max_retries: int
    retention_policy: str
    raw_response_retention: str
    redacted_response_retention: str
    redaction_profile: str
    sensitivity: str
    endpoints: tuple[ApiEndpointConfig, ...]


@dataclass(frozen=True)
class ApiRequestPlan:
    endpoint_name: str
    method: str
    path: str
    response_type: str
    downstream_route: str
    request_id: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "endpoint_name": self.endpoint_name,
            "method": self.method,
            "path": self.path,
            "response_type": self.response_type,
            "downstream_route": self.downstream_route,
            "request_id": self.request_id,
        }


@dataclass(frozen=True)
class ApiPlanManifest:
    source_id: str
    source_type: str
    api_source_class: str
    provider_name: str
    provider_product: str
    policy_status: str
    api_run_id: str
    api_manifest_id: str
    requests: tuple[ApiRequestPlan, ...]
    max_requests_per_run: int
    max_requests_per_minute: int
    max_concurrent_requests: int
    max_bytes_per_run: int
    max_items_per_run: int
    max_retries: int
    retention_policy: str
    redaction_profile: str
    sensitivity: str
    manifest_sha256: str = ""
    no_network: bool = True
    no_mutation: bool = True
    no_credentials_resolved: bool = True
    no_scheduler: bool = True

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
            "request_count": self.request_count,
            "requests": [request.to_jsonable() for request in self.requests],
            "limits": {
                "max_requests_per_run": self.max_requests_per_run,
                "max_requests_per_minute": self.max_requests_per_minute,
                "max_concurrent_requests": self.max_concurrent_requests,
                "max_bytes_per_run": self.max_bytes_per_run,
                "max_items_per_run": self.max_items_per_run,
                "max_retries": self.max_retries,
            },
            "retention_policy": self.retention_policy,
            "redaction_profile": self.redaction_profile,
            "sensitivity": self.sensitivity,
            "manifest_sha256": self.manifest_sha256,
            "no_network": self.no_network,
            "no_mutation": self.no_mutation,
            "no_credentials_resolved": self.no_credentials_resolved,
            "no_scheduler": self.no_scheduler,
        }


@dataclass(frozen=True)
class ApiTransportResponse:
    status_code: int
    body: bytes
    response_type: str


@dataclass(frozen=True)
class ApiResponseRecord:
    endpoint_name: str
    method: str
    path_template: str
    response_type: str
    status_code: int
    response_byte_count: int
    response_sha256: str
    artifact_path: str
    redacted: bool
    redaction_profile: str
    retention_policy: str
    downstream_route: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "endpoint_name": self.endpoint_name,
            "method": self.method,
            "path_template": self.path_template,
            "response_type": self.response_type,
            "status_code": self.status_code,
            "response_byte_count": self.response_byte_count,
            "response_sha256": self.response_sha256,
            "artifact_path": self.artifact_path,
            "redacted": self.redacted,
            "redaction_profile": self.redaction_profile,
            "retention_policy": self.retention_policy,
            "downstream_route": self.downstream_route,
        }


@dataclass(frozen=True)
class ApiAcquireSummary:
    source_id: str
    source_type: str
    api_source_class: str
    provider_name: str
    provider_product: str
    policy_status: str
    api_run_id: str
    api_manifest_id: str
    requests: int
    responses: int
    observations: int
    raw_observations: tuple[RawObservation, ...]
    output_path: Path
    output_path_summary: str
    manifest: ApiPlanManifest
    response_records: tuple[ApiResponseRecord, ...]
    publication: NonPublicationResult

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "api_source_class": self.api_source_class,
            "provider_name": self.provider_name,
            "provider_product": self.provider_product,
            "policy_status": self.policy_status,
            "api_run_id": self.api_run_id,
            "api_manifest_id": self.api_manifest_id,
            "requests": self.requests,
            "responses": self.responses,
            "observations": self.observations,
            "output_path": self.output_path_summary,
            "publication": self.publication.to_jsonable(),
            "manifest": self.manifest.to_jsonable(),
            "response_records": [record.to_jsonable() for record in self.response_records],
            "no_network": True,
            "no_mutation": True,
            "no_credentials_resolved": True,
            "no_scheduler": True,
        }
