"""Backup-first schema adoption for RepoMap-owned graph databases."""

from __future__ import annotations

import subprocess
from pathlib import Path

from repomap_kg.ops.config import resolve_repo_map_home
from repomap_kg.runtime._schema_upgrade_ledger import (
    GraphSchemaUpgradeResult as GraphSchemaUpgradeResult,
    _reference_database_name,
    _upgrade_error,
    apply_forward_schema as apply_forward_schema,
    bootstrap_schema_ledger as bootstrap_schema_ledger,
    format_graph_schema_upgrade_table as format_graph_schema_upgrade_table,
    query_schema_ledger as query_schema_ledger,
    schema_ledger_exists as schema_ledger_exists,
)
from repomap_kg.runtime.backup import (
    apply_source_schema as apply_source_schema,
    create_database as create_database,
    database_exists as database_exists,
    drop_runtime_database as drop_runtime_database,
    dump_database as dump_database,
    inspect_backup as inspect_backup,
    inspect_owned_postgres_container as inspect_owned_postgres_container,
    validate_owned_database,
)
from repomap_kg.runtime.backup_commands import (
    CommandRunner,
    planned_drop_database_command,
    run_container_command as run_container_command,
    timestamp_utc,
    validate_database_name,
)
from repomap_kg.runtime.database_roles import (
    reconcile_graph_database_roles as reconcile_graph_database_roles,
)
from repomap_kg.runtime.local import build_local_runtime_plan
from repomap_kg.runtime.repository_identity_migration import (
    RepositoryIdentityState as RepositoryIdentityState,
    _repository_identity_target as _repository_identity_target,
    apply_repository_identity_reconciliation,
    query_repository_identity_state,
)
from repomap_kg.runtime.schema_decommission import (
    LEGACY_SCHEMA_REMOVAL_MIGRATION_PATH,
    REPOSITORY_IDENTITY_MIGRATION_PATH,
    migration_ordinal,
    reconcile_repository_identity_before_removal,
)
from repomap_kg.runtime.schema_manifest import (
    query_schema_manifest as query_schema_manifest,
)
from repomap_kg.storage import (
    StorageSchemaError,
    discover_migrations,
    graph_schema_forward_sql,
    graph_schema_ledger_bootstrap_sql,
)

# Re-export storage symbols for tests patching repomap_kg.runtime.schema_upgrade
__all__ = [
    "GraphSchemaUpgradeResult",
    "RepositoryIdentityState",
    "apply_forward_schema",
    "apply_repository_identity_reconciliation",
    "apply_source_schema",
    "bootstrap_schema_ledger",
    "create_database",
    "database_exists",
    "discover_migrations",
    "drop_runtime_database",
    "dump_database",
    "format_graph_schema_upgrade_table",
    "graph_schema_forward_sql",
    "graph_schema_ledger_bootstrap_sql",
    "inspect_backup",
    "inspect_owned_postgres_container",
    "query_repository_identity_state",
    "query_schema_ledger",
    "query_schema_manifest",
    "reconcile_graph_database_roles",
    "run_container_command",
    "schema_ledger_exists",
    "upgrade_graph_schema",
]


