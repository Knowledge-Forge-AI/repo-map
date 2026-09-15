"""Command construction and process helpers for local DB backup lifecycle."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Callable, Sequence

from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import (
    LocalRuntimeDiagnostic,
    LocalRuntimePlan,
    redact_runtime_text,
)
from repomap_kg.runtime.release import PACKAGED_PG_RESTORE, PACKAGED_PSQL

BACKUP_ROOT_DIR = "backups"
CONTAINER_INTERNAL_MARKER = Path("/etc/repomap-release-container")
SAFE_DATABASE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,62}$")
RUNTIME_HOME_HASH_RE = re.compile(r"^[0-9a-f]{12}$")

CommandRunner = Callable[..., subprocess.CompletedProcess]


def validate_database_name(database: str) -> None:
    if not isinstance(database, str) or not SAFE_DATABASE_RE.match(database):
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "invalid-database-name",
                    "database",
                    "database name must be a safe PostgreSQL identifier",
                ),
            )
        )


def read_runtime_password(env_file: Path) -> str:
    if not env_file.is_file():
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "runtime-env-missing",
                    str(env_file),
                    "runtime env file is missing; run repomap-kg local setup",
                ),
            )
        )
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("POSTGRES_PASSWORD="):
            return line.split("=", 1)[1]
    raise LocalDbBackupError(
        (
            LocalRuntimeDiagnostic(
                "error",
                "runtime-password-missing",
                str(env_file),
                "runtime env file does not define POSTGRES_PASSWORD",
            ),
        )
    )


def read_runtime_home_hash(env_file: Path) -> str | None:
    """Read one unambiguous rendered runtime identity from the private env file."""

    if not env_file.is_file():
        return None
    values = [
        line.split("=", 1)[1]
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if line.startswith("REPOMAP_RUNTIME_HOME_HASH=")
    ]
    if len(values) != 1 or RUNTIME_HOME_HASH_RE.fullmatch(values[0]) is None:
        return None
    return values[0]


def run_container_command(
    plan: LocalRuntimePlan,
    command: Sequence[str],
    command_runner: CommandRunner,
    *,
    label: str,
    input_data: bytes | str | None = None,
    input_stream: BinaryIO | None = None,
):
    if input_data is not None and input_stream is not None:
        raise ValueError("input_data and input_stream are mutually exclusive")
    password = read_runtime_password(plan.env_file)
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    command_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": env,
        "check": False,
    }
    if input_stream is not None:
        command_kwargs["stdin"] = input_stream
    elif input_data is not None:
        command_kwargs["input"] = input_data
    result = command_runner(list(command), **command_kwargs)
    if result.returncode != 0:
        stderr = decode_process_output(result.stderr)
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "local-db-command-failed",
                    label,
                    redact_runtime_text(stderr or f"{label} failed"),
                ),
            )
        )
    return result


def planned_psql_command(
    plan: LocalRuntimePlan,
    database: str,
    *psql_args: str,
) -> tuple[str, ...]:
    if container_internal_enabled():
        return (
            PACKAGED_PSQL,
            *_internal_connection_args(plan),
            "-U",
            plan.user,
            "-d",
            database,
            *psql_args,
        )
    return (
        plan.container_runtime,
        "exec",
        "-e",
        "PGPASSWORD",
        plan.identity.postgres_container,
        PACKAGED_PSQL,
        "-U",
        plan.user,
        "-d",
        database,
        *psql_args,
    )


def planned_psql_stdin_command(plan: LocalRuntimePlan, database: str) -> tuple[str, ...]:
    if container_internal_enabled():
        return (
            PACKAGED_PSQL,
            *_internal_connection_args(plan),
            "-U",
            plan.user,
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
        )
    return (
        plan.container_runtime,
        "exec",
        "-i",
        "-e",
        "PGPASSWORD",
        plan.identity.postgres_container,
        PACKAGED_PSQL,
        "-U",
        plan.user,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
    )


def planned_create_database_command(plan: LocalRuntimePlan) -> tuple[str, ...]:
    return planned_psql_command(
        plan,
        plan.maintenance_database,
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        "CREATE DATABASE <database>",
    )


def planned_pg_restore_command(plan: LocalRuntimePlan, database: str) -> tuple[str, ...]:
    if container_internal_enabled():
        return (
            PACKAGED_PG_RESTORE,
            *_internal_connection_args(plan),
            "-U",
            plan.user,
            "-d",
            database,
            "--no-owner",
            "--no-privileges",
        )
    return (
        plan.container_runtime,
        "exec",
        "-i",
        "-e",
        "PGPASSWORD",
        plan.identity.postgres_container,
        PACKAGED_PG_RESTORE,
        "-U",
        plan.user,
        "-d",
        database,
        "--no-owner",
        "--no-privileges",
    )


def planned_pg_restore_list_command(plan: LocalRuntimePlan) -> tuple[str, ...]:
    if container_internal_enabled():
        return (PACKAGED_PG_RESTORE, "-l")
    return (
        plan.container_runtime,
        "exec",
        "-i",
        "-e",
        "PGPASSWORD",
        plan.identity.postgres_container,
        PACKAGED_PG_RESTORE,
        "-l",
    )


def planned_drop_database_command(plan: LocalRuntimePlan, database: str) -> tuple[str, ...]:
    quoted = quote_sql_identifier(database)
    terminate_sql = (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{database}' AND pid <> pg_backend_pid();"
    )
    return planned_psql_command(
        plan,
        plan.maintenance_database,
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        terminate_sql,
        "-c",
        f"DROP DATABASE {quoted};",
    )


def quote_sql_identifier(identifier: str) -> str:
    validate_database_name(identifier)
    return '"' + identifier.replace('"', '""') + '"'


def backup_root(repo_map_home: Path) -> Path:
    admin_root = os.environ.get("REPOMAP_ADMIN_ROOT")
    authority_root = (
        Path(admin_root)
        if admin_root and container_internal_enabled()
        else repo_map_home
    )
    return authority_root / BACKUP_ROOT_DIR


def container_internal_enabled() -> bool:
    return (
        os.environ.get("REPOMAP_CONTAINER_INTERNAL") == "1"
        and CONTAINER_INTERNAL_MARKER.is_file()
    )


def _internal_connection_args(plan: LocalRuntimePlan) -> tuple[str, ...]:
    host = plan.config.postgres.host if plan.config is not None else "postgres"
    port = plan.config.postgres.port if plan.config is not None else 5432
    return ("-h", host, "-p", str(port))


def timestamp_utc() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def safe_timestamp(value: str) -> None:
    if not re.match(r"^[0-9]{8}T[0-9]{6}Z$", value):
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "invalid-backup-timestamp",
                    "timestamp",
                    "backup timestamp must use YYYYMMDDTHHMMSSZ",
                ),
            )
        )


def decode_process_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def decode_process_bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    if isinstance(value, str):
        return value.encode("utf-8")
    return value
