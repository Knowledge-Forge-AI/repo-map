"""Infrastructure profile helpers for structured configuration extraction."""

from __future__ import annotations

from typing import Any

from repomap_kg.extractors.config.paths import _pointer_segments, json_pointer
from repomap_kg.graph.keys import external_key, external_url_key
from repomap_kg.observations.raw import RawObservation


def _generic_helper(name: str) -> Any:
    from repomap_kg.extractors.config import generic_contracts as generic

    return getattr(generic, name)


def _profile_observation(*args: Any, **kwargs: Any) -> RawObservation:
    return _generic_helper("_profile_observation")(*args, **kwargs)


def _safe_value_summary(value: Any) -> Any:
    return _generic_helper("_safe_value_summary")(value)


def _normalized_key(value: str) -> str:
    return _generic_helper("_normalized_key")(value)


def _is_url(value: str) -> bool:
    return _generic_helper("_is_url")(value)


def _yaml_simple_image_pattern() -> Any:
    return _generic_helper("YAML_SIMPLE_IMAGE_PATTERN")


def _json_pointer_is_kubernetes_secret_data(pointer: str, root_value: Any) -> bool:
    segments = _pointer_segments(pointer)
    if "data" not in segments and "stringData" not in segments:
        return False
    return isinstance(root_value, dict) and root_value.get("kind") == "Secret"


def _kubernetes_json_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    observations = [
        _profile_observation(
            "kubernetes.resource",
            relative_path,
            profile="kubernetes_json",
            format_name=format_name,
            confidence=confidence,
            metadata={
                "api_version": _safe_value_summary(value.get("apiVersion")),
                "kind": _safe_value_summary(value.get("kind")),
                "name": _safe_value_summary(metadata.get("name")),
                "namespace": _safe_value_summary(metadata.get("namespace")),
            },
            name=str(metadata.get("name") or value.get("kind") or "resource"),
            source_suffix=(
                f"kubernetes-resource:{value.get('kind')}:"
                f"{metadata.get('name') or 'unnamed'}"
            ),
        )
    ]
    observations.extend(
        _docker_image_observations(
            relative_path,
            value,
            format_name=format_name,
            confidence="heuristic",
            profile="kubernetes_json",
        )
    )
    return observations


def _argocd_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
    spec = value.get("spec") if isinstance(value.get("spec"), dict) else {}
    source = spec.get("source") if isinstance(spec.get("source"), dict) else {}
    return [
        _profile_observation(
            "argocd.application",
            relative_path,
            profile="argocd_json",
            format_name=format_name,
            confidence=confidence,
            metadata={
                "kind": _safe_value_summary(value.get("kind")),
                "name": _safe_value_summary(metadata.get("name")),
                "repo_url_summary": _safe_value_summary(source.get("repoURL")),
                "path_summary": _safe_value_summary(source.get("path")),
                "target_revision_summary": _safe_value_summary(
                    source.get("targetRevision")
                ),
                "not_fetched": True,
            },
            name=str(metadata.get("name") or "argocd-application"),
            target=(
                external_url_key(source["repoURL"])
                if isinstance(source.get("repoURL"), str) and _is_url(source["repoURL"])
                else None
            ),
            source_suffix=f"argocd-application:{metadata.get('name') or 'unnamed'}",
        )
    ]


def _liquibase_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    changelog = value.get("databaseChangeLog")
    entries = changelog if isinstance(changelog, list) else []
    observations = [
        _profile_observation(
            "liquibase.changelog",
            relative_path,
            profile="liquibase_json",
            format_name=format_name,
            confidence=confidence,
            metadata={"changeset_count": _liquibase_changeset_count(entries)},
            source_suffix="liquibase-changelog",
        )
    ]
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("changeSet"), dict):
            continue
        changeset = entry["changeSet"]
        observations.append(
            _profile_observation(
                "liquibase.changeset",
                relative_path,
                profile="liquibase_json",
                format_name=format_name,
                confidence=confidence,
                metadata={
                    "changeset_id": _safe_value_summary(changeset.get("id")),
                    "author": _safe_value_summary(changeset.get("author")),
                    "context": _safe_value_summary(changeset.get("context")),
                    "labels": _safe_value_summary(changeset.get("labels")),
                },
                name=str(changeset.get("id") or index),
                source_suffix=f"liquibase-changeset:{index}",
            )
        )
    return observations


def _liquibase_changeset_count(entries: list[Any]) -> int:
    return sum(
        1
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("changeSet"), dict)
    )


def _docker_json_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
) -> list[RawObservation]:
    return list(
        _docker_image_observations(
            relative_path,
            value,
            format_name=format_name,
            confidence=confidence,
            profile=profile,
        )
    )


def _docker_image_observations(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
    confidence: str,
    profile: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    for pointer, image in _json_image_values(value):
        observations.append(
            _profile_observation(
                "docker.reference",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata={
                    "reference_kind": "docker.image",
                    "pointer": pointer,
                    "image_summary": _safe_value_summary(image),
                    "not_fetched": True,
                },
                target=external_key("docker.image", image),
                source_suffix=f"docker-reference:{pointer}",
            )
        )
    return tuple(observations)


def _json_image_values(value: Any) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []

    def walk(current: Any, segments: tuple[str, ...]) -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                child_segments = (*segments, str(key))
                if (
                    _normalized_key(str(key)) == "image"
                    and isinstance(child, str)
                    and _looks_like_container_image(child)
                ):
                    result.append((json_pointer(child_segments), child))
                walk(child, child_segments)
        elif isinstance(current, list):
            for index, child in enumerate(current):
                walk(child, (*segments, str(index)))

    walk(value, ())
    return tuple(result)


def _is_argocd_json_document(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and str(value.get("apiVersion", "")).startswith("argoproj.io/")
        and value.get("kind") in ("Application", "ApplicationSet")
    )


def _is_liquibase_json_document(value: Any) -> bool:
    return isinstance(value, dict) and "databaseChangeLog" in value


def _is_kubernetes_document(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and "apiVersion" in value
        and "kind" in value
        and isinstance(value.get("metadata"), dict)
    )


def _is_docker_compose_document(value: Any) -> bool:
    return isinstance(value, dict) and "services" in value and (
        "networks" in value or "volumes" in value or "secrets" in value
    )


def _is_grafana_document(value: Any) -> bool:
    return isinstance(value, dict) and (
        "datasources" in value or "dashboards" in value or "secureJsonData" in value
    )


def _looks_like_container_image(value: str) -> bool:
    if _is_url(value) or value.startswith(("./", "../", "/", "$", "~")):
        return False
    return bool(_yaml_simple_image_pattern().match(value)) and (
        "/" in value or ":" in value or "@" in value
    )
