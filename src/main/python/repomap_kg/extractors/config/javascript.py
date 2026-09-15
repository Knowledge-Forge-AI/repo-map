"""JavaScript/package ecosystem configuration raw observation extraction."""

from __future__ import annotations

import re
from typing import Any

from repomap_kg import __version__
from repomap_kg.extractors.config.paths import json_pointer
from repomap_kg.graph.keys import (
    config_document_key,
    config_path_key,
    external_key,
    external_url_key,
)
from repomap_kg.observations.raw import RawObservation


TFJSON_PACKAGE_DEPENDENCY_GROUPS = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
)
TFJSON_FRAMEWORK_DEPENDENCY_HINTS = {
    "@angular/core": "angular",
    "@nestjs/core": "nestjs",
    "express": "express",
    "jest": "jest",
    "jquery": "jquery",
    "next": "next",
    "react": "react",
    "vue": "vue",
}


def _generic_helper(name: str) -> Any:
    from repomap_kg.extractors.config import generic_contracts as generic

    return getattr(generic, name)


def _profile_observation(*args: Any, **kwargs: Any) -> RawObservation:
    return _generic_helper("_profile_observation")(*args, **kwargs)


def _extractor_name() -> str:
    return _generic_helper("EXTRACTOR_NAME")


def _safe_value_summary(value: Any) -> Any:
    return _generic_helper("_safe_value_summary")(value)


def _is_url(value: str) -> bool:
    return _generic_helper("_is_url")(value)


def _file_reference(relative_path: str, value: str, *, redacted: bool) -> dict[str, Any]:
    return _generic_helper("_file_reference")(relative_path, value, redacted=redacted)


def _line_for_pointer(content: str, pointer: str) -> int | None:
    return _generic_helper("_line_for_pointer")(content, pointer)


def _normalized_key(key: str) -> str:
    return _generic_helper("_normalized_key")(key)


def _is_clear_command_name(value: str) -> bool:
    return _generic_helper("_is_clear_command_name")(value)


def _package_json_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    content: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    declared_sections = sorted(
        key
        for key in (
            "scripts",
            *TFJSON_PACKAGE_DEPENDENCY_GROUPS,
            "workspaces",
            "bin",
            "exports",
            "imports",
            "engines",
        )
        if key in value
    )
    package_metadata: dict[str, Any] = {
        "declared_sections": declared_sections,
        "source_document_key": config_document_key(relative_path),
    }
    for source_key, target_key in (
        ("name", "package_name"),
        ("version", "package_version"),
        ("type", "package_type"),
        ("packageManager", "package_manager"),
    ):
        summary = _safe_value_summary(value.get(source_key))
        if isinstance(summary, str):
            package_metadata[target_key] = summary
    if isinstance(value.get("private"), bool):
        package_metadata["private"] = value["private"]
    observations.append(
        _profile_observation(
            "npm.package",
            relative_path,
            profile="package_json",
            format_name=format_name,
            confidence=confidence,
            metadata=package_metadata,
            name=str(value.get("name") or "package.json"),
            source_suffix="npm-package",
        )
    )
    scripts = value.get("scripts")
    if isinstance(scripts, dict):
        for script_name in sorted(str(key) for key in scripts):
            script_value = scripts.get(script_name)
            if not isinstance(script_value, str):
                continue
            redacted = _script_is_secret_prone(script_value)
            metadata = {
                "script_name": script_name,
                "redacted": redacted,
                "source_path_key": config_path_key(
                    relative_path,
                    json_pointer(("scripts", script_name)),
                ),
            }
            if redacted:
                metadata["redaction_reason"] = "secret-prone-script"
                metadata["command_summary"] = "<redacted-script>"
            else:
                metadata["command_summary"] = _script_command_summary(script_value)
            observations.append(
                _profile_observation(
                    "npm.script",
                    relative_path,
                    profile="package_json",
                    format_name=format_name,
                    confidence=confidence,
                    metadata=metadata,
                    name=script_name,
                    source_suffix=f"npm-script:{script_name}",
                )
            )
    observations.extend(
        _package_dependency_observations(
            relative_path,
            value,
            format_name=format_name,
            confidence=confidence,
        )
    )
    observations.extend(
        _package_framework_hints(
            relative_path,
            value,
            format_name=format_name,
            confidence=confidence,
        )
    )
    observations.extend(
        _package_reference_observations(
            relative_path,
            value,
            format_name=format_name,
            confidence=confidence,
        )
    )
    return observations


