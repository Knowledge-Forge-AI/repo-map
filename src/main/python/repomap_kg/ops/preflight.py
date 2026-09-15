"""Ops refresh preflight root scanning helpers."""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from repomap_kg.graph.discovery import (
    DEFAULT_DISCOVERY_EXCLUDE_PATHS,
    LANGUAGE_BY_EXTENSION,
    RUBY_FILENAMES,
    _is_excluded_relative_path,
    detect_role,
    is_generated,
    is_python_requirements_file_name,
    normalize_discovery_exclude_paths,
)

def _scan_preflight_root(
    root: Path,
    exclude_paths: Sequence[str],
) -> dict[str, Any]:
    configured_excludes = normalize_discovery_exclude_paths(exclude_paths)
    default_excludes = DEFAULT_DISCOVERY_EXCLUDE_PATHS
    configured_hits = Counter({path: 0 for path in configured_excludes})
    default_hits = Counter({path: 0 for path in default_excludes})
    language_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    extractor_categories: Counter[str] = Counter()
    top_level_directories: set[str] = set()
    top_level_files: set[str] = set()
    files_considered = 0
    files_included = 0
    files_skipped = 0
    directories_skipped = 0
    symlink_count = 0
    symlinks_skipped_outside_root = 0
    symlinks_skipped_nix_store = 0
    generated_output_skips = 0
    secret_like_path_count = 0

    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        kept_dirnames: list[str] = []
        for dirname in sorted(dirnames):
            dir_path = directory_path / dirname
            relative_dir = _relative_posix_path(root, dir_path)
            if _is_secret_like_path(relative_dir):
                secret_like_path_count += 1
            default_match = _first_matching_exclude(relative_dir, default_excludes)
            configured_match = _first_matching_exclude(
                relative_dir,
                configured_excludes,
            )
            if dir_path.is_symlink():
                symlink_count += 1
                if not _resolved_path_stays_under(root, dir_path):
                    symlinks_skipped_outside_root += 1
                    if _resolves_to_nix_store(dir_path):
                        symlinks_skipped_nix_store += 1
                    directories_skipped += 1
                    if default_match:
                        default_hits[default_match] += 1
                    if configured_match:
                        configured_hits[configured_match] += 1
                    if _is_generated_output_skip(relative_dir, default_match, configured_match):
                        generated_output_skips += 1
                    continue
            if default_match or configured_match:
                directories_skipped += 1
                if default_match:
                    default_hits[default_match] += 1
                if configured_match:
                    configured_hits[configured_match] += 1
                if _is_generated_output_skip(relative_dir, default_match, configured_match):
                    generated_output_skips += 1
                continue
            kept_dirnames.append(dirname)
        dirnames[:] = kept_dirnames

        for filename in sorted(filenames):
            file_path = directory_path / filename
            relative_file = _relative_posix_path(root, file_path)
            files_considered += 1
            if _is_secret_like_path(relative_file):
                secret_like_path_count += 1
            default_match = _first_matching_exclude(relative_file, default_excludes)
            configured_match = _first_matching_exclude(
                relative_file,
                configured_excludes,
            )
            if file_path.is_symlink():
                symlink_count += 1
                if not _resolved_path_stays_under(root, file_path):
                    symlinks_skipped_outside_root += 1
                    if _resolves_to_nix_store(file_path):
                        symlinks_skipped_nix_store += 1
                    files_skipped += 1
                    if default_match:
                        default_hits[default_match] += 1
                    if configured_match:
                        configured_hits[configured_match] += 1
                    if _is_generated_output_skip(relative_file, default_match, configured_match):
                        generated_output_skips += 1
                    continue
            if default_match or configured_match:
                files_skipped += 1
                if default_match:
                    default_hits[default_match] += 1
                if configured_match:
                    configured_hits[configured_match] += 1
                if _is_generated_output_skip(relative_file, default_match, configured_match):
                    generated_output_skips += 1
                continue

            files_included += 1
            top_part = relative_file.split("/", 1)[0]
            if "/" in relative_file:
                top_level_directories.add(top_part)
            else:
                top_level_files.add(top_part)
            language = _path_only_language(relative_file)
            executable = os.access(file_path, os.X_OK)
            generated = is_generated(relative_file)
            role = detect_role(
                relative_file,
                executable=executable,
                generated=generated,
            )
            language_counts[language] += 1
            role_counts[role] += 1
            for category in _extractor_categories_for_language(language):
                extractor_categories[category] += 1

    return {
        "configured_exclude_hit_counts": dict(configured_hits),
        "default_exclude_hit_counts": dict(default_hits),
        "files_considered": files_considered,
        "files_included": files_included,
        "files_skipped": files_skipped,
        "directories_skipped": directories_skipped,
        "symlink_count": symlink_count,
        "symlinks_skipped_outside_root": symlinks_skipped_outside_root,
        "symlinks_skipped_nix_store": symlinks_skipped_nix_store,
        "generated_output_skips": generated_output_skips,
        "secret_like_path_count": secret_like_path_count,
        "path_examples_included": False,
        "top_level_directory_count": len(top_level_directories),
        "top_level_file_count": len(top_level_files),
        "language_counts": dict(sorted(language_counts.items())),
        "role_counts": dict(sorted(role_counts.items())),
        "extractor_categories": dict(sorted(extractor_categories.items())),
    }

def _relative_posix_path(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()

def _resolved_path_stays_under(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True

def _resolves_to_nix_store(path: Path) -> bool:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        return False
    return resolved.as_posix().startswith("/nix/store/")

def _is_generated_output_skip(
    relative_path: str,
    default_match: str | None,
    configured_match: str | None,
) -> bool:
    matches = tuple(match for match in (default_match, configured_match) if match)
    if any(match in {"build", "dist", "htmlcov", "result"} for match in matches):
        return True
    if any(match.startswith("result") and "*" in match for match in matches):
        return True
    return is_generated(relative_path)

_SECRET_LIKE_PATH_RE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|private[_-]?key|"
    r"access[_-]?key|client[_-]?secret|credential|auth|bearer|session|"
    r"cookie|database[_-]?url)"
)

def _is_secret_like_path(relative_path: str) -> bool:
    return bool(_SECRET_LIKE_PATH_RE.search(relative_path))

def _first_matching_exclude(
    relative_path: str,
    exclude_paths: Sequence[str],
) -> str | None:
    for exclude_path in exclude_paths:
        if _is_excluded_relative_path(relative_path, (exclude_path,)):
            return exclude_path
    return None

def _path_only_language(relative_path: str) -> str:
    name = Path(relative_path).name
    suffix = Path(relative_path).suffix
    if is_python_requirements_file_name(name):
        return "python"
    if name in RUBY_FILENAMES:
        return "ruby"
    return LANGUAGE_BY_EXTENSION.get(suffix, "unknown")

def _extractor_categories_for_language(language: str) -> tuple[str, ...]:
    categories = ["file"]
    if language in {"markdown", "shell", "python", "css", "html", "javascript", "ruby", "nix"}:
        categories.append(language)
    elif language in {
        "json",
        "jsonc",
        "jsonl",
        "plist",
        "terraform",
        "toml",
        "xml",
        "yaml",
    }:
        categories.append("config")
    elif language in {"eml", "mbox"}:
        categories.append("email")
    elif language in {"csv", "latex", "odf", "text", "tsv"}:
        categories.append("document")
    return tuple(categories)
