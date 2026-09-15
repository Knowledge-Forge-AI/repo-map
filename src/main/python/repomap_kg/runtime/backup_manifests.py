"""Backup manifest and dump inspection helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from repomap_kg import __version__
from repomap_kg.runtime._backup_manifest_records import (
    BACKUP_FORMAT_VERSION as BACKUP_FORMAT_VERSION,
    SAFE_IDENTIFIER_RE as SAFE_IDENTIFIER_RE,
    backup_dump_not_found as backup_dump_not_found,
    backup_not_found as backup_not_found,
    bounded_text as bounded_text,
    ensure_path_under_backups_root as ensure_path_under_backups_root,
    infer_dump_format as infer_dump_format,
    is_incomplete_backup_path as is_incomplete_backup_path,
    list_manifest_paths as list_manifest_paths,
    malformed_backup_manifest as malformed_backup_manifest,
    optional_manifest_text as optional_manifest_text,
    read_manifest_file as read_manifest_file,
    resolve_backup_manifest_path as resolve_backup_manifest_path,
    resolve_dump_file_for_inspection as resolve_dump_file_for_inspection,
    safe_dump_file_name as safe_dump_file_name,
    sanitize_toc_identifier as sanitize_toc_identifier,
    select_dump_file_for_database as select_dump_file_for_database,
    verify_dump_file_checksum as verify_dump_file_checksum,
    verify_dump_file_checksum_for_inspection as verify_dump_file_checksum_for_inspection,
)
from repomap_kg.runtime.backup_records import (
    MAX_TOC_TABLE_NAMES,
    BackupDumpFile,
    DumpTocSummary,
    LocalDbBackupPlan,
    RuntimeContainerMetadata,
    restore_hint,
)
from repomap_kg.runtime.backup_streaming import (
    write_private_bytes,
    write_private_text,
)


def write_dump_file(path: Path, content: bytes) -> BackupDumpFile:
    write_private_bytes(path, content)
    return BackupDumpFile(
        name=path.name,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def write_manifest_and_restore_docs(
    plan: LocalDbBackupPlan,
    *,
    dump_files: tuple[BackupDumpFile, ...],
    container: RuntimeContainerMetadata,
    command_invoked: Sequence[str],
    scope: str,
    recovery_point: Mapping[str, str] | None = None,
) -> None:
    manifest = build_manifest(
        plan,
        dump_files=dump_files,
        container=container,
        command_invoked=command_invoked,
        scope=scope,
        recovery_point=recovery_point,
    )
    write_private_text(
        plan.manifest_path,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    write_private_text(plan.restore_path, render_restore_doc(manifest))


def build_manifest(
    plan: LocalDbBackupPlan,
    *,
    dump_files: tuple[BackupDumpFile, ...],
    container: RuntimeContainerMetadata,
    command_invoked: Sequence[str],
    scope: str,
    recovery_point: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "repo_map_version": __version__,
        "backup_id": plan.backup_id,
        "backup_kind": plan.backup_kind,
        "runtime_id": plan.plan.identity.home_hash,
        "repo_map_home": {
            "display": str(plan.plan.repo_map_home),
            "home_hash": plan.plan.identity.home_hash,
        },
        "container_runtime": plan.plan.container_runtime,
        "container": container.to_jsonable(),
        "database": plan.database,
        "databases": list(plan.databases),
        "timestamp": plan.timestamp,
        "command_invoked": list(command_invoked),
        "reason": plan.reason,
        "scope": scope,
        "recovery_point": dict(recovery_point) if recovery_point else None,
        "dump_files": [item.to_jsonable() for item in dump_files],
        "dump_format": plan.dump_format,
        "compression": "none",
        "direct_db_exposure": {
            "enabled": plan.plan.direct_db_host_port_enabled,
            "required": False,
        },
        "redacted_connection": {
            "host": "postgres",
            "port": 5432,
            "database": plan.database or ",".join(plan.databases),
            "user": plan.plan.user,
            "password": "[REDACTED]",
        },
        "restore_supported": True,
        "restore_hint": restore_hint(plan),
        "warnings": [
            "Restore/init creates only new databases and refuses existing targets."
        ],
    }
    return {key: value for key, value in manifest.items() if value is not None}


def render_restore_doc(manifest: Mapping[str, Any]) -> str:
    database = manifest.get("database") or "<database>"
    backup_id = manifest.get("backup_id", "<backup-id>")
    dump_files = manifest.get("dump_files", [])
    file_lines = "\n".join(
        f"- `{item.get('name')}` sha256 `{item.get('sha256')}`"
        for item in dump_files
        if isinstance(item, Mapping)
    )
    return (
        f"# RepoMap Backup {backup_id}\n\n"
        "This backup was created by RepoMap local database lifecycle commands.\n\n"
        "Restore/init support is available for new databases only. Existing target "
        "databases are refused and are not modified.\n\n"
        "## Dump Files\n\n"
        f"{file_lines or '- none recorded'}\n\n"
        "## Future Restore Command\n\n"
        "The intended future command shape is:\n\n"
        "```sh\n"
        f"repomap-kg local db init --database {database} --from-dump <backup-dir>\n"
        "```\n\n"
        "No passwords are stored in this restore note.\n"
    )


def summarize_pg_restore_toc(
    toc_text: str,
    *,
    dump_file: str,
    dump_format: str | None,
) -> DumpTocSummary:
    toc_entry_count = 0
    tables: set[str] = set()
    table_data_tables: set[str] = set()
    for raw_line in toc_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or ";" not in line:
            continue
        toc_entry_count += 1
        parts = line.split(";", 1)[1].strip().split()
        if len(parts) < 5:
            continue
        if parts[2:4] == ["TABLE", "DATA"] and len(parts) >= 6:
            table = sanitize_toc_identifier(parts[5])
            if table:
                table_data_tables.add(table)
            continue
        if parts[2] == "TABLE":
            table = sanitize_toc_identifier(parts[4])
            if table:
                tables.add(table)
    bounded_tables = tuple(sorted(tables)[:MAX_TOC_TABLE_NAMES])
    bounded_table_data_tables = tuple(sorted(table_data_tables)[:MAX_TOC_TABLE_NAMES])
    return DumpTocSummary(
        dump_file=dump_file,
        dump_format=dump_format,
        dump_contents_read=True,
        toc_entry_count=toc_entry_count,
        table_count=len(bounded_tables),
        table_data_count=len(bounded_table_data_tables),
        tables=bounded_tables,
        table_data_tables=bounded_table_data_tables,
    )


__all__ = [
    "BACKUP_FORMAT_VERSION",
    "SAFE_IDENTIFIER_RE",
    "backup_dump_not_found",
    "backup_not_found",
    "bounded_text",
    "build_manifest",
    "ensure_path_under_backups_root",
    "infer_dump_format",
    "is_incomplete_backup_path",
    "list_manifest_paths",
    "malformed_backup_manifest",
    "optional_manifest_text",
    "read_manifest_file",
    "render_restore_doc",
    "resolve_backup_manifest_path",
    "resolve_dump_file_for_inspection",
    "safe_dump_file_name",
    "sanitize_toc_identifier",
    "select_dump_file_for_database",
    "summarize_pg_restore_toc",
    "verify_dump_file_checksum",
    "verify_dump_file_checksum_for_inspection",
    "write_dump_file",
    "write_manifest_and_restore_docs",
]
