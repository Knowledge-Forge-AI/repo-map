"""Backup manifest and dump inspection helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from common_lore_index import __version__
from common_lore_index.runtime._backup_manifest_records import (
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
from common_lore_index.runtime._backup_provenance import (
    SUPPORTED_BACKUP_FORMAT_VERSIONS,
    provenance_error,
)
from common_lore_index.runtime._backup_support import (
    BackupSupportEvaluation,
    derive_manifest_support,
)
from common_lore_index.runtime._extension_restore_policy import (
    TrustedExtensionRestorePolicy,
    resolve_extension_restore_policy,
)
from common_lore_index.runtime._extension_restore_qualification import engine_image_content_id
from common_lore_index.runtime.backup_records import (
    MAX_TOC_TABLE_NAMES,
    BackupDumpFile,
    DumpTocSummary,
    LocalDbBackupPlan,
    RuntimeContainerMetadata,
    restore_hint,
)
from common_lore_index.runtime.backup_streaming import (
    write_private_bytes,
    write_private_text,
)
from common_lore_index.runtime.release import (
    PACKAGED_PG_DUMP,
    PACKAGED_PG_RESTORE,
    PACKAGED_PSQL,
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
    server_provenance: Mapping[str, Any] | None = None,
    database_catalogs: Mapping[str, Mapping[str, Any]] | None = None,
    toc_digests: Mapping[str, str] | None = None,
    quiescence: Mapping[str, Any] | None = None,
    support_evaluation: BackupSupportEvaluation | None = None,
    extension_restore_policy: TrustedExtensionRestorePolicy | None = None,
) -> BackupSupportEvaluation:
    manifest = build_manifest(
        plan,
        dump_files=dump_files,
        container=container,
        command_invoked=command_invoked,
        scope=scope,
        recovery_point=recovery_point,
        server_provenance=server_provenance,
        database_catalogs=database_catalogs,
        toc_digests=toc_digests,
        quiescence=quiescence,
        support_evaluation=support_evaluation,
        extension_restore_policy=extension_restore_policy,
    )
    write_private_text(
        plan.manifest_path,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    write_private_text(plan.restore_path, render_restore_doc(manifest))
    return BackupSupportEvaluation(
        restore_protocol=str(manifest["restore_protocol"]),
        restore_supported=bool(manifest["restore_supported"]),
        restore_blockers=tuple(manifest["restore_blockers"]),
        extension_census_state="complete",
    )


def build_manifest(
    plan: LocalDbBackupPlan,
    *,
    dump_files: tuple[BackupDumpFile, ...],
    container: RuntimeContainerMetadata,
    command_invoked: Sequence[str],
    scope: str,
    recovery_point: Mapping[str, str] | None = None,
    server_provenance: Mapping[str, Any] | None = None,
    database_catalogs: Mapping[str, Mapping[str, Any]] | None = None,
    toc_digests: Mapping[str, str] | None = None,
    quiescence: Mapping[str, Any] | None = None,
    support_evaluation: BackupSupportEvaluation | None = None,
    extension_restore_policy: TrustedExtensionRestorePolicy | None = None,
) -> dict[str, Any]:
    if (
        server_provenance is None
        or database_catalogs is None
        or toc_digests is None
        or quiescence is None
    ):
        raise provenance_error(
            "backup-manifest-invalid",
            "manifest.json",
            "format-2 manifest requires explicit server, catalog, TOC, and quiescence provenance",
        )
    resolved_server = dict(server_provenance)
    resolved_catalogs: dict[str, dict[str, Any]] = {
        db: dict(cat) for db, cat in database_catalogs.items()
    }
    resolved_toc = dict(toc_digests)
    resolved_quiescence: dict[str, Any] = dict(quiescence)
    fp_matched = resolved_quiescence.get("before_after_fingerprint_matched")
    if not isinstance(fp_matched, bool):
        raise provenance_error(
            "backup-manifest-invalid",
            "manifest.json",
            "format-2 manifest requires explicit boolean before_after_fingerprint_matched in quiescence",
        )
    if len(plan.databases) != len(dump_files):
        raise provenance_error(
            "backup-manifest-invalid",
            "manifest.json",
            "format-2 manifest dump_files count must match plan.databases",
        )
    resolved_policy = resolve_extension_restore_policy(extension_restore_policy)
    support = support_evaluation or derive_manifest_support(
        resolved_catalogs,
        before_after_fingerprint_matched=fp_matched,
        quiescence=resolved_quiescence,
        extension_restore_policy=resolved_policy,
        server_provenance=resolved_server,
    )
    archive_bindings = []
    for db_name, dump_file in zip(plan.databases, dump_files, strict=True):
        toc_sha = resolved_toc.get(dump_file.name, resolved_toc.get(db_name))
        if not isinstance(toc_sha, str) or len(toc_sha) != 64:
            raise provenance_error(
                "backup-manifest-invalid",
                db_name,
                "format-2 manifest requires a verified 64-char toc_sha256 for every dump file",
            )
        archive_bindings.append(
            {
                "database": db_name,
                "dump_file": dump_file.name,
                "sha256": dump_file.sha256,
                "size_bytes": dump_file.size_bytes,
                "toc_sha256": toc_sha,
            }
        )
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
        "restore_protocol": support.restore_protocol,
        "restore_supported": support.restore_supported,
        "restore_blockers": list(support.restore_blockers),
        "server_provenance": resolved_server,
        "artifact_provenance": {
            "archive_bindings": archive_bindings,
            "client_identities": resolved_server.get(
                "client_identities",
                {
                    "pg_dump_version": "unavailable",
                    "pg_restore_version": "unavailable",
                    "psql_version": "unavailable",
                },
            ),
            "container_id": container.container_id,
            "container_image": container.image or "unavailable",
            "container_image_id": engine_image_content_id(container.image_id) or "unavailable",
            "dump_format": plan.dump_format,
            "pg_dump_executable": PACKAGED_PG_DUMP,
            "pg_restore_executable": PACKAGED_PG_RESTORE,
            "policy_binding": resolved_policy.policy_binding_record(),
            "psql_executable": PACKAGED_PSQL,
        },
        "database_catalogs": resolved_catalogs,
        "quiescence": resolved_quiescence,
        "restore_hint": restore_hint(plan) if support.restore_supported else None,
        "warnings": [
            "Restore/init creates only new databases and refuses existing targets."
        ],
    }
    return {key: value for key, value in manifest.items() if value is not None}


def render_restore_doc(manifest: Mapping[str, Any]) -> str:
    database = manifest.get("database") or "<database>"
    backup_id = manifest.get("backup_id", "<backup-id>")
    dump_files = manifest.get("dump_files", [])
    protocol = str(manifest.get("restore_protocol") or "core_v1")
    supported = bool(manifest.get("restore_supported", False))
    blockers = manifest.get("restore_blockers") or []
    file_lines = "\n".join(
        f"- `{item.get('name')}` sha256 `{item.get('sha256')}`"
        for item in dump_files
        if isinstance(item, Mapping)
    )
    if not supported or blockers:
        blocker_text = ", ".join(str(b) for b in blockers) or "restore_supported=false"
        return (
            f"# RepoMap Backup {backup_id}\n\n"
            "This backup was created by RepoMap local database lifecycle commands.\n\n"
            f"Restore status: `restore_supported=false` (`restore_protocol={protocol}`).\n"
            f"Automatic restore/init is refused due to blockers: `{blocker_text}`.\n\n"
            "## Dump Files\n\n"
            f"{file_lines or '- none recorded'}\n\n"
            "No passwords are stored in this restore note.\n"
        )
    return (
        f"# RepoMap Backup {backup_id}\n\n"
        "This backup was created by RepoMap local database lifecycle commands.\n\n"
        "Restore/init support is available for new databases only. Existing target "
        "databases are refused and are not modified.\n"
        f"Restore status: `restore_supported=true` (`restore_protocol={protocol}`).\n\n"
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
    extensions: set[str] = set()
    schemas: set[str] = set()
    for raw_line in toc_text.split("\n"):
        line = raw_line.rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith(";") or ";" not in line:
            continue
        dump_id_str, after_semi = line.split(";", 1)
        parts = after_semi.lstrip(" ").split(" ", 2)
        if not dump_id_str.strip().isdigit() or len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit() or not parts[2]:
            continue
        toc_entry_count += 1
        rest = parts[2]
        if rest.startswith("EXTENSION - "):
            ext_tail = rest[len("EXTENSION - "):]
            ext = ext_tail[:-1] if ext_tail.endswith(" ") else ext_tail
            if ext:
                extensions.add(ext)
        elif rest.startswith("SCHEMA - "):
            sch_tail = rest[len("SCHEMA - "):]
            raw_sch = (sch_tail[:-1] if sch_tail.endswith(" ") else sch_tail.rpartition(" ")[0]).strip()
            sch = sanitize_toc_identifier(raw_sch) or raw_sch
            if sch:
                schemas.add(sch)
        elif rest.startswith("TABLE DATA "):
            data_tail = rest[len("TABLE DATA "):]
            ns_and_rel = (data_tail[:-1] if data_tail.endswith(" ") else data_tail.rpartition(" ")[0]).strip()
            raw_tbl = ns_and_rel.split(" ", 1)[1] if " " in ns_and_rel else ""
            table = sanitize_toc_identifier(raw_tbl)
            if table:
                table_data_tables.add(table)
        elif rest.startswith("TABLE "):
            tbl_tail = rest[len("TABLE "):]
            ns_and_rel = (tbl_tail[:-1] if tbl_tail.endswith(" ") else tbl_tail.rpartition(" ")[0]).strip()
            raw_tbl = ns_and_rel.split(" ", 1)[1] if " " in ns_and_rel else ""
            table = sanitize_toc_identifier(raw_tbl)
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
        extensions=tuple(sorted(extensions)[:MAX_TOC_TABLE_NAMES]),
        schemas=tuple(sorted(schemas)[:MAX_TOC_TABLE_NAMES]),
    )


__all__ = [
    "BACKUP_FORMAT_VERSION",
    "SAFE_IDENTIFIER_RE",
    "SUPPORTED_BACKUP_FORMAT_VERSIONS",
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
