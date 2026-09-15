"""OpenAPI profile shared helpers."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from repomap_kg import __version__
from repomap_kg.extractors.config.paths import _pointer_segments, json_pointer
from repomap_kg.graph.keys import (
    config_path_key,
    external_key,
    external_url_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


def _generic_helper(name: str) -> Any:
    from repomap_kg.extractors.config import generic_contracts as generic

    return getattr(generic, name)


def _profile_observation(*args: Any, **kwargs: Any) -> RawObservation:
    return _generic_helper("_profile_observation")(*args, **kwargs)


def _extractor_name() -> str:
    return _generic_helper("EXTRACTOR_NAME")


def _safe_error_message(error: Exception | None, fallback: str) -> str:
    return _generic_helper("_safe_error_message")(error, fallback)


def _secret_prone_keys() -> tuple[str, ...]:
    return _generic_helper("SECRET_PRONE_KEYS")


def _file_reference(relative_path: str, value: str, *, redacted: bool) -> dict[str, Any]:
    return _generic_helper("_file_reference")(relative_path, value, redacted=redacted)


def _is_url(value: str) -> bool:
    return _generic_helper("_is_url")(value)


def _looks_like_secret_scalar(value: str) -> bool:
    return _generic_helper("_looks_like_secret_scalar")(value)


def _normalized_key(key: str) -> str:
    return _generic_helper("_normalized_key")(key)


def _stable_text_sha256(value: str) -> str:
    return _generic_helper("_stable_text_sha256")(value)


def _stable_value_sha256(value: Any) -> str:
    return _generic_helper("_stable_value_sha256")(value)


def _url_has_credentials(value: str) -> bool:
    return _generic_helper("_url_has_credentials")(value)


def _value_shape(value: Any) -> Any:
    return _generic_helper("_value_shape")(value)


def _value_type(value: Any) -> str:
    return _generic_helper("_value_type")(value)


def _yaml_documents(value: Any, *, document_count: int) -> tuple[Any, ...]:
    return _generic_helper("_yaml_documents")(value, document_count=document_count)


def _yaml_format() -> str:
    return _generic_helper("YAML_FORMAT")


OPENAPI_HTTP_METHODS = frozenset(
    ("get", "post", "put", "patch", "delete", "options", "head", "trace")
)


OPENAPI_MAX_PATHS = 128


OPENAPI_MAX_OPERATIONS = 256


OPENAPI_MAX_PARAMETERS_PER_OPERATION = 64


OPENAPI_MAX_RESPONSES_PER_OPERATION = 64


OPENAPI_MAX_SCHEMAS = 256


OPENAPI_MAX_REFERENCES = 512


OPENAPI_MAX_EXAMPLES = 128


OPENAPI_MAX_METADATA_STRING = 160


OPENAPI_TEXT_KEYS = frozenset(("description", "summary"))


OPENAPI_EXAMPLE_KEYS = frozenset(("example", "examples", "default"))


def _openapi_components(
    value: dict[str, Any],
    spec_family: str,
) -> dict[str, dict[str, Any]]:
    if spec_family == "swagger2":
        components: dict[str, dict[str, Any]] = {}
        definitions = value.get("definitions")
        if isinstance(definitions, dict):
            components["definitions"] = definitions
        security_definitions = value.get("securityDefinitions")
        if isinstance(security_definitions, dict):
            components["securityDefinitions"] = security_definitions
        return components
    raw_components = value.get("components")
    if not isinstance(raw_components, dict):
        return {}
    components = {}
    for key in ("schemas", "responses", "parameters", "securitySchemes"):
        item = raw_components.get(key)
        if isinstance(item, dict):
            components[key] = item
    return components


def _openapi_parameters(
    operation: dict[str, Any],
    path_parameters: Any,
) -> list[Any]:
    parameters: list[Any] = []
    if isinstance(path_parameters, list):
        parameters.extend(path_parameters)
    operation_parameters = operation.get("parameters")
    if isinstance(operation_parameters, list):
        parameters.extend(operation_parameters)
    return parameters


def _openapi_media_types(value: dict[str, Any]) -> list[str]:
    content = value.get("content")
    if not isinstance(content, dict):
        return []
    return sorted(
        media_type
        for media_type in (str(key) for key in content)
        if len(media_type) <= 120 and "/" in media_type
    )


def _openapi_operation_count(paths: dict[str, Any]) -> int:
    count = 0
    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        count += sum(
            1
            for method in path_item
            if _normalized_key(str(method)) in OPENAPI_HTTP_METHODS
        )
    return count


def _openapi_server_count(value: dict[str, Any], spec_family: str) -> int:
    if spec_family == "openapi3":
        servers = value.get("servers")
        return len(servers) if isinstance(servers, list) else 0
    return 1 if value.get("host") is not None or value.get("basePath") is not None else 0


def _openapi_ref_values(value: Any) -> tuple[tuple[tuple[str, ...], str], ...]:
    refs: list[tuple[tuple[str, ...], str]] = []
    for pointer_segments, path_value in _openapi_walk(value):
        if pointer_segments and pointer_segments[-1] == "$ref" and isinstance(path_value, str):
            refs.append((pointer_segments, path_value))
    return tuple(refs)


def _openapi_walk(value: Any, pointer_segments: tuple[str, ...] = ()) -> tuple[tuple[tuple[str, ...], Any], ...]:
    items: list[tuple[tuple[str, ...], Any]] = [(pointer_segments, value)]
    if isinstance(value, dict):
        for key, item in value.items():
            items.extend(_openapi_walk(item, (*pointer_segments, str(key))))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            items.extend(_openapi_walk(item, (*pointer_segments, str(index))))
    return tuple(items)


def _openapi_reference_metadata(
    relative_path: str,
    ref_value: str,
    *,
    spec_metadata: dict[str, str],
    source_pointer: str,
    reference_scope_override: str | None = None,
) -> tuple[dict[str, Any], str]:
    credentialed = _url_has_credentials(ref_value)
    scope = reference_scope_override or _openapi_reference_scope(ref_value)
    target: str
    if scope == "internal" and ref_value.startswith("#/"):
        target = config_path_key(relative_path, ref_value[1:])
    elif scope == "local_file":
        path_part = ref_value.split("#", 1)[0]
        target = _file_reference(relative_path, path_part, redacted=False)["target"]
    elif _is_url(ref_value) and not credentialed:
        target = external_url_key(ref_value)
    elif _is_url(ref_value):
        target = external_key("url", "credentialed-openapi-reference")
    else:
        target = unknown_key("openapi.reference", "unsupported-ref")
    local_ref_outside_root = scope == "local_file" and target.startswith(
        "unknown:file:"
    )
    metadata = {
        **spec_metadata,
        "pointer": source_pointer,
        "reference_scope": scope,
        "not_fetched": True,
        "redacted": credentialed or local_ref_outside_root,
        "target_kind": target.split(":", 1)[0],
        "ref_summary": "<redacted-url>"
        if credentialed
        else "<redacted-local-ref>"
        if local_ref_outside_root
        else _openapi_bounded_string(ref_value),
        "ref_sha256": _stable_text_sha256(ref_value),
    }
    if credentialed:
        metadata["redaction_reason"] = "credentialed-url"
    if local_ref_outside_root:
        metadata["redaction_reason"] = "local-ref-outside-root"
    return metadata, target


def _openapi_reference_scope(ref_value: str) -> str:
    if ref_value.startswith("#/"):
        return "internal"
    if _is_url(ref_value):
        return "remote"
    return "local_file"


def _openapi_oauth_flow_names(value: dict[str, Any]) -> list[str]:
    flows = value.get("flows")
    if not isinstance(flows, dict):
        return []
    return sorted(
        str(name)
        for name in flows
        if len(str(name)) <= OPENAPI_MAX_METADATA_STRING
    )


def _openapi_scope_names(value: dict[str, Any]) -> list[str]:
    scope_names: set[str] = set()
    flows = value.get("flows")
    if not isinstance(flows, dict):
        return []
    for flow in flows.values():
        if not isinstance(flow, dict):
            continue
        scopes = flow.get("scopes")
        if isinstance(scopes, dict):
            scope_names.update(
                str(name)
                for name in scopes
                if len(str(name)) <= OPENAPI_MAX_METADATA_STRING
                and not _openapi_sensitive_key(str(name))
            )
    return sorted(scope_names)


def _openapi_text_metadata(value: Any, key: str) -> dict[str, Any]:
    if not isinstance(value, str):
        return {f"{key}_present": False}
    return {
        f"{key}_present": True,
        f"{key}_length": len(value),
        f"{key}_sha256": _stable_text_sha256(value),
    }


def _openapi_url_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, str):
        return {"url_present": False}
    parsed = urlsplit(value)
    credentialed = _url_has_credentials(value)
    metadata: dict[str, Any] = {
        "url_present": True,
        "url_length": len(value),
        "url_sha256": _stable_text_sha256(value),
        "redacted": credentialed,
    }
    if parsed.scheme and len(parsed.scheme) <= 16:
        metadata["scheme"] = parsed.scheme
    if parsed.hostname and not credentialed:
        metadata["host"] = _openapi_bounded_string(parsed.hostname)
    if credentialed:
        metadata["redaction_reason"] = "credentialed-url"
    return metadata


def _openapi_safe_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if _openapi_sensitive_key(value) or _looks_like_secret_scalar(value):
        return None
    return _openapi_bounded_string(value)


def _openapi_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    strings: list[str] = []
    for item in value:
        safe = _openapi_safe_string(item)
        if safe is not None:
            strings.append(safe)
    return strings[:32]


def _openapi_bounded_string(value: str) -> str:
    if len(value) <= OPENAPI_MAX_METADATA_STRING:
        return value
    return f"<string:{len(value)}>"


def _openapi_pointer_is_redacted(pointer: str, value: Any) -> bool:
    segments = _pointer_segments(pointer)
    normalized_segments = tuple(_normalized_key(segment) for segment in segments)
    if (
        normalized_segments
        and normalized_segments[-1] == "$ref"
        and isinstance(value, str)
        and value.startswith("../")
    ):
        return True
    if any(_openapi_sensitive_key(segment) for segment in normalized_segments):
        return True
    if any(segment in OPENAPI_TEXT_KEYS for segment in normalized_segments):
        return True
    if any(segment in OPENAPI_EXAMPLE_KEYS for segment in normalized_segments):
        return True
    if isinstance(value, str) and _url_has_credentials(value):
        return True
    return _looks_like_secret_scalar(value)


def _openapi_redaction_reason(pointer: str, value: Any) -> str:
    if isinstance(value, str) and _url_has_credentials(value):
        return "credentialed-url"
    segments = tuple(_normalized_key(segment) for segment in _pointer_segments(pointer))
    if (
        segments
        and segments[-1] == "$ref"
        and isinstance(value, str)
        and value.startswith("../")
    ):
        return "openapi-ref-summary-only"
    if any(segment in OPENAPI_TEXT_KEYS for segment in segments):
        return "openapi-text-summary-only"
    if any(segment in OPENAPI_EXAMPLE_KEYS for segment in segments):
        return "openapi-example-summary-only"
    return "secret-prone-openapi-field"


def _openapi_sensitive_key(value: str) -> bool:
    normalized = _normalized_key(value)
    squashed = re.sub(r"[^0-9a-z]", "", normalized)
    markers = tuple(_secret_prone_keys()) + (
        "key",
        "authorization",
        "jwt",
        "database_url",
        "webhook",
        "oauth",
        "openid",
        "x_api_key",
    )
    return any(marker.replace("_", "") in squashed for marker in markers)


def _openapi_source_suffix(kind: str, pointer: str) -> str:
    return f"openapi-{kind}:{_stable_text_sha256(pointer)[:16]}"


def _openapi_parse_error_observation(
    relative_path: str,
    *,
    format_name: str,
    error_kind: str,
    message: str,
    start_line: int | None = None,
    document_index: int | None = None,
) -> RawObservation:
    metadata: dict[str, Any] = {
        "format": format_name,
        "profile": "openapi" if format_name == _yaml_format() else "openapi_json",
        "error_kind": error_kind,
        "message_summary": _safe_error_message(None, message),
        "recovered": False,
        "raw_profile_only": True,
    }
    if document_index is not None:
        metadata["document_index"] = document_index
    if start_line is not None:
        metadata["line_number"] = start_line
    return RawObservation(
        kind="openapi.parse_error",
        source_id=(
            f"{relative_path}#openapi-parse-error:"
            f"{_stable_text_sha256(error_kind + ':' + message)[:16]}"
        ),
        path=relative_path,
        start_line=start_line,
        end_line=start_line,
        confidence="unknown",
        extractor=_extractor_name(),
        extractor_version=__version__,
        metadata=metadata,
    )


def _is_openapi_document(value: Any) -> bool:
    return isinstance(value, dict) and (
        "openapi" in value
        or "swagger" in value
        or ("paths" in value and "components" in value)
    )


def _is_openapi_file_name(relative_path: str) -> bool:
    name = PurePosixPath(relative_path).name.lower()
    return name in (
        "openapi.json",
        "openapi.yaml",
        "openapi.yml",
        "swagger.json",
        "swagger.yaml",
        "swagger.yml",
    ) or name.endswith(
        (
            ".openapi.json",
            ".openapi.yaml",
            ".openapi.yml",
            ".swagger.json",
            ".swagger.yaml",
            ".swagger.yml",
        )
    )
