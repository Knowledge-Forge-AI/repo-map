"""Local archive-source ingestion helpers."""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from repomap_kg.extractors.documents.css_html_matching import (
    extract_css_selector_match_observations,
)
from repomap_kg.extractors.languages.python import PythonModuleIndex
from repomap_kg.graph.discovery import classify_path, markdown_anchor_index
from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion._source_archive_extraction import (
    _annotate_archive_observations,
    _archive_observation_metadata,
    _observations_for_archive_file,
)
from repomap_kg.ops.ingestion._source_archive_records import (
    ARCHIVE_EXCLUDED_DIR_NAMES,
    JAVASCRIPT_ARCHIVE_EXTENSIONS,
    ArchiveImportSummary,
    ArchiveIncludedFile,
    ArchiveManifest,
    ArchiveSkippedFile,
    ArchiveSourceConfig,
)
from repomap_kg.ops.ingestion._source_archive_scan import (
    _archive_extractor_route,
    _archive_included_file,
    _archive_media_type,
    _is_hidden_relative_path,
    _resolve_archive_artifact_path,
    _scan_archive_directory,
    _scan_archive_file,
)
from repomap_kg.ops.ingestion.acquisition_contracts import (
    NonPublicationResult,
    non_publication_result,
)
from repomap_kg.ops.ingestion.source_common import (
    SourcePolicyError,
    _mapping,
    _optional_bool,
    _optional_text,
    _reject_archive_network_fields,
    _required_bool,
    _required_positive_int,
    _required_text,
    _secret_key_paths,
    _utc_now,
    _validate_archive_source_type,
    _validate_disallowed_flags,
    _validate_local_artifact_path,
    _validate_policy_status,
    _validate_source_id,
    json_dumps_stable,
)

Clock = Callable[[], datetime]


def load_archive_source_config(path: Path | str) -> ArchiveSourceConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, Mapping):
        raise SourcePolicyError("source config must be a TOML object")
    _reject_archive_network_fields(payload)
    source = _mapping(payload, "source")
    policy = _mapping(payload, "policy")
    artifact = _mapping(payload, "artifact")

    source_id = _required_text(source, "id", "source.id")
    source_type = _required_text(source, "type", "source.type")
    display_name = _optional_text(source, "display_name")
    policy_status = _required_text(policy, "status", "policy.status")
    max_artifact_bytes = _required_positive_int(
        policy,
        "max_artifact_bytes",
        "policy.max_artifact_bytes",
    )
    max_file_count = _required_positive_int(
        policy,
        "max_file_count",
        "policy.max_file_count",
    )
    max_depth = _required_positive_int(policy, "max_depth", "policy.max_depth")
    symlink_policy = _required_text(policy, "symlink_policy", "policy.symlink_policy")
    hidden_files = _required_bool(policy, "hidden_files", "policy.hidden_files")
    retention_policy = _required_text(
        policy,
        "retention_policy",
        "policy.retention_policy",
    )
    requires_manual_review = _optional_bool(
        policy.get("requires_manual_review"),
        "policy.requires_manual_review",
        default=False,
    )
    artifact_path = _required_text(artifact, "path", "artifact.path")
    artifact_kind = _required_text(artifact, "kind", "artifact.kind")
    artifact_profile = _required_text(artifact, "profile", "artifact.profile")

    _validate_source_id(source_id)
    _validate_archive_source_type(source_type)
    _validate_policy_status(policy_status)
    _validate_disallowed_flags(payload)
    if requires_manual_review:
        raise SourcePolicyError("source requires manual review before import")
    if symlink_policy != "do_not_follow":
        raise SourcePolicyError("policy.symlink_policy must be do_not_follow")
    if artifact_kind not in {"directory", "file"}:
        raise SourcePolicyError("artifact.kind must be directory or file")
    _validate_local_artifact_path(artifact_path)

    return ArchiveSourceConfig(
        source_id=source_id,
        source_type=source_type,
        display_name=display_name,
        policy_status=policy_status,
        max_artifact_bytes=max_artifact_bytes,
        max_file_count=max_file_count,
        max_depth=max_depth,
        symlink_policy=symlink_policy,
        hidden_files=hidden_files,
        retention_policy=retention_policy,
        requires_manual_review=requires_manual_review,
        artifact_path=artifact_path,
        artifact_kind=artifact_kind,
        artifact_profile=artifact_profile,
        entry_document=_optional_text(artifact, "entry_document"),
        redacted_config_keys=tuple(_secret_key_paths(payload)),
    )


