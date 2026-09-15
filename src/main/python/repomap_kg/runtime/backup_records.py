"""Record types for local database backup lifecycle results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from repomap_kg.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan
from repomap_kg.runtime.release import PACKAGED_PG_DUMP


MAX_TOC_TABLE_NAMES = 50
EXPECTED_REPOMAP_TABLES = (
    "repositories", "runs", "files", "nodes", "edges", "evidence",
    "raw_observations", "canonical_nodes", "canonical_edges",
    "canonical_evidence", "canonical_node_evidence", "canonical_edge_evidence",
)


class LocalDbBackupError(RuntimeError):
    """Raised when a local DB backup command cannot continue safely."""

    def __init__(self, diagnostics: Sequence[LocalRuntimeDiagnostic]):
        self.diagnostics = tuple(diagnostics)
        message = "; ".join(diagnostic.message for diagnostic in self.diagnostics)
        super().__init__(message or "local DB backup error")


@dataclass(frozen=True)
class RuntimeContainerMetadata:
    container_id: str
    name: str
    image: str | None
    labels: Mapping[str, str]

    def to_jsonable(self) -> dict[str, Any]:
        return {"id": self.container_id, "name": self.name, "image": self.image, "labels_verified": True}


@dataclass(frozen=True)
class BackupDumpFile:
    name: str
    size_bytes: int
    sha256: str

    def to_jsonable(self) -> dict[str, Any]:
        return {"name": self.name, "size_bytes": self.size_bytes, "sha256": self.sha256}


@dataclass(frozen=True)
class LocalDbBackupPlan:
    command: str
    plan: LocalRuntimePlan
    backup_kind: str
    timestamp: str
    database: str | None
    databases: tuple[str, ...]
    backup_id: str
    backup_path: Path
    dump_format: str
    reason: str | None = None
    container_internal: bool = False

    @property
    def manifest_path(self) -> Path:
        return self.backup_path / "manifest.json"

    @property
    def restore_path(self) -> Path:
        return self.backup_path / "restore.md"

    def planned_dump_command(self, database: str) -> tuple[str, ...]:
        if self.container_internal:
            cfg = self.plan.config
            host = cfg.postgres.host if cfg is not None else "postgres"
            port = cfg.postgres.port if cfg is not None else 5432
            return (PACKAGED_PG_DUMP, "-h", host, "-p", str(port), "-Fc", "-U", self.plan.user, "-d", database)
        return (
            self.plan.container_runtime, "exec", "-e", "PGPASSWORD",
            self.plan.identity.postgres_container, PACKAGED_PG_DUMP,
            "-Fc", "-U", self.plan.user, "-d", database,
        )


@dataclass(frozen=True)
class LocalDbBackupResult:
    command: str
    result: str
    plan: LocalDbBackupPlan
    dump_files: tuple[BackupDumpFile, ...] = ()
    container: RuntimeContainerMetadata | None = None
    diagnostics: tuple[LocalRuntimeDiagnostic, ...] = ()
    planned_command: tuple[str, ...] = ()
    backup_path_created: bool = False
    dump_executed: bool = False
    destructive_db_actions: bool = False
    direct_db_required: bool = False

    def to_jsonable(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "command": self.command,
            "result": self.result,
            "backup_id": self.plan.backup_id,
            "backup_kind": self.plan.backup_kind,
            "database": self.plan.database,
            "databases": list(self.plan.databases),
            "timestamp": self.plan.timestamp,
            "dump_format": self.plan.dump_format,
            "dump_files": [item.to_jsonable() for item in self.dump_files],
            "diagnostics": [item.to_jsonable() for item in self.diagnostics],
            "backup_path_created": self.backup_path_created,
            "dump_executed": self.dump_executed,
            "destructive_db_actions": self.destructive_db_actions,
            "direct_db_required": self.direct_db_required,
            "direct_db_exposure": {
                "enabled": self.plan.plan.direct_db_host_port_enabled,
                "required": self.direct_db_required,
            },
            "container": self.container.to_jsonable() if self.container else None,
            "restore_supported": bool(self.dump_files),
        }
        if self.plan.reason:
            payload["reason"] = self.plan.reason
        return payload


@dataclass(frozen=True)
class BackupListingResult:
    repo_map_home: Path
    backups_root: Path
    backups: tuple[dict[str, Any], ...]
    diagnostics: tuple[LocalRuntimeDiagnostic, ...] = ()

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "command": "backups",
            "backup_count": len(self.backups),
            "backups": list(self.backups),
            "diagnostics": [item.to_jsonable() for item in self.diagnostics],
            "dump_contents_read": False,
            "destructive_db_actions": False,
        }


@dataclass(frozen=True)
class BackupInfoResult:
    repo_map_home: Path
    backups_root: Path
    manifest_path: Path
    manifest: Mapping[str, Any]

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "command": "backup-info",
            "manifest": safe_manifest_summary(self.manifest, self.manifest_path.parent),
            "dump_contents_read": False,
            "destructive_db_actions": False,
        }


@dataclass(frozen=True)
class DumpTocSummary:
    dump_file: str
    dump_format: str | None
    dump_contents_read: bool
    toc_entry_count: int = 0
    table_count: int = 0
    table_data_count: int = 0
    tables: tuple[str, ...] = ()
    table_data_tables: tuple[str, ...] = ()

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "dump_file": self.dump_file,
            "dump_format": self.dump_format,
            "dump_contents_read": self.dump_contents_read,
            "toc_entry_count": self.toc_entry_count,
            "table_count": self.table_count,
            "table_data_count": self.table_data_count,
            "tables": list(self.tables),
            "table_data_tables": list(self.table_data_tables),
        }


@dataclass(frozen=True)
class BackupInspectResult:
    repo_map_home: Path
    backups_root: Path
    manifest_path: Path
    manifest: Mapping[str, Any]
    dump_summaries: tuple[DumpTocSummary, ...] = ()
    checksum_verified: bool = False
    diagnostics: tuple[LocalRuntimeDiagnostic, ...] = ()
    container: RuntimeContainerMetadata | None = None

    def to_jsonable(self) -> dict[str, Any]:
        manifest = safe_manifest_summary(self.manifest, self.manifest_path.parent)
        tables = bounded_sorted_union(summary.tables for summary in self.dump_summaries)
        table_data_tables = bounded_sorted_union(
            summary.table_data_tables for summary in self.dump_summaries
        )
        table_presence = set(tables) | set(table_data_tables)
        return {
            "command": "backup-inspect",
            "backup_id": manifest.get("backup_id"),
            "backup_kind": manifest.get("backup_kind"),
            "database": manifest.get("database"),
            "databases": manifest.get("databases", []),
            "manifest_verified": True,
            "checksum_verified": self.checksum_verified,
            "restore_supported": bool(manifest.get("restore_supported", False)),
            "dump_contents_read": any(
                summary.dump_contents_read for summary in self.dump_summaries
            ),
            "dump_format": self.manifest.get("dump_format"),
            "toc_entry_count": sum(
                summary.toc_entry_count for summary in self.dump_summaries
            ),
            "table_count": len(tables),
            "table_data_count": len(table_data_tables),
            "tables": list(tables),
            "table_data_tables": list(table_data_tables),
            "expected_repomap_tables": {
                table: table in table_presence for table in EXPECTED_REPOMAP_TABLES
            },
            "dump_summaries": [summary.to_jsonable() for summary in self.dump_summaries],
            "diagnostics": [diagnostic.to_jsonable() for diagnostic in self.diagnostics],
            "destructive_db_actions": False,
            "raw_dump_contents_exposed": False,
            "planned_command_exposed": False,
        }


@dataclass(frozen=True)
class LocalDbInitResult:
    command: str
    result: str
    repo_map_home: Path
    database: str
    source_mode: str
    runtime_plan: LocalRuntimePlan
    container: RuntimeContainerMetadata | None = None
    backup_id: str | None = None
    backup_path: Path | None = None
    manifest_path: Path | None = None
    dump_file: str | None = None
    dump_path: Path | None = None
    checksum_verified: bool = False
    target_existed: bool = False
    planned_actions: tuple[str, ...] = ()
    planned_command: tuple[str, ...] = ()
    diagnostics: tuple[LocalRuntimeDiagnostic, ...] = ()
    database_created: bool = False
    schema_initialized: bool = False
    dump_restored: bool = False
    schema_ready: bool = False
    destructive_db_actions: bool = False
    direct_db_required: bool = False

    def to_jsonable(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "command": self.command,
            "result": self.result,
            "database": self.database,
            "source_mode": self.source_mode,
            "backup_id": self.backup_id,
            "dump_file": self.dump_file,
            "checksum_verified": self.checksum_verified,
            "target_existed": self.target_existed,
            "planned_actions": list(self.planned_actions),
            "diagnostics": [item.to_jsonable() for item in self.diagnostics],
            "database_created": self.database_created,
            "schema_initialized": self.schema_initialized,
            "dump_restored": self.dump_restored,
            "schema_ready": self.schema_ready,
            "restore_supported": bool(self.dump_file and self.checksum_verified),
            "destructive_db_actions": self.destructive_db_actions,
            "direct_db_required": self.direct_db_required,
            "direct_db_exposure": {
                "enabled": self.runtime_plan.direct_db_host_port_enabled,
                "required": self.direct_db_required,
            },
            "container": self.container.to_jsonable() if self.container else None,
        }
        return payload


@dataclass(frozen=True)
class LocalDbDropResult:
    command: str
    result: str
    repo_map_home: Path
    database: str
    runtime_plan: LocalRuntimePlan
    backup_plan: LocalDbBackupPlan
    backup_result: LocalDbBackupResult | None = None
    container: RuntimeContainerMetadata | None = None
    backup_first: bool = True
    confirmation_received: bool = False
    dry_run: bool = False
    target_existed: bool = False
    checksum_verified: bool = False
    restore_note_verified: bool = False
    planned_actions: tuple[str, ...] = ()
    planned_command: tuple[str, ...] = ()
    diagnostics: tuple[LocalRuntimeDiagnostic, ...] = ()
    database_dropped: bool = False
    destructive_db_actions: bool = False
    direct_db_required: bool = False

    def to_jsonable(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "command": self.command,
            "result": self.result,
            "database": self.database,
            "backup_first": self.backup_first,
            "confirmation_received": self.confirmation_received,
            "dry_run": self.dry_run,
            "backup_id": self.backup_plan.backup_id,
            "backup_kind": self.backup_plan.backup_kind,
            "restore_command_hint": restore_hint(self.backup_plan),
            "target_existed": self.target_existed,
            "checksum_verified": self.checksum_verified,
            "restore_note_verified": self.restore_note_verified,
            "planned_actions": list(self.planned_actions),
            "diagnostics": [item.to_jsonable() for item in self.diagnostics],
            "backup_path_created": bool(
                self.backup_result and self.backup_result.backup_path_created
            ),
            "dump_executed": bool(self.backup_result and self.backup_result.dump_executed),
            "database_dropped": self.database_dropped,
            "restore_supported": self.backup_first,
            "destructive_db_actions": self.destructive_db_actions,
            "direct_db_required": self.direct_db_required,
            "direct_db_exposure": {
                "enabled": self.runtime_plan.direct_db_host_port_enabled,
                "required": self.direct_db_required,
            },
            "container": self.container.to_jsonable() if self.container else None,
        }
        if self.backup_plan.reason:
            payload["reason"] = self.backup_plan.reason
        return payload


def safe_manifest_summary(manifest: Mapping[str, Any], backup_path: Path) -> dict[str, Any]:
    dump_files = [
        {
            "name": item.get("name"),
            "size_bytes": item.get("size_bytes"),
            "sha256": item.get("sha256"),
        }
        for item in manifest.get("dump_files", [])
        if isinstance(item, Mapping)
    ]
    backup_id = manifest.get("backup_id")
    database = manifest.get("database")
    restore_command_hint = None
    if backup_id and database and manifest.get("restore_supported", False):
        restore_command_hint = (
            f"repomap-kg local db init --database {database} --from-dump {backup_id}"
        )
    return {
        "backup_id": backup_id,
        "timestamp": manifest.get("timestamp"),
        "backup_kind": manifest.get("backup_kind"),
        "database": database,
        "databases": manifest.get("databases", []),
        "runtime_id": manifest.get("runtime_id"),
        "dump_files": dump_files,
        "total_bytes": sum(item.get("size_bytes") or 0 for item in dump_files),
        "restore_supported": bool(manifest.get("restore_supported", False)),
        "restore_command_hint": restore_command_hint,
    }


def bounded_sorted_union(groups: Iterable[Sequence[str]]) -> tuple[str, ...]:
    values: set[str] = set()
    for group in groups:
        values.update(group)
    return tuple(sorted(values)[:MAX_TOC_TABLE_NAMES])


def restore_hint(plan: LocalDbBackupPlan) -> str:
    database = plan.database or "<database>"
    return f"repomap-kg local db init --database {database} --from-dump {plan.backup_id}"
