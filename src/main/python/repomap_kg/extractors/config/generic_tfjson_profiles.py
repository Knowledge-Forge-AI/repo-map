"""TFJSON profile detection and observation helpers for generic config extraction."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from repomap_kg.extractors.config.generic_profile_helpers import (
    _profile_observation,
    _safe_selected_metadata,
)
from repomap_kg.extractors.config.generic_values import (
    _is_secret_pointer,
    _looks_like_secret_scalar,
    _normalized_key,
)
from repomap_kg.extractors.config.infrastructure import (
    _argocd_observations,
    _docker_json_observations,
    _is_argocd_json_document,
    _is_docker_compose_document,
    _is_kubernetes_document,
    _is_liquibase_json_document,
    _json_pointer_is_kubernetes_secret_data,
    _kubernetes_json_observations,
    _liquibase_observations,
)
from repomap_kg.extractors.config.javascript import (
    _angular_observations,
    _package_json_observations,
    _package_lock_observations,
    _playwright_observation,
    _script_is_secret_prone,
    _typescript_config_observations,
)
from repomap_kg.extractors.config.openapi import (
    _is_openapi_document,
    _is_openapi_file_name,
    _openapi_pointer_is_redacted,
    _openapi_profile_observations,
)
from repomap_kg.extractors.config.paths import (
    _pointer_segments,
    json_pointer,
)
from repomap_kg.extractors.config.terraform import (
    _terraform_json_observations,
    _terraform_tfvars_observations,
)
from repomap_kg.graph.keys import config_document_key
from repomap_kg.observations.raw import RawObservation

TFJSON_PROFILE_FORMATS = frozenset({"json", "jsonc"})


def _tfjson_profile(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
) -> str | None:
    if format_name not in TFJSON_PROFILE_FORMATS or not isinstance(value, dict):
        return None
    path = PurePosixPath(relative_path)
    name = path.name
    normalized_name = _normalized_key(name)
    lower_path = relative_path.lower()
    if _is_openapi_file_name(relative_path) or _is_openapi_document(value):
        return "openapi_json"
    if lower_path.endswith(".tfvars.json") or normalized_name == "terraform.tfvars.json":
        return "terraform_tfvars_json"
    if lower_path.endswith(".tf.json"):
        return "terraform_json"
    if normalized_name == "package.json":
        return "package_json"
    if normalized_name in ("package_lock.json", "npm_shrinkwrap.json"):
        return "package_lock_json"
    if normalized_name == "tsconfig.json" or (
        normalized_name.startswith("tsconfig.")
        and normalized_name.endswith(".json")
    ):
        return "typescript_config"
    if normalized_name == "jsconfig.json":
        return "javascript_config"
    if normalized_name in ("angular.json", ".angular_cli.json"):
        return "angular_workspace"
    if normalized_name in ("project.json", "workspace.json", "nx.json"):
        return "workspace_config"
    if normalized_name == "nest_cli.json":
        return "nest_config"
    if normalized_name == "jest.config.json":
        return "jest_config"
    if normalized_name in ("babel.config.json", ".babelrc", ".babelrc.json"):
        return "babel_config"
    if normalized_name in (".eslintrc", ".eslintrc.json"):
        return "eslint_config"
    if normalized_name in (".prettierrc", ".prettierrc.json"):
        return "prettier_config"
    if normalized_name == "playwright.config.json":
        return "playwright_config"
    if _is_argocd_json_document(value):
        return "argocd_json"
    if _is_kubernetes_document(value):
        return "kubernetes_json"
    if _is_liquibase_json_document(value):
        return "liquibase_json"
    if _is_docker_compose_document(value):
        return "docker_compose_json"
    return None


def _tfjson_document_metadata(profile: str | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {"profile": profile}


def _tfjson_metadata_overrides(
    relative_path: str,
    value: Any,
    *,
    profile: str | None,
) -> dict[str, dict[str, Any]]:
    overrides: dict[str, dict[str, Any]] = {}
    if profile == "terraform_tfvars_json":
        for pointer, _path_value in _json_pointer_values(value):
            overrides.setdefault(pointer, {}).update(
                {
                    "profile": profile,
                    "redacted": True,
                    "redaction_reason": "tfvars-sensitive-by-default",
                }
            )
        return overrides
    if profile is not None:
        for pointer, path_value in _json_pointer_values(value):
            metadata = overrides.setdefault(pointer, {})
            metadata["profile"] = profile
            if _tfjson_pointer_is_redacted(pointer, path_value, value, profile=profile):
                metadata["redacted"] = True
                metadata.setdefault(
                    "redaction_reason",
                    _tfjson_redaction_reason(pointer, profile),
                )
    return overrides


def _tfjson_pointer_is_redacted(
    pointer: str,
    path_value: Any,
    root_value: Any,
    *,
    profile: str,
) -> bool:
    if _is_secret_pointer(pointer):
        return True
    if _looks_like_secret_scalar(path_value):
        return True
    segments = _pointer_segments(pointer)
    normalized_segments = tuple(_normalized_key(segment) for segment in segments)
    if profile == "package_json" and len(segments) >= 2 and segments[0] == "scripts":
        return _script_is_secret_prone(path_value)
    if profile == "kubernetes_json" and _json_pointer_is_kubernetes_secret_data(
        pointer,
        root_value,
    ):
        return True
    if profile == "openapi_json" and _openapi_pointer_is_redacted(pointer, path_value):
        return True
    if "securejsondata" in normalized_segments:
        return True
    return False


def _tfjson_redaction_reason(pointer: str, profile: str) -> str:
    if profile == "package_json" and pointer.startswith("/scripts/"):
        return "secret-prone-script"
    if profile == "kubernetes_json" and (
        "/data/" in pointer or "/stringData/" in pointer
    ):
        return "secret-prone-json-path"
    if _is_secret_pointer(pointer):
        return "secret-prone-key"
    return "secret-prone-config-context"


def _json_pointer_values(value: Any) -> tuple[tuple[str, Any], ...]:
    result: list[tuple[str, Any]] = []

    def walk(current: Any, segments: tuple[str, ...]) -> None:
        if segments:
            result.append((json_pointer(segments), current))
        if isinstance(current, dict):
            for key, child in current.items():
                walk(child, (*segments, str(key)))
        elif isinstance(current, list):
            for index, child in enumerate(current):
                walk(child, (*segments, str(index)))

    walk(value, ())
    return tuple(result)


def _tfjson_profile_observations(
    relative_path: str,
    value: Any,
    *,
    format_name: str,
    confidence: str,
    profile: str | None,
    content: str,
) -> tuple[RawObservation, ...]:
    if profile is None or not isinstance(value, dict):
        return ()
    observations: list[RawObservation] = [
        _profile_observation(
            "ecosystem.config_profile",
            relative_path,
            profile=profile,
            format_name=format_name,
            confidence=confidence,
            metadata={
                "profile": profile,
                "profile_family": _tfjson_profile_family(profile),
                "source_document_key": config_document_key(relative_path),
            },
        )
    ]
    if profile == "package_json":
        observations.extend(
            _package_json_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
                content=content,
            )
        )
    elif profile == "package_lock_json":
        observations.extend(
            _package_lock_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
            )
        )
    elif profile in ("typescript_config", "javascript_config"):
        observations.extend(
            _typescript_config_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
                content=content,
            )
        )
    elif profile == "angular_workspace":
        observations.extend(
            _angular_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
                content=content,
            )
        )
    elif profile == "nest_config":
        observations.append(
            _profile_observation(
                "nest.config",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata=_safe_selected_metadata(
                    value,
                    ("sourceRoot", "entryFile", "collection", "compilerOptions"),
                ),
            )
        )
    elif profile == "jest_config":
        observations.append(
            _profile_observation(
                "jest.config",
                relative_path,
                profile=profile,
                format_name=format_name,
                confidence=confidence,
                metadata=_safe_selected_metadata(
                    value,
                    (
                        "testEnvironment",
                        "preset",
                        "rootDir",
                        "testMatch",
                        "setupFilesAfterEnv",
                    ),
                ),
            )
        )
    elif profile == "playwright_config":
        observations.append(
            _playwright_observation(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
            )
        )
    elif profile == "openapi_json":
        observations.extend(
            _openapi_profile_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
            )
        )
    elif profile == "terraform_json":
        observations.extend(
            _terraform_json_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
            )
        )
    elif profile == "terraform_tfvars_json":
        observations.extend(
            _terraform_tfvars_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
            )
        )
    elif profile == "kubernetes_json":
        observations.extend(
            _kubernetes_json_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
            )
        )
    elif profile == "argocd_json":
        observations.extend(
            _argocd_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
            )
        )
    elif profile == "liquibase_json":
        observations.extend(
            _liquibase_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
            )
        )
    elif profile == "docker_compose_json":
        observations.extend(
            _docker_json_observations(
                relative_path,
                value,
                format_name=format_name,
                confidence=confidence,
                profile=profile,
            )
        )
    return tuple(observations)


def _tfjson_profile_family(profile: str) -> str:
    if profile.startswith("terraform_"):
        return "terraform"
    if profile in ("package_json", "package_lock_json"):
        return "npm"
    if profile in ("typescript_config", "javascript_config"):
        return "typescript"
    if profile == "openapi_json":
        return "openapi"
    if profile.endswith("_json"):
        return profile.removesuffix("_json")
    return profile
