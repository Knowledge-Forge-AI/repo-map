"""Shared Python configuration extraction primitives."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from repomap_kg.graph.keys import file_key
from repomap_kg.observations.raw import RawObservation


PYTHON_REQUIREMENTS_FORMAT = "python-requirements"
PYTHON_REQUIREMENTS_PROFILE = "python"
PYTHON_REQUIREMENTS_NAME_PATTERN = re.compile(
    r"^(?:requirements(?:-[0-9A-Za-z_.-]+)?|dev-requirements|test-requirements)\.txt$"
)
PYTHON_REQUIREMENT_NAME_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)"
    r"(?P<extras>\[[A-Za-z0-9_, .-]+\])?"
    r"(?P<specifier>.*)$"
)
PYTHON_MAX_REQUIREMENTS = 256
PYTHON_MAX_REQUIREMENT_REFERENCES = 128
PYTHON_MAX_REQUIREMENT_DIAGNOSTICS = 64
PYTHON_MAX_METADATA_STRING = 160


@dataclass(frozen=True)
class _PythonRequirement:
    package_name: str | None
    specifier: str | None
    extras: tuple[str, ...]
    environment_marker: str | None
    source: str | None
    editable: bool
    direct_url: bool
    local_path: bool
    line_number: int | None
    raw_kind: str


def _generic_helper(name: str) -> Any:
    from repomap_kg.extractors.config import generic_contracts as generic

    return getattr(generic, name)


def _profile_observation(*args: Any, **kwargs: Any) -> RawObservation:
    return _generic_helper("_profile_observation")(*args, **kwargs)


def _extractor_name() -> str:
    return _generic_helper("EXTRACTOR_NAME")


def _safe_value_summary(value: Any) -> Any:
    return _generic_helper("_safe_value_summary")(value)


def _url_has_credentials(value: str) -> bool:
    return _generic_helper("_url_has_credentials")(value)


def _is_url(value: str) -> bool:
    return _generic_helper("_is_url")(value)


def _stable_text_sha256(value: str) -> str:
    return _generic_helper("_stable_text_sha256")(value)


def _resolve_repo_path(relative_path: str, value: str) -> str | None:
    return _generic_helper("_resolve_repo_path")(relative_path, value)


def _normalize_repo_path(value: str) -> str | None:
    return _generic_helper("_normalize_repo_path")(value)


def _safe_error_message(error: Exception | None, fallback: str) -> str:
    return _generic_helper("_safe_error_message")(error, fallback)


def _is_secret_key(key: str) -> bool:
    return _generic_helper("_is_secret_key")(key)


def _normalized_key(key: str) -> str:
    return _generic_helper("_normalized_key")(key)


def _looks_like_secret_scalar(value: str) -> bool:
    return _generic_helper("_looks_like_secret_scalar")(value)


def _python_requirement_line_without_comment(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    if " #" in stripped:
        return stripped.split(" #", 1)[0].strip()
    return stripped


def _parse_python_requirement_line(
    stripped: str,
    *,
    line_number: int | None,
) -> _PythonRequirement | None:
    editable = False
    value = stripped
    if value.startswith(("-e ", "--editable ")):
        editable = True
        value = value.split(maxsplit=1)[1].strip()
    package_part: str | None = None
    source: str | None = None
    if " @ " in value:
        package_part, source = value.split(" @ ", 1)
    elif _python_requirement_is_direct_source(value) or editable:
        source = value
        package_part = _python_requirement_package_from_source(value)
    else:
        package_part = value
    if package_part is None:
        return None
    marker: str | None = None
    if ";" in package_part:
        package_part, marker = (item.strip() for item in package_part.split(";", 1))
    match = PYTHON_REQUIREMENT_NAME_PATTERN.match(package_part.strip())
    if match is None:
        return None
    package_name = match.group("name")
    specifier = match.group("specifier").strip()
    if specifier and not specifier.startswith(("=", "!", "~", ">", "<")):
        return None
    extras = _python_requirement_extras(match.group("extras"))
    if source is not None and ";" in source:
        source, source_marker = (item.strip() for item in source.split(";", 1))
        marker = marker or source_marker
    return _PythonRequirement(
        package_name=package_name,
        specifier=specifier or None,
        extras=extras,
        environment_marker=marker,
        source=source,
        editable=editable,
        direct_url=_python_requirement_is_direct_source(source or ""),
        local_path=_python_requirement_is_local_path(source or ""),
        line_number=line_number,
        raw_kind="requirement",
    )


def _python_requirement_extras(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    inner = value.strip()[1:-1]
    return tuple(sorted(item.strip() for item in inner.split(",") if item.strip()))


def _python_requirement_package_from_source(value: str) -> str | None:
    if "#egg=" in value:
        egg = value.split("#egg=", 1)[1].split("&", 1)[0].strip()
        if PYTHON_REQUIREMENT_NAME_PATTERN.match(egg):
            return egg
    name = PurePosixPath(value.rstrip("/")).name
    if name.endswith((".git", ".zip", ".tar.gz", ".tgz", ".whl")):
        name = name.split(".", 1)[0]
    if PYTHON_REQUIREMENT_NAME_PATTERN.match(name):
        return name
    return None


def _python_requirement_file_family(relative_path: str) -> str:
    name = PurePosixPath(relative_path).name
    if name == "requirements.txt":
        return "requirements.txt"
    if name == "dev-requirements.txt":
        return "dev-requirements.txt"
    if name == "test-requirements.txt":
        return "test-requirements.txt"
    if name.startswith("requirements-") and name.endswith(".txt"):
        return "requirements-variant"
    return "requirements"


def _python_requirement_is_direct_source(value: str) -> bool:
    return (
        _is_url(value)
        or value.startswith("file:")
        or _python_requirement_is_vcs_source(value)
    )


def _python_requirement_is_vcs_source(value: str) -> bool:
    return value.startswith(("git+", "hg+", "svn+", "bzr+"))


def _python_requirement_is_local_path(value: str) -> bool:
    if value.startswith("file:"):
        return not _is_url(value.removeprefix("file:"))
    return value.startswith(("./", "../", "/")) and not _is_url(value)


def _python_requirement_local_path_value(value: str) -> str:
    return value.removeprefix("file:")


def _python_requirement_local_path_target(
    relative_path: str,
    value: str,
) -> str | None:
    local_value = _python_requirement_local_path_value(value)
    if local_value.startswith("/"):
        return None
    if local_value.startswith(("./", "../")):
        resolved = _resolve_repo_path(relative_path, local_value)
    else:
        resolved = _normalize_repo_path(local_value)
    if resolved is None:
        return None
    return file_key(resolved)


def _python_sequence_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _python_bounded_string(value: str) -> str:
    if len(value) <= PYTHON_MAX_METADATA_STRING:
        return value
    return f"<string:{len(value)}>"


def _python_slug(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "-", value).strip("-") or "unknown"


def _is_python_requirements_file_name(relative_path: str) -> bool:
    return bool(PYTHON_REQUIREMENTS_NAME_PATTERN.match(PurePosixPath(relative_path).name))


def _is_pyproject_file_name(relative_path: str) -> bool:
    return PurePosixPath(relative_path).name == "pyproject.toml"