def _package_dependency_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for group in TFJSON_PACKAGE_DEPENDENCY_GROUPS:
        dependencies = value.get(group)
        if not isinstance(dependencies, dict):
            continue
        for dependency_name in sorted(str(key) for key in dependencies):
            version_summary = _safe_value_summary(dependencies.get(dependency_name))
            metadata = {
                "dependency_name": dependency_name,
                "dependency_group": group,
                "target_reference": external_key("npm.package", dependency_name),
                "source_path_key": config_path_key(
                    relative_path,
                    json_pointer((group, dependency_name)),
                ),
            }
            if isinstance(version_summary, str):
                metadata["version_constraint"] = version_summary
            observations.append(
                _profile_observation(
                    "npm.dependency",
                    relative_path,
                    profile="package_json",
                    format_name=format_name,
                    confidence=confidence,
                    metadata=metadata,
                    name=dependency_name,
                    target=external_key("npm.package", dependency_name),
                    source_suffix=f"npm-dependency:{group}:{dependency_name}",
                )
            )
    return observations


def _package_framework_hints(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    dependency_names: set[str] = set()
    for group in TFJSON_PACKAGE_DEPENDENCY_GROUPS:
        dependencies = value.get(group)
        if isinstance(dependencies, dict):
            dependency_names.update(str(key) for key in dependencies)
    for dependency_name in sorted(dependency_names):
        framework = TFJSON_FRAMEWORK_DEPENDENCY_HINTS.get(dependency_name)
        if framework is None:
            continue
        observations.append(
            _profile_observation(
                "ecosystem.framework_hint",
                relative_path,
                profile="package_json",
                format_name=format_name,
                confidence="heuristic",
                metadata={
                    "framework": framework,
                    "hint_reason": "package-dependency",
                    "dependency_name": dependency_name,
                },
                name=framework,
                source_suffix=f"ecosystem-framework:{framework}:{dependency_name}",
            )
        )
    scripts = value.get("scripts")
    if isinstance(scripts, dict):
        for script_name, script_value in sorted((str(k), v) for k, v in scripts.items()):
            if not isinstance(script_value, str) or _script_is_secret_prone(script_value):
                continue
            command = _script_command_summary(script_value)
            if command in ("jest", "next", "ng", "nest", "playwright"):
                observations.append(
                    _profile_observation(
                        "ecosystem.framework_hint",
                        relative_path,
                        profile="package_json",
                        format_name=format_name,
                        confidence="heuristic",
                        metadata={
                            "framework": command,
                            "hint_reason": "package-script",
                            "script_name": script_name,
                        },
                        name=command,
                        source_suffix=f"ecosystem-framework:script:{script_name}",
                    )
                )
    return observations


def _package_reference_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    for pointer, raw_value in (
        ("/repository/url", value.get("repository", {}).get("url") if isinstance(value.get("repository"), dict) else value.get("repository")),
        ("/homepage", value.get("homepage")),
        ("/bugs/url", value.get("bugs", {}).get("url") if isinstance(value.get("bugs"), dict) else value.get("bugs")),
    ):
        if not isinstance(raw_value, str) or not _is_url(raw_value):
            continue
        observations.append(
            _profile_observation(
                "ecosystem.reference",
                relative_path,
                profile="package_json",
                format_name=format_name,
                confidence="heuristic",
                metadata={
                    "reference_kind": "external.url",
                    "pointer": pointer,
                    "resolution_reason": "package-url-field",
                    "raw_value_summary": _safe_value_summary(raw_value),
                },
                target=external_url_key(raw_value),
                source_suffix=f"ecosystem-reference:{pointer}",
            )
        )
    return observations


def _package_lock_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
) -> list[RawObservation]:
    package_count = 0
    packages = value.get("packages")
    dependencies = value.get("dependencies")
    if isinstance(packages, dict):
        package_count = len(packages)
    elif isinstance(dependencies, dict):
        package_count = len(dependencies)
    return [
        _profile_observation(
            "ecosystem.package",
            relative_path,
            profile="package_lock_json",
            format_name=format_name,
            confidence=confidence,
            metadata={
                "lockfile": True,
                "lockfile_version": _safe_value_summary(value.get("lockfileVersion")),
                "package_count": package_count,
            },
            source_suffix="ecosystem-package-lock",
        )
    ]


def _typescript_config_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
    content: str,
) -> list[RawObservation]:
    compiler_options = value.get("compilerOptions")
    metadata = {
        "source_document_key": config_document_key(relative_path),
        "has_compiler_options": isinstance(compiler_options, dict),
        "extends": _safe_value_summary(value.get("extends")),
        "jsx": (
            _safe_value_summary(compiler_options.get("jsx"))
            if isinstance(compiler_options, dict)
            else None
        ),
    }
    path_aliases = compiler_options.get("paths") if isinstance(compiler_options, dict) else None
    if isinstance(path_aliases, dict):
        metadata["path_alias_count"] = len(path_aliases)
        metadata["path_aliases"] = sorted(str(key) for key in path_aliases)[:20]
    references = value.get("references")
    if isinstance(references, list):
        metadata["project_reference_count"] = len(references)
    observations = [
        _profile_observation(
            "typescript.config",
            relative_path,
            profile=profile,
            format_name=format_name,
            confidence=confidence,
            metadata={key: item for key, item in metadata.items() if item is not None},
            source_suffix="typescript-config",
        )
    ]
    if isinstance(value.get("extends"), str):
        observations.append(
            _typescript_reference_observation(
                relative_path,
                value["extends"],
                pointer="/extends",
                reference_kind="extends",
                format_name=format_name,
                confidence="heuristic",
                profile=profile,
                content=content,
            )
        )
    if isinstance(references, list):
        for index, item in enumerate(references):
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                observations.append(
                    _typescript_reference_observation(
                        relative_path,
                        item["path"],
                        pointer=f"/references/{index}/path",
                        reference_kind="project-reference",
                        format_name=format_name,
                        confidence="heuristic",
                        profile=profile,
                        content=content,
                    )
                )
    return observations


