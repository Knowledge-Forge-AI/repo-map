"""Repository file discovery and classification."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

from common_lore_index.extractors.documents.css_html_matching import (
    extract_css_selector_match_observations,
)
from common_lore_index.extractors.languages.golang import (
    extract_go_repository_observations,
)
from common_lore_index.extractors.languages.python import PythonModuleIndex

# Same-name aliases are facade compatibility re-exports pinned by the PKG5 tests.
from common_lore_index.graph.discovery_extractors import (
    extract_awk_file_observations as extract_awk_file_observations,
    extract_awk_file_observations_from_file,
    extract_bash_file_observations as extract_bash_file_observations,
    extract_bash_file_observations_from_file,
    extract_bats_file_observations as extract_bats_file_observations,
    extract_bats_file_observations_from_file,
    extract_config_file_observations as extract_config_file_observations,
    extract_config_file_observations_from_file,
    extract_css_file_observations as extract_css_file_observations,
    extract_css_file_observations_from_file,
    extract_document_file_observations as extract_document_file_observations,
    extract_document_file_observations_from_file,
    extract_eml_file_observations as extract_eml_file_observations,
    extract_eml_file_observations_from_file,
    extract_feed_file_observations as extract_feed_file_observations,
    extract_feed_file_observations_from_file,
    extract_html_file_observations as extract_html_file_observations,
    extract_html_file_observations_from_file,
    extract_go_metadata_observations_from_file,
    extract_javascript_file_observations as extract_javascript_file_observations,
    extract_javascript_file_observations_from_file,
    extract_markdown_file_observations as extract_markdown_file_observations,
    extract_markdown_file_observations_from_file,
    extract_mbox_file_observations as extract_mbox_file_observations,
    extract_mbox_file_observations_from_file,
    extract_nix_file_observations as extract_nix_file_observations,
    extract_nix_file_observations_from_file,
    extract_odf_file_observations as extract_odf_file_observations,
    extract_powershell_file_observations as extract_powershell_file_observations,
    extract_powershell_file_observations_from_file,
    extract_python_file_observations as extract_python_file_observations,
    extract_python_file_observations_from_file,
    extract_ruby_file_observations as extract_ruby_file_observations,
    extract_ruby_file_observations_from_file,
    extract_shell_file_observations,
    extract_zsh_file_observations as extract_zsh_file_observations,
    extract_zsh_file_observations_from_file,
    extract_zunit_file_observations as extract_zunit_file_observations,
    extract_zunit_file_observations_from_file,
    markdown_anchor_index,
    markdown_anchors_for_content as markdown_anchors_for_content,
)
from common_lore_index.graph._capture_control import CancelCheck, check_function
from common_lore_index.graph.discovery_records import FileInfo
from common_lore_index.graph.discovery_file_metadata import (
    content_hash as content_hash,
    first_line as first_line,
)
# Classification moved to a sibling (ADR 0173 P6); same-name re-exports keep
# every import and the ``discovery.classify_path`` patch seam unchanged.
from common_lore_index.graph._discovery_classify import (
    ClassificationReaderHooks,
    CONFIG_FILENAMES as CONFIG_FILENAMES,
    GENERATED_DIR_NAMES as GENERATED_DIR_NAMES,
    GO_METADATA_LANGUAGE_BY_NAME as GO_METADATA_LANGUAGE_BY_NAME,
    LANGUAGE_BY_EXTENSION as LANGUAGE_BY_EXTENSION,
    PYTHON_REQUIREMENTS_NAME_PATTERN as PYTHON_REQUIREMENTS_NAME_PATTERN,
    RUBY_FILENAMES as RUBY_FILENAMES,
    classify_path as classify_path,
    detect_language as detect_language,
    detect_role as detect_role,
    is_generated as is_generated,
    is_go_generated_file as is_go_generated_file,
    is_python_requirements_file_name as is_python_requirements_file_name,
)
# Traversal selection lives in a sibling with same-name re-exports.
from common_lore_index.graph._discovery_selection import (
    DEFAULT_DISCOVERY_EXCLUDE_PATHS as DEFAULT_DISCOVERY_EXCLUDE_PATHS,
    IGNORED_DIR_NAMES as IGNORED_DIR_NAMES,
    _is_excluded_relative_path as _is_excluded_relative_path,
    _matches_glob as _matches_glob,
    _relative_posix_path as _relative_posix_path,
    _resolved_path_stays_under as _resolved_path_stays_under,
    normalize_discovery_exclude_paths as normalize_discovery_exclude_paths,
    selected_files,
)
from common_lore_index.graph.profiles import ProjectProfile
from common_lore_index.observations.raw import RawObservation

class DiscoveryIOHooks(Protocol):
    """Caller-chosen traversal and classification readers (ADR 0173).

    The metered implementation is selected by the sealing caller, so this
    module's import graph stays graph-local and never reaches ``artifacts``
    or ``ops`` (the D12 Rust-qualification import closure includes it).
    """

    def walk(self, top: Path) -> Iterable[tuple[str, list[str], list[str]]]: ...

    def readers(self) -> ClassificationReaderHooks: ...


def discover_repository(
    root: Path | str,
    *,
    profile: ProjectProfile | None = None,
    exclude_paths: Sequence[str] = (),
    io_hooks: DiscoveryIOHooks | None = None,
) -> list[FileInfo]:
    repository_root = Path(root).resolve()
    configured_excludes = normalize_discovery_exclude_paths(exclude_paths)
    classify_kwargs: dict[str, Any] = {}
    if io_hooks is None:
        walk: Iterable[tuple[str, list[str], list[str]]] = os.walk(repository_root)
    else:  # explicit caller hooks count (and may govern) every read
        walk = io_hooks.walk(repository_root)
        classify_kwargs["readers"] = io_hooks.readers()
    files = [
        classify_path(repository_root, file_path, profile=profile, **classify_kwargs)
        for file_path in selected_files(repository_root, configured_excludes, walk)
    ]
    files_by_path = {file_info.path: file_info for file_info in files}
    return sorted(files_by_path.values(), key=lambda file_info: file_info.path)


def discover_observations(
    root: Path | str,
    *,
    profile: ProjectProfile | None = None,
    exclude_paths: Sequence[str] = (),
) -> list[RawObservation]:
    repository_root = Path(root).resolve()
    file_infos = discover_repository(
        repository_root,
        profile=profile,
        exclude_paths=exclude_paths,
    )
    return extract_observations_from_repository_files(repository_root, file_infos)


def extract_observations_from_repository_files(
    repository_root: Path,
    file_infos: Sequence[FileInfo],
    *,
    nix_flake_ref: str | None = None,
    include_nix_input_references: bool = False,
    cancel_check: CancelCheck | None = None,
) -> list[RawObservation]:
    """Extract observations from one already discovered static file inventory."""

    check = check_function(cancel_check)
    check()
    module_index = PythonModuleIndex.from_python_paths(
        (file_info.path for file_info in file_infos if file_info.language == "python"),
        repository_root=repository_root,
    )
    repository_paths = frozenset(file_info.path for file_info in file_infos)
    check()
    markdown_anchors = markdown_anchor_index(repository_root, file_infos)
    observations = []
    for file_info in file_infos:
        check()
        observations.append(file_info.to_observation())
        if file_info.language in ("go", "go-module", "go-workspace"):
            observations.extend(
                extract_go_metadata_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "markdown":
            observations.extend(
                extract_markdown_file_observations_from_file(
                    repository_root,
                    file_info,
                    repository_paths=repository_paths,
                    markdown_anchors=markdown_anchors,
                )
            )
        if file_info.language == "shell":
            observations.extend(
                extract_shell_file_observations(repository_root, file_info.path)
            )
        if file_info.language == "bash":
            observations.extend(
                extract_bash_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "bats":
            observations.extend(
                extract_bats_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "awk":
            observations.extend(
                extract_awk_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "zsh":
            observations.extend(
                extract_zsh_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "zunit":
            observations.extend(
                extract_zunit_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if is_python_requirements_file_name(file_info.path):
            observations.extend(
                extract_config_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        elif file_info.language == "python":
            observations.extend(
                extract_python_file_observations_from_file(
                    repository_root,
                    file_info.path,
                    module_index=module_index,
                )
            )
        if file_info.language == "ruby":
            observations.extend(
                extract_ruby_file_observations_from_file(
                    repository_root,
                    file_info.path,
                    repository_paths=repository_paths,
                )
            )
        if file_info.language == "javascript":
            observations.extend(
                extract_javascript_file_observations_from_file(
                    repository_root,
                    file_info.path,
                    repository_paths=repository_paths,
                )
            )
        if file_info.language == "eml":
            observations.extend(
                extract_eml_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "mbox":
            observations.extend(
                extract_mbox_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "nix":
            observations.extend(
                extract_nix_file_observations_from_file(
                    repository_root,
                    file_info.path,
                    flake_ref=nix_flake_ref,
                    include_input_references=include_nix_input_references,
                )
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
                continue
        if file_info.language in (
            "json",
            "jsonc",
            "jsonl",
            "toml",
            "terraform",
            "plist",
            "xml",
            "yaml",
        ):
            observations.extend(
                extract_config_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "html":
            observations.extend(
                extract_html_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language == "css":
            observations.extend(
                extract_css_file_observations_from_file(
                    repository_root,
                    file_info.path,
                )
            )
        if file_info.language in ("text", "csv", "tsv", "latex", "odf"):
            observations.extend(
                extract_document_file_observations_from_file(
                    repository_root,
                    file_info.path,
                    repository_paths=repository_paths,
                )
            )
    check()
    observations.extend(extract_go_repository_observations(repository_root, file_infos))
    check()
    observations.extend(extract_css_selector_match_observations(observations))
    check()
    return observations
