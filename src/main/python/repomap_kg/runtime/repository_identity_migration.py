"""Configured repository identity migration support."""

from __future__ import annotations

from dataclasses import dataclass

from repomap_kg.ops.resolved_config import resolve_ops_config
from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    decode_process_output,
    planned_psql_stdin_command,
    run_container_command,
)
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan
from repomap_kg.storage import (
    StorageSchemaError,
    repository_identity_reconciliation_sql,
    repository_identity_state_sql,
)


@dataclass(frozen=True)
class RepositoryIdentityState:
    total_repositories: int
    expected_identity_rows: int
    other_identity_rows: int
    current_root_rows: int

    @property
    def stable(self) -> bool:
        return (
            self.total_repositories == 1
            and self.expected_identity_rows == 1
            and self.other_identity_rows == 0
            and self.current_root_rows == 1
        )

    @property
    def reconcilable(self) -> bool:
        return (
            self.total_repositories > 0
            and self.expected_identity_rows <= 1
            and self.other_identity_rows == 0
        )


def query_repository_identity_state(
    plan: LocalRuntimePlan,
    database: str,
    repository_identity: str,
    root_path: str,
    command_runner: CommandRunner,
) -> RepositoryIdentityState:
    try:
        sql = repository_identity_state_sql(repository_identity, root_path)
    except StorageSchemaError as error:
        raise _identity_error("repository-identity-invalid", str(error)) from error
    result = run_container_command(
        plan,
        (
            *planned_psql_stdin_command(plan, database),
            "-X",
            "-A",
            "-t",
            "-F",
            "\t",
        ),
        command_runner,
        label="repository identity state",
        input_data=sql.encode("utf-8"),
    )
    lines = [
        line
        for line in decode_process_output(result.stdout).splitlines()
        if line.strip()
    ]
    fields = lines[-1].split("\t") if lines else []
    if len(fields) != 4 or any(not field.isdigit() for field in fields):
        raise _identity_error(
            "invalid-repository-identity-state",
            "repository identity state returned an invalid row",
        )
    return RepositoryIdentityState(*(int(field) for field in fields))


def apply_repository_identity_reconciliation(
    plan: LocalRuntimePlan,
    database: str,
    repository_identity: str,
    repository_name: str,
    root_path: str,
    command_runner: CommandRunner,
) -> None:
    try:
        sql = repository_identity_reconciliation_sql(
            repository_identity,
            repository_name,
            root_path,
        )
    except StorageSchemaError as error:
        raise _identity_error("repository-identity-invalid", str(error)) from error
    run_container_command(
        plan,
        planned_psql_stdin_command(plan, database),
        command_runner,
        label="repository identity reconciliation",
        input_data=sql.encode("utf-8"),
    )


def _repository_identity_target(
    plan: LocalRuntimePlan,
    database: str,
) -> tuple[str, str, str] | None:
    if plan.config is None:
        return None
    resolved = resolve_ops_config(plan.config)
    matches = tuple(
        graph for graph in resolved.graphs if str(graph.database) == database
    )
    if len(matches) != 1:
        return None
    graph = matches[0]
    return (
        str(graph.repository_identity),
        graph.source.repository_name,
        graph.source.root_path_expanded,
    )


def _identity_error(code: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError(
        (LocalRuntimeDiagnostic("error", code, "schema-upgrade", message),)
    )
