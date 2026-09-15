"""Directory and file scanning helpers for archive sources."""

from __future__ import annotations

import hashlib
from pathlib import Path

from repomap_kg.ops.ingestion._source_archive_records import (
    ARCHIVE_EXCLUDED_DIR_NAMES,
    JAVASCRIPT_ARCHIVE_EXTENSIONS,
    ArchiveIncludedFile,
    ArchiveSkippedFile,
    ArchiveSourceConfig,
)
from repomap_kg.ops.ingestion.source_common import SourcePolicyError


def _scan_archive_directory(
    config: ArchiveSourceConfig,
    root: Path,
    artifact_root: Path,
) -> tuple[tuple[ArchiveIncludedFile, ...], tuple[ArchiveSkippedFile, ...]]:
    included: list[ArchiveIncludedFile] = []
    skipped: list[ArchiveSkippedFile] = []
    total_bytes = 0

    def scan(directory: Path) -> None:
        nonlocal total_bytes
        for child in sorted(directory.iterdir(), key=lambda path: path.name):
            relative_path = child.relative_to(artifact_root).as_posix()
            if child.name in ARCHIVE_EXCLUDED_DIR_NAMES and child.is_dir():
                skipped.append(ArchiveSkippedFile(relative_path, "excluded-directory"))
                continue
            if _is_hidden_relative_path(relative_path) and not config.hidden_files:
                skipped.append(ArchiveSkippedFile(relative_path, "hidden"))
                continue
            if child.is_symlink():
                skipped.append(ArchiveSkippedFile(relative_path, "symlink"))
                continue
            if len(Path(relative_path).parts) > config.max_depth:
                skipped.append(ArchiveSkippedFile(relative_path, "max_depth"))
                continue
            if child.is_dir():
                scan(child)
                continue
            if not child.is_file():
                skipped.append(ArchiveSkippedFile(relative_path, "special-file"))
                continue
            if len(included) >= config.max_file_count:
                skipped.append(ArchiveSkippedFile(relative_path, "max_file_count"))
                continue
            byte_length = child.stat().st_size
            if total_bytes + byte_length > config.max_artifact_bytes:
                skipped.append(ArchiveSkippedFile(relative_path, "max_artifact_bytes"))
                continue
            included.append(_archive_included_file(root, artifact_root, child, byte_length))
            total_bytes += byte_length

    scan(artifact_root)
    return tuple(included), tuple(skipped)


def _scan_archive_file(
    config: ArchiveSourceConfig,
    root: Path,
    artifact_path: Path,
) -> tuple[tuple[ArchiveIncludedFile, ...], tuple[ArchiveSkippedFile, ...]]:
    if artifact_path.stat().st_size > config.max_artifact_bytes:
        return (), (ArchiveSkippedFile(artifact_path.name, "max_artifact_bytes"),)
    return (
        (
            _archive_included_file(
                root,
                artifact_path.parent,
                artifact_path,
                artifact_path.stat().st_size,
            ),
        ),
        (),
    )


def _archive_included_file(
    root: Path,
    artifact_root: Path,
    file_path: Path,
    byte_length: int,
) -> ArchiveIncludedFile:
    return ArchiveIncludedFile(
        relative_path=file_path.relative_to(artifact_root).as_posix(),
        repository_path=file_path.relative_to(root).as_posix(),
        byte_length=byte_length,
        sha256=hashlib.sha256(file_path.read_bytes()).hexdigest(),
        extractor_route=_archive_extractor_route(file_path),
        media_type=_archive_media_type(file_path),
    )


def _archive_extractor_route(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".css":
        return "css"
    if suffix in {".json", ".jsonc", ".jsonl", ".toml", ".plist", ".xml"}:
        return "config-or-feed"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix == ".bash":
        return "bash"
    if suffix == ".bats":
        return "bats"
    if suffix == ".awk":
        return "awk"
    if suffix == ".zsh":
        return "zsh"
    if suffix == ".zunit":
        return "zunit"
    if suffix == ".sh":
        return "shell"
    if suffix == ".py":
        return "python"
    if suffix == ".nix":
        return "nix"
    if suffix in {".ps1", ".psm1", ".psd1"}:
        return "powershell"
    if suffix in JAVASCRIPT_ARCHIVE_EXTENSIONS:
        return "javascript"
    return "file"


def _archive_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return "text/html"
    if suffix == ".css":
        return "text/css"
    if suffix == ".json":
        return "application/json"
    if suffix == ".jsonc":
        return "application/jsonc"
    if suffix == ".jsonl":
        return "application/jsonl"
    if suffix == ".toml":
        return "application/toml"
    if suffix in {".xml", ".plist"}:
        return "application/xml"
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    if suffix in {".js", ".mjs", ".cjs", ".jsx"}:
        return "text/javascript"
    if suffix in {".ts", ".mts", ".cts", ".tsx"}:
        return "text/typescript"
    if suffix in {".ps1", ".psm1", ".psd1"}:
        return "text/x-powershell"
    return "application/octet-stream"


def _resolve_archive_artifact_path(root: Path, artifact_path: str) -> Path:
    candidate = root / artifact_path
    if _archive_path_contains_symlink(root, candidate):
        raise SourcePolicyError("artifact.path must not be a symlink")
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise SourcePolicyError("artifact.path must normalize inside root_path") from error
    return candidate


def _archive_path_contains_symlink(root: Path, candidate: Path) -> bool:
    """Check lexical path components without resolving any symlink targets."""

    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _is_hidden_relative_path(relative_path: str) -> bool:
    return any(part.startswith(".") for part in Path(relative_path).parts)
