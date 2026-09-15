"""Ledger and migration execution helpers for schema upgrade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    decode_process_output,
    planned_psql_command,
    planned_psql_stdin_command,
    run_container_command as _default_run_container_command,
    validate_database_name,
)
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import (
    LocalRuntimeDiagnostic,
    LocalRuntimePlan,
)
from repomap_kg.storage import (
    StorageSchemaError,
    graph_schema_forward_sql as _default_graph_schema_forward_sql,
    graph_schema_ledger_bootstrap_sql as _default_graph_schema_ledger_bootstrap_sql,
)


@dataclass(frozen=True)
class GraphSchemaUpgradeResult:
    result: str
    schema_before: str
    schema_after: str
    backup_id: str | None = None
    backup_verified: bool = False
    rollback_available: bool = False
    reference_cleaned: bool = False
    planned_actions: tuple[str, ...] = ()

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "command": "upgrade-schema",
            "result": self.result,
            "schema_before": self.schema_before,
            "schema_after": self.schema_after,
            "backup_id": self.backup_id,
            "backup_verified": self.backup_verified,
            "rollback_available": self.rollback_available,
            "reference_cleaned": self.reference_cleaned,
            "planned_actions": list(self.planned_actions),
            "destructive_db_actions": False,
            "direct_db_required": False,
        }


def format_graph_schema_upgrade_table(result: GraphSchemaUpgradeResult) -> str:
    payload = result.to_jsonable()
    lines = [
        f"RepoMap graph schema upgrade: result={payload['result']}",
        f"schema_before={payload['schema_before']}",
        f"schema_after={payload['schema_after']}",
        f"backup_id={payload['backup_id']}",
        (
            "safety: "
            f"backup_verified={str(payload['backup_verified']).lower()} "
            f"rollback_available={str(payload['rollback_available']).lower()} "
            f"reference_cleaned={str(payload['reference_cleaned']).lower()} "
            f"destructive_db_actions={str(payload['destructive_db_actions']).lower()}"
        ),
    ]
    if payload["planned_actions"]:
        lines.append("planned_actions=" + ",".join(payload["planned_actions"]))
    return "\n".join(lines)


def _upgrade_error(code: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError(
        (LocalRuntimeDiagnostic("error", code, "schema-upgrade", message),)
    )


def _reference_database_name(timestamp: str) -> str:
    compact = timestamp.replace("T", "_").removesuffix("Z")
    reference = f"repomap_schema_ref_{compact}"
    validate_database_name(reference)
    return reference


def apply_forward_schema(
    plan: LocalRuntimePlan,
    database: str,
    applied_count: int,
    command_runner: CommandRunner,
    *,
    target_count: int | None = None,
) -> None:
    """Apply the authoritative pending migration suffix transactionally."""
    forward_sql_fn = _default_graph_schema_forward_sql
    runner_fn = _default_run_container_command
    try:
        sql = forward_sql_fn(
            applied_count,
            target_count=target_count,
        )
    except StorageSchemaError as error:
        raise _upgrade_error("source-schema-unavailable", str(error)) from error
    runner_fn(
        plan,
        planned_psql_stdin_command(plan, database),
        command_runner,
        label="graph schema forward migration",
        input_data=sql.encode("utf-8"),
    )


def schema_ledger_exists(
    plan: LocalRuntimePlan,
    database: str,
    command_runner: CommandRunner,
) -> bool:
    runner_fn = _default_run_container_command
    sql = "SELECT to_regclass('public.repomap_schema_migrations') IS NOT NULL;"
    result = runner_fn(
        plan,
        planned_psql_command(plan, database, "-X", "-tAc", sql),
        command_runner,
        label="schema ledger presence",
    )
    return decode_process_output(result.stdout).strip() == "t"


def bootstrap_schema_ledger(
    plan: LocalRuntimePlan,
    database: str,
    command_runner: CommandRunner,
) -> None:
    bootstrap_sql_fn = _default_graph_schema_ledger_bootstrap_sql
    runner_fn = _default_run_container_command
    try:
        sql = bootstrap_sql_fn()
    except StorageSchemaError as error:
        raise _upgrade_error("source-schema-unavailable", str(error)) from error
    runner_fn(
        plan,
        planned_psql_stdin_command(plan, database),
        command_runner,
        label="schema ledger bootstrap",
        input_data=sql.encode("utf-8"),
    )


def query_schema_ledger(
    plan: LocalRuntimePlan,
    database: str,
    command_runner: CommandRunner,
) -> tuple[tuple[int, str, str, str], ...]:
    runner_fn = _default_run_container_command
    sql = (
        "SELECT ordinal, changeset_id, migration_path, checksum "
        "FROM repomap_schema_migrations ORDER BY ordinal;"
    )
    result = runner_fn(
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
            sql,
        ),
        command_runner,
        label="schema ledger verification",
    )
    rows = []
    for line in decode_process_output(result.stdout).splitlines():
        fields = line.split("\t")
        if len(fields) != 4 or not fields[0].isdigit():
            raise _upgrade_error(
                "invalid-schema-ledger",
                "graph schema ledger returned an invalid row",
            )
        rows.append((int(fields[0]), fields[1], fields[2], fields[3]))
    return tuple(rows)
