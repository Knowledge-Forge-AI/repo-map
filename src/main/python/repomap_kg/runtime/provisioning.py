"""Deterministic readiness and failed-target cleanup for fresh graph provision."""

from __future__ import annotations

from collections.abc import Callable

from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    decode_process_output,
    planned_drop_database_command,
    planned_psql_command,
    run_container_command,
)
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan
from repomap_kg.storage import discover_migrations


def complete_graph_provision(
    plan: LocalRuntimePlan,
    database: str,
    command_runner: CommandRunner,
    provision: Callable[[], None],
) -> None:
    """Provision and verify a target created by the current invocation."""

    try:
        provision()
        require_graph_schema_ready(plan, database, command_runner)
    except Exception:
        try:
            cleanup_created_database(plan, database, command_runner)
        except LocalDbBackupError as cleanup_error:
            raise _provision_error(
                "failed-target-cleanup-failed",
                "provisioning failed and the created target could not be removed",
            ) from cleanup_error
        raise


def require_graph_schema_ready(
    plan: LocalRuntimePlan,
    database: str,
    command_runner: CommandRunner,
) -> None:
    """Require the exact ordered checksummed graph migration ledger."""

    presence_sql = (
        "SELECT to_regclass('public.repomap_schema_migrations') IS NOT NULL;"
    )
    presence = run_container_command(
        plan,
        planned_psql_command(plan, database, "-X", "-tAc", presence_sql),
        command_runner,
        label="graph schema readiness",
    )
    if decode_process_output(presence.stdout).strip() != "t":
        raise _provision_error(
            "graph-schema-not-ready",
            "provisioned graph schema is not exact-current",
        )

    ledger_sql = (
        "SELECT ordinal, changeset_id, migration_path, checksum "
        "FROM repomap_schema_migrations ORDER BY ordinal;"
    )
    result = run_container_command(
        plan,
        planned_psql_command(
            plan,
            database,
            "-X",
            "-A",
            "-t",
            "-F",
            "\t",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            ledger_sql,
        ),
        command_runner,
        label="graph schema readiness",
    )
    applied = tuple(
        tuple(line.split("\t"))
        for line in decode_process_output(result.stdout).splitlines()
        if line
    )
    expected = tuple(
        (
            str(migration.ordinal),
            migration.changeset_id,
            migration.relative_path,
            migration.checksum,
        )
        for migration in discover_migrations()
    )
    if applied != expected:
        raise _provision_error(
            "graph-schema-not-ready",
            "provisioned graph schema is not exact-current",
        )


def cleanup_created_database(
    plan: LocalRuntimePlan,
    database: str,
    command_runner: CommandRunner,
) -> None:
    """Remove only the target created by the current provisioning invocation."""

    run_container_command(
        plan,
        planned_drop_database_command(plan, database),
        command_runner,
        label="failed target cleanup",
    )


def _provision_error(code: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError(
        (LocalRuntimeDiagnostic("error", code, "provisioning", message),)
    )


__all__ = [
    "cleanup_created_database",
    "complete_graph_provision",
    "require_graph_schema_ready",
]
