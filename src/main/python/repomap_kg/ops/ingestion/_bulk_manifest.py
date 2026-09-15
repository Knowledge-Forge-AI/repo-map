"""Manifest generation and directory traversal for bulk ingestion."""

from __future__ import annotations

import os
import stat
from collections import Counter
from dataclasses import replace
from pathlib import Path

from repomap_kg.ops.ingestion._bulk_helpers import (
    DEFAULT_EXCLUDED_DIRECTORIES,
    classify_bulk_route,
    depth,
    deterministic_run_id,
    ensure_contained,
    is_contained,
    is_excluded_path,
    manifest_digest,
    relative_to_root,
    root_path_summary,
    route_included,
    safe_size,
    sha256_file,
    sha256_text,
)
from repomap_kg.ops.ingestion.bulk_records import (
    BulkIncludedFile,
    BulkManifest,
    BulkSkippedFile,
    BulkSourceConfig,
)


def build_bulk_manifest(
    config: BulkSourceConfig,
    *,
    repository_root: Path | str | None = None,
) -> BulkManifest:
    source_root = config.resolved_root
    repo_root = Path(repository_root).resolve() if repository_root else source_root
    ensure_contained(source_root, repo_root, "root_path")
    included: list[BulkIncludedFile] = []
    skipped: list[BulkSkippedFile] = []
    total_seen: int = 0
    total_included: int = 0
    limit_reasons: list[str] = []
    excluded_directories = DEFAULT_EXCLUDED_DIRECTORIES | frozenset(
        config.excluded_directories
    )

    def add_skipped(
        path: Path,
        reason: str,
        *,
        byte_count: int | None = None,
        route: str | None = None,
    ) -> None:
        relative = relative_to_root(source_root, path)
        skipped.append(
            BulkSkippedFile(
                relative_path=relative,
                reason=reason,
                byte_count=byte_count,
                route=route,
            )
        )
        if reason.startswith("max_") and reason not in limit_reasons:
            limit_reasons.append(reason)

    def add_skipped_tree(path: Path, reason: str) -> None:
        nonlocal total_seen
        if path.is_file() or path.is_symlink():
            add_skipped(path, reason, byte_count=safe_size(path))
            total_seen += safe_size(path) or 0
            return
        for directory, dirnames, filenames in os.walk(path, followlinks=False):
            dirnames[:] = sorted(dirnames)
            for filename in sorted(filenames):
                file_path = Path(directory) / filename
                byte_count = safe_size(file_path)
                total_seen += byte_count or 0
                add_skipped(file_path, reason, byte_count=byte_count)

    def walk(directory: Path) -> None:
        nonlocal total_seen
        for entry in sorted(directory.iterdir(), key=lambda item: relative_to_root(source_root, item)):
            relative = relative_to_root(source_root, entry)
            if is_excluded_path(relative, config.excluded_paths):
                add_skipped_tree(entry, "excluded_path")
                continue
            if entry.name.startswith(".") and not config.include_hidden:
                add_skipped_tree(entry, "hidden_excluded")
                continue
            if entry.is_symlink():
                if not config.follow_symlinks:
                    add_skipped(entry, "symlink_excluded", byte_count=safe_size(entry))
                    continue
                target = entry.resolve()
                if not is_contained(target, source_root):
                    add_skipped(entry, "symlink_escapes_root", byte_count=safe_size(entry))
                    continue
            if entry.is_dir():
                if entry.name in excluded_directories:
                    add_skipped_tree(entry, "excluded_directory")
                    continue
                if depth(relative) > config.max_depth:
                    add_skipped_tree(entry, "max_depth_exceeded")
                    continue
                walk(entry)
                continue
            try:
                mode = entry.stat().st_mode
            except OSError:
                add_skipped(entry, "special_file")
                continue
            if not stat.S_ISREG(mode):
                add_skipped(entry, "special_file")
                continue
            total_seen += entry.stat().st_size
            process_file(entry)

    def process_file(path: Path) -> None:
        nonlocal total_included
        relative = relative_to_root(source_root, path)
        file_depth = depth(relative)
        route = classify_bulk_route(path)
        byte_count = path.stat().st_size
        if file_depth > config.max_depth:
            add_skipped(path, "max_depth_exceeded", byte_count=byte_count, route=route)
            return
        if route is None or not route_included(config, path, route):
            add_skipped(path, "unsupported_extension", byte_count=byte_count, route=route)
            return
        if route == "archive":
            add_skipped(path, "archive_deferred", byte_count=byte_count, route=route)
            return
        if route == "warc":
            add_skipped(path, "warc_deferred", byte_count=byte_count, route=route)
            return
        if byte_count > config.max_file_bytes:
            add_skipped(path, "max_file_bytes_exceeded", byte_count=byte_count, route=route)
            return
        if total_included + byte_count > config.max_total_bytes:
            add_skipped(path, "max_total_bytes_exceeded", byte_count=byte_count, route=route)
            return
        if len(included) >= config.max_files:
            add_skipped(path, "max_files_exceeded", byte_count=byte_count, route=route)
            return
        repository_path = path.resolve().relative_to(repo_root).as_posix()
        digest = sha256_file(path)
        included.append(
            BulkIncludedFile(
                relative_path=relative,
                repository_path=repository_path,
                route=route,
                byte_count=byte_count,
                sha256=digest,
            )
        )
        total_included += byte_count

    walk(source_root)
    included.sort(key=lambda item: item.relative_path)
    skipped.sort(key=lambda item: item.relative_path)
    extractor_counts = Counter(item.route for item in included)
    diagnostic_counts = Counter(item.reason for item in skipped)
    run_id = deterministic_run_id(config, included)
    manifest_id = sha256_text(f"{config.source_id}:{run_id}")[:24]
    manifest = BulkManifest(
        source_id=config.source_id,
        source_type=config.source_type,
        corpus_kind=config.corpus_kind,
        policy_status=config.policy_status,
        root_path_summary=root_path_summary(config),
        bulk_run_id=run_id,
        bulk_manifest_id=manifest_id,
        included_files=tuple(included),
        skipped_files=tuple(skipped),
        total_bytes_seen=total_seen,
        total_bytes_included=total_included,
        limit_hit=bool(limit_reasons),
        limit_reason=",".join(limit_reasons) or None,
        extractor_counts=dict(extractor_counts),
        diagnostic_counts=dict(diagnostic_counts),
    )
    digest = manifest_digest(manifest)
    return replace(manifest, manifest_sha256=digest)