def build_archive_manifest(
    config: ArchiveSourceConfig,
    *,
    root_path: Path | str,
    clock: Clock | None = None,
) -> ArchiveManifest:
    root = Path(root_path).resolve()
    artifact_root = _resolve_archive_artifact_path(root, config.artifact_path)
    if config.artifact_kind == "directory":
        if not artifact_root.is_dir():
            raise SourcePolicyError("artifact.path must be an existing directory")
        included, skipped = _scan_archive_directory(config, root, artifact_root)
    else:
        if artifact_root.is_symlink():
            raise SourcePolicyError("artifact.path must not be a symlink")
        if not artifact_root.is_file():
            raise SourcePolicyError("artifact.path must be an existing file")
        included, skipped = _scan_archive_file(config, root, artifact_root)
    now = clock() if clock is not None else _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)
    artifact_run_id = now.strftime("%Y%m%dT%H%M%SZ")
    policy_snapshot = _archive_policy_snapshot(config)
    manifest_payload = {
        "source_id": config.source_id,
        "source_type": config.source_type,
        "policy_status": config.policy_status,
        "artifact_run_id": artifact_run_id,
        "artifact_profile": config.artifact_profile,
        "artifact_root": config.artifact_path,
        "entry_document": config.entry_document,
        "included_files": [item.to_jsonable() for item in included],
        "skipped_files": [item.to_jsonable() for item in skipped],
        "policy_snapshot": policy_snapshot,
    }
    artifact_manifest_id = hashlib.sha256(
        json_dumps_stable(manifest_payload).encode("utf-8")
    ).hexdigest()[:16]
    return ArchiveManifest(
        source_id=config.source_id,
        source_type=config.source_type,
        policy_status=config.policy_status,
        artifact_run_id=artifact_run_id,
        artifact_manifest_id=artifact_manifest_id,
        artifact_profile=config.artifact_profile,
        artifact_root=config.artifact_path,
        entry_document=config.entry_document,
        included_files=included,
        skipped_files=skipped,
        policy_snapshot=policy_snapshot,
    )


def archive_observations_from_manifest(
    config: ArchiveSourceConfig,
    manifest: ArchiveManifest,
    *,
    root_path: Path | str,
) -> tuple[RawObservation, ...]:
    repository_root = Path(root_path).resolve()
    file_infos = [
        classify_path(repository_root, repository_root / item.repository_path)
        for item in manifest.included_files
    ]
    file_infos = sorted(file_infos, key=lambda file_info: file_info.path)
    module_index = PythonModuleIndex.from_python_paths(
        (file_info.path for file_info in file_infos if file_info.language == "python"),
        repository_root=repository_root,
    )
    repository_paths = frozenset(file_info.path for file_info in file_infos)
    markdown_anchors: dict[str, set[str] | frozenset[str]] = dict(
        markdown_anchor_index(repository_root, file_infos)
    )
    observations: list[RawObservation] = []
    for file_info in file_infos:
        observations.extend(
            _observations_for_archive_file(
                repository_root,
                file_info,
                module_index=module_index,
                repository_paths=repository_paths,
                markdown_anchors=markdown_anchors,
            )
        )
    observations.extend(extract_css_selector_match_observations(observations))
    return _annotate_archive_observations(observations, config, manifest)


def import_archive_source(
    config_path: Path | str,
    *,
    root_path: Path | str,
    clock: Clock | None = None,
) -> ArchiveImportSummary:
    config = load_archive_source_config(config_path)
    manifest = build_archive_manifest(config, root_path=root_path, clock=clock)
    observations = archive_observations_from_manifest(
        config,
        manifest,
        root_path=root_path,
    )
    return ArchiveImportSummary(
        source_id=config.source_id,
        source_type=config.source_type,
        policy_status=config.policy_status,
        artifact_run_id=manifest.artifact_run_id,
        artifact_manifest_id=manifest.artifact_manifest_id,
        included_files=manifest.file_count,
        skipped_files=manifest.skipped_file_count,
        observations=len(observations),
        raw_observations=tuple(observations),
        manifest=manifest,
        publication=non_publication_result(),
    )


def _archive_policy_snapshot(config: ArchiveSourceConfig) -> dict[str, Any]:
    return {
        "status": config.policy_status,
        "max_artifact_bytes": config.max_artifact_bytes,
        "max_file_count": config.max_file_count,
        "max_depth": config.max_depth,
        "symlink_policy": config.symlink_policy,
        "hidden_files": config.hidden_files,
        "retention_policy": config.retention_policy,
        "requires_manual_review": config.requires_manual_review,
    }


__all__ = [
    "ARCHIVE_EXCLUDED_DIR_NAMES",
    "JAVASCRIPT_ARCHIVE_EXTENSIONS",
    "ArchiveImportSummary",
    "ArchiveIncludedFile",
    "ArchiveManifest",
    "ArchiveSkippedFile",
    "ArchiveSourceConfig",
    "Clock",
    "NonPublicationResult",
    "SourcePolicyError",
    "_annotate_archive_observations",
    "_archive_extractor_route",
    "_archive_included_file",
    "_archive_media_type",
    "_archive_observation_metadata",
    "_archive_policy_snapshot",
    "_is_hidden_relative_path",
    "_observations_for_archive_file",
    "_resolve_archive_artifact_path",
    "_scan_archive_directory",
    "_scan_archive_file",
    "archive_observations_from_manifest",
    "build_archive_manifest",
    "import_archive_source",
    "load_archive_source_config",
]
