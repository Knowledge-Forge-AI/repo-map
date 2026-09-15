"""API manifest summary records and payload decoders."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.row_helpers import (
    manifest_int,
    manifest_list,
    optional_manifest_text,
    payload_bool,
    payload_count_map,
    payload_int,
    payload_optional_text,
    payload_string_tuple,
    payload_text,
)

__all__ = (
    "APISummaryRecord",
    "api_manifest_summary_payload",
    "read_api_manifest_payloads",
    "api_summary_from_storage_payload",
)


@dataclass(frozen=True)
class APISummaryRecord:
    root_path_summary: str
    repository_name: str | None
    api_runs: int
    sources: int
    source_ids: tuple[str, ...]
    source_types: dict[str, int]
    api_source_classes: dict[str, int]
    provider_names: dict[str, int]
    provider_products: dict[str, int]
    policy_statuses: dict[str, int]
    requests: int
    responses: int
    endpoints: int
    endpoint_names: tuple[str, ...]
    methods: dict[str, int]
    downstream_routes: dict[str, int]
    response_types: dict[str, int]
    response_byte_count: int
    redacted_responses: int
    diagnostic_counts: dict[str, int]
    routed_artifacts: int
    observations_with_api_provenance: int
    config_documents_from_api: int
    no_network: bool
    no_mutation: bool
    no_credentials_resolved: bool
    no_scheduler: bool
    no_provider_specific_behavior: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def api_manifest_summary_payload(root_path: Path) -> dict[str, Any]:
    resolved_root = root_path.resolve()
    run_root = resolved_root / ".repomap" / "api-runs"
    manifests = read_api_manifest_payloads(run_root, root_path=resolved_root)
    source_ids: set[str] = set()
    run_ids: set[str] = set()
    endpoint_names: set[str] = set()
    source_types: Counter[str] = Counter()
    api_source_classes: Counter[str] = Counter()
    provider_names: Counter[str] = Counter()
    provider_products: Counter[str] = Counter()
    policy_statuses: Counter[str] = Counter()
    methods: Counter[str] = Counter()
    downstream_routes: Counter[str] = Counter()
    response_types: Counter[str] = Counter()
    diagnostic_counts: Counter[str] = Counter()
    request_count = 0
    response_count = 0
    response_byte_count = 0
    redacted_responses = 0
    routed_artifacts = 0
    no_network = True
    no_mutation = True
    no_credentials_resolved = True
    no_scheduler = True

    for manifest in manifests:
        if manifest.get("_manifest_parse_error"):
            diagnostic_counts["manifest_parse_error"] += 1
            continue
        source_id = optional_manifest_text(manifest, "source_id")
        run_id = optional_manifest_text(manifest, "api_run_id")
        source_type = optional_manifest_text(manifest, "source_type")
        api_source_class = optional_manifest_text(manifest, "api_source_class")
        provider_name = optional_manifest_text(manifest, "provider_name")
        provider_product = optional_manifest_text(manifest, "provider_product")
        policy_status = optional_manifest_text(manifest, "policy_status")
        if source_id is not None:
            source_ids.add(source_id)
        if run_id is not None:
            run_ids.add(run_id)
        if source_type is not None:
            source_types[source_type] += 1
        if api_source_class is not None:
            api_source_classes[api_source_class] += 1
        if provider_name is not None:
            provider_names[provider_name] += 1
        if provider_product is not None:
            provider_products[provider_product] += 1
        if policy_status is not None:
            policy_statuses[policy_status] += 1
        if manifest.get("no_network") is False:
            no_network = False
        if manifest.get("no_mutation") is False:
            no_mutation = False
        if manifest.get("no_credentials_resolved") is False:
            no_credentials_resolved = False
        if manifest.get("no_scheduler") is False:
            no_scheduler = False
        for request in manifest_list(manifest.get("requests")):
            request_count += 1
            endpoint_name = optional_manifest_text(request, "endpoint_name")
            method = optional_manifest_text(request, "method")
            downstream_route = optional_manifest_text(request, "downstream_route")
            response_type = optional_manifest_text(request, "response_type")
            if endpoint_name is not None:
                endpoint_names.add(endpoint_name)
            if method is not None:
                methods[method] += 1
            if downstream_route is not None:
                downstream_routes[downstream_route] += 1
            if response_type is not None:
                response_types[response_type] += 1
        for response in manifest_list(manifest.get("responses")):
            response_count += 1
            endpoint_name = optional_manifest_text(response, "endpoint_name")
            if endpoint_name is not None:
                endpoint_names.add(endpoint_name)
            response_byte_count += manifest_int(response, "response_byte_count")
            if response.get("redacted") is True:
                redacted_responses += 1
            if optional_manifest_text(response, "artifact_path") is not None:
                routed_artifacts += 1

    return {
        "root_path_summary": ".",
        "repository_name": None,
        "api_runs": len(run_ids),
        "sources": len(source_ids),
        "source_ids": sorted(source_ids),
        "source_types": dict(sorted(source_types.items())),
        "api_source_classes": dict(sorted(api_source_classes.items())),
        "provider_names": dict(sorted(provider_names.items())),
        "provider_products": dict(sorted(provider_products.items())),
        "policy_statuses": dict(sorted(policy_statuses.items())),
        "requests": request_count,
        "responses": response_count,
        "endpoints": len(endpoint_names),
        "endpoint_names": sorted(endpoint_names),
        "methods": dict(sorted(methods.items())),
        "downstream_routes": dict(sorted(downstream_routes.items())),
        "response_types": dict(sorted(response_types.items())),
        "response_byte_count": response_byte_count,
        "redacted_responses": redacted_responses,
        "diagnostic_counts": dict(sorted(diagnostic_counts.items())),
        "routed_artifacts": routed_artifacts,
        "observations_with_api_provenance": 0,
        "config_documents_from_api": 0,
        "no_network": no_network,
        "no_mutation": no_mutation,
        "no_credentials_resolved": no_credentials_resolved,
        "no_scheduler": no_scheduler,
        "no_provider_specific_behavior": True,
    }


def read_api_manifest_payloads(
    run_root: Path,
    *,
    root_path: Path,
) -> tuple[dict[str, Any], ...]:
    if not run_root.is_dir():
        return ()
    resolved_run_root = run_root.resolve()
    try:
        resolved_run_root.relative_to(root_path)
    except ValueError:
        return ({"_manifest_parse_error": True},)
    payloads: list[dict[str, Any]] = []
    for manifest_path in sorted(run_root.glob("*/*/manifest.json")):
        try:
            resolved_manifest = manifest_path.resolve()
            resolved_manifest.relative_to(resolved_run_root)
            payload = json.loads(resolved_manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            payloads.append({"_manifest_parse_error": True})
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
        else:
            payloads.append({"_manifest_parse_error": True})
    return tuple(payloads)


def api_summary_from_storage_payload(payload: Any) -> APISummaryRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed api summary")
    return APISummaryRecord(
        root_path_summary=payload_text(
            payload,
            "root_path_summary",
            label="api summary",
        ),
        repository_name=payload_optional_text(
            payload,
            "repository_name",
            label="api summary",
        ),
        api_runs=payload_int(payload, "api_runs", label="api summary"),
        sources=payload_int(payload, "sources", label="api summary"),
        source_ids=payload_string_tuple(
            payload,
            "source_ids",
            label="api summary",
        ),
        source_types=payload_count_map(
            payload,
            "source_types",
            label="api summary",
        ),
        api_source_classes=payload_count_map(
            payload,
            "api_source_classes",
            label="api summary",
        ),
        provider_names=payload_count_map(
            payload,
            "provider_names",
            label="api summary",
        ),
        provider_products=payload_count_map(
            payload,
            "provider_products",
            label="api summary",
        ),
        policy_statuses=payload_count_map(
            payload,
            "policy_statuses",
            label="api summary",
        ),
        requests=payload_int(payload, "requests", label="api summary"),
        responses=payload_int(payload, "responses", label="api summary"),
        endpoints=payload_int(payload, "endpoints", label="api summary"),
        endpoint_names=payload_string_tuple(
            payload,
            "endpoint_names",
            label="api summary",
        ),
        methods=payload_count_map(payload, "methods", label="api summary"),
        downstream_routes=payload_count_map(
            payload,
            "downstream_routes",
            label="api summary",
        ),
        response_types=payload_count_map(
            payload,
            "response_types",
            label="api summary",
        ),
        response_byte_count=payload_int(
            payload,
            "response_byte_count",
            label="api summary",
        ),
        redacted_responses=payload_int(
            payload,
            "redacted_responses",
            label="api summary",
        ),
        diagnostic_counts=payload_count_map(
            payload,
            "diagnostic_counts",
            label="api summary",
        ),
        routed_artifacts=payload_int(
            payload,
            "routed_artifacts",
            label="api summary",
        ),
        observations_with_api_provenance=payload_int(
            payload,
            "observations_with_api_provenance",
            label="api summary",
        ),
        config_documents_from_api=payload_int(
            payload,
            "config_documents_from_api",
            label="api summary",
        ),
        no_network=payload_bool(payload, "no_network", label="api summary"),
        no_mutation=payload_bool(payload, "no_mutation", label="api summary"),
        no_credentials_resolved=payload_bool(
            payload,
            "no_credentials_resolved",
            label="api summary",
        ),
        no_scheduler=payload_bool(payload, "no_scheduler", label="api summary"),
        no_provider_specific_behavior=payload_bool(
            payload,
            "no_provider_specific_behavior",
            label="api summary",
        ),
    )
