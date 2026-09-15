"""File-reading adapters for repository discovery extractors."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from repomap_kg import __version__
from repomap_kg.extractors.config.generic import extract_config_file_observations
from repomap_kg.extractors.config.nix import extract_nix_file_observations
from repomap_kg.extractors.documents.css import extract_css_file_observations
from repomap_kg.extractors.documents.email import (
    extract_eml_file_observations,
    extract_mbox_file_observations,
)
from repomap_kg.extractors.documents.feed import extract_feed_file_observations
from repomap_kg.extractors.documents.html import extract_html_file_observations
from repomap_kg.extractors.documents.markdown import (
    extract_markdown_file_observations,
    markdown_anchors_for_content,
)
from repomap_kg.extractors.documents.office import (
    extract_document_file_observations,
    extract_odf_file_observations,
)
from repomap_kg.extractors.languages.go_metadata import (
    extract_go_metadata_observations,
)
from repomap_kg.extractors.languages.javascript import (
    extract_javascript_file_observations,
)
from repomap_kg.extractors.languages.python import (
    PythonModuleIndex,
    extract_python_file_observations,
)
from repomap_kg.extractors.languages.ruby import extract_ruby_file_observations
from repomap_kg.extractors.shell.awk import extract_awk_file_observations
from repomap_kg.extractors.shell.base import extract_shell_observations
from repomap_kg.extractors.shell.bash import extract_bash_file_observations
from repomap_kg.extractors.shell.bats import extract_bats_file_observations
from repomap_kg.extractors.shell.powershell import (
    extract_powershell_file_observations,
)
from repomap_kg.extractors.shell.zsh import extract_zsh_file_observations
from repomap_kg.extractors.shell.zunit import extract_zunit_file_observations
from repomap_kg.graph.discovery_records import FileInfo
from repomap_kg.observations.raw import RawObservation


def _read_utf8(repository_root: Path, relative_path: str) -> str | None:
    try:
        return (repository_root / relative_path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def extract_shell_file_observations(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_shell_observations(relative_path, content)


def extract_bash_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_bash_file_observations(relative_path, content)


def extract_bats_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_bats_file_observations(relative_path, content)


def extract_awk_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_awk_file_observations(relative_path, content)


def extract_zsh_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_zsh_file_observations(relative_path, content)


def extract_zunit_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_zunit_file_observations(relative_path, content)


def extract_python_file_observations_from_file(
    repository_root: Path,
    relative_path: str,
    *,
    module_index: PythonModuleIndex,
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_python_file_observations(
        relative_path,
        content,
        module_index=module_index,
        repository_root=repository_root,
    )


def extract_nix_file_observations_from_file(
    repository_root: Path,
    relative_path: str,
    *,
    flake_ref: str | None = None,
    include_input_references: bool = False,
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_nix_file_observations(
        relative_path,
        content,
        flake_ref=flake_ref or repository_root.name,
        include_input_references=include_input_references,
    )


def extract_powershell_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_powershell_file_observations(relative_path, content)


def extract_ruby_file_observations_from_file(
    repository_root: Path,
    relative_path: str,
    *,
    repository_paths: frozenset[str] | None = None,
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_ruby_file_observations(
        relative_path,
        content,
        repository_paths=repository_paths,
    )


def extract_javascript_file_observations_from_file(
    repository_root: Path,
    relative_path: str,
    *,
    repository_paths: frozenset[str] | None = None,
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_javascript_file_observations(
        relative_path,
        content,
        repository_paths=repository_paths,
    )


def extract_eml_file_observations_from_file(
    repository_root: Path,
    relative_path: str,
) -> tuple[RawObservation, ...]:
    try:
        content = (repository_root / relative_path).read_bytes()
    except OSError as error:
        return (
            RawObservation(
                kind="email.parse_error",
                source_id=f"{relative_path}#email-parse-error:read",
                path=relative_path,
                confidence="unknown",
                extractor="repo-email",
                extractor_version=__version__,
                metadata={
                    "format": "eml",
                    "parser": "stdlib-email",
                    "error_kind": "read-error",
                    "message_summary": str(error)[:120],
                    "recovered": False,
                },
            ),
        )
    return extract_eml_file_observations(relative_path, content)


def extract_mbox_file_observations_from_file(
    repository_root: Path,
    relative_path: str,
) -> tuple[RawObservation, ...]:
    try:
        content = (repository_root / relative_path).read_bytes()
    except OSError as error:
        return (
            RawObservation(
                kind="email.parse_error",
                source_id=f"{relative_path}#email-parse-error:read",
                path=relative_path,
                confidence="unknown",
                extractor="repo-email",
                extractor_version=__version__,
                metadata={
                    "format": "mbox",
                    "parser": "stdlib-email",
                    "error_kind": "read-error",
                    "message_summary": str(error)[:120],
                    "recovered": False,
                },
            ),
        )
    return extract_mbox_file_observations(relative_path, content)


def extract_config_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_config_file_observations(relative_path, content)


def extract_go_metadata_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_go_metadata_observations(relative_path, content)


def extract_feed_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_feed_file_observations(relative_path, content)


def extract_html_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_html_file_observations(relative_path, content)


def extract_css_file_observations_from_file(
    repository_root: Path, relative_path: str
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return ()
    return extract_css_file_observations(relative_path, content)


def extract_document_file_observations_from_file(
    repository_root: Path,
    relative_path: str,
    *,
    repository_paths: frozenset[str] | None = None,
) -> tuple[RawObservation, ...]:
    suffix = Path(relative_path).suffix.lower()
    if suffix in (".odt", ".ods", ".ott", ".ots"):
        try:
            odf_bytes = (repository_root / relative_path).read_bytes()
        except OSError as error:
            return (
                RawObservation(
                    kind="document.parse_error",
                    source_id=f"{relative_path}#document-parse-error:read",
                    path=relative_path,
                    confidence="unknown",
                    extractor="repo-documents",
                    extractor_version=__version__,
                    metadata={
                        "format": suffix.lstrip(".") or "unknown",
                        "parser": "stdlib-document-conservative",
                        "error_kind": "read-error",
                        "message_summary": str(error)[:120],
                        "recovered": False,
                    },
                ),
            )
        return extract_odf_file_observations(
            relative_path,
            odf_bytes,
            repository_paths=repository_paths,
        )
    content = _read_utf8(repository_root, relative_path)
    if content is None:
        return (
            RawObservation(
                kind="document.parse_error",
                source_id=f"{relative_path}#document-parse-error:decode",
                path=relative_path,
                confidence="unknown",
                extractor="repo-documents",
                extractor_version=__version__,
                metadata={
                    "format": Path(relative_path).suffix.lower().lstrip(".")
                    or "unknown",
                    "parser": "stdlib-document-conservative",
                    "error_kind": "decode-error",
                    "message_summary": "file is not valid UTF-8",
                    "recovered": False,
                },
            ),
        )
    return extract_document_file_observations(
        relative_path,
        content,
        repository_paths=repository_paths,
    )


def extract_markdown_file_observations_from_file(
    repository_root: Path,
    file_info: FileInfo,
    *,
    repository_paths: frozenset[str],
    markdown_anchors: dict[str, set[str] | frozenset[str]],
) -> tuple[RawObservation, ...]:
    content = _read_utf8(repository_root, file_info.path)
    if content is None:
        return ()
    return extract_markdown_file_observations(
        file_info.path,
        content,
        repository_paths=repository_paths,
        markdown_anchors=markdown_anchors,
        content_hash=file_info.content_hash,
        generated=file_info.generated,
    )


def markdown_anchor_index(
    repository_root: Path,
    file_infos: Sequence[FileInfo],
) -> dict[str, set[str] | frozenset[str]]:
    anchors: dict[str, set[str] | frozenset[str]] = {}
    for file_info in file_infos:
        if file_info.language != "markdown":
            continue
        content = _read_utf8(repository_root, file_info.path)
        if content is None:
            continue
        anchors[file_info.path] = frozenset(markdown_anchors_for_content(content))
    return anchors