def _typescript_reference_observation(
    relative_path: str,
    value: str,
    *,
    pointer: str,
    reference_kind: str,
    format_name: str,
    confidence: str,
    profile: str,
    content: str,
) -> RawObservation:
    reference = _file_reference(relative_path, value, redacted=False)
    line_number = _line_for_pointer(content, pointer)
    return RawObservation(
        kind="typescript.reference",
        source_id=f"{relative_path}#typescript-reference:{pointer}",
        path=relative_path,
        start_line=line_number,
        end_line=line_number,
        name=pointer,
        target=reference["target"],
        confidence=confidence,
        extractor=_extractor_name(),
        extractor_version=__version__,
        metadata={
            "format": format_name,
            "profile": profile,
            "pointer": pointer,
            "reference_kind": reference_kind,
            "resolution_reason": reference["reason"],
            "raw_value_summary": _safe_value_summary(value),
            "source_document_key": config_document_key(relative_path),
        },
    )


def _angular_observations(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    content: str,
) -> list[RawObservation]:
    observations: list[RawObservation] = []
    projects = value.get("projects")
    if not isinstance(projects, dict):
        return observations
    for project_name in sorted(str(key) for key in projects):
        project = projects.get(project_name)
        if not isinstance(project, dict):
            continue
        metadata = {
            "project_name": project_name,
            "root": _safe_value_summary(project.get("root")),
            "source_root": _safe_value_summary(project.get("sourceRoot")),
            "source_path_key": config_path_key(
                relative_path,
                json_pointer(("projects", project_name)),
            ),
        }
        observations.append(
            _profile_observation(
                "angular.project",
                relative_path,
                profile="angular_workspace",
                format_name=format_name,
                confidence=confidence,
                metadata={key: item for key, item in metadata.items() if item is not None},
                name=project_name,
                source_suffix=f"angular-project:{project_name}",
            )
        )
        targets = project.get("architect") or project.get("targets")
        if not isinstance(targets, dict):
            continue
        for target_name in sorted(str(key) for key in targets):
            target_value = targets.get(target_name)
            builder = (
                target_value.get("builder")
                if isinstance(target_value, dict)
                else None
            )
            observations.append(
                _profile_observation(
                    "angular.target",
                    relative_path,
                    profile="angular_workspace",
                    format_name=format_name,
                    confidence=confidence,
                    metadata={
                        "project_name": project_name,
                        "target_name": target_name,
                        "builder": _safe_value_summary(builder),
                        "source_path_key": config_path_key(
                            relative_path,
                            json_pointer(("projects", project_name, "architect", target_name)),
                        ),
                    },
                    name=f"{project_name}:{target_name}",
                    source_suffix=f"angular-target:{project_name}:{target_name}",
                )
            )
    return observations


def _playwright_observation(
    relative_path: str,
    value: dict[str, Any],
    *,
    format_name: str,
    confidence: str,
    profile: str,
) -> RawObservation:
    project_names: list[str] = []
    projects = value.get("projects")
    if isinstance(projects, list):
        for project in projects:
            if isinstance(project, dict):
                name = _safe_value_summary(project.get("name"))
                if isinstance(name, str):
                    project_names.append(name)
    return _profile_observation(
        "playwright.config",
        relative_path,
        profile=profile,
        format_name=format_name,
        confidence=confidence,
        metadata={
            "test_dir": _safe_value_summary(value.get("testDir")),
            "project_names": project_names,
            "project_count": len(project_names),
        },
        source_suffix="playwright-config",
    )


def _script_is_secret_prone(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = _normalized_key(value)
    if any(marker in normalized for marker in ("token", "secret", "password", "credential")):
        return True
    return bool(re.search(r"\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|KEY)=", value))


def _script_command_summary(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return "<empty-script>"
    first = stripped.split()[0]
    if "=" in first and len(stripped.split()) > 1:
        first = stripped.split()[1]
    if _is_clear_command_name(first):
        return first
    return "<script-command>"
