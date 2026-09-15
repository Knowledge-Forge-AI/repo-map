"""YAML profile metadata and reference helpers."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from repomap_kg.extractors.config import generic_values as _generic_values
from repomap_kg.extractors.config import infrastructure as _infrastructure
from repomap_kg.extractors.config import openapi_helpers as _openapi_helpers
from repomap_kg.extractors.config.paths import _pointer_segments, json_pointer
from repomap_kg.extractors.config.yaml_reference_contracts import (
    _yaml_openapi_ref,
    _yaml_spring_file_reference_value,
    _yaml_string_references,
    _yaml_uses_reference,
)


def _generic_helper(name: str) -> Any:
    for owner in (
        _generic_values,
        _openapi_helpers,
        _infrastructure,
    ):
        if hasattr(owner, name):
            return getattr(owner, name)
    raise AttributeError(name)


def _normalized_key(value: str) -> str:
    return _generic_helper("_normalized_key")(value)


def _is_openapi_file_name(relative_path: str) -> bool:
    return _generic_helper("_is_openapi_file_name")(relative_path)


def _is_openapi_document(value: Any) -> bool:
    return _generic_helper("_is_openapi_document")(value)


def _is_kubernetes_document(value: Any) -> bool:
    return _generic_helper("_is_kubernetes_document")(value)


def _is_docker_compose_document(value: Any) -> bool:
    return _generic_helper("_is_docker_compose_document")(value)


def _is_grafana_document(value: Any) -> bool:
    return _generic_helper("_is_grafana_document")(value)


def _stable_array_members(value: list[Any]) -> list[Any]:
    return _generic_helper("_stable_array_members")(value)


def _is_secret_pointer(pointer: str) -> bool:
    return _generic_helper("_is_secret_pointer")(pointer)


def _openapi_pointer_is_redacted(pointer: str, value: Any) -> bool:
    return _generic_helper("_openapi_pointer_is_redacted")(pointer, value)


def _looks_like_secret_scalar(value: Any) -> bool:
    return _generic_helper("_looks_like_secret_scalar")(value)


def _yaml_profile(
    relative_path: str,
    value: Any,
    *,
    document_count: int,
) -> str:
    path = PurePosixPath(relative_path)
    path_parts = tuple(_normalized_key(part) for part in path.parts)
    name = path.name
    normalized_name = _normalized_key(name)
    if ".github" in path.parts and "workflows" in path.parts:
        return "github_actions"
    if ".circleci" in path.parts and name in ("config.yml", "config.yaml"):
        return "circleci"
    if normalized_name in ("docker_compose.yml", "docker_compose.yaml") or name in (
        "docker-compose.yml",
        "docker-compose.yaml",
    ):
        return "docker_compose"
    if name == "Chart.yaml":
        return "helm_chart"
    if name == "values.yaml":
        return "helm_values"
    if name == "application.yml" or name == "application.yaml" or normalized_name.startswith("application_"):
        return "spring_boot"
    if "grafana" in path_parts:
        return "grafana"
    if "serena" in normalized_name or "serena" in path_parts:
        return "serena"
    if "arq" in normalized_name or "arq" in path_parts:
        return "arq_backup"
    documents = _yaml_documents(value, document_count=document_count)
    if _is_openapi_file_name(relative_path) or any(
        _is_openapi_document(document) for document in documents
    ):
        return "openapi"
    if any(_is_kubernetes_document(document) for document in documents):
        return "kubernetes"
    if any(isinstance(document, dict) and "pipeline" in document for document in documents):
        return "harness"
    if any(_is_docker_compose_document(document) for document in documents):
        return "docker_compose"
    if any(_is_grafana_document(document) for document in documents):
        return "grafana"
    return "generic_yaml"


_yaml_documents = _generic_values._yaml_documents


def _apply_yaml_profile_metadata(
    value: Any,
    metadata_overrides: dict[str, dict[str, Any]],
    *,
    profile: str,
    document_count: int,
) -> None:
    for pointer, path_value in _yaml_pointer_values(value):
        metadata = metadata_overrides.setdefault(pointer, {})
        metadata["profile"] = profile
        if document_count > 1:
            document_index = _yaml_document_index_from_pointer(pointer)
            if document_index is not None:
                metadata["document_index"] = document_index
        if _yaml_pointer_is_redacted(
            pointer,
            path_value=path_value,
            root_value=value,
            profile=profile,
        ):
            metadata["redacted"] = True
            metadata.setdefault("redaction_reason", _yaml_redaction_reason(pointer, profile))
    _apply_yaml_stable_array_metadata(value, metadata_overrides)


def _apply_yaml_stable_array_metadata(
    value: Any,
    metadata_overrides: dict[str, dict[str, Any]],
) -> None:
    def walk(
        current: Any,
        segments: tuple[str, ...],
        active_stable_keys: tuple[str, ...],
    ) -> None:
        if segments and active_stable_keys:
            metadata_overrides.setdefault(json_pointer(segments), {}).setdefault(
                "stable_member_keys",
                list(active_stable_keys),
            )
        if isinstance(current, dict):
            for key, child in current.items():
                walk(child, (*segments, str(key)), active_stable_keys)
            return
        if isinstance(current, list):
            stable_members = _stable_array_members(current)
            if not stable_members:
                return
            stable_keys = tuple(sorted({member.key for member in stable_members}))
            for member in stable_members:
                walk(member.value, (*segments, member.segment), stable_keys)

    walk(value, (), ())


def _yaml_pointer_values(value: Any) -> tuple[tuple[str, Any], ...]:
    result: list[tuple[str, Any]] = []

    def walk(current: Any, segments: tuple[str, ...]) -> None:
        if segments:
            result.append((json_pointer(segments), current))
        if isinstance(current, dict):
            for key, child in current.items():
                walk(child, (*segments, str(key)))
        elif isinstance(current, list):
            for member in _stable_array_members(current):
                walk(member.value, (*segments, member.segment))

    walk(value, ())
    return tuple(result)


def _yaml_document_index_from_pointer(pointer: str) -> int | None:
    segments = _pointer_segments(pointer)
    if len(segments) >= 2 and segments[0] == "documents" and segments[1].isdigit():
        return int(segments[1])
    return None


def _yaml_pointer_is_redacted(
    pointer: str,
    *,
    path_value: Any,
    root_value: Any,
    profile: str,
) -> bool:
    segments = _pointer_segments(pointer)
    normalized_segments = tuple(_normalized_key(segment) for segment in segments)
    if _is_secret_pointer(pointer):
        return True
    if any(segment in ("securejsondata", "dockerconfigjson") for segment in normalized_segments):
        return True
    if profile == "kubernetes" and _yaml_pointer_is_kubernetes_secret_data(pointer, root_value):
        return True
    if profile == "github_actions" and "secrets" in normalized_segments:
        return True
    if profile == "grafana" and "securejsondata" in normalized_segments:
        return True
    if profile == "openapi" and _openapi_pointer_is_redacted(pointer, path_value):
        return True
    return _looks_like_secret_scalar(path_value)


def _yaml_pointer_is_kubernetes_secret_data(pointer: str, root_value: Any) -> bool:
    segments = _pointer_segments(pointer)
    if "data" not in segments and "stringData" not in segments:
        return False
    if len(segments) >= 2 and segments[0] == "documents" and segments[1].isdigit():
        document = root_value.get("documents", {}).get(segments[1]) if isinstance(root_value, dict) else None
    else:
        document = root_value
    return isinstance(document, dict) and document.get("kind") == "Secret"


def _yaml_redaction_reason(pointer: str, profile: str) -> str:
    if profile == "kubernetes" and (
        "/data/" in pointer or "/stringData/" in pointer
    ):
        return "secret-prone-yaml-path"
    if _is_secret_pointer(pointer):
        return "secret-prone-yaml-path"
    return "secret-prone-yaml-context"
