"""Container inspection and Postgres operations for local database backups."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Iterator, Sequence

from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    container_internal_enabled,
    decode_process_output,
    planned_psql_command,
    planned_psql_stdin_command,
    read_runtime_home_hash,
    read_runtime_password,
    run_container_command,
)
from repomap_kg.runtime.backup_records import (
    BackupDumpFile,
    LocalDbBackupError,
    RuntimeContainerMetadata,
)
from repomap_kg.runtime.backup_streaming import stream_pg_dump_to_file
from repomap_kg.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan
from repomap_kg.runtime.postgres_route import execution_postgres
from repomap_kg.storage import StorageSchemaError, graph_schema_initialization_sql


class _LazyPsycopg:
    def __getattr__(self, name: str) -> Any:
        import psycopg as _psycopg

        return getattr(_psycopg, name)


psycopg: Any = _LazyPsycopg()


def maintenance_window(connect_factory: Any, **kwargs: Any) -> Any:
    from repomap_kg.runtime.maintenance import maintenance_window as _mw

    return _mw(connect_factory, **kwargs)


def default_backup_runner() -> CommandRunner:
    """Return the subprocess runner for backup commands."""
    return subprocess.run


def _backup_err(code: str, field: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError((LocalRuntimeDiagnostic("error", code, field, message),))


@contextmanager
def acquire_or_reuse_backup_maintenance_window(
    plan: LocalRuntimePlan,
    databases: Sequence[str],
    *,
    command_runner: CommandRunner,
    require_window: bool = True,
) -> Iterator[str]:
    from repomap_kg.runtime.maintenance import (
        MaintenanceUnavailableError,
        bind_maintenance_custody,
        held_maintenance_custody_for,
        runtime_maintenance_namespace,
    )

    _ = command_runner
    target_set = {str(db) for db in databases if str(db)}
    control_dbs = tuple(db for db in plan.owned_databases if db not in plan.graph_databases)
    control_db = control_dbs[0] if control_dbs else None
    if control_db is not None:
        ordered_dbs = (control_db, *sorted(target_set - {control_db}))
        ctrl_name: str | None = control_db
    else:
        ordered_dbs = tuple(sorted(target_set))
        ctrl_name = None

    try:
        endpoint = execution_postgres(load_ops_config_home(plan.repo_map_home))
    except Exception as error:
        raise _backup_err(
            "backup-maintenance-window-unavailable",
            ",".join(ordered_dbs),
            "could not resolve Postgres endpoint for maintenance window",
        ) from error
    namespace = runtime_maintenance_namespace(
        plan.repo_map_home, host=endpoint.host, port=endpoint.port
    )

    existing_custody = held_maintenance_custody_for(
        *ordered_dbs, authority_namespace=namespace
    )
    if existing_custody is not None and (
        ctrl_name is None or existing_custody.control_database == ctrl_name
    ):
        with bind_maintenance_custody(
            mode="reused-outer-maintenance-window",
            control_database=existing_custody.control_database,
            databases=existing_custody.databases,
            authority_namespace=namespace,
        ):
            yield namespace
        return
    if not require_window:
        yield namespace
        return

    password = read_runtime_password(plan.env_file)
    opts = "-c lock_timeout=30000 -c statement_timeout=30000"
    with ExitStack() as stack:
        try:
            with psycopg.connect(
                host=endpoint.host, port=endpoint.port, user=plan.user,
                dbname="postgres", password=password, connect_timeout=10, options=opts,
            ) as probe:
                rows = probe.execute(
                    "SELECT datname FROM pg_database WHERE datname = ANY(%s)",
                    (list(ordered_dbs),),
                ).fetchall()
            existing = {str(r[0]) for r in rows}
            if not target_set.issubset(existing):
                raise _backup_err(
                    "backup-maintenance-window-unavailable",
                    ",".join(sorted(target_set - existing)),
                    "target database does not exist for maintenance window acquisition",
                )
            lock_targets = tuple(db for db in ordered_dbs if db in existing)
            for db_name in lock_targets:
                stack.enter_context(
                    maintenance_window(
                        lambda db=db_name: psycopg.connect(
                            host=endpoint.host, port=endpoint.port, user=plan.user,
                            dbname=db, password=password, connect_timeout=10, options=opts,
                        )
                    )
                )
        except (psycopg.Error, MaintenanceUnavailableError) as error:
            raise _backup_err(
                "backup-maintenance-window-unavailable",
                ",".join(ordered_dbs),
                "could not acquire advisory maintenance window",
            ) from error
        with bind_maintenance_custody(
            mode="direct-advisory-lock-window",
            control_database=ctrl_name if ctrl_name in existing else None,
            databases=lock_targets,
            authority_namespace=namespace,
        ):
            yield namespace


def inspect_owned_postgres_container(
    plan: LocalRuntimePlan,
    command_runner: CommandRunner,
) -> RuntimeContainerMetadata:
    if container_internal_enabled():
        runtime_hash = os.environ.get("REPOMAP_RUNTIME_HOME_HASH", "")
        rendered_hash = read_runtime_home_hash(plan.env_file)
        if rendered_hash is None or runtime_hash != rendered_hash:
            raise _backup_err(
                "runtime-container-ownership-mismatch",
                "container-internal",
                "container is not owned by this RepoMap runtime",
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
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
    )
    if result.returncode != 0:
        raise _backup_err(
            "runtime-container-unavailable",
            plan.identity.postgres_container,
            "RepoMap Postgres container is not available; run local up first",
        )
    try:
        item = json.loads(result.stdout or "[]")[0]
    except (IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise _backup_err(
            "runtime-container-inspect-error",
            plan.identity.postgres_container,
            "could not parse container inspection output",
        ) from error
    labels = item.get("Config", {}).get("Labels", {}) or {}
    for key, value in plan.identity.labels("postgres").items():
        if labels.get(key) != value:
            raise _backup_err(
                "runtime-container-ownership-mismatch",
                plan.identity.postgres_container,
                "target container is not RepoMap-owned for this REPOMAP_HOME",
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
        raise _backup_err(
            "backup-directory-exists",
            str(path),
            "backup directory already exists and will not be overwritten",
        )
    path.mkdir(parents=True)


def cleanup_empty_backup_directory(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def database_already_exists(database: str) -> LocalDbBackupError:
    return _backup_err(
        "database-already-exists",
        database,
        "target database already exists; replacement or restore-over-existing "
        "is not implemented and would require a future backup-first phase",
    )


def backup_first_required() -> LocalDbBackupError:
    return _backup_err(
        "backup-first-required",
        "backup_first",
        "database drop requires --backup-first; no backup bypass is available",
    )


def drop_confirmation_required() -> LocalDbBackupError:
    return _backup_err(
        "drop-confirmation-required",
        "yes",
        "non-dry-run database drop requires explicit confirmation",
    )


def database_not_found(database: str) -> LocalDbBackupError:
    return _backup_err(
        "database-not-found",
        database,
        "target database does not exist; drop did not run",
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
