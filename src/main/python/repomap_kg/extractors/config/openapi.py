"""OpenAPI/Swagger configuration raw observation extraction."""

from __future__ import annotations

from typing import Any

from repomap_kg.extractors.config.paths import _pointer_segments, json_pointer
from repomap_kg.graph.keys import (
    config_document_key,
    config_path_key,
)
from repomap_kg.observations.raw import RawObservation

from repomap_kg.extractors.config._openapi_components import (
    _openapi_component_observations,
)
from repomap_kg.extractors.config.openapi_helpers import (
    OPENAPI_EXAMPLE_KEYS,
    OPENAPI_HTTP_METHODS,
    OPENAPI_MAX_EXAMPLES,
    OPENAPI_MAX_METADATA_STRING,
    OPENAPI_MAX_OPERATIONS,
    OPENAPI_MAX_PARAMETERS_PER_OPERATION,
    OPENAPI_MAX_PATHS,
    OPENAPI_MAX_REFERENCES,
    OPENAPI_MAX_RESPONSES_PER_OPERATION,
    OPENAPI_MAX_SCHEMAS,
    OPENAPI_TEXT_KEYS,
    _extractor_name,
    _file_reference,
    _generic_helper,
    _is_openapi_document,
    _is_openapi_file_name,
    _is_url,
    _looks_like_secret_scalar,
    _normalized_key,
    _openapi_bounded_string,
    _openapi_components,
    _openapi_media_types,
    _openapi_oauth_flow_names,
    _openapi_operation_count,
    _openapi_parameters,
    _openapi_parse_error_observation,
    _openapi_pointer_is_redacted,
    _openapi_redaction_reason,
    _openapi_ref_values,
    _openapi_reference_metadata,
    _openapi_reference_scope,
    _openapi_safe_string,
    _openapi_scope_names,
    _openapi_sensitive_key,
    _openapi_server_count,
    _openapi_source_suffix,
    _openapi_string_list,
    _openapi_text_metadata,
    _openapi_url_metadata,
    _openapi_walk,
    _profile_observation,
    _safe_error_message,
    _secret_prone_keys,
    _stable_text_sha256,
    _stable_value_sha256,
    _url_has_credentials,
    _value_shape,
    _value_type,
    _yaml_documents,
    _yaml_format,
)


def _openapi_profile_observations(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
    confidence: str,
    profile: str,
    document_count: int = 1,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for document_index, document in enumerate(
        _yaml_documents(value, document_count=document_count)
        if format_name == _yaml_format()
        else (value,)
    ):
        document_pointer_prefix = (
            ("documents", str(document_index))
            if format_name == _yaml_format() and document_count > 1
            else ()
        )
        if not isinstance(document, dict) or not _is_openapi_document(document):
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="unsupported-openapi-document",
                    message="OpenAPI profile file lacks a supported OpenAPI/Swagger object",
                    document_index=(
                        document_index if document_count > 1 else None
                    ),
                )
            )
            continue

        spec_metadata = _openapi_spec_metadata(document)
        if spec_metadata is None:
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="unsupported-openapi-version",
                    message="OpenAPI/Swagger version is unsupported",
                    document_index=(
                        document_index if document_count > 1 else None
                    ),
                )
            )
            continue

        paths = document.get("paths")
        paths_dict = paths if isinstance(paths, dict) else {}
        if len(paths_dict) > OPENAPI_MAX_PATHS:
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="openapi-path-limit",
                    message="OpenAPI path count exceeds OPENAPI1 limit",
                    document_index=(
                        document_index if document_count > 1 else None
                    ),
                )
            )
            continue

        operation_count = _openapi_operation_count(paths_dict)
        if operation_count > OPENAPI_MAX_OPERATIONS:
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="openapi-operation-limit",
                    message="OpenAPI operation count exceeds OPENAPI1 limit",
                    document_index=(
                        document_index if document_count > 1 else None
                    ),
                )
            )
            continue

        components = _openapi_components(document, spec_metadata["spec_family"])
        schema_count = len(components.get("schemas", {}))
        if schema_count > OPENAPI_MAX_SCHEMAS:
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="openapi-schema-limit",
                    message="OpenAPI schema count exceeds OPENAPI1 limit",
                    document_index=(
                        document_index if document_count > 1 else None
                    ),
                )
            )
            continue

        observations.append(
            _profile_observation(
                "openapi.document",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata={
                    **spec_metadata,
                    "source_document_key": config_document_key(relative_path),
                    "document_index": (
                        document_index if document_count > 1 else None
                    ),
                    "path_count": len(paths_dict),
                    "operation_count": operation_count,
                    "schema_count": schema_count,
                    "server_count": _openapi_server_count(document, spec_metadata["spec_family"]),
                    "raw_profile_only": True,
                },
                source_suffix=_openapi_source_suffix(
                    "document", json_pointer(document_pointer_prefix)
                ),
            )
        )
        observations.extend(
            _openapi_info_observations(
                relative_path,
                document,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                spec_metadata=spec_metadata,
                pointer_prefix=document_pointer_prefix,
            )
        )
        observations.extend(
            _openapi_server_observations(
                relative_path,
                document,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                spec_metadata=spec_metadata,
                pointer_prefix=document_pointer_prefix,
            )
        )
        observations.extend(
            _openapi_path_operation_observations(
                relative_path,
                paths_dict,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                spec_metadata=spec_metadata,
                pointer_prefix=(*document_pointer_prefix, "paths"),
            )
        )
        observations.extend(
            _openapi_component_observations(
                relative_path,
                components,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                spec_metadata=spec_metadata,
                pointer_prefix=document_pointer_prefix,
            )
        )
        observations.extend(
            _openapi_reference_observations(
                relative_path,
                document,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                spec_metadata=spec_metadata,
                pointer_prefix=document_pointer_prefix,
            )
        )
        observations.extend(
            _openapi_example_and_redaction_observations(
                relative_path,
                document,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                spec_metadata=spec_metadata,
                pointer_prefix=document_pointer_prefix,
            )
        )
    return observations
