"""OpenAPI component, schema, and security-scheme observations."""

from __future__ import annotations

from typing import Any

from repomap_kg.extractors.config.openapi_helpers import (
    _openapi_oauth_flow_names,
    _openapi_safe_string,
    _openapi_scope_names,
    _openapi_source_suffix,
    _profile_observation,
)
from repomap_kg.extractors.config.paths import json_pointer
from repomap_kg.graph.keys import config_path_key
from repomap_kg.observations.raw import RawObservation


def _openapi_component_observations(
    relative_path: str,
    components: dict[str, dict[str, Any]],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_prefix: tuple[str, ...],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for component_type in sorted(components):
        entries = components[component_type]
        if not isinstance(entries, dict):
            continue
        for component_name in sorted(str(key) for key in entries):
            component = entries.get(component_name)
            if not isinstance(component, dict):
                continue
            pointer_segments = (
                (*pointer_prefix, component_type, component_name)
                if spec_metadata["spec_family"] == "swagger2"
                else (*pointer_prefix, "components", component_type, component_name)
            )
            pointer = json_pointer(pointer_segments)
            metadata = {
                **spec_metadata,
                "component_type": component_type,
                "component_name": _openapi_safe_string(component_name),
                "source_path_key": config_path_key(relative_path, pointer),
            }
            observations.append(
                _profile_observation(
                    "openapi.component",
                    relative_path,
                    profile=profile,
                    format_name=format_name,
                    confidence=confidence,
                    metadata=metadata,
                    name=_openapi_safe_string(component_name),
                    source_suffix=_openapi_source_suffix("component", pointer),
                )
            )
            if component_type in ("schemas", "definitions"):
                observations.append(
                    _profile_observation(
                        "openapi.schema",
                        relative_path,
                        profile=profile,
                        format_name=format_name,
                        confidence=confidence,
                        metadata={
                            **metadata,
                            "schema_name": _openapi_safe_string(component_name),
                            "schema_type": _openapi_safe_string(component.get("type")),
                            "property_count": len(component.get("properties", {}))
                            if isinstance(component.get("properties"), dict)
                            else 0,
                        },
                        name=_openapi_safe_string(component_name),
                        source_suffix=_openapi_source_suffix("schema", pointer),
                    )
                )
            if component_type in ("securitySchemes", "securityDefinitions"):
                observations.append(
                    _profile_observation(
                        "openapi.security_scheme",
                        relative_path,
                        profile=profile,
                        format_name=format_name,
                        confidence=confidence,
                        metadata={
                            **metadata,
                            "scheme_name": _openapi_safe_string(component_name),
                            "type": _openapi_safe_string(component.get("type")),
                            "in": _openapi_safe_string(component.get("in")),
                            "name_present": isinstance(component.get("name"), str),
                            "scheme": _openapi_safe_string(component.get("scheme")),
                            "bearer_format": _openapi_safe_string(
                                component.get("bearerFormat")
                            ),
                            "oauth_flow_names": _openapi_oauth_flow_names(component),
                            "scope_names": _openapi_scope_names(component),
                        },
                        name=_openapi_safe_string(component_name),
                        source_suffix=_openapi_source_suffix("security", pointer),
                    )
                )
    return observations
