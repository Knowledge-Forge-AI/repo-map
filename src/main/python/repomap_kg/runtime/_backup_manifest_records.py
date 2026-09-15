"""Backup manifest records, validation, and inspection helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.backup_streaming import describe_dump_file
from repomap_kg.runtime.local import LocalRuntimeDiagnostic

BACKUP_FORMAT_VERSION = 1
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def list_manifest_paths(backups_root: Path) -> tuple[Path, ...]:
    if not backups_root.exists():
        return ()
    return tuple(
        sorted(
            path
            for path in backups_root.rglob("manifest.json")
            if not is_incomplete_backup_path(backups_root, path)
        )
    )


def is_incomplete_backup_path(backups_root: Path, path: Path) -> bool:
    try:
        relative_path = path.resolve().relative_to(backups_root.resolve())
    except ValueError:
        return False
    return any(
        part.startswith(".") and part.endswith(".incomplete")
        for part in relative_path.parts
    )


def read_manifest_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "warning",
                    "backup-manifest-unreadable",
                    str(path),
                    "backup manifest could not be read",
                ),
            )
        ) from error
    if not isinstance(payload, dict):
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "warning",
                    "backup-manifest-invalid",
                    str(path),
                    "backup manifest must be a JSON object",
                ),
            )
        )
    return payload


def sanitize_toc_identifier(value: str) -> str | None:
    return value if SAFE_IDENTIFIER_RE.match(value) else None


def select_dump_file_for_database(
    manifest: Mapping[str, Any],
    database: str,
) -> dict[str, Any]:
    if manifest.get("backup_format_version") != BACKUP_FORMAT_VERSION:
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "backup-format-unsupported",
                    "manifest.json",
                    "backup manifest format is unsupported",
                ),
            )
        )
    if manifest.get("dump_format") not in (None, "pgcustom"):
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "backup-dump-format-unsupported",
                    "manifest.json",
                    "backup dump format is unsupported",
                ),
            )
        )
    dump_files = manifest.get("dump_files", [])
    if not isinstance(dump_files, list):
        raise malformed_backup_manifest("dump_files")
    expected_database = manifest.get("database")
    expected_databases = manifest.get("databases", [])
    if expected_database and expected_database != database:
        raise backup_dump_not_found(database)
    if expected_database:
        expected_name = "dump.pgcustom"
    else:
        if database not in expected_databases:
            raise backup_dump_not_found(database)
        expected_name = f"{database}.pgcustom"
    for item in dump_files:
        if isinstance(item, Mapping) and item.get("name") == expected_name:
            sha256 = item.get("sha256")
            size_bytes = item.get("size_bytes")
            if not isinstance(sha256, str) or not isinstance(size_bytes, int):
                raise malformed_backup_manifest("dump_files")
            return {
                "name": expected_name,
                "sha256": sha256,
                "size_bytes": size_bytes,
            }
    raise backup_dump_not_found(database)


def verify_dump_file_checksum(path: Path, dump_file: Mapping[str, Any]) -> None:
    if not path.is_file():
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "backup-dump-missing",
                    str(path),
                    "backup dump file is missing",
                ),
            )
        )
    expected_size = dump_file.get("size_bytes")
    expected_sha = dump_file.get("sha256")
    actual = describe_dump_file(path)
    if actual.size_bytes != expected_size or actual.sha256 != expected_sha:
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "backup-checksum-mismatch",
                    path.name,
                    "backup dump checksum does not match manifest",
                ),
            )
        )


def verify_dump_file_checksum_for_inspection(
    path: Path,
    dump_file: Mapping[str, Any],
    dump_name: str,
) -> tuple[bool, tuple[LocalRuntimeDiagnostic, ...]]:
    if not path.is_file():
        return (
            False,
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "backup-dump-missing",
                    dump_name,
                    "backup dump file is missing",
                ),
            ),
        )
    expected_size = dump_file.get("size_bytes")
    expected_sha = dump_file.get("sha256")
    actual = describe_dump_file(path)
    if actual.size_bytes != expected_size or actual.sha256 != expected_sha:
        return (
            False,
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "backup-checksum-mismatch",
                    dump_name,
                    "backup dump checksum does not match manifest",
                ),
            ),
        )
    return True, ()


def safe_dump_file_name(value: Any) -> str:
    name = Path(str(value or "dump")).name
    if not name or name in {".", ".."}:
        return "dump"
    return bounded_text(name, 120)


def resolve_dump_file_for_inspection(
    backup_dir: Path,
    dump_file: Mapping[str, Any],
) -> tuple[Path | None, str]:
    raw_name = str(dump_file.get("name") or "")
    safe_name = safe_dump_file_name(raw_name)
    if raw_name != safe_name:
        return None, safe_name
    return backup_dir / safe_name, safe_name


def infer_dump_format(dump_name: str) -> str:
    if dump_name.endswith(".pgcustom"):
        return "pgcustom"
    return "unknown"


def malformed_backup_manifest(key: str) -> LocalDbBackupError:
    return LocalDbBackupError(
        (
            LocalRuntimeDiagnostic(
                "error",
                "backup-manifest-invalid",
                key,
                "backup manifest is malformed",
            ),
        )
    )


def backup_dump_not_found(database: str) -> LocalDbBackupError:
    return LocalDbBackupError(
        (
            LocalRuntimeDiagnostic(
                "error",
                "backup-dump-not-found",
                database,
                "backup manifest does not contain a dump for the requested database",
            ),
        )
    )


def optional_manifest_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def resolve_backup_manifest_path(
    backups_root: Path,
    backup_id_or_path: str | Path,
) -> Path:
    candidate_text = str(backup_id_or_path)
    candidate = Path(candidate_text)
    if candidate.is_absolute() or "/" in candidate_text:
        path = candidate
        if path.is_dir():
            path = path / "manifest.json"
        ensure_path_under_backups_root(backups_root, path)
        if is_incomplete_backup_path(backups_root, path) or not path.is_file():
            raise backup_not_found(candidate_text)
        return path
    for manifest_path in list_manifest_paths(backups_root):
        manifest = read_manifest_file(manifest_path)
        if manifest.get("backup_id") == candidate_text:
            return manifest_path
    raise backup_not_found(candidate_text)


def ensure_path_under_backups_root(backups_root: Path, path: Path) -> None:
    root = backups_root.resolve()
    resolved = path.resolve()
    if root != resolved and root not in resolved.parents:
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "backup-path-outside-root",
                    str(path),
                    "backup path must stay under REPOMAP_HOME/backups",
                ),
            )
        )


def backup_not_found(value: str) -> LocalDbBackupError:
    return LocalDbBackupError(
        (
            LocalRuntimeDiagnostic(
                "error",
                "backup-not-found",
                value,
                "backup manifest was not found",
            ),
        )
    )


def bounded_text(value: str, limit: int = 200) -> str:
    return value[:limit]


for _fn in (
    backup_dump_not_found,
    backup_not_found,
    bounded_text,
    ensure_path_under_backups_root,
    infer_dump_format,
    is_incomplete_backup_path,
    list_manifest_paths,
    malformed_backup_manifest,
    optional_manifest_text,
    read_manifest_file,
    resolve_backup_manifest_path,
    resolve_dump_file_for_inspection,
    safe_dump_file_name,
    sanitize_toc_identifier,
    select_dump_file_for_database,
    verify_dump_file_checksum,
    verify_dump_file_checksum_for_inspection,
):
    _fn.__module__ = "repomap_kg.runtime.backup_manifests"


__all__ = [
    "BACKUP_FORMAT_VERSION",
    "SAFE_IDENTIFIER_RE",
    "backup_dump_not_found",
    "backup_not_found",
    "bounded_text",
    "ensure_path_under_backups_root",
    "infer_dump_format",
    "is_incomplete_backup_path",
    "list_manifest_paths",
    "malformed_backup_manifest",
    "optional_manifest_text",
    "read_manifest_file",
    "resolve_backup_manifest_path",
    "resolve_dump_file_for_inspection",
    "safe_dump_file_name",
    "sanitize_toc_identifier",
    "select_dump_file_for_database",
    "verify_dump_file_checksum",
    "verify_dump_file_checksum_for_inspection",
]
