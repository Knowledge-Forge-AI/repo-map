"""Neutral YAML reference projection contracts."""

from __future__ import annotations

from typing import Any

from repomap_kg.extractors.config.generic_reference_contracts import (
    _file_reference,
    _reference,
)
from repomap_kg.extractors.config.generic_values import (
    _is_dynamic_value,
    _is_url,
    _looks_like_container_image,
    _normalize_repo_path,
    _safe_value_summary,
)
from repomap_kg.graph.keys import (
    config_path_key,
    dynamic_key,
    external_key,
    external_url_key,
    file_key,
    unknown_key,
)


def _yaml_string_references(
    relative_path: str,
    pointer_segments: tuple[str, ...],
    key_normalized: str,
    pointer_key_normalized: str,
    value: str,
    *,
    redacted: bool,
) -> tuple[dict[str, Any], ...]:
    stripped = value.strip()
    if not stripped:
        return ()
    if pointer_segments[-1] == "$ref" or key_normalized in ("$ref", "ref"):
        return (_yaml_openapi_ref(relative_path, stripped, redacted=redacted),)
    if key_normalized == "uses":
        return (_yaml_uses_reference(relative_path, stripped, redacted=redacted),)
    if key_normalized == "image" and _looks_like_container_image(stripped):
        return (
            _reference(
                "external",
                external_key("docker.image", stripped),
                "yaml-container-image",
                stripped,
                redacted=redacted,
            ),
        )
    if key_normalized in ("context", "dockerfile", "env_file"):
        return (_file_reference(relative_path, stripped, redacted=redacted),)
    if key_normalized in ("import", "additional_location", "location"):
        spring_file = _yaml_spring_file_reference_value(stripped)
        if spring_file is not None:
            return (_file_reference(relative_path, spring_file, redacted=redacted),)
    if key_normalized in ("repository", "url") and _is_url(stripped):
        return (
            _reference(
                "external.url",
                external_url_key(stripped),
                "yaml-url-field",
                stripped,
                redacted=redacted,
            ),
        )
    if "path" in pointer_key_normalized or key_normalized in (
        "file",
        "files",
        "config",
        "config_path",
        "include_file",
    ):
        return (_file_reference(relative_path, stripped, redacted=redacted),)
    return ()


def _yaml_openapi_ref(
    relative_path: str,
    value: str,
    *,
    redacted: bool,
) -> dict[str, Any]:
    if _is_url(value):
        return _reference(
            "external.url",
            external_url_key(value),
            "openapi-remote-ref",
            value,
            redacted=redacted,
        )
    if value.startswith("#/"):
        return _reference(
            "config.path",
            config_path_key(relative_path, value[1:]),
            "openapi-local-pointer-ref",
            value,
            redacted=redacted,
        )
    if "#" in value:
        path_part, pointer_part = value.split("#", 1)
        if path_part and not _is_dynamic_value(path_part):
            target = _file_reference(relative_path, path_part, redacted=redacted)
            target["reason"] = "openapi-local-file-ref"
            if pointer_part:
                target["summary"] = _safe_value_summary(value)
            return target
    return _file_reference(relative_path, value, redacted=redacted)


def _yaml_uses_reference(
    relative_path: str,
    value: str,
    *,
    redacted: bool,
) -> dict[str, Any]:
    if value.startswith("./"):
        resolved = _normalize_repo_path(value)
        if resolved is None:
            return _reference(
                "unknown",
                unknown_key("file", "repo-escaping-config-reference"),
                "repo-escaping-file-reference",
                value,
                redacted=redacted,
            )
        return _reference(
            "file",
            file_key(resolved),
            "github-actions-local-uses",
            value,
            redacted=redacted,
        )
    if value.startswith(("../", "/")):
        return _file_reference(relative_path, value, redacted=redacted)
    if _is_dynamic_value(value):
        return _reference(
            "dynamic",
            dynamic_key("github.action", "dynamic-yaml-uses"),
            "dynamic-yaml-uses",
            value,
            redacted=redacted,
        )
    return _reference(
        "external",
        external_key("github.action", value),
        "github-actions-uses",
        value,
        redacted=redacted,
    )


def _yaml_spring_file_reference_value(value: str) -> str | None:
    for prefix in ("optional:file:", "file:"):
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return None
