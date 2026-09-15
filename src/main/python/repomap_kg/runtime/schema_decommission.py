"""Compatibility sequencing for destructive graph-schema migrations."""

from __future__ import annotations

from typing import Any

from repomap_kg.runtime.backup_commands import CommandRunner
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import LocalRuntimeDiagnostic, LocalRuntimePlan
from repomap_kg.runtime.repository_identity_migration import (
    apply_repository_identity_reconciliation,
    query_repository_identity_state,
)


REPOSITORY_IDENTITY_MIGRATION_PATH = (
    "2026/07/16-001-arch5c-add-repository-identity.sql"
)
LEGACY_SCHEMA_REMOVAL_MIGRATION_PATH = (
    "2026/07/16-002-arch5d-drop-legacy-graph-schema.sql"
)


def migration_ordinal(
    migrations: tuple[Any, ...],
    relative_path: str,
) -> int | None:
    """Return one migration ordinal without assuming it is the latest."""

    return next(
        (
            migration.ordinal
            for migration in migrations
            if migration.relative_path == relative_path
        ),
        None,
    )


def reconcile_repository_identity_before_removal(
    plan: LocalRuntimePlan,
    database: str,
    identity_target: tuple[str, str, str],
    command_runner: CommandRunner,
) -> None:
    """Make configured repository ownership stable before legacy-table DDL."""

    identity_state = query_repository_identity_state(
        plan,
        database,
        identity_target[0],
        identity_target[2],
        command_runner,
    )
    if identity_state.other_identity_rows or (
        identity_state.total_repositories > 0 and not identity_state.reconcilable
    ):
        raise _decommission_error(
            "diverged-repository-identity",
            "target database repository identity is diverged",
        )
    if identity_state.stable or identity_state.total_repositories == 0:
        return
    apply_repository_identity_reconciliation(
        plan,
        database,
        identity_target[0],
        identity_target[1],
        identity_target[2],
        command_runner,
    )
    migrated_state = query_repository_identity_state(
        plan,
        database,
        identity_target[0],
        identity_target[2],
        command_runner,
    )
    if not migrated_state.stable:
        raise _decommission_error(
            "repository-identity-verification-failed",
            "repository identity is not stable after reconciliation",
        )


def _decommission_error(code: str, message: str) -> LocalDbBackupError:
    return LocalDbBackupError(
        (LocalRuntimeDiagnostic("error", code, "schema-upgrade", message),)
    )
