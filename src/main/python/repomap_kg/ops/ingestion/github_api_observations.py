"""Observation projection for acquired GitHub API records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from repomap_kg.graph.discovery import (
    classify_path,
    extract_config_file_observations_from_file,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion.github_api_helpers import (
    EXTRACTOR,
    EXTRACTOR_VERSION,
    GITHUB_ENDPOINT_KINDS,
)
from repomap_kg.ops.ingestion.github_api_records import (
    GitHubApiPlanManifest,
    GitHubApiSourceConfig,
    GitHubResponseRecord,
)


def github_api_observations_from_records(
    config: GitHubApiSourceConfig,
    manifest: GitHubApiPlanManifest,
    *,
    response_records: Sequence[GitHubResponseRecord],
    redacted_payloads: Mapping[str, Any],
    repository_root: Path,
    output_path: Path,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    observations.extend(
        github_api_provenance_observations(config, manifest, response_records)
    )
    for record in response_records:
        payload = redacted_payloads.get(record.endpoint_name)
        observations.extend(
            github_provider_observations(
                config,
                manifest,
                record=record,
                payload=payload,
            )
        )
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
            annotate_github_observation(
                observation,
                config=config,
                manifest=manifest,
                record=record,
            )
            for observation in routed
        )
    return tuple(observations)


def github_api_provenance_observations(
    config: GitHubApiSourceConfig,
    manifest: GitHubApiPlanManifest,
    response_records: Sequence[GitHubResponseRecord],
) -> tuple[RawObservation, ...]:
    base_metadata = github_base_metadata(config, manifest)
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
    for request in manifest.requests:
        observations.append(
            RawObservation(
                kind="api.request",
                source_id=(
                    f"{config.source_id}#{manifest.api_run_id}"
                    f"#{request.endpoint_name}#request"
                ),
                path=".repomap/api-runs",
                confidence="extracted",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                name=request.endpoint_name,
                metadata={**base_metadata, **request.to_jsonable()},
            )
        )
    for record in response_records:
        observations.append(
            RawObservation(
                kind="api.response",
                source_id=(
                    f"{config.source_id}#{manifest.api_run_id}"
                    f"#{record.endpoint_name}#response"
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
        observations.append(
            RawObservation(
                kind="api.artifact",
                source_id=(
                    f"{config.source_id}#{manifest.api_run_id}"
                    f"#{record.endpoint_name}#artifact"
                ),
                path=".repomap/api-runs",
                confidence="extracted",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                name=record.artifact_path,
                metadata={
                    **base_metadata,
                    "endpoint_name": record.endpoint_name,
                    "artifact_path": record.artifact_path,
                    "redacted": record.redacted,
                    "downstream_route": record.downstream_route,
                },
            )
        )
    return tuple(observations)


def github_provider_observations(
    config: GitHubApiSourceConfig,
    manifest: GitHubApiPlanManifest,
    *,
    record: GitHubResponseRecord,
    payload: Any,
) -> tuple[RawObservation, ...]:
    kind = GITHUB_ENDPOINT_KINDS.get(record.endpoint_name)
    if kind is None:
        return ()
    items = github_observation_items(record.endpoint_name, payload)
    observations: list[RawObservation] = []
    base_metadata = {
        **github_base_metadata(config, manifest),
        **record.to_jsonable(),
    }
    for index, item in enumerate(items):
        item_metadata = item if isinstance(item, dict) else {"value": item}
        safe_name = github_item_name(record.endpoint_name, item, index)
        observations.append(
            RawObservation(
                kind=kind,
                source_id=(
                    f"{config.source_id}#{manifest.api_run_id}"
                    f"#{record.endpoint_name}#{index}"
                ),
                path=".repomap/api-runs",
                confidence="extracted",
                extractor=EXTRACTOR,
                extractor_version=EXTRACTOR_VERSION,
                name=safe_name,
                metadata={**base_metadata, "github_item": item_metadata},
            )
        )
    return tuple(observations)


def github_observation_items(endpoint_name: str, payload: Any) -> tuple[Any, ...]:
    if endpoint_name == "repository":
        return (payload,)
    if endpoint_name == "actions_runs" and isinstance(payload, dict):
        runs = payload.get("workflow_runs")
        if isinstance(runs, list):
            return tuple(runs)
    if isinstance(payload, list):
        return tuple(payload)
    return (payload,)


def github_item_name(endpoint_name: str, item: Any, index: int) -> str:
    if isinstance(item, dict):
        for key in ("full_name", "number", "tag_name", "id", "name"):
            value = item.get(key)
            if isinstance(value, (str, int)):
                return str(value)
    return f"{endpoint_name}:{index}"


def annotate_github_observation(
    observation: RawObservation,
    *,
    config: GitHubApiSourceConfig,
    manifest: GitHubApiPlanManifest,
    record: GitHubResponseRecord,
) -> RawObservation:
    metadata = dict(observation.metadata)
    metadata.update(
        {
            "source_id": config.source_id,
            "source_type": config.source_type,
            "api_source_class": config.api_source_class,
            "provider_name": config.provider_name,
            "provider_product": config.provider_product,
            "owner": config.owner,
            "repository": config.repository,
            "repository_visibility": config.repository_visibility,
            "transport": config.acquisition_transport,
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


def github_base_metadata(
    config: GitHubApiSourceConfig,
    manifest: GitHubApiPlanManifest,
) -> dict[str, Any]:
    return {
        "source_id": config.source_id,
        "source_type": config.source_type,
        "api_source_class": config.api_source_class,
        "provider_name": config.provider_name,
        "provider_product": config.provider_product,
        "owner": config.owner,
        "repository": config.repository,
        "repository_visibility": config.repository_visibility,
        "transport": config.acquisition_transport,
        "credential_mode": config.credential_mode,
        "api_run_id": manifest.api_run_id,
        "api_manifest_id": manifest.api_manifest_id,
        "api_policy_status": config.policy_status,
        "api_retention_policy": config.retention_policy,
        "api_sensitivity": config.sensitivity,
        "redaction_profile": config.redaction_profile,
        "network_capable": config.acquisition_transport == "github_public_rest",
        "no_network": config.acquisition_transport == "fixture",
        "no_mutation": True,
        "no_credentials_resolved": True,
        "no_scheduler": True,
        "fixture_transport_only": config.acquisition_transport == "fixture",
    }