def upgrade_graph_schema(
    repo_map_home: str | Path | None,
    *,
    database: str,
    backup_first: bool = False,
    confirmed: bool = False,
    dry_run: bool = False,
    reason: str | None = None,
    timestamp: str | None = None,
    command_runner: CommandRunner | None = None,
) -> GraphSchemaUpgradeResult:
    """Advance one recognized graph schema after a verified backup."""

    validate_database_name(database)
    if not backup_first:
        raise _upgrade_error(
            "backup-first-required",
            "schema upgrade requires --backup-first",
        )
    if not dry_run and not confirmed:
        raise _upgrade_error(
            "upgrade-confirmation-required",
            "schema upgrade confirmation requires --yes",
        )
    runner = command_runner or subprocess.run
    home = resolve_repo_map_home(repo_map_home)
    plan = build_local_runtime_plan(home)
    validate_owned_database(database, plan, graph_only=True)
    actions = (
        "inspect-target",
        "classify-schema-ledger",
        "create-and-inspect-backup",
        "create-reference-database",
        "compare-schema-manifest",
        "apply-pending-migrations",
        "bootstrap-schema-ledger",
        "reconcile-repository-identity",
        "reconcile-database-roles",
        "verify-schema-ledger",
        "drop-reference-database",
    )
    if dry_run:
        return GraphSchemaUpgradeResult(
            result="dry_run",
            schema_before="unknown",
            schema_after="planned",
            planned_actions=actions,
        )

    inspect_owned_postgres_container(plan, runner)
    if not database_exists(plan, database, runner):
        raise _upgrade_error("database-not-found", "target database does not exist")

    try:
        migrations = discover_migrations()
        expected_ledger = tuple(
            (
                migration.ordinal,
                migration.changeset_id,
                migration.relative_path,
                migration.checksum,
            )
            for migration in migrations
        )
    except StorageSchemaError as error:
        raise _upgrade_error("source-schema-unavailable", str(error)) from error

    managed = schema_ledger_exists(plan, database, runner)
    applied_ledger: tuple[tuple[int, str, str, str], ...] = ()
    identity_target: tuple[str, str, str] | None = None
    identity_migration_needed = False
    if managed:
        applied_ledger = query_schema_ledger(plan, database, runner)
        if applied_ledger == expected_ledger:
            identity_target = _repository_identity_target(plan, database)
            if identity_target is None:
                raise _upgrade_error(
                    "schema-already-current",
                    "target database graph schema is exact-current",
                )
            identity_state = query_repository_identity_state(
                plan,
                database,
                identity_target[0],
                identity_target[2],
                runner,
            )
            if identity_state.other_identity_rows:
                raise _upgrade_error(
                    "diverged-repository-identity",
                    "target database repository identity is diverged",
                )
            if identity_state.stable or identity_state.total_repositories == 0:
                raise _upgrade_error(
                    "schema-already-current",
                    "target database graph schema and repository identity are exact-current",
                )
            if not identity_state.reconcilable:
                raise _upgrade_error(
                    "diverged-repository-identity",
                    "target database repository identity is diverged",
                )
            identity_migration_needed = True
        if (
            applied_ledger != expected_ledger
            and (
                not applied_ledger
                or len(applied_ledger) >= len(expected_ledger)
                or applied_ledger != expected_ledger[: len(applied_ledger)]
            )
        ):
            raise _upgrade_error(
                "diverged-schema-ledger",
                "target database graph schema ledger is diverged",
            )

    upgrade_timestamp = timestamp or timestamp_utc()
    reference_database = _reference_database_name(upgrade_timestamp)
    if not managed and database_exists(plan, reference_database, runner):
        raise _upgrade_error(
            "schema-reference-exists",
            "disposable schema reference database already exists",
        )

    backup = dump_database(
        home,
        database=database,
        reason=reason or "pre-schema-upgrade",
        timestamp=upgrade_timestamp,
        command_runner=runner,
    )
    inspection = inspect_backup(
        home,
        backup.plan.backup_path,
        command_runner=runner,
    )
    if not (
        inspection.checksum_verified
        and inspection.dump_summaries
        and inspection.manifest.get("restore_supported") is True
    ):
        raise _upgrade_error(
            "schema-upgrade-backup-invalid",
            "schema upgrade backup is not verified and restorable",
        )

    reference_created = False
    reference_cleaned = False
    if identity_migration_needed and identity_target is not None:
        apply_repository_identity_reconciliation(
            plan,
            database,
            identity_target[0],
            identity_target[1],
            identity_target[2],
            runner,
        )
        migrated_state = query_repository_identity_state(
            plan,
            database,
            identity_target[0],
            identity_target[2],
            runner,
        )
        if not migrated_state.stable:
            raise _upgrade_error(
                "repository-identity-verification-failed",
                "repository identity is not stable after reconciliation",
            )
        reconcile_graph_database_roles(plan, database, runner)
        return GraphSchemaUpgradeResult(
            result="success",
            schema_before="current-path-keyed",
            schema_after="current-stable-identity",
            backup_id=backup.plan.backup_id,
            backup_verified=True,
            rollback_available=True,
            reference_cleaned=False,
            planned_actions=actions,
        )

    if managed:
        applied_count = len(applied_ledger)
        identity_ordinal = migration_ordinal(
            migrations,
            REPOSITORY_IDENTITY_MIGRATION_PATH,
        )
        removal_ordinal = migration_ordinal(
            migrations,
            LEGACY_SCHEMA_REMOVAL_MIGRATION_PATH,
        )
        identity_target = _repository_identity_target(plan, database)
        if (
            identity_target is not None
            and identity_ordinal is not None
            and removal_ordinal is not None
            and applied_count < removal_ordinal
        ):
            if applied_count < identity_ordinal:
                apply_forward_schema(
                    plan,
                    database,
                    applied_count,
                    runner,
                    target_count=identity_ordinal,
                )
                applied_count = identity_ordinal
                if (
                    query_schema_ledger(plan, database, runner)
                    != expected_ledger[:identity_ordinal]
                ):
                    raise _upgrade_error(
                        "schema-ledger-verification-failed",
                        "graph identity schema ledger is not exact after migration",
                    )
            reconcile_repository_identity_before_removal(
                plan,
                database,
                identity_target,
                runner,
            )
        apply_forward_schema(
            plan,
            database,
            applied_count,
            runner,
        )
        if query_schema_ledger(plan, database, runner) != expected_ledger:
            raise _upgrade_error(
                "schema-ledger-verification-failed",
                "graph schema ledger is not exact-current after migration",
            )
        reconcile_graph_database_roles(plan, database, runner)
        return GraphSchemaUpgradeResult(
            result="success",
            schema_before="behind",
            schema_after="current",
            backup_id=backup.plan.backup_id,
            backup_verified=True,
            rollback_available=True,
            reference_cleaned=False,
            planned_actions=actions,
        )

    try:
        create_database(plan, reference_database, runner)
        reference_created = True
        apply_source_schema(plan, reference_database, runner)
        target_manifest = query_schema_manifest(plan, database, runner)
        reference_manifest = query_schema_manifest(plan, reference_database, runner)
        if target_manifest != reference_manifest:
            raise _upgrade_error(
                "unsupported-preledger-schema",
                "target is not a supported pre-ledger graph schema",
            )

        bootstrap_schema_ledger(plan, database, runner)
        if query_schema_ledger(plan, database, runner) != expected_ledger:
            raise _upgrade_error(
                "schema-ledger-verification-failed",
                "graph schema ledger is not exact-current after adoption",
            )
    finally:
        if reference_created:
            drop_runtime_database(
                plan,
                reference_database,
                planned_drop_database_command(plan, reference_database),
                runner,
            )
            reference_cleaned = True

    reconcile_graph_database_roles(plan, database, runner)
    return GraphSchemaUpgradeResult(
        result="success",
        schema_before="supported-preledger",
        schema_after="current",
        backup_id=backup.plan.backup_id,
        backup_verified=True,
        rollback_available=True,
        reference_cleaned=reference_cleaned,
        planned_actions=actions,
    )