def _openapi_spec_metadata(value: dict[str, Any]) -> dict[str, str] | None:
    openapi_version = value.get("openapi")
    if isinstance(openapi_version, str) and openapi_version.startswith("3."):
        return {"spec_family": "openapi3", "spec_version": openapi_version}
    swagger_version = value.get("swagger")
    if str(swagger_version) == "2.0":
        return {"spec_family": "swagger2", "spec_version": "2.0"}
    return None


def _openapi_info_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_prefix: tuple[str, ...],
) -> list[RawObservation]:
    info = value.get("info")
    if not isinstance(info, dict):
        return []
    description = info.get("description")
    metadata: dict[str, Any] = {
        **spec_metadata,
        "source_document_key": config_document_key(relative_path),
        "title": _openapi_safe_string(info.get("title")),
        "version": _openapi_safe_string(info.get("version")),
        **_openapi_text_metadata(description, "description"),
    }
    pointer = json_pointer((*pointer_prefix, "info"))
    return [
        _profile_observation(
            "openapi.info",
            relative_path,
            profile=profile,
            format_name=format_name,
            confidence=confidence,
            metadata={key: item for key, item in metadata.items() if item is not None},
            name=_openapi_safe_string(info.get("title")),
            source_suffix=_openapi_source_suffix("info", pointer),
        )
    ]


def _openapi_server_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_prefix: tuple[str, ...],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    if spec_metadata["spec_family"] == "openapi3":
        servers = value.get("servers")
        if not isinstance(servers, list):
            return observations
        for index, server in enumerate(servers):
            if not isinstance(server, dict):
                continue
            url = server.get("url")
            metadata = {
                **spec_metadata,
                "server_index": index,
                "not_fetched": True,
                **_openapi_url_metadata(url),
            }
            pointer = json_pointer((*pointer_prefix, "servers", str(index), "url"))
            observations.append(
                _profile_observation(
                    "openapi.server",
                    relative_path,
                    profile=profile,
                    format_name=format_name,
                    confidence=confidence,
                    metadata=metadata,
                    source_suffix=_openapi_source_suffix("server", pointer),
                )
            )
        return observations

    host = value.get("host")
    base_path = value.get("basePath")
    schemes = value.get("schemes")
    metadata = {
        **spec_metadata,
        "not_fetched": True,
        "host": _openapi_safe_string(host),
        "base_path_present": isinstance(base_path, str),
        "schemes": [
            scheme
            for scheme in schemes
            if isinstance(scheme, str) and len(scheme) <= 16
        ]
        if isinstance(schemes, list)
        else [],
    }
    observations.append(
        _profile_observation(
            "openapi.server",
            relative_path,
            profile=profile,
            format_name=format_name,
            confidence=confidence,
            metadata=metadata,
            source_suffix=_openapi_source_suffix(
                "server", json_pointer((*pointer_prefix, "host"))
            ),
        )
    )
    return observations


