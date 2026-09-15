"""Project profile loading and validation."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repomap_kg.observations.raw import VALID_CONFIDENCES


VALID_ROLES = frozenset(
    {
        "config",
        "documentation",
        "entrypoint",
        "generated",
        "script",
        "source",
        "test",
        "unknown",
    }
)


class ProfileValidationError(ValueError):
    """Raised when a RepoMap project profile is invalid."""


@dataclass(frozen=True)
class ProjectProfile:
    command_dirs: tuple[str, ...] = ()
    script_dirs: tuple[str, ...] = ()
    generated_dirs: tuple[str, ...] = ()
    role_overrides: Mapping[str, str] = field(default_factory=dict)
    confidence_overrides: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("command_dirs", "script_dirs", "generated_dirs"):
            values = getattr(self, field_name)
            for value in values:
                validate_relative_path(value, field_name)
        validate_mapping(self.role_overrides, "role_overrides", VALID_ROLES)
        validate_mapping(
            self.confidence_overrides,
            "confidence_overrides",
            VALID_CONFIDENCES,
        )

    def role_for_path(self, relative_path: str, default: str) -> str:
        if relative_path in self.role_overrides:
            return self.role_overrides[relative_path]
        if path_is_under(relative_path, self.generated_dirs):
            return "generated"
        if path_is_under(relative_path, self.command_dirs):
            return "entrypoint"
        if path_is_under(relative_path, self.script_dirs):
            return "script"
        return default

    def confidence_for_path(self, relative_path: str, default: str = "extracted") -> str:
        return self.confidence_overrides.get(relative_path, default)

    def generated_for_path(self, relative_path: str, default: bool) -> bool:
        return default or path_is_under(relative_path, self.generated_dirs)


def load_profile(path: Path | str) -> ProjectProfile:
    profile_path = Path(path)
    with profile_path.open("rb") as handle:
        payload = tomllib.load(handle)
    return profile_from_dict(payload)


def profile_from_dict(payload: Mapping[str, Any]) -> ProjectProfile:
    if not isinstance(payload, Mapping):
        raise ProfileValidationError("profile must be a TOML table")
    return ProjectProfile(
        command_dirs=tuple_list(payload.get("command_dirs", ()), "command_dirs"),
        script_dirs=tuple_list(payload.get("script_dirs", ()), "script_dirs"),
        generated_dirs=tuple_list(
            payload.get("generated_dirs", ()), "generated_dirs"
        ),
        role_overrides=string_mapping(
            payload.get("role_overrides", {}), "role_overrides"
        ),
        confidence_overrides=string_mapping(
            payload.get("confidence_overrides", {}), "confidence_overrides"
        ),
    )


def tuple_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value in (None, ()):
        return ()
    if not isinstance(value, list):
        raise ProfileValidationError(f"{field_name} must be a list of strings")
    for item in value:
        if not isinstance(item, str):
            raise ProfileValidationError(f"{field_name} must be a list of strings")
    return tuple(normalize_path(item) for item in value)


def string_mapping(value: Any, field_name: str) -> dict[str, str]:
    if value in (None, {}):
        return {}
    if not isinstance(value, Mapping):
        raise ProfileValidationError(f"{field_name} must be a table")
    result = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ProfileValidationError(f"{field_name} must map strings to strings")
        result[normalize_path(key)] = item
    return result


def validate_mapping(
    mapping: Mapping[str, str], field_name: str, allowed_values: frozenset[str]
) -> None:
    for path, value in mapping.items():
        validate_relative_path(path, field_name)
        if value not in allowed_values:
            values = ", ".join(sorted(allowed_values))
            raise ProfileValidationError(
                f"{field_name} for {path} must be one of: {values}"
            )


def validate_relative_path(path: str, field_name: str) -> None:
    if not path or path.startswith("/") or ".." in Path(path).parts:
        raise ProfileValidationError(f"{field_name} entries must be relative paths")


def path_is_under(relative_path: str, directories: tuple[str, ...]) -> bool:
    return any(
        relative_path == directory or relative_path.startswith(f"{directory}/")
        for directory in directories
    )


def normalize_path(path: str) -> str:
    return path.strip().strip("/")
