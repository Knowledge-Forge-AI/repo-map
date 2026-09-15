"""Observation extraction and metadata annotation for archive sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from repomap_kg.extractors.languages.python import PythonModuleIndex
from repomap_kg.graph.discovery import (
    FileInfo,
    extract_awk_file_observations_from_file,
    extract_bash_file_observations_from_file,
    extract_bats_file_observations_from_file,
    extract_config_file_observations_from_file,
    extract_css_file_observations_from_file,
    extract_feed_file_observations_from_file,
    extract_html_file_observations_from_file,
    extract_javascript_file_observations_from_file,
    extract_markdown_file_observations_from_file,
    extract_nix_file_observations_from_file,
    extract_powershell_file_observations_from_file,
    extract_python_file_observations_from_file,
    extract_shell_file_observations,
    extract_zsh_file_observations_from_file,
    extract_zunit_file_observations_from_file,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion._source_archive_records import (
    ArchiveIncludedFile,
    ArchiveManifest,
    ArchiveSourceConfig,
)


def _observations_for_archive_file(
    repository_root: Path,
    file_info: FileInfo,
    *,
    module_index: PythonModuleIndex,
    repository_paths: frozenset[str],
    markdown_anchors: Mapping[str, set[str] | frozenset[str]],
) -> tuple[RawObservation, ...]:
    observations = [file_info.to_observation()]
    if file_info.language == "markdown":
        observations.extend(
            extract_markdown_file_observations_from_file(
                repository_root,
                file_info,
                repository_paths=repository_paths,
                markdown_anchors=dict(markdown_anchors),
            )
        )
    if file_info.language == "shell":
        observations.extend(extract_shell_file_observations(repository_root, file_info.path))
    if file_info.language == "bash":
        observations.extend(
            extract_bash_file_observations_from_file(repository_root, file_info.path)
        )
    if file_info.language == "bats":
        observations.extend(
            extract_bats_file_observations_from_file(repository_root, file_info.path)
        )
    if file_info.language == "awk":
        observations.extend(
            extract_awk_file_observations_from_file(repository_root, file_info.path)
        )
    if file_info.language == "zsh":
        observations.extend(
            extract_zsh_file_observations_from_file(repository_root, file_info.path)
        )
    if file_info.language == "zunit":
        observations.extend(
            extract_zunit_file_observations_from_file(repository_root, file_info.path)
        )
    if file_info.language == "python":
        observations.extend(
            extract_python_file_observations_from_file(
                repository_root,
                file_info.path,
                module_index=module_index,
            )
        )
    if file_info.language == "nix":
        observations.extend(
            extract_nix_file_observations_from_file(repository_root, file_info.path)
        )
    if file_info.language == "powershell":
        observations.extend(
            extract_powershell_file_observations_from_file(
                repository_root,
                file_info.path,
            )
        )
    if file_info.language in ("json", "xml"):
        feed_observations = extract_feed_file_observations_from_file(
            repository_root,
            file_info.path,
        )
        if feed_observations:
            observations.extend(feed_observations)
            return tuple(observations)
    if file_info.language in ("json", "jsonc", "jsonl", "toml", "plist", "xml"):
        observations.extend(
            extract_config_file_observations_from_file(repository_root, file_info.path)
        )
    if file_info.language == "html":
        observations.extend(
            extract_html_file_observations_from_file(repository_root, file_info.path)
        )
    if file_info.language == "css":
        observations.extend(
            extract_css_file_observations_from_file(repository_root, file_info.path)
        )
    if file_info.language == "javascript":
        observations.extend(
            extract_javascript_file_observations_from_file(
                repository_root,
                file_info.path,
                repository_paths=repository_paths,
            )
        )
    return tuple(observations)


def _annotate_archive_observations(
    observations: Sequence[RawObservation],
    config: ArchiveSourceConfig,
    manifest: ArchiveManifest,
) -> tuple[RawObservation, ...]:
    by_repository_path = {
        item.repository_path: item for item in manifest.included_files
    }
    return tuple(
        replace(
            observation,
            metadata={
                **dict(observation.metadata),
                **_archive_observation_metadata(
                    observation,
                    config,
                    manifest,
                    by_repository_path,
                ),
            },
        )
        for observation in observations
    )


def _archive_observation_metadata(
    observation: RawObservation,
    config: ArchiveSourceConfig,
    manifest: ArchiveManifest,
    by_repository_path: Mapping[str, ArchiveIncludedFile],
) -> dict[str, Any]:
    included = by_repository_path.get(observation.path or "")
    artifact_relative_path = (
        included.repository_path
        if included is not None
        else observation.path or observation.source_id
    )
    metadata: dict[str, Any] = {
        "source_id": config.source_id,
        "source_id_configured": config.source_id,
        "source_type": config.source_type,
        "source_display_name": config.display_name,
        "source_policy_status": config.policy_status,
        "source_run_id": manifest.artifact_run_id,
        "source_artifact_id": manifest.artifact_manifest_id,
        "artifact_policy_status": config.policy_status,
        "artifact_run_id": manifest.artifact_run_id,
        "artifact_manifest_id": manifest.artifact_manifest_id,
        "artifact_profile": config.artifact_profile,
        "artifact_relative_path": artifact_relative_path,
        "source_artifact_path": artifact_relative_path,
        "artifact_retention_policy": config.retention_policy,
        "retention_policy": config.retention_policy,
        "config_redacted_keys": list(config.redacted_config_keys),
    }
    if included is not None:
        metadata.update(
            {
                "artifact_byte_length": included.byte_length,
                "source_artifact_bytes": included.byte_length,
                "artifact_sha256": included.sha256,
                "source_artifact_sha256": included.sha256,
                "artifact_extractor_route": included.extractor_route,
            }
        )
    return metadata