def _openapi_path_operation_observations(
    relative_path: str,
    paths: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_prefix: tuple[str, ...],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for path_template in sorted(str(key) for key in paths):
        path_item = paths.get(path_template)
        if not isinstance(path_item, dict):
            continue
        path_pointer = json_pointer((*pointer_prefix, path_template))
        observations.append(
            _profile_observation(
                "openapi.path",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata={
                    **spec_metadata,
                    "path_template": _openapi_bounded_string(path_template),
                    "method_count": sum(
                        1
                        for method in path_item
                        if _normalized_key(str(method)) in OPENAPI_HTTP_METHODS
                    ),
                    "source_path_key": config_path_key(relative_path, path_pointer),
                },
                name=_openapi_bounded_string(path_template),
                source_suffix=_openapi_source_suffix("path", path_pointer),
            )
        )
        path_parameters = path_item.get("parameters")
        for method_name in sorted(str(key) for key in path_item):
            method = _normalized_key(method_name)
            if method not in OPENAPI_HTTP_METHODS:
                continue
            operation = path_item.get(method_name)
            if not isinstance(operation, dict):
                continue
            operation_pointer_segments = (*pointer_prefix, path_template, method_name)
            operation_pointer = json_pointer(operation_pointer_segments)
            operation_id = _openapi_safe_string(operation.get("operationId"))
            observations.append(
                _profile_observation(
                    "openapi.operation",
                    relative_path,
                    profile=profile,
                    format_name=format_name,
                    confidence=confidence,
                    metadata={
                        **spec_metadata,
                        "path_template": _openapi_bounded_string(path_template),
                        "method": method.upper(),
                        "operation_id": operation_id,
                        "tags": _openapi_string_list(operation.get("tags")),
                        **_openapi_text_metadata(operation.get("summary"), "summary"),
                        **_openapi_text_metadata(
                            operation.get("description"), "description"
                        ),
                        "source_path_key": config_path_key(relative_path, operation_pointer),
                    },
                    name=operation_id or f"{method.upper()} {path_template}",
                    source_suffix=_openapi_source_suffix("operation", operation_pointer),
                )
            )
            parameters = _openapi_parameters(operation, path_parameters)
            if len(parameters) > OPENAPI_MAX_PARAMETERS_PER_OPERATION:
                observations.append(
                    _openapi_parse_error_observation(
                        relative_path,
                        format_name=format_name,
                        error_kind="openapi-parameter-limit",
                        message="OpenAPI parameter count exceeds OPENAPI1 limit",
                    )
                )
            else:
                for index, parameter in enumerate(parameters):
                    observations.extend(
                        _openapi_parameter_observation(
                            relative_path,
                            parameter,
                            format_name=format_name,
                            confidence=confidence,
                            profile=profile,
                            spec_metadata=spec_metadata,
                            pointer_segments=(
                                *operation_pointer_segments,
                                "parameters",
                                str(index),
                            ),
                        )
                    )
            observations.extend(
                _openapi_request_body_observations(
                    relative_path,
                    operation,
                    format_name=format_name,
                    confidence=confidence,
                    profile=profile,
                    spec_metadata=spec_metadata,
                    pointer_segments=operation_pointer_segments,
                )
            )
            observations.extend(
                _openapi_response_observations(
                    relative_path,
                    operation,
                    format_name=format_name,
                    confidence=confidence,
                    profile=profile,
                    spec_metadata=spec_metadata,
                    pointer_segments=operation_pointer_segments,
                )
            )
            observations.extend(
                _openapi_tag_observations(
                    relative_path,
                    operation,
                    format_name=format_name,
                    confidence=confidence,
                    profile=profile,
                    spec_metadata=spec_metadata,
                    pointer_segments=operation_pointer_segments,
                )
            )
    return observations


def _openapi_parameter_observation(
    relative_path: str,
    parameter: Any,
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_segments: tuple[str, ...],
) -> list[RawObservation]:
    if not isinstance(parameter, dict):
        return []
    pointer = json_pointer(pointer_segments)
    return [
        _profile_observation(
            "openapi.parameter",
            relative_path,
            profile=profile,
            format_name=format_name,
            confidence=confidence,
            metadata={
                **spec_metadata,
                "parameter_name": _openapi_safe_string(parameter.get("name")),
                "parameter_in": _openapi_safe_string(parameter.get("in")),
                "required": bool(parameter.get("required", False)),
                "source_path_key": config_path_key(relative_path, pointer),
            },
            name=_openapi_safe_string(parameter.get("name")),
            source_suffix=_openapi_source_suffix("parameter", pointer),
        )
    ]


def _openapi_request_body_observations(
    relative_path: str,
    operation: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_segments: tuple[str, ...],
) -> list[RawObservation]:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return []
    pointer = json_pointer((*pointer_segments, "requestBody"))
    return [
        _profile_observation(
            "openapi.request_body",
            relative_path,
            profile=profile,
            format_name=format_name,
            confidence=confidence,
            metadata={
                **spec_metadata,
                "media_types": _openapi_media_types(request_body),
                "source_path_key": config_path_key(relative_path, pointer),
            },
            source_suffix=_openapi_source_suffix("request-body", pointer),
        )
    ]


def _openapi_response_observations(
    relative_path: str,
    operation: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_segments: tuple[str, ...],
) -> list[RawObservation]:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return []
    observations: list[RawObservation] = []
    if len(responses) > OPENAPI_MAX_RESPONSES_PER_OPERATION:
        return [
            _openapi_parse_error_observation(
                relative_path,
                format_name=format_name,
                error_kind="openapi-response-limit",
                message="OpenAPI response count exceeds OPENAPI1 limit",
            )
        ]
    for status_code in sorted(str(key) for key in responses):
        response = responses.get(status_code)
        if not isinstance(response, dict):
            continue
        pointer = json_pointer((*pointer_segments, "responses", status_code))
        observations.append(
            _profile_observation(
                "openapi.response",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata={
                    **spec_metadata,
                    "status_code": status_code,
                    "media_types": _openapi_media_types(response),
                    "description_present": isinstance(response.get("description"), str),
                    "source_path_key": config_path_key(relative_path, pointer),
                },
                name=status_code,
                source_suffix=_openapi_source_suffix("response", pointer),
            )
        )
    return observations


def _openapi_tag_observations(
    relative_path: str,
    operation: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_segments: tuple[str, ...],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for tag in _openapi_string_list(operation.get("tags")):
        pointer = json_pointer((*pointer_segments, "tags", tag))
        observations.append(
            _profile_observation(
                "openapi.tag",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata={**spec_metadata, "tag_name": tag},
                name=tag,
                source_suffix=_openapi_source_suffix("tag", pointer),
            )
        )
    return observations


def _openapi_reference_observations(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_prefix: tuple[str, ...],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for pointer_segments, ref_value in _openapi_ref_values(value):
        if len(observations) >= OPENAPI_MAX_REFERENCES:
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="openapi-reference-limit",
                    message="OpenAPI reference count exceeds OPENAPI1 limit",
                )
            )
            break
        pointer = json_pointer((*pointer_prefix, *pointer_segments))
        metadata, target = _openapi_reference_metadata(
            relative_path,
            ref_value,
            spec_metadata=spec_metadata,
            source_pointer=pointer,
        )
        observations.append(
            _profile_observation(
                "openapi.reference",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata=metadata,
                target=target,
                source_suffix=_openapi_source_suffix("reference", pointer),
            )
        )
        if metadata.get("reference_scope") == "local_file" and target.startswith(
            "unknown:file:"
        ):
            observations.append(
                _openapi_parse_error_observation(
                    relative_path,
                    format_name=format_name,
                    error_kind="openapi-local-ref-outside-root",
                    message="OpenAPI local file reference is outside the repository root",
                )
            )
    external_docs = value.get("externalDocs") if isinstance(value, dict) else None
    if isinstance(external_docs, dict) and isinstance(external_docs.get("url"), str):
        pointer = json_pointer((*pointer_prefix, "externalDocs", "url"))
        metadata, target = _openapi_reference_metadata(
            relative_path,
            external_docs["url"],
            spec_metadata=spec_metadata,
            source_pointer=pointer,
            reference_scope_override="external_docs",
        )
        observations.append(
            _profile_observation(
                "openapi.reference",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata=metadata,
                target=target,
                source_suffix=_openapi_source_suffix("external-docs", pointer),
            )
        )
    return observations


def _openapi_example_and_redaction_observations(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
    confidence: str,
    profile: str,
    spec_metadata: dict[str, str],
    pointer_prefix: tuple[str, ...],
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    example_count = 0
    for pointer_segments, path_value in _openapi_walk(value):
        pointer = json_pointer((*pointer_prefix, *pointer_segments))
        key = pointer_segments[-1] if pointer_segments else ""
        if _normalized_key(key) in OPENAPI_EXAMPLE_KEYS:
            if example_count < OPENAPI_MAX_EXAMPLES:
                observations.append(
                    _profile_observation(
                        "openapi.example",
                        relative_path,
                        profile=profile,
                        format_name=format_name,
                        confidence=confidence,
                        metadata={
                            **spec_metadata,
                            "pointer": pointer,
                            "value_type": _value_type(path_value),
                            "value_shape": _value_shape(path_value),
                            "value_sha256": _stable_value_sha256(path_value),
                            "redacted": _openapi_pointer_is_redacted(
                                pointer, path_value
                            ),
                        },
                        source_suffix=_openapi_source_suffix("example", pointer),
                    )
                )
                example_count += 1
        if _openapi_pointer_is_redacted(pointer, path_value):
            observations.append(
                _profile_observation(
                    "openapi.redaction",
                    relative_path,
                    profile=profile,
                    format_name=format_name,
                    confidence=confidence,
                    metadata={
                        **spec_metadata,
                        "pointer": pointer,
                        "value_type": _value_type(path_value),
                        "value_sha256": _stable_value_sha256(path_value),
                        "redaction_reason": _openapi_redaction_reason(
                            pointer, path_value
                        ),
                    },
                    source_suffix=_openapi_source_suffix("redaction", pointer),
                )
            )
    return observations
