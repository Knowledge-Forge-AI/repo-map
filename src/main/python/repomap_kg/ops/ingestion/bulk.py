"""Explicit-policy-gated local bulk corpus ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from repomap_kg.extractors.documents.css_html_matching import (
    extract_css_selector_match_observations,
)
from repomap_kg.extractors.languages.python import PythonModuleIndex
from repomap_kg.graph.discovery import (
    FileInfo,
    classify_path,
    extract_awk_file_observations_from_file,
    extract_bash_file_observations_from_file,
    extract_bats_file_observations_from_file,
    extract_config_file_observations_from_file,
    extract_css_file_observations_from_file,
    extract_document_file_observations_from_file,
    extract_eml_file_observations_from_file,
    extract_feed_file_observations_from_file,
    extract_html_file_observations_from_file,
    extract_javascript_file_observations_from_file,
    extract_markdown_file_observations_from_file,
    extract_mbox_file_observations_from_file,
    extract_nix_file_observations_from_file,
    extract_powershell_file_observations_from_file,
    extract_python_file_observations_from_file,
    extract_ruby_file_observations_from_file,
    extract_shell_file_observations,
    extract_zsh_file_observations_from_file,
    extract_zunit_file_observations_from_file,
    markdown_anchor_index,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.ingestion._bulk_helpers import (
    ALLOWED_CORPUS_KINDS,
    ALLOWED_POLICY_STATUSES,
    ALLOWED_SOURCE_TYPES,
    ARCHIVE_EXTENSIONS,
    DEFAULT_EXCLUDED_DIRECTORIES,
    EXTENSION_ROUTES,
    SPECIAL_FILENAME_ROUTES,
    WARC_EXTENSIONS,
    classify_bulk_route,
    depth,
    deterministic_run_id,
    ensure_contained,
    is_contained,
    is_excluded_path,
    load_bulk_source_config,
    manifest_digest,
    relative_to_root,
    root_path_summary,
    route_included,
    safe_size,
    sha256_file,
    sha256_json,
    sha256_text,
    write_json,
    write_jsonl,
)
from repomap_kg.ops.ingestion._bulk_manifest import build_bulk_manifest
from repomap_kg.ops.ingestion._bulk_observations import (
    annotate_observation,
    write_bulk_run_files,
)
from repomap_kg.ops.ingestion.acquisition_contracts import non_publication_result
from repomap_kg.ops.ingestion.bulk_config_values import (
    bool_value,
    normalized_path_tuple,
    optional_string,
    required_bool,
    required_positive_int,
    required_string,
    required_table,
    resolve_config_root,
    string_tuple,
    table,
)
from repomap_kg.ops.ingestion.bulk_records import (
    BulkImportSummary,
    BulkIncludedFile,
    BulkManifest,
    BulkPolicyError,
    BulkSkippedFile,
    BulkSourceConfig,
)

EXTRACTOR = "bulk-local-ingestion"
EXTRACTOR_VERSION = "0.1.0"


def observations_for_file_info(
    repo_root: Path,
    file_info: FileInfo,
    *,
    module_index: PythonModuleIndex,
    repository_paths: frozenset[str],
    markdown_anchors: Mapping[str, set[str] | frozenset[str]],
) -> tuple[RawObservation, ...]:
    if file_info.language == "markdown":
        converted_anchors: dict[str, set[str] | frozenset[str]] = {
            key: frozenset(val) for key, val in markdown_anchors.items()
        }
        return extract_markdown_file_observations_from_file(
            repo_root,
            file_info,
            repository_paths=repository_paths,
            markdown_anchors=converted_anchors,
        )
    if file_info.language == "shell":
        return extract_shell_file_observations(repo_root, file_info.path)
    if file_info.language == "bash":
        return extract_bash_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "bats":
        return extract_bats_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "awk":
        return extract_awk_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "zsh":
        return extract_zsh_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "zunit":
        return extract_zunit_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "python":
        return extract_python_file_observations_from_file(
            repo_root,
            file_info.path,
            module_index=module_index,
        )
    if file_info.language == "ruby":
        return extract_ruby_file_observations_from_file(
            repo_root,
            file_info.path,
            repository_paths=repository_paths,
        )
    if file_info.language == "javascript":
        return extract_javascript_file_observations_from_file(
            repo_root,
            file_info.path,
            repository_paths=repository_paths,
        )
    if file_info.language == "eml":
        return extract_eml_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "mbox":
        return extract_mbox_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "nix":
        return extract_nix_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "powershell":
        return extract_powershell_file_observations_from_file(
            repo_root,
            file_info.path,
        )
    if file_info.language in ("json", "xml"):
        feed_observations = extract_feed_file_observations_from_file(
            repo_root,
            file_info.path,
        )
        if feed_observations:
            return feed_observations
    if file_info.language in (
        "json",
        "jsonc",
        "jsonl",
        "toml",
        "plist",
        "xml",
        "yaml",
    ):
        return extract_config_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "html":
        return extract_html_file_observations_from_file(repo_root, file_info.path)
    if file_info.language == "css":
        return extract_css_file_observations_from_file(repo_root, file_info.path)
    if file_info.language in ("text", "csv", "tsv", "latex", "odf"):
        return extract_document_file_observations_from_file(
            repo_root,
            file_info.path,
            repository_paths=repository_paths,
        )
    return ()



def build_bulk_plan_from_config(config_path: Path | str) -> BulkManifest:
    config = load_bulk_source_config(config_path)
    return build_bulk_plan(config, repository_root=config.resolved_root)


def build_bulk_plan(
    config: BulkSourceConfig,
    *,
    repository_root: Path | str | None = None,
) -> BulkManifest:
    return build_bulk_manifest(config, repository_root=repository_root)


def bulk_observations_from_plan(
    config: BulkSourceConfig,
    manifest: BulkManifest,
    *,
    repository_root: Path | str,
) -> tuple[RawObservation, ...]:
    repo_root = Path(repository_root).resolve()
    file_infos = [
        classify_path(repo_root, repo_root / item.repository_path)
        for item in manifest.included_files
    ]
    module_index = PythonModuleIndex.from_python_paths(
        (info.path for info in file_infos if info.language == "python"),
        repository_root=repo_root,
    )
    repository_paths = frozenset(info.path for info in file_infos)
    markdown_anchors = markdown_anchor_index(repo_root, file_infos)
    included_by_repository_path = {item.repository_path: item for item in manifest.included_files}
    observations: list[RawObservation] = []
    for file_info in file_infos:
        included = included_by_repository_path[file_info.path]
        routed = [file_info.to_observation()]
        routed.extend(
            observations_for_file_info(
                repo_root,
                file_info,
                module_index=module_index,
                repository_paths=repository_paths,
                markdown_anchors=markdown_anchors,
            )
        )
        observations.extend(
            annotate_observation(
                observation,
                config=config,
                manifest=manifest,
                included=included,
            )
            for observation in routed
        )
    observations.extend(extract_css_selector_match_observations(observations))
    return tuple(observations)


def import_bulk_source(
    config_path: Path | str,
    *,
    root_path: Path | str,
) -> BulkImportSummary:
    config = load_bulk_source_config(config_path)
    repo_root = Path(root_path).resolve()
    manifest = build_bulk_plan(config, repository_root=repo_root)
    observations = bulk_observations_from_plan(
        config,
        manifest,
        repository_root=repo_root,
    )
    output_path = write_bulk_run_files(
        manifest,
        observations=observations,
        repository_root=repo_root,
    )
    return BulkImportSummary(
        source_id=config.source_id,
        source_type=config.source_type,
        corpus_kind=config.corpus_kind,
        policy_status=config.policy_status,
        bulk_run_id=manifest.bulk_run_id,
        bulk_manifest_id=manifest.bulk_manifest_id,
        observations=len(observations),
        raw_observations=tuple(observations),
        included_files=manifest.file_count_included,
        skipped_files=manifest.file_count_skipped,
        output_path=output_path,
        output_path_summary=output_path.relative_to(repo_root).as_posix(),
        manifest=manifest,
        publication=non_publication_result(),
    )


__all__ = [
    "ALLOWED_CORPUS_KINDS",
    "ALLOWED_POLICY_STATUSES",
    "ALLOWED_SOURCE_TYPES",
    "ARCHIVE_EXTENSIONS",
    "BulkImportSummary",
    "BulkIncludedFile",
    "BulkManifest",
    "BulkPolicyError",
    "BulkSkippedFile",
    "BulkSourceConfig",
    "DEFAULT_EXCLUDED_DIRECTORIES",
    "EXTENSION_ROUTES",
    "EXTRACTOR",
    "EXTRACTOR_VERSION",
    "FileInfo",
    "PythonModuleIndex",
    "SPECIAL_FILENAME_ROUTES",
    "WARC_EXTENSIONS",
    "annotate_observation",
    "bool_value",
    "build_bulk_manifest",
    "build_bulk_plan",
    "build_bulk_plan_from_config",
    "bulk_observations_from_plan",
    "classify_bulk_route",
    "classify_path",
    "depth",
    "deterministic_run_id",
    "ensure_contained",
    "extract_awk_file_observations_from_file",
    "extract_bash_file_observations_from_file",
    "extract_bats_file_observations_from_file",
    "extract_config_file_observations_from_file",
    "extract_css_file_observations_from_file",
    "extract_document_file_observations_from_file",
    "extract_eml_file_observations_from_file",
    "extract_feed_file_observations_from_file",
    "extract_html_file_observations_from_file",
    "extract_javascript_file_observations_from_file",
    "extract_markdown_file_observations_from_file",
    "extract_mbox_file_observations_from_file",
    "extract_nix_file_observations_from_file",
    "extract_powershell_file_observations_from_file",
    "extract_python_file_observations_from_file",
    "extract_ruby_file_observations_from_file",
    "extract_shell_file_observations",
    "extract_zsh_file_observations_from_file",
    "extract_zunit_file_observations_from_file",
    "import_bulk_source",
    "is_contained",
    "is_excluded_path",
    "load_bulk_source_config",
    "manifest_digest",
    "markdown_anchor_index",
    "normalized_path_tuple",
    "observations_for_file_info",
    "optional_string",
    "relative_to_root",
    "required_bool",
    "required_positive_int",
    "required_string",
    "required_table",
    "resolve_config_root",
    "root_path_summary",
    "route_included",
    "safe_size",
    "sha256_file",
    "sha256_json",
    "sha256_text",
    "string_tuple",
    "table",
    "write_bulk_run_files",
    "write_json",
    "write_jsonl",
]
