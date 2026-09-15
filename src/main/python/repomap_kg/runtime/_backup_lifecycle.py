"""Database initialization and backup plan execution."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from repomap_kg.ops.config import resolve_repo_map_home
from repomap_kg.runtime._backup_operations import (
    apply_source_schema,
    create_database,
    database_already_exists,
    database_exists,
    default_backup_runner,
    inspect_owned_postgres_container,
    run_pg_dump,
    run_pg_restore,
)
from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    backup_root,
    container_internal_enabled,
    planned_create_database_command,
    planned_pg_restore_command,
    safe_timestamp,
    timestamp_utc,
    validate_database_name,
)
from repomap_kg.runtime.backup_manifests import (
    bounded_text,
    optional_manifest_text,
    read_manifest_file,
    resolve_backup_manifest_path,
    select_dump_file_for_database,
    verify_dump_file_checksum,
    write_manifest_and_restore_docs,
)
from repomap_kg.runtime.backup_records import (
    LocalDbBackupError,
    LocalDbBackupPlan,
    LocalDbBackupResult,
    LocalDbInitResult,
    RuntimeContainerMetadata,
)
from repomap_kg.runtime.backup_streaming import atomic_private_backup_directory
from repomap_kg.runtime.database_roles import reconcile_graph_database_roles
from repomap_kg.runtime.local import (
    LocalRuntimeDiagnostic,
    LocalRuntimePlan,
    build_local_runtime_plan,
)
from repomap_kg.runtime.provisioning import complete_graph_provision


def validate_owned_database(
    database: str,
    plan: LocalRuntimePlan,
    *,
    graph_only: bool = False,
) -> None:
    """Require one exact configured graph or graph/control lifecycle target."""

    allowed = plan.graph_databases if graph_only else plan.owned_databases
    if database in allowed:
        return
    raise LocalDbBackupError(
        (
            LocalRuntimeDiagnostic(
                "error",
                "database-not-owned",
                "database",
                "database is not an authorized RepoMap lifecycle target",
            ),
        )
    )


def init_database_from_source(
    repo_map_home: str | Path | None,
    *,
    database: str,
    dry_run: bool = False,
    command_runner: CommandRunner | None = None,
) -> LocalDbInitResult:
    validate_database_name(database)
    runner = command_runner or default_backup_runner()
    home = resolve_repo_map_home(repo_map_home)
    runtime_plan = build_local_runtime_plan(home)
    validate_owned_database(database, runtime_plan, graph_only=True)
    inspect_fn = inspect_owned_postgres_container
    container = inspect_fn(runtime_plan, runner)
    exists_fn = database_exists
    existed = exists_fn(runtime_plan, database, runner)
    if existed:
        raise database_already_exists(database)
    planned = planned_create_database_command(runtime_plan)
    if dry_run:
        return LocalDbInitResult(
            command="init",
            result="dry_run",
            repo_map_home=home,
            database=database,
            source_mode="source",
            runtime_plan=runtime_plan,
            container=container,
            target_existed=False,
            planned_actions=("create-database", "apply-source-schema"),
            planned_command=planned,
        )
    create_fn = create_database
    create_fn(runtime_plan, database, runner)

    schema_fn = apply_source_schema
    roles_fn = reconcile_graph_database_roles

    def provision_from_source() -> None:
        schema_fn(runtime_plan, database, runner)
        roles_fn(runtime_plan, database, runner)

    complete_graph_provision(
        runtime_plan,
        database,
        runner,
        provision_from_source,
    )
    return LocalDbInitResult(
        command="init",
        result="success",
        repo_map_home=home,
        database=database,
        source_mode="source",
        runtime_plan=runtime_plan,
        container=container,
        target_existed=False,
        planned_actions=("create-database", "apply-source-schema"),
        planned_command=planned,
        database_created=True,
        schema_initialized=True,
        schema_ready=True,
    )


def init_database_from_dump(
    repo_map_home: str | Path | None,
    *,
    database: str,
    backup: str | Path,
    dry_run: bool = False,
    command_runner: CommandRunner | None = None,
) -> LocalDbInitResult:
    validate_database_name(database)
    runner = command_runner or default_backup_runner()
    home = resolve_repo_map_home(repo_map_home)
    runtime_plan = build_local_runtime_plan(home)
    validate_owned_database(database, runtime_plan, graph_only=True)
    backups_root = backup_root(home)
    manifest_path = resolve_backup_manifest_path(backups_root, backup)
    manifest = read_manifest_file(manifest_path)
    dump_file = select_dump_file_for_database(manifest, database)
    dump_path = manifest_path.parent / dump_file["name"]
    verify_dump_file_checksum(dump_path, dump_file)
    inspect_fn = inspect_owned_postgres_container
    container = inspect_fn(runtime_plan, runner)
    exists_fn = database_exists
    existed = exists_fn(runtime_plan, database, runner)
    if existed:
        raise database_already_exists(database)
    planned = planned_pg_restore_command(runtime_plan, database)
    if dry_run:
        return LocalDbInitResult(
            command="init",
            result="dry_run",
            repo_map_home=home,
            database=database,
            source_mode="dump",
            runtime_plan=runtime_plan,
            container=container,
            backup_id=optional_manifest_text(manifest.get("backup_id")),
            backup_path=manifest_path.parent,
            manifest_path=manifest_path,
            dump_file=dump_file["name"],
            dump_path=dump_path,
            checksum_verified=True,
            target_existed=False,
            planned_actions=("create-database", "restore-dump"),
            planned_command=planned,
        )
    create_fn = create_database
    create_fn(runtime_plan, database, runner)

    restore_fn = run_pg_restore
    roles_fn = reconcile_graph_database_roles

    def provision_from_dump() -> None:
        restore_fn(runtime_plan, database, dump_path, planned, runner)
        roles_fn(runtime_plan, database, runner)

    complete_graph_provision(
        runtime_plan,
        database,
        runner,
        provision_from_dump,
    )
    return LocalDbInitResult(
        command="init",
        result="success",
        repo_map_home=home,
        database=database,
        source_mode="dump",
        runtime_plan=runtime_plan,
        container=container,
        backup_id=optional_manifest_text(manifest.get("backup_id")),
        backup_path=manifest_path.parent,
        manifest_path=manifest_path,
        dump_file=dump_file["name"],
        dump_path=dump_path,
        checksum_verified=True,
        target_existed=False,
        planned_actions=("create-database", "restore-dump"),
        planned_command=planned,
        database_created=True,
        dump_restored=True,
        schema_ready=True,
    )


def build_backup_plan(
    runtime_plan: LocalRuntimePlan,
    *,
    command: str,
    backup_kind: str,
    database: str | None,
    databases: tuple[str, ...],
    timestamp: str | None,
    reason: str | None,
) -> LocalDbBackupPlan:
    stamp = timestamp or timestamp_utc()
    safe_timestamp(stamp)
    runtime_id = runtime_plan.identity.home_hash
    if database:
        backup_id = f"{runtime_id}--{database}--{stamp}"
        path = backup_root(runtime_plan.repo_map_home) / runtime_id / database / stamp
    else:
        backup_id = f"{runtime_id}--all-databases--{stamp}"
        path = backup_root(runtime_plan.repo_map_home) / runtime_id / "all-databases" / stamp
    return LocalDbBackupPlan(
        command=command,
        plan=runtime_plan,
        backup_kind=backup_kind,
        timestamp=stamp,
        database=database,
        databases=databases,
        backup_id=backup_id,
        backup_path=path,
        dump_format="pgcustom",
        reason=bounded_text(reason) if reason else None,
        container_internal=container_internal_enabled(),
    )


def execute_backup_plan(
    backup_plan: LocalDbBackupPlan,
    *,
    database: str,
    command_runner: CommandRunner,
    container: RuntimeContainerMetadata,
    scope: str,
) -> LocalDbBackupResult:
    planned_command = backup_plan.planned_dump_command(database)
    with atomic_private_backup_directory(
        backup_plan.backup_path,
        backups_root=backup_root(backup_plan.plan.repo_map_home),
    ) as staging_path:
        staging_plan = replace(backup_plan, backup_path=staging_path)
        dump_file = run_pg_dump(
            backup_plan.plan,
            planned_command,
            command_runner,
            staging_path / "dump.pgcustom",
        )
        write_manifest_and_restore_docs(
            staging_plan,
            dump_files=(dump_file,),
            container=container,
            command_invoked=planned_command,
            scope=scope,
        )
    return LocalDbBackupResult(
        command=backup_plan.command,
        result="success",
        plan=backup_plan,
        dump_files=(dump_file,),
        container=container,
        planned_command=planned_command,
        backup_path_created=True,
        dump_executed=True,
    )
