"""Container inspection and Postgres operations for local database backups."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Sequence

from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    container_internal_enabled,
    decode_process_output,
    planned_psql_command,
    planned_psql_stdin_command,
    read_runtime_home_hash,
    run_container_command,
)
from repomap_kg.runtime.backup_records import (
    BackupDumpFile,
    LocalDbBackupError,
    RuntimeContainerMetadata,
)
from repomap_kg.runtime.backup_streaming import stream_pg_dump_to_file
from repomap_kg.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan
from repomap_kg.storage import StorageSchemaError, graph_schema_initialization_sql


def default_backup_runner() -> CommandRunner:
    """Return the subprocess runner for backup commands."""
    return subprocess.run


def inspect_owned_postgres_container(
    plan: LocalRuntimePlan,
    command_runner: CommandRunner,
) -> RuntimeContainerMetadata:
    if container_internal_enabled():
        runtime_hash = os.environ.get("REPOMAP_RUNTIME_HOME_HASH", "")
        rendered_hash = read_runtime_home_hash(plan.env_file)
        if rendered_hash is None or runtime_hash != rendered_hash:
            raise LocalDbBackupError(
                (
                    LocalRuntimeDiagnostic(
                        "error",
                        "runtime-container-ownership-mismatch",
                        "container-internal",
                        "container is not owned by this RepoMap runtime",
                    ),
                )
            )
        return RuntimeContainerMetadata(
            container_id="container-internal",
            name=f"repomap-postgres-{runtime_hash}",
            image=None,
            labels={
                "org.repomap.runtime": "true",
                "org.repomap.home_hash": runtime_hash,
                "org.repomap.component": "postgres",
            },
        )
    command = [plan.container_runtime, "inspect", plan.identity.postgres_container]
    result = command_runner(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "runtime-container-unavailable",
                    plan.identity.postgres_container,
                    "RepoMap Postgres container is not available; run local up first",
                ),
            )
        )
    try:
        inspected = json.loads(result.stdout or "[]")
        item = inspected[0]
    except (IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "runtime-container-inspect-error",
                    plan.identity.postgres_container,
                    "could not parse container inspection output",
                ),
            )
        ) from error
    labels = item.get("Config", {}).get("Labels", {}) or {}
    expected = plan.identity.labels("postgres")
    for key, value in expected.items():
        if labels.get(key) != value:
            raise LocalDbBackupError(
                (
                    LocalRuntimeDiagnostic(
                        "error",
                        "runtime-container-ownership-mismatch",
                        plan.identity.postgres_container,
                        "target container is not RepoMap-owned for this REPOMAP_HOME",
                    ),
                )
            )
    return RuntimeContainerMetadata(
        container_id=str(item.get("Id", "")),
        name=plan.identity.postgres_container,
        image=item.get("Config", {}).get("Image"),
        labels=labels,
    )


def run_pg_dump(
    plan: LocalRuntimePlan,
    command: Sequence[str],
    command_runner: CommandRunner,
    destination: Path,
) -> BackupDumpFile:
    return stream_pg_dump_to_file(plan, command, command_runner, destination)


def ensure_new_backup_directory(path: Path) -> None:
    if path.exists():
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "backup-directory-exists",
                    str(path),
                    "backup directory already exists and will not be overwritten",
                ),
            )
        )
    path.mkdir(parents=True)


def cleanup_empty_backup_directory(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def database_already_exists(database: str) -> LocalDbBackupError:
    return LocalDbBackupError(
        (
            LocalRuntimeDiagnostic(
                "error",
                "database-already-exists",
                database,
                (
                    "target database already exists; replacement or restore-over-existing "
                    "is not implemented and would require a future backup-first phase"
                ),
            ),
        )
    )


def backup_first_required() -> LocalDbBackupError:
    return LocalDbBackupError(
        (
            LocalRuntimeDiagnostic(
                "error",
                "backup-first-required",
                "backup_first",
                "database drop requires --backup-first; no backup bypass is available",
            ),
        )
    )


def drop_confirmation_required() -> LocalDbBackupError:
    return LocalDbBackupError(
        (
            LocalRuntimeDiagnostic(
                "error",
                "drop-confirmation-required",
                "yes",
                "non-dry-run database drop requires explicit confirmation",
            ),
        )
    )


def database_not_found(database: str) -> LocalDbBackupError:
    return LocalDbBackupError(
        (
            LocalRuntimeDiagnostic(
                "error",
                "database-not-found",
                database,
                "target database does not exist; drop did not run",
            ),
        )
    )


def database_exists(
    plan: LocalRuntimePlan,
    database: str,
    command_runner: CommandRunner,
) -> bool:
    sql = f"SELECT COUNT(*) FROM pg_database WHERE datname = '{database}';"
    result = run_container_command(
        plan,
        planned_psql_command(plan, "postgres", "-tAc", sql),
        command_runner,
        label="database existence check",
    )
    return decode_process_output(result.stdout).strip() not in ("", "0")


def create_database(
    plan: LocalRuntimePlan,
    database: str,
    command_runner: CommandRunner,
) -> None:
    sql = f'CREATE DATABASE "{database}";'
    run_container_command(
        plan,
        planned_psql_command(plan, "postgres", "-v", "ON_ERROR_STOP=1", "-c", sql),
        command_runner,
        label="database create",
    )


def apply_source_schema(
    plan: LocalRuntimePlan,
    database: str,
    command_runner: CommandRunner,
) -> None:
    sql_resolver = graph_schema_initialization_sql
    try:
        schema_sql = sql_resolver()
    except StorageSchemaError as error:
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "source-schema-unavailable",
                    "migrations",
                    str(error),
                ),
            )
        ) from error
    run_container_command(
        plan,
        planned_psql_stdin_command(plan, database),
        command_runner,
        label="source schema init",
        input_data=schema_sql.encode("utf-8"),
    )


def run_pg_restore(
    plan: LocalRuntimePlan,
    database: str,
    dump_path: Path,
    command: Sequence[str],
    command_runner: CommandRunner,
) -> None:
    with dump_path.open("rb") as input_stream:
        run_container_command(
            plan,
            command,
            command_runner,
            label="pg_restore",
            input_stream=input_stream,
        )


def drop_runtime_database(
    plan: LocalRuntimePlan,
    database: str,
    command: Sequence[str],
    command_runner: CommandRunner,
) -> None:
    run_container_command(
        plan,
        command,
        command_runner,
        label="database drop",
    )
