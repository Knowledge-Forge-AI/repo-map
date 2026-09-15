"""Local database backup, restoration, and managed lifecycle operations."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import repomap_kg.runtime.backup_inspection as _backup_inspection
from repomap_kg.ops.config import resolve_repo_map_home
from repomap_kg.runtime._backup_lifecycle import (
    build_backup_plan,
    execute_backup_plan,
    init_database_from_dump,
    init_database_from_source,
    validate_owned_database,
)
from repomap_kg.runtime._backup_operations import (
    apply_source_schema,
    backup_first_required,
    cleanup_empty_backup_directory,
    create_database,
    database_already_exists,
    database_exists,
    database_not_found,
    default_backup_runner,
    drop_confirmation_required,
    drop_runtime_database,
    ensure_new_backup_directory,
    inspect_owned_postgres_container,
    run_pg_dump,
    run_pg_restore,
)
from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    backup_root,
    planned_drop_database_command,
    validate_database_name,
)
from repomap_kg.runtime.backup_formatting import (
    format_backup_info_table,
    format_backup_inspect_table,
    format_backup_listing_table,
    format_backup_result_table,
    format_drop_result_table,
    format_init_result_table,
)
from repomap_kg.runtime.backup_inspection import (
    list_backups,
    read_backup_info,
    run_pg_restore_list,
    verify_drop_backup,
)
from repomap_kg.runtime.backup_manifests import (
    BACKUP_FORMAT_VERSION,
    write_manifest_and_restore_docs,
)
from repomap_kg.runtime.backup_records import (
    BackupDumpFile,
    BackupInspectResult,
    LocalDbBackupError,
    LocalDbBackupPlan,
    LocalDbBackupResult,
    LocalDbDropResult,
    LocalDbInitResult,
    RuntimeContainerMetadata,
)
from repomap_kg.runtime.backup_streaming import atomic_private_backup_directory
from repomap_kg.runtime.database_roles import reconcile_graph_database_roles
from repomap_kg.runtime.local import (
    LocalRuntimePlan,
    build_local_runtime_plan,
)
from repomap_kg.storage import (
    StorageSchemaError,
    discover_migrations,
    graph_schema_initialization_sql,
)


def dump_database(
    repo_map_home: str | Path | None,
    *,
    database: str,
    dry_run: bool = False,
    reason: str | None = None,
    timestamp: str | None = None,
    command_runner: CommandRunner | None = None,
) -> LocalDbBackupResult:
    validate_database_name(database)
    runner = command_runner or default_backup_runner()
    home = resolve_repo_map_home(repo_map_home)
    runtime_plan = build_local_runtime_plan(home)
    validate_owned_database(database, runtime_plan)
    backup_plan = build_backup_plan(
        runtime_plan,
        command="dump",
        backup_kind="manual-dump",
        database=database,
        databases=(database,),
        timestamp=timestamp,
        reason=reason,
    )
    planned_command = backup_plan.planned_dump_command(database)
    if dry_run:
        return LocalDbBackupResult(
            command="dump",
            result="dry_run",
            plan=backup_plan,
            planned_command=planned_command,
        )
    with atomic_private_backup_directory(
        backup_plan.backup_path,
        backups_root=backup_root(home),
    ) as staging_path:
        staging_plan = replace(backup_plan, backup_path=staging_path)
        container = inspect_owned_postgres_container(runtime_plan, runner)
        dump_file = run_pg_dump(
            runtime_plan,
            planned_command,
            runner,
            staging_path / "dump.pgcustom",
        )
        write_manifest_and_restore_docs(
            staging_plan,
            dump_files=(dump_file,),
            container=container,
            command_invoked=planned_command,
            scope="single-database",
        )
    return LocalDbBackupResult(
        command="dump",
        result="success",
        plan=backup_plan,
        dump_files=(dump_file,),
        container=container,
        planned_command=planned_command,
        backup_path_created=True,
        dump_executed=True,
    )


def dump_all_databases(
    repo_map_home: str | Path | None,
    *,
    dry_run: bool = False,
    reason: str | None = None,
    timestamp: str | None = None,
    command_runner: CommandRunner | None = None,
    stable_recovery_point: bool = False,
) -> LocalDbBackupResult:
    runner = command_runner or default_backup_runner()
    home = resolve_repo_map_home(repo_map_home)
    runtime_plan = build_local_runtime_plan(home)
    databases = runtime_plan.owned_databases or (runtime_plan.database,)
    for database in databases:
        validate_owned_database(database, runtime_plan)
    backup_plan = build_backup_plan(
        runtime_plan,
        command="dump-all",
        backup_kind="manual-dump-all",
        database=None,
        databases=databases,
        timestamp=timestamp,
        reason=reason,
    )
    planned_command = backup_plan.planned_dump_command(databases[0])
    if dry_run:
        return LocalDbBackupResult(
            command="dump-all",
            result="dry_run",
            plan=backup_plan,
            planned_command=planned_command,
        )
    dump_files: list[BackupDumpFile] = []
    with atomic_private_backup_directory(
        backup_plan.backup_path,
        backups_root=backup_root(home),
    ) as staging_path:
        staging_plan = replace(backup_plan, backup_path=staging_path)
        container = inspect_owned_postgres_container(runtime_plan, runner)
        for database in databases:
            dump_files.append(
                run_pg_dump(
                    runtime_plan,
                    backup_plan.planned_dump_command(database),
                    runner,
                    staging_path / f"{database}.pgcustom",
                )
            )
        write_manifest_and_restore_docs(
            staging_plan,
            dump_files=tuple(dump_files),
            container=container,
            command_invoked=planned_command,
            scope="exact-configured-graph-control-databases",
            recovery_point=(
                {
                    "status": "stable",
                    "method": "control-then-graph-maintenance-exclusion",
                    "held_through": "atomic-backup-publication",
                }
                if stable_recovery_point
                else None
            ),
        )
    return LocalDbBackupResult(
        command="dump-all",
        result="success",
        plan=backup_plan,
        dump_files=tuple(dump_files),
        container=container,
        planned_command=planned_command,
        backup_path_created=True,
        dump_executed=True,
    )


def inspect_backup(
    repo_map_home: str | Path | None,
    backup_id_or_path: str | Path,
    *,
    command_runner: CommandRunner | None = None,
) -> BackupInspectResult:
    return _backup_inspection.inspect_backup(
        **locals(),
        default_command_runner=subprocess.run,
        build_local_runtime_plan=build_local_runtime_plan,
        inspect_owned_postgres_container=inspect_owned_postgres_container,
        run_pg_restore_list=run_pg_restore_list,
    )


def drop_database(
    repo_map_home: str | Path | None,
    *,
    database: str,
    backup_first: bool = False,
    confirmed: bool = False,
    dry_run: bool = False,
    reason: str | None = None,
    timestamp: str | None = None,
    command_runner: CommandRunner | None = None,
) -> LocalDbDropResult:
    validate_database_name(database)
    if not backup_first:
        raise backup_first_required()
    if not dry_run and not confirmed:
        raise drop_confirmation_required()
    runner = command_runner or default_backup_runner()
    home = resolve_repo_map_home(repo_map_home)
    runtime_plan = build_local_runtime_plan(home)
    validate_drop_database_name(database, runtime_plan)
    backup_plan = build_backup_plan(
        runtime_plan,
        command="drop",
        backup_kind="pre-drop",
        database=database,
        databases=(database,),
        timestamp=timestamp,
        reason=reason,
    )
    planned_drop = planned_drop_database_command(runtime_plan, database)
    container = inspect_owned_postgres_container(runtime_plan, runner)
    existed = database_exists(runtime_plan, database, runner)
    if not existed:
        raise database_not_found(database)
    planned_actions = ("create-backup", "verify-backup", "drop-database")
    if dry_run:
        return LocalDbDropResult(
            command="drop",
            result="dry_run",
            repo_map_home=home,
            database=database,
            runtime_plan=runtime_plan,
            backup_plan=backup_plan,
            container=container,
            backup_first=True,
            confirmation_received=confirmed,
            dry_run=True,
            target_existed=True,
            planned_actions=planned_actions,
            planned_command=planned_drop,
        )

    backup_result = execute_backup_plan(
        backup_plan,
        database=database,
        command_runner=runner,
        container=container,
        scope="pre-drop-single-database",
    )
    verify_drop_backup(backup_result, database)
    drop_runtime_database(runtime_plan, database, planned_drop, runner)
    return LocalDbDropResult(
        command="drop",
        result="success",
        repo_map_home=home,
        database=database,
        runtime_plan=runtime_plan,
        backup_plan=backup_plan,
        backup_result=backup_result,
        container=container,
        backup_first=True,
        confirmation_received=True,
        dry_run=False,
        target_existed=True,
        checksum_verified=True,
        restore_note_verified=True,
        planned_actions=planned_actions,
        planned_command=planned_drop,
        database_dropped=True,
        destructive_db_actions=True,
    )


def validate_drop_database_name(database: str, plan: LocalRuntimePlan) -> None:
    validate_owned_database(database, plan)


__all__ = [
    "BACKUP_FORMAT_VERSION",
    "BackupDumpFile",
    "BackupInspectResult",
    "CommandRunner",
    "LocalDbBackupError",
    "LocalDbBackupPlan",
    "LocalDbBackupResult",
    "LocalDbDropResult",
    "LocalDbInitResult",
    "RuntimeContainerMetadata",
    "StorageSchemaError",
    "apply_source_schema",
    "atomic_private_backup_directory",
    "backup_first_required",
    "backup_root",
    "build_backup_plan",
    "cleanup_empty_backup_directory",
    "create_database",
    "database_already_exists",
    "database_exists",
    "database_not_found",
    "discover_migrations",
    "drop_confirmation_required",
    "drop_database",
    "drop_runtime_database",
    "dump_all_databases",
    "dump_database",
    "ensure_new_backup_directory",
    "execute_backup_plan",
    "format_backup_info_table",
    "format_backup_inspect_table",
    "format_backup_listing_table",
    "format_backup_result_table",
    "format_drop_result_table",
    "format_init_result_table",
    "graph_schema_initialization_sql",
    "init_database_from_dump",
    "init_database_from_source",
    "inspect_backup",
    "inspect_owned_postgres_container",
    "list_backups",
    "read_backup_info",
    "reconcile_graph_database_roles",
    "run_pg_dump",
    "run_pg_restore",
    "run_pg_restore_list",
    "subprocess",
    "validate_drop_database_name",
    "validate_owned_database",
]
