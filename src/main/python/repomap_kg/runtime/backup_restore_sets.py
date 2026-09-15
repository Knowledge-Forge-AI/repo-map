"""Deterministic restore of complete coordinated graph/control backup sets."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from repomap_kg.ops.config import resolve_repo_map_home
from repomap_kg.runtime.backup import (
    create_database,
    database_exists,
    inspect_owned_postgres_container,
    run_pg_restore,
)
from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    backup_root,
    planned_pg_restore_command,
)
from repomap_kg.runtime.backup_manifests import (
    BACKUP_FORMAT_VERSION,
    optional_manifest_text,
    read_manifest_file,
    resolve_backup_manifest_path,
    select_dump_file_for_database,
    verify_dump_file_checksum,
)
from repomap_kg.runtime.backup_records import (
    LocalDbBackupError,
    RuntimeContainerMetadata,
)
from repomap_kg.runtime.local import (
    LocalRuntimeDiagnostic,
    LocalRuntimePlan,
    build_local_runtime_plan,
)
from repomap_kg.runtime.provisioning import cleanup_created_database
from repomap_kg.runtime.database_roles import (
    reconcile_control_database_roles,
    reconcile_graph_database_roles,
)


COORDINATED_SCOPE = "exact-configured-graph-control-databases"
STABLE_RECOVERY_POINT = {
    "held_through": "atomic-backup-publication",
    "method": "control-then-graph-maintenance-exclusion",
    "status": "stable",
}


@dataclass(frozen=True)
class CoordinatedRestoreResult:
    """Bounded outcome for one complete-set restore attempt."""

    result: str
    repo_map_home: Path
    runtime_plan: LocalRuntimePlan
    backup_id: str | None
    backup_path: Path
    manifest_path: Path
    databases: tuple[str, ...]
    restore_order: tuple[str, ...]
    container: RuntimeContainerMetadata | None = None
    checksum_verified: bool = False
    target_preflight_complete: bool = False
    databases_created: tuple[str, ...] = ()
    dumps_restored: tuple[str, ...] = ()

    @property
    def command(self) -> str:
        return "restore-all"

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "result": self.result,
            "backup_id": self.backup_id,
            "databases": list(self.databases),
            "restore_order": list(self.restore_order),
            "checksum_verified": self.checksum_verified,
            "target_preflight_complete": self.target_preflight_complete,
            "databases_created": list(self.databases_created),
            "dumps_restored": list(self.dumps_restored),
            "control_restored_last": bool(
                self.dumps_restored
                and self.dumps_restored[-1] == self.restore_order[-1]
            ),
            "cleanup_required": False,
            "destructive_db_actions": False,
            "direct_db_required": False,
            "container": self.container.to_jsonable() if self.container else None,
        }


def restore_coordinated_backup(
    repo_map_home: str | Path | None,
    *,
    backup: str | Path,
    dry_run: bool = False,
    command_runner: CommandRunner | None = None,
) -> CoordinatedRestoreResult:
    """Restore one exact stable coordinated set into an empty topology."""

    runner = command_runner or subprocess.run
    home = resolve_repo_map_home(repo_map_home)
    runtime_plan = build_local_runtime_plan(home)
    manifest_path = resolve_backup_manifest_path(backup_root(home), backup)
    manifest = read_manifest_file(manifest_path)
    databases, restore_order, dumps = _validate_complete_set(
        runtime_plan,
        manifest_path,
        manifest,
    )
    container = inspect_owned_postgres_container(runtime_plan, runner)
    existing = tuple(
        database
        for database in restore_order
        if database_exists(runtime_plan, database, runner)
    )
    if existing:
        raise _restore_error(
            "coordinated-restore-target-exists",
            "restore requires every configured target database to be absent",
        )
    base_result = CoordinatedRestoreResult(
        result="dry_run" if dry_run else "success",
        repo_map_home=home,
        runtime_plan=runtime_plan,
        backup_id=optional_manifest_text(manifest.get("backup_id")),
        backup_path=manifest_path.parent,
        manifest_path=manifest_path,
        databases=databases,
        restore_order=restore_order,
        container=container,
        checksum_verified=True,
        target_preflight_complete=True,
    )
    if dry_run:
        return base_result

    created: list[str] = []
    restored: list[str] = []
    try:
        for database in restore_order:
            create_database(runtime_plan, database, runner)
            created.append(database)
            run_pg_restore(
                runtime_plan,
                database,
                dumps[database],
                planned_pg_restore_command(runtime_plan, database),
                runner,
            )
            restored.append(database)
        for database in sorted(runtime_plan.graph_databases):
            reconcile_graph_database_roles(runtime_plan, database, runner)
        reconcile_control_database_roles(runtime_plan, restore_order[-1], runner)
    except Exception as restore_error:
        cleanup_failed = False
        for database in reversed(created):
            try:
                cleanup_created_database(runtime_plan, database, runner)
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            raise _restore_error(
                "coordinated-restore-cleanup-failed",
                "restore failed and one or more invocation-created targets remain",
            ) from restore_error
        raise
    return replace(
        base_result,
        databases_created=tuple(created),
        dumps_restored=tuple(restored),
    )


def _validate_complete_set(
    plan: LocalRuntimePlan,
    manifest_path: Path,
    manifest: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, Path]]:
    databases = plan.owned_databases
    graph_databases = tuple(sorted(plan.graph_databases))
    control_databases = tuple(
        database for database in databases if database not in plan.graph_databases
    )
    if not databases or len(control_databases) != 1:
        raise _restore_error(
            "coordinated-restore-topology-invalid",
            "configured graph/control authority is not an exact restorable topology",
        )
    if (
        manifest.get("backup_format_version") != BACKUP_FORMAT_VERSION
        or manifest.get("scope") != COORDINATED_SCOPE
        or manifest.get("database") is not None
    ):
        raise _restore_error(
            "coordinated-backup-scope-invalid",
            "backup is not a supported coordinated complete set",
        )
    if manifest.get("recovery_point") != STABLE_RECOVERY_POINT:
        raise _restore_error(
            "coordinated-backup-unstable",
            "backup does not assert the required stable recovery point",
        )
    if manifest.get("databases") != list(databases):
        raise _restore_error(
            "coordinated-backup-topology-mismatch",
            "backup database authority does not match current configuration",
        )
    dump_files = manifest.get("dump_files")
    expected_names = {f"{database}.pgcustom" for database in databases}
    if not isinstance(dump_files, list) or len(dump_files) != len(databases):
        raise _invalid_dump_set()
    actual_names = [
        item.get("name") if isinstance(item, Mapping) else None
        for item in dump_files
    ]
    if (
        any(not isinstance(name, str) for name in actual_names)
        or len(set(actual_names)) != len(actual_names)
        or set(actual_names) != expected_names
    ):
        raise _invalid_dump_set()
    dumps: dict[str, Path] = {}
    for database in databases:
        dump_file = select_dump_file_for_database(manifest, database)
        dump_path = manifest_path.parent / dump_file["name"]
        verify_dump_file_checksum(dump_path, dump_file)
        dumps[database] = dump_path
    return databases, graph_databases + control_databases, dumps


def _invalid_dump_set() -> LocalDbBackupError:
    return _restore_error(
        "coordinated-backup-dump-set-invalid",
        "backup must contain exactly one dump for every configured database",
    )


def _restore_error(code: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError(
        (LocalRuntimeDiagnostic("error", code, "coordinated restore", message),)
    )


def format_coordinated_restore_table(result: CoordinatedRestoreResult) -> str:
    """Render a concise public-safe complete-set restore result."""

    payload = result.to_jsonable()
    return "\n".join(
        (
            f"RepoMap local DB restore-all: result={payload['result']}",
            f"backup_id={payload['backup_id']}",
            f"restore_order={','.join(payload['restore_order'])}",
            (
                "safety: "
                f"checksum_verified={str(payload['checksum_verified']).lower()} "
                "all_targets_absent=true "
                f"control_restored_last="
                f"{str(payload['control_restored_last']).lower()}"
            ),
        )
    )


__all__ = [
    "CoordinatedRestoreResult",
    "format_coordinated_restore_table",
    "restore_coordinated_backup",
]
