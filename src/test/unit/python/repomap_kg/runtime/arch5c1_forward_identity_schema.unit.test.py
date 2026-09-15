from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.schema_decommission import (
    LEGACY_SCHEMA_REMOVAL_MIGRATION_PATH,
    REPOSITORY_IDENTITY_MIGRATION_PATH,
)
from repomap_kg.runtime.schema_upgrade import upgrade_graph_schema
from repomap_kg.storage import (
    StorageSchemaError,
    discover_migrations,
    graph_schema_forward_sql,
)


def test_forward_sql_contains_only_the_exact_pending_suffix() -> None:
    migrations = discover_migrations()

    script = graph_schema_forward_sql(len(migrations) - 1)

    assert script.startswith("BEGIN;\n")
    assert script.endswith("COMMIT;\n")
    assert migrations[-1].changeset_id in script
    assert migrations[-2].changeset_id not in script
    assert "CREATE TABLE repomap_schema_migrations" not in script

    with pytest.raises(StorageSchemaError, match="exact nonempty applied prefix"):
        graph_schema_forward_sql(0)
    with pytest.raises(StorageSchemaError, match="exact nonempty applied prefix"):
        graph_schema_forward_sql(len(migrations))


def test_backup_first_upgrade_applies_exact_pending_ledger_prefix(
    tmp_path: Path,
) -> None:
    home = tmp_path / "repo-map-home"
    setup_local_runtime(home)
    migrations = discover_migrations()
    expected = tuple(
        (
            migration.ordinal,
            migration.changeset_id,
            migration.relative_path,
            migration.checksum,
        )
        for migration in migrations
    )
    removal_ordinal = next(
        migration.ordinal
        for migration in migrations
        if migration.relative_path == LEGACY_SCHEMA_REMOVAL_MIGRATION_PATH
    )
    applied = expected[: removal_ordinal - 1]
    backup = SimpleNamespace(
        plan=SimpleNamespace(
            backup_path=home / "backups" / "verified",
            backup_id="public-backup-id",
        )
    )
    inspection = SimpleNamespace(
        checksum_verified=True,
        dump_summaries=(object(),),
        manifest={"restore_supported": True},
    )
    events: list[str] = []

    def record(name: str, value=None):
        def action(*args, **kwargs):
            events.append(name)
            return value

        return action

    with (
        patch(
            "repomap_kg.runtime.schema_upgrade.inspect_owned_postgres_container",
            record("inspect-runtime", object()),
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.database_exists",
            return_value=True,
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.schema_ledger_exists",
            return_value=True,
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.query_schema_ledger",
            side_effect=[applied, expected],
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.dump_database",
            record("backup", backup),
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.inspect_backup",
            record("verify-backup", inspection),
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.apply_forward_schema",
            record("apply-forward"),
            create=True,
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade."
            "reconcile_repository_identity_before_removal",
            record("reconcile-identity"),
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.reconcile_graph_database_roles",
            record("reconcile-roles"),
        ),
    ):
        result = upgrade_graph_schema(
            home,
            database="repomap",
            backup_first=True,
            confirmed=True,
            timestamp="20260716T130000Z",
            command_runner=lambda *args, **kwargs: pytest.fail(str(args)),
        )

    assert result.schema_before == "behind"
    assert result.schema_after == "current"
    assert result.backup_verified is True
    assert result.rollback_available is True
    assert events.index("verify-backup") < events.index("reconcile-identity")
    assert events.index("reconcile-identity") < events.index("apply-forward")
    assert events.index("verify-backup") < events.index("apply-forward")
    assert events.index("apply-forward") < events.index("reconcile-roles")


def test_backup_first_upgrade_applies_interim_identity_prefix_when_behind_identity(
    tmp_path: Path,
) -> None:
    home = tmp_path / "repo-map-home"
    setup_local_runtime(home)
    migrations = discover_migrations()
    expected = tuple(
        (
            migration.ordinal,
            migration.changeset_id,
            migration.relative_path,
            migration.checksum,
        )
        for migration in migrations
    )
    identity_ordinal = next(
        migration.ordinal
        for migration in migrations
        if migration.relative_path == REPOSITORY_IDENTITY_MIGRATION_PATH
    )
    applied = expected[: identity_ordinal - 1]
    backup = SimpleNamespace(
        plan=SimpleNamespace(
            backup_path=home / "backups" / "verified",
            backup_id="public-backup-id",
        )
    )
    inspection = SimpleNamespace(
        checksum_verified=True,
        dump_summaries=(object(),),
        manifest={"restore_supported": True},
    )
    events: list[str] = []

    def record(name: str, value=None):
        def action(*args, **kwargs):
            events.append(name)
            return value

        return action

    with (
        patch(
            "repomap_kg.runtime.schema_upgrade.inspect_owned_postgres_container",
            record("inspect-runtime", object()),
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.database_exists",
            return_value=True,
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.schema_ledger_exists",
            return_value=True,
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.query_schema_ledger",
            side_effect=[applied, expected[:identity_ordinal], expected],
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.dump_database",
            record("backup", backup),
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.inspect_backup",
            record("verify-backup", inspection),
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.apply_forward_schema",
            record("apply-forward"),
            create=True,
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade."
            "reconcile_repository_identity_before_removal",
            record("reconcile-identity"),
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.reconcile_graph_database_roles",
            record("reconcile-roles"),
        ),
    ):
        result = upgrade_graph_schema(
            home,
            database="repomap",
            backup_first=True,
            confirmed=True,
            timestamp="20260716T130000Z",
            command_runner=lambda *args, **kwargs: pytest.fail(str(args)),
        )

    assert result.schema_before == "behind"
    assert result.schema_after == "current"
    assert result.backup_verified is True
    assert result.rollback_available is True
    assert events.index("verify-backup") < events.index("apply-forward")
    assert events.index("apply-forward") < events.index("reconcile-identity")
    assert events.index("reconcile-identity") < events.index("reconcile-roles")


def test_diverged_managed_ledger_is_refused_before_backup(tmp_path: Path) -> None:
    home = tmp_path / "repo-map-home"
    setup_local_runtime(home)
    with (
        patch("repomap_kg.runtime.schema_upgrade.inspect_owned_postgres_container"),
        patch("repomap_kg.runtime.schema_upgrade.database_exists", return_value=True),
        patch("repomap_kg.runtime.schema_upgrade.schema_ledger_exists", return_value=True),
        patch(
            "repomap_kg.runtime.schema_upgrade.query_schema_ledger",
            return_value=((1, "wrong", "wrong.sql", "0" * 64),),
        ),
        patch("repomap_kg.runtime.schema_upgrade.dump_database") as backup,
    ):
        with pytest.raises(Exception, match="diverged"):
            upgrade_graph_schema(
                home,
                database="repomap",
                backup_first=True,
                confirmed=True,
                command_runner=lambda *args, **kwargs: pytest.fail(str(args)),
            )
    backup.assert_not_called()
