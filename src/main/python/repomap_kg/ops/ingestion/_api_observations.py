"""Observation generation and artifact writing for documented REST API ingestion."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from repomap_kg.graph.discovery import (
    classify_path,
    extract_config_file_observations_from_file,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion._api_helpers import (
    ensure_contained,
    redact_value,
    safe_artifact_name,
    sha256_bytes,
    write_json,
    write_jsonl,
)
from repomap_kg.ops.ingestion.api_records import (
    ApiPlanManifest,
    ApiRequestPlan,
    ApiResponseRecord,
    ApiSourceConfig,
    ApiTransportResponse,
)

EXTRACTOR = "api-documented-rest-ingestion"
EXTRACTOR_VERSION = "0.1.0"


def api_observations_from_records(
    config: ApiSourceConfig,
    manifest: ApiPlanManifest,
    *,
    response_records: Sequence[ApiResponseRecord],
    repository_root: Path,
    output_path: Path,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    observations.extend(api_provenance_observations(config, manifest, response_records))
    for record in response_records:
        if record.downstream_route != "config":
            continue
        artifact_path = output_path / record.artifact_path
        file_info = classify_path(repository_root, artifact_path)
        routed: list[RawObservation] = [file_info.to_observation()]
        routed.extend(
            extract_config_file_observations_from_file(
                repository_root,
                file_info.path,
            )
        )
        observations.extend(
            annotate_observation(
                observation,
                config=config,
                manifest=manifest,
                record=record,
            )
            for observation in routed
        )
    return tuple(observations)


def api_provenance_observations(
    config: ApiSourceConfig,
    manifest: ApiPlanManifest,
    response_records: Sequence[ApiResponseRecord],
) -> tuple[RawObservation, ...]:
    base_metadata = {
        "source_id": config.source_id,
        "source_type": config.source_type,
        "api_source_class": config.api_source_class,
        "provider_name": config.provider_name,
        "provider_product": config.provider_product,
        "api_run_id": manifest.api_run_id,
        "api_manifest_id": manifest.api_manifest_id,
        "api_policy_status": config.policy_status,
        "api_retention_policy": config.retention_policy,
        "api_sensitivity": config.sensitivity,
        "redaction_profile": config.redaction_profile,
        "no_network": True,
        "no_mutation": True,
        "no_credentials_resolved": True,
    }
    observations = [
        RawObservation(
            kind="api.source",
            source_id=f"{config.source_id}#api-source",
            path=".repomap/api-runs",
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=EXTRACTOR_VERSION,
            name=config.source_id,
            metadata=base_metadata,
        ),
        RawObservation(
            kind="api.run",
            source_id=f"{config.source_id}#{manifest.api_run_id}",
            path=".repomap/api-runs",
            confidence="extracted",
            extractor=EXTRACTOR,
            extractor_version=EXTRACTOR_VERSION,
            name=manifest.api_run_id,
            metadata={**base_metadata, "request_count": manifest.request_count},
        ),
    ]
    for record in response_records:
        observations.append(
            RawObservation(
                kind="api.response",
                source_id=(
                    f"{config.source_id}#{manifest.api_run_id}"
                    f"#{record.endpoint_name}"
                ),
                path=".repomap/api-runs",
                confidence="extracted",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                name=record.endpoint_name,
                metadata={
                    **base_metadata,
                    **record.to_jsonable(),
                },
            )
        )
    return tuple(observations)


def annotate_observation(
    observation: RawObservation,
    *,
    config: ApiSourceConfig,
    manifest: ApiPlanManifest,
    record: ApiResponseRecord,
) -> RawObservation:
    metadata = dict(observation.metadata)
    metadata.update(
        {
            "source_id": config.source_id,
            "source_type": config.source_type,
            "api_source_class": config.api_source_class,
            "provider_name": config.provider_name,
            "provider_product": config.provider_product,
            "api_run_id": manifest.api_run_id,
            "api_manifest_id": manifest.api_manifest_id,
            "endpoint_name": record.endpoint_name,
            "method": record.method,
            "path_template": record.path_template,
            "downstream_route": record.downstream_route,
            "api_policy_status": config.policy_status,
            "api_retention_policy": config.retention_policy,
            "api_sensitivity": config.sensitivity,
        }
    )
    return replace(observation, metadata=metadata)


def write_api_run_files(
    config: ApiSourceConfig,
    manifest: ApiPlanManifest,
    *,
    fetched: Sequence[tuple[ApiRequestPlan, ApiTransportResponse, Any]],
    repository_root: Path,
) -> tuple[Path, tuple[ApiResponseRecord, ...]]:
    output_path = (
        repository_root
        / ".repomap"
        / "api-runs"
        / config.source_id
        / manifest.api_run_id
    ).resolve()
    ensure_contained(output_path, repository_root, "api output path")
    artifacts_path = output_path / "artifacts"
    artifacts_path.mkdir(parents=True, exist_ok=True)
    records: list[ApiResponseRecord] = []
    for request, response, parsed in fetched:
        redacted_payload = redact_value(parsed)
        artifact_name = safe_artifact_name(request.endpoint_name, request.response_type)
        artifact_path = artifacts_path / artifact_name
        write_json(artifact_path, redacted_payload)
        relative_artifact = artifact_path.relative_to(output_path).as_posix()
        records.append(
            ApiResponseRecord(
                endpoint_name=request.endpoint_name,
                method=request.method,
                path_template=request.path,
                response_type=request.response_type,
                status_code=response.status_code,
                response_byte_count=len(response.body),
                response_sha256=sha256_bytes(response.body),
                artifact_path=relative_artifact,
                redacted=True,
                redaction_profile=config.redaction_profile,
                retention_policy=config.retention_policy,
                downstream_route=request.downstream_route,
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
    return output_path, tuple(records)
