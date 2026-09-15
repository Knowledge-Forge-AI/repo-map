"""Python ecosystem configuration raw observation extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from repomap_kg import __version__
from repomap_kg.extractors.config.paths import json_pointer
from repomap_kg.graph.keys import external_key, external_url_key, file_key
from repomap_kg.observations.raw import RawObservation
from repomap_kg.extractors.config.python_support import (
    PYTHON_MAX_METADATA_STRING,
    PYTHON_MAX_REQUIREMENT_DIAGNOSTICS,
    PYTHON_MAX_REQUIREMENT_REFERENCES,
    PYTHON_MAX_REQUIREMENTS,
    PYTHON_REQUIREMENT_NAME_PATTERN,
    PYTHON_REQUIREMENTS_FORMAT,
    PYTHON_REQUIREMENTS_NAME_PATTERN,
    PYTHON_REQUIREMENTS_PROFILE,
    _PythonRequirement,
    _extractor_name,
    _generic_helper,
    _is_pyproject_file_name,
    _is_python_requirements_file_name,
    _is_secret_key,
    _is_url,
    _looks_like_secret_scalar,
    _normalize_repo_path,
    _normalized_key,
    _parse_python_requirement_line,
    _profile_observation,
    _python_bounded_string,
    _python_requirement_extras,
    _python_requirement_file_family,
    _python_requirement_is_direct_source,
    _python_requirement_is_local_path,
    _python_requirement_is_vcs_source,
    _python_requirement_line_without_comment,
    _python_requirement_local_path_target,
    _python_requirement_local_path_value,
    _python_requirement_package_from_source,
    _python_sequence_count,
    _python_slug,
    _resolve_repo_path,
    _safe_error_message,
    _safe_value_summary,
    _stable_text_sha256,
    _url_has_credentials,
)


def _extract_python_requirements_observations(
    relative_path: str,
    content: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    requirement_count = 0
    reference_count = 0
    redaction_count = 0
    parse_error_count = 0
    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = _python_requirement_line_without_comment(line)
        if not stripped:
            continue
        if stripped.startswith(("-r ", "--requirement ")):
            path_value = stripped.split(maxsplit=1)[1].strip()
            refs, errors = _python_requirement_file_reference_observations(
                relative_path,
                path_value,
                line_number=line_number,
                reference_kind="include_file",
            )
            observations.extend(refs)
            observations.extend(errors)
            reference_count += len(refs)
            parse_error_count += len(errors)
            continue
        if stripped.startswith(("-c ", "--constraint ")):
            path_value = stripped.split(maxsplit=1)[1].strip()
            refs, errors = _python_requirement_file_reference_observations(
                relative_path,
                path_value,
                line_number=line_number,
                reference_kind="constraint_file",
            )
            observations.extend(refs)
            observations.extend(errors)
            reference_count += len(refs)
            parse_error_count += len(errors)
            continue
        if stripped.startswith(("--index-url ", "--extra-index-url ", "--find-links ")):
            option, value = stripped.split(maxsplit=1)
            refs, redactions = _python_requirement_url_reference_observations(
                relative_path,
                value.strip(),
                line_number=line_number,
                reference_kind=option.lstrip("-").replace("-", "_"),
                redact_all=True,
            )
            observations.extend(refs)
            observations.extend(redactions)
            reference_count += len(refs)
            redaction_count += len(redactions)
            continue
        if stripped.startswith("--hash=") or stripped.startswith("--"):
            continue
        requirement = _parse_python_requirement_line(stripped, line_number=line_number)
        if requirement is None:
            observations.append(
                _python_parse_error_observation(
                    relative_path,
                    error_kind="malformed-python-requirement",
                    message="requirement line is not statically supported",
                    start_line=line_number,
                    source_suffix=f"requirement:{line_number}",
                )
            )
            parse_error_count += 1
            continue
        if requirement_count >= PYTHON_MAX_REQUIREMENTS:
            observations.append(
                _python_parse_error_observation(
                    relative_path,
                    error_kind="python-requirements-limit",
                    message="requirements file exceeds dependency limit",
                    start_line=line_number,
                    source_suffix=f"requirement-limit:{line_number}",
                )
            )
            parse_error_count += 1
            break
        observations.append(_python_requirement_observation(relative_path, requirement))
        requirement_count += 1
        refs, redactions = _python_requirement_source_observations(
            relative_path,
            requirement,
        )
        observations.extend(refs)
        observations.extend(redactions)
        reference_count += len(refs)
        redaction_count += len(redactions)
    package_file = _python_package_file_observation(
        relative_path,
        requirement_count=requirement_count,
        reference_count=reference_count,
        redaction_count=redaction_count,
        parse_error_count=parse_error_count,
    )
    return (package_file, *observations)


def _python_package_file_observation(
    relative_path: str,
    *,
    requirement_count: int,
    reference_count: int,
    redaction_count: int,
    parse_error_count: int,
) -> RawObservation:
    return _profile_observation(
        "python.package_file",
        relative_path,
        profile=PYTHON_REQUIREMENTS_PROFILE,
        format_name=PYTHON_REQUIREMENTS_FORMAT,
        confidence="extracted",
        metadata={
            "file_family": _python_requirement_file_family(relative_path),
            "source_format": PYTHON_REQUIREMENTS_FORMAT,
            "requirement_count": requirement_count,
            "reference_count": reference_count,
            "redaction_count": redaction_count,
            "parse_error_count": parse_error_count,
            "raw_profile_only": True,
        },
        name=PurePosixPath(relative_path).name,
        source_suffix="python-package-file",
    )




def _python_requirement_observation(
    relative_path: str,
    requirement: _PythonRequirement,
    *,
    dependency_group: str = "requirements",
    source_suffix_prefix: str = "python-requirement",
) -> RawObservation:
    metadata: dict[str, Any] = {
        "profile": "python",
        "file_family": _python_requirement_file_family(relative_path),
        "source_format": PYTHON_REQUIREMENTS_FORMAT,
        "dependency_group": dependency_group,
        "editable": requirement.editable,
        "direct_url": requirement.direct_url,
        "local_path": requirement.local_path,
        "not_fetched": requirement.direct_url,
        "raw_profile_only": True,
    }
    if requirement.line_number is not None:
        metadata["line"] = requirement.line_number
    if requirement.package_name is not None:
        metadata["package_name"] = _python_bounded_string(requirement.package_name)
    if requirement.specifier is not None:
        metadata["specifier"] = _python_bounded_string(requirement.specifier)
    if requirement.extras:
        metadata["extras"] = list(requirement.extras)
    if requirement.environment_marker is not None:
        metadata["environment_marker"] = _python_bounded_string(
            requirement.environment_marker
        )
    if requirement.source is not None:
        metadata.update(_python_dependency_source_metadata(requirement.source))
    return RawObservation(
        kind="python.requirement",
        source_id=(
            f"{relative_path}#{source_suffix_prefix}:"
            f"{requirement.line_number or 'document'}:"
            f"{_python_slug(requirement.package_name or 'source')}"
        ),
        path=relative_path,
        start_line=requirement.line_number,
        end_line=requirement.line_number,
        name=requirement.package_name,
        confidence="extracted",
        extractor=_extractor_name(),
        extractor_version=__version__,
        metadata=metadata,
    )


def _python_requirement_source_observations(
    relative_path: str,
    requirement: _PythonRequirement,
) -> tuple[list[RawObservation], list[RawObservation]]:
    if requirement.source is None:
        return [], []
    if requirement.local_path:
        refs, errors = _python_requirement_file_reference_observations(
            relative_path,
            _python_requirement_local_path_value(requirement.source),
            line_number=requirement.line_number,
            reference_kind="local_path",
        )
        return refs, errors
    return _python_requirement_url_reference_observations(
        relative_path,
        requirement.source,
        line_number=requirement.line_number,
        reference_kind="direct_url",
        redact_all=False,
    )


def _python_requirement_file_reference_observations(
    relative_path: str,
    value: str,
    *,
    line_number: int | None,
    reference_kind: str,
) -> tuple[list[RawObservation], list[RawObservation]]:
    target = _python_requirement_local_path_target(relative_path, value)
    if target is None:
        return [], [
            _python_parse_error_observation(
                relative_path,
                error_kind="repo-escaping-requirement-reference",
                message="requirement file reference escapes repository root",
                start_line=line_number,
                source_suffix=f"requirement-reference:{reference_kind}:{line_number}",
            )
        ]
    return [
        _python_reference_observation(
            relative_path,
            reference_kind=reference_kind,
            target=target,
            line_number=line_number,
            metadata={
                "resolution": "local",
                "not_fetched": False,
                "redacted": False,
            },
        )
    ], []


def _python_requirement_url_reference_observations(
    relative_path: str,
    value: str,
    *,
    line_number: int | None,
    reference_kind: str,
    redact_all: bool,
) -> tuple[list[RawObservation], list[RawObservation]]:
    redacted = redact_all or _url_has_credentials(value)
    if redacted:
        target = external_key("url", f"redacted-python-{reference_kind}")
    elif _is_url(value) or _python_requirement_is_vcs_source(value):
        target = external_url_key(value)
    else:
        target = external_key("python.source", "unknown-direct-source")
    metadata = {
        "not_fetched": True,
        "redacted": redacted,
        **_python_dependency_source_metadata(value),
    }
    if redacted:
        metadata["redaction_reason"] = (
            "credentialed-url" if _url_has_credentials(value) else "index-url"
        )
    references = [
        _python_reference_observation(
            relative_path,
            reference_kind=reference_kind,
            target=target,
            line_number=line_number,
            metadata=metadata,
        )
    ]
    redactions = []
    if redacted:
        redactions.append(
            _python_redaction_observation(
                relative_path,
                redaction_kind=reference_kind,
                reason=metadata["redaction_reason"],
                line_number=line_number,
            )
        )
    return references, redactions


def _python_reference_observation(
    relative_path: str,
    *,
    reference_kind: str,
    target: str,
    line_number: int | None,
    metadata: dict[str, Any],
) -> RawObservation:
    return RawObservation(
        kind="python.reference",
        source_id=f"{relative_path}#python-reference:{reference_kind}:{line_number}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=reference_kind,
        target=target,
        confidence="extracted",
        extractor=_extractor_name(),
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": PYTHON_REQUIREMENTS_FORMAT,
            "reference_kind": reference_kind,
            "raw_profile_only": True,
            **metadata,
        },
    )


def _python_pyproject_metadata_overrides(
    value: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    overrides: dict[str, dict[str, Any]] = {}
    for pointer_segments, item in _python_pyproject_walk(value):
        pointer = json_pointer(pointer_segments)
        if _python_pyproject_value_requires_redaction(pointer_segments, item):
            overrides[pointer] = {
                "redacted": True,
                "redaction_reason": "python-profile-redaction",
            }
            if pointer_segments:
                parent_pointer = json_pointer(pointer_segments[:-1])
                if parent_pointer:
                    overrides[parent_pointer] = {
                        "redacted": True,
                        "redaction_reason": "python-profile-redaction",
                    }
    return overrides


def _python_pyproject_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> tuple[RawObservation, ...]:
    observations: list[RawObservation] = []
    project = value.get("project")
    if isinstance(project, dict):
        metadata: dict[str, Any] = {
            "source_format": "pyproject.toml",
            "raw_profile_only": True,
            "dependency_count": _python_sequence_count(project.get("dependencies")),
        }
        name_summary = _safe_value_summary(project.get("name"))
        if isinstance(name_summary, str) and not _is_secret_key(name_summary):
            metadata["project_name"] = _python_bounded_string(name_summary)
        version_summary = _safe_value_summary(project.get("version"))
        if isinstance(version_summary, str):
            metadata["project_version"] = _python_bounded_string(version_summary)
        dynamic = project.get("dynamic")
        if isinstance(dynamic, list):
            metadata["dynamic_metadata"] = [
                _python_bounded_string(str(item))
                for item in dynamic
                if isinstance(item, str) and not _is_secret_key(item)
            ]
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            metadata["optional_dependency_groups"] = sorted(str(key) for key in optional)
        observations.append(
            _profile_observation(
                "python.pyproject",
                relative_path,
                profile="python",
                format_name=format_name,
                confidence=confidence,
                metadata=metadata,
                name=metadata.get("project_name", "pyproject.toml"),
                source_suffix="python-pyproject",
            )
        )
        observations.extend(
            _python_requirement_observations_from_values(
                relative_path,
                project.get("dependencies"),
                dependency_group="project.dependencies",
                source_suffix_prefix="python-pyproject-dependency",
            )
        )
        if isinstance(optional, dict):
            for group in sorted(str(key) for key in optional):
                observations.append(
                    _profile_observation(
                        "python.dependency_group",
                        relative_path,
                        profile="python",
                        format_name=format_name,
                        confidence=confidence,
                        metadata={
                            "source_format": "pyproject.toml",
                            "dependency_group": f"project.optional-dependencies.{group}",
                            "optional_group": group,
                            "dependency_count": _python_sequence_count(
                                optional.get(group)
                            ),
                            "raw_profile_only": True,
                        },
                        name=group,
                        source_suffix=f"python-dependency-group:{group}",
                    )
                )
                observations.extend(
                    _python_requirement_observations_from_values(
                        relative_path,
                        optional.get(group),
                        dependency_group=f"project.optional-dependencies.{group}",
                        source_suffix_prefix=f"python-pyproject-optional:{group}",
                    )
                )
        for section_name in ("scripts", "gui-scripts"):
            observations.extend(
                _python_entry_point_observations(
                    relative_path,
                    project.get(section_name),
                    entry_point_group=f"project.{section_name}",
                    format_name=format_name,
                    confidence=confidence,
                )
            )
        entry_points = project.get("entry-points")
        if isinstance(entry_points, dict):
            for group in sorted(str(key) for key in entry_points):
                observations.extend(
                    _python_entry_point_observations(
                        relative_path,
                        entry_points.get(group),
                        entry_point_group=f"project.entry-points.{group}",
                        format_name=format_name,
                        confidence=confidence,
                    )
                )
    build_system = value.get("build-system")
    if isinstance(build_system, dict):
        requires = build_system.get("requires")
        metadata = {
            "source_format": "pyproject.toml",
            "requires_count": _python_sequence_count(requires),
            "raw_profile_only": True,
        }
        backend_summary = _safe_value_summary(build_system.get("build-backend"))
        if isinstance(backend_summary, str):
            metadata["build_backend"] = _python_bounded_string(backend_summary)
        observations.append(
            _profile_observation(
                "python.build_system",
                relative_path,
                profile="python",
                format_name=format_name,
                confidence=confidence,
                metadata=metadata,
                name=metadata.get("build_backend", "build-system"),
                source_suffix="python-build-system",
            )
        )
        observations.extend(
            _python_requirement_observations_from_values(
                relative_path,
                requires,
                dependency_group="build-system.requires",
                source_suffix_prefix="python-build-system-requirement",
            )
        )
    tool = value.get("tool")
    if isinstance(tool, dict):
        for tool_name in sorted(str(key) for key in tool):
            if len(observations) >= PYTHON_MAX_REQUIREMENTS:
                break
            observations.append(
                _profile_observation(
                    "python.tool_config",
                    relative_path,
                    profile="python",
                    format_name=format_name,
                    confidence=confidence,
                    metadata={
                        "source_format": "pyproject.toml",
                        "tool_name": _python_bounded_string(tool_name),
                        "tool_section": f"tool.{tool_name}",
                        "raw_profile_only": True,
                    },
                    name=tool_name,
                    source_suffix=f"python-tool-config:{tool_name}",
                )
            )
    groups = value.get("dependency-groups")
    if isinstance(groups, dict):
        for group in sorted(str(key) for key in groups):
            observations.extend(
                _python_requirement_observations_from_values(
                    relative_path,
                    groups.get(group),
                    dependency_group=f"dependency-groups.{group}",
                    source_suffix_prefix=f"python-dependency-group:{group}",
                )
            )
    return tuple(observations)


def _python_requirement_observations_from_values(
    relative_path: str,
    value: Any,
    *,
    dependency_group: str,
    source_suffix_prefix: str,
) -> list[RawObservation]:
    if not isinstance(value, list):
        return []
    observations: list[RawObservation] = []
    for index, item in enumerate(value[:PYTHON_MAX_REQUIREMENTS]):
        if not isinstance(item, str):
            observations.append(
                _python_parse_error_observation(
                    relative_path,
                    error_kind="unsupported-pyproject-dependency",
                    message="dependency entry is not a string",
                    start_line=None,
                    source_suffix=f"{source_suffix_prefix}:{index}:unsupported",
                )
            )
            continue
        requirement = _parse_python_requirement_line(item, line_number=None)
        if requirement is None:
            observations.append(
                _python_parse_error_observation(
                    relative_path,
                    error_kind="malformed-pyproject-dependency",
                    message="dependency entry is not statically supported",
                    start_line=None,
                    source_suffix=f"{source_suffix_prefix}:{index}:malformed",
                )
            )
            continue
        observations.append(
            _python_requirement_observation(
                relative_path,
                requirement,
                dependency_group=dependency_group,
                source_suffix_prefix=f"{source_suffix_prefix}:{index}",
            )
        )
        refs, redactions = _python_requirement_source_observations(
            relative_path,
            requirement,
        )
        observations.extend(refs)
        observations.extend(redactions)
    return observations


def _python_entry_point_observations(
    relative_path: str,
    value: Any,
    *,
    entry_point_group: str,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    if not isinstance(value, dict):
        return []
    observations = []
    for entry_point_name in sorted(str(key) for key in value):
        target_summary = _safe_value_summary(value.get(entry_point_name))
        metadata = {
            "source_format": "pyproject.toml",
            "entry_point_group": entry_point_group,
            "entry_point_name": _python_bounded_string(entry_point_name),
            "raw_profile_only": True,
        }
        if isinstance(target_summary, str) and not _looks_like_secret_scalar(
            target_summary
        ):
            metadata["entry_point_target"] = _python_bounded_string(target_summary)
        observations.append(
            _profile_observation(
                "python.entry_point",
                relative_path,
                profile="python",
                format_name=format_name,
                confidence=confidence,
                metadata=metadata,
                name=entry_point_name,
                source_suffix=f"python-entry-point:{entry_point_group}:{entry_point_name}",
            )
        )
    return observations


def _python_parse_error_observation(
    relative_path: str,
    *,
    error_kind: str,
    message: str,
    start_line: int | None,
    source_suffix: str,
) -> RawObservation:
    return RawObservation(
        kind="python.parse_error",
        source_id=f"{relative_path}#python-parse-error:{source_suffix}",
        path=relative_path,
        start_line=start_line,
        end_line=start_line,
        confidence="unknown",
        extractor=_extractor_name(),
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "pyproject.toml"
            if _is_pyproject_file_name(relative_path)
            else PYTHON_REQUIREMENTS_FORMAT,
            "error_kind": error_kind,
            "message_summary": _safe_error_message(None, message),
            "recovered": False,
            "raw_profile_only": True,
        },
    )


def _python_redaction_observation(
    relative_path: str,
    *,
    redaction_kind: str,
    reason: str,
    line_number: int | None,
) -> RawObservation:
    return RawObservation(
        kind="python.redaction",
        source_id=f"{relative_path}#python-redaction:{redaction_kind}:{line_number or 'document'}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        confidence="extracted",
        extractor=_extractor_name(),
        extractor_version=__version__,
        metadata={
            "profile": "python",
            "source_format": "pyproject.toml"
            if _is_pyproject_file_name(relative_path)
            else PYTHON_REQUIREMENTS_FORMAT,
            "redaction_kind": redaction_kind,
            "redaction_reason": reason,
            "redacted": True,
            "raw_profile_only": True,
        },
    )


def _python_dependency_source_metadata(value: str) -> dict[str, Any]:
    parsed = urlsplit(value)
    credentialed = _url_has_credentials(value)
    metadata: dict[str, Any] = {
        "source_present": True,
        "source_length": len(value),
        "source_sha256": _stable_text_sha256(value),
    }
    if parsed.scheme:
        metadata["source_scheme"] = _python_bounded_string(parsed.scheme)
    if parsed.hostname and not credentialed:
        metadata["source_host"] = _python_bounded_string(parsed.hostname)
    if credentialed:
        metadata["redacted"] = True
        metadata["redaction_reason"] = "credentialed-url"
    return metadata




def _python_pyproject_walk(
    value: Any,
    pointer_segments: tuple[str, ...] = (),
) -> tuple[tuple[tuple[str, ...], Any], ...]:
    items: list[tuple[tuple[str, ...], Any]] = [(pointer_segments, value)]
    if isinstance(value, dict):
        for key, item in value.items():
            items.extend(_python_pyproject_walk(item, (*pointer_segments, str(key))))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            items.extend(_python_pyproject_walk(item, (*pointer_segments, str(index))))
    return tuple(items)


def _python_pyproject_value_requires_redaction(
    pointer_segments: tuple[str, ...],
    value: Any,
) -> bool:
    if any(_is_secret_key(segment) for segment in pointer_segments):
        return True
    if isinstance(value, str):
        if (
            _url_has_credentials(value)
            or _python_value_has_credentialed_url_fragment(value)
            or _looks_like_secret_scalar(value)
        ):
            return True
        if pointer_segments and _normalized_key(pointer_segments[-1]) in (
            "index_url",
            "extra_index_url",
            "url",
        ):
            return _is_url(value)
    return False


def _python_value_has_credentialed_url_fragment(value: str) -> bool:
    fragments = re.findall(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s,]+", value)
    return any(_url_has_credentials(fragment.strip("\"'")) for fragment in fragments)
