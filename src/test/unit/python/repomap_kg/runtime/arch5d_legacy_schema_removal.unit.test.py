from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import LocalRuntimePlan, setup_local_runtime
from repomap_kg.runtime.repository_identity_migration import RepositoryIdentityState
from repomap_kg.runtime.schema_decommission import (
    migration_ordinal,
    reconcile_repository_identity_before_removal,
)
from repomap_kg.runtime.schema_upgrade import upgrade_graph_schema
from repomap_kg.storage import discover_migrations, graph_schema_forward_sql


def _runner(*_args: object, **_kwargs: object) -> CompletedProcess[object]:
    return CompletedProcess([], 0)


_PLAN = object.__new__(LocalRuntimePlan)


_IDENTITY_MIGRATION = "2026/07/16-001-arch5c-add-repository-identity.sql"
_REMOVAL_MIGRATION = "2026/07/16-002-arch5d-drop-legacy-graph-schema.sql"


def test_migration_ordinal_matches_exact_path_or_returns_none() -> None:
    migrations = discover_migrations()
    identity = next(
        migration
        for migration in migrations
        if migration.relative_path == _IDENTITY_MIGRATION
    )

    assert migration_ordinal(migrations, _IDENTITY_MIGRATION) == identity.ordinal
    assert migration_ordinal(migrations, "missing/migration.sql") is None


@pytest.mark.parametrize(
    "state",
    (
        RepositoryIdentityState(1, 1, 0, 1),
        RepositoryIdentityState(0, 0, 0, 0),
    ),
)
def test_identity_reconciliation_skips_stable_or_empty_database(state) -> None:
    with (
        patch(
            "repomap_kg.runtime.schema_decommission."
            "query_repository_identity_state",
            return_value=state,
        ),
        patch(
            "repomap_kg.runtime.schema_decommission."
            "apply_repository_identity_reconciliation"
        ) as apply_reconciliation,
    ):
        reconcile_repository_identity_before_removal(
            _PLAN,
            "repomap",
            ("repo1:public", "public", "/public/source"),
            _runner,
        )

    apply_reconciliation.assert_not_called()


@pytest.mark.parametrize(
    "state",
    (
        RepositoryIdentityState(2, 1, 1, 1),
        RepositoryIdentityState(2, 2, 0, 1),
    ),
)
def test_identity_reconciliation_refuses_diverged_database(state) -> None:
    with (
        patch(
            "repomap_kg.runtime.schema_decommission."
            "query_repository_identity_state",
            return_value=state,
        ),
        pytest.raises(
            LocalDbBackupError,
            match="target database repository identity is diverged",
        ),
    ):
        reconcile_repository_identity_before_removal(
            _PLAN,
            "repomap",
            ("repo1:public", "public", "/public/source"),
            _runner,
        )


def test_identity_reconciliation_applies_and_verifies_stable_result() -> None:
    with (
        patch(
            "repomap_kg.runtime.schema_decommission."
            "query_repository_identity_state",
            side_effect=(
                RepositoryIdentityState(1, 0, 0, 1),
                RepositoryIdentityState(1, 1, 0, 1),
            ),
        ),
        patch(
            "repomap_kg.runtime.schema_decommission."
            "apply_repository_identity_reconciliation"
        ) as apply_reconciliation,
    ):
        reconcile_repository_identity_before_removal(
            _PLAN,
            "repomap",
            ("repo1:public", "public", "/public/source"),
            _runner,
        )

    apply_reconciliation.assert_called_once()


def test_identity_reconciliation_refuses_unstable_result() -> None:
    with (
        patch(
            "repomap_kg.runtime.schema_decommission."
            "query_repository_identity_state",
            side_effect=(
                RepositoryIdentityState(1, 0, 0, 1),
                RepositoryIdentityState(1, 0, 0, 1),
            ),
        ),
        patch(
            "repomap_kg.runtime.schema_decommission."
            "apply_repository_identity_reconciliation"
        ),
        pytest.raises(
            LocalDbBackupError,
            match="repository identity is not stable after reconciliation",
        ),
    ):
        reconcile_repository_identity_before_removal(
            _PLAN,
            "repomap",
            ("repo1:public", "public", "/public/source"),
            _runner,
        )


def test_arch5d_migration_is_guarded_and_foreign_key_safe() -> None:
    migrations = discover_migrations()
    removal = next(
        migration
        for migration in migrations
        if migration.relative_path == _REMOVAL_MIGRATION
    )
    sql = removal.path.read_text(encoding="utf-8")

    assert "repository_identity IS NULL" in sql
    assert sql.index("DROP TABLE stage_legacy_edges") < sql.index(
        "DROP TABLE stage_legacy_evidence"
    )
    assert sql.index("DROP TABLE stage_legacy_evidence") < sql.index(
        "DROP TABLE stage_legacy_nodes"
    )
    assert sql.index("DROP TABLE edges") < sql.index("DROP TABLE evidence")
    assert sql.index("DROP TABLE evidence") < sql.index("DROP TABLE nodes")
    for retained in (
        "repositories",
        "runs",
        "files",
        "raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "canonical_evidence",
        "ingestion_stages",
    ):
        assert f"DROP TABLE {retained}" not in sql


def test_forward_sql_can_stop_before_a_destructive_suffix() -> None:
    migrations = discover_migrations()
    identity = next(
        migration
        for migration in migrations
        if migration.relative_path == _IDENTITY_MIGRATION
    )
    removal = next(
        migration
        for migration in migrations
        if migration.relative_path == _REMOVAL_MIGRATION
    )

    script = graph_schema_forward_sql(
        identity.ordinal - 1,
        target_count=identity.ordinal,
    )

    assert identity.changeset_id in script
    assert removal.changeset_id not in script


def test_upgrade_reconciles_identity_before_destructive_suffix(
    tmp_path: Path,
) -> None:
    home = tmp_path / "repo-map-home"
    setup_local_runtime(home)
    migrations = discover_migrations()
    identity = next(
        migration
        for migration in migrations
        if migration.relative_path == _IDENTITY_MIGRATION
    )
    removal = next(
        migration
        for migration in migrations
        if migration.relative_path == _REMOVAL_MIGRATION
    )
    assert removal.ordinal > identity.ordinal
    expected = tuple(
        (
            migration.ordinal,
            migration.changeset_id,
            migration.relative_path,
            migration.checksum,
        )
        for migration in migrations
    )
    applied = expected[: identity.ordinal - 1]
    identity_prefix = expected[: identity.ordinal]
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
    reconcilable = RepositoryIdentityState(1, 0, 0, 1)
    stable = RepositoryIdentityState(1, 1, 0, 1)
    forwards: list[tuple[int, int | None]] = []
    events: list[str] = []

    def apply_forward(*args, **kwargs) -> None:
        forwards.append((args[2], kwargs.get("target_count")))
        events.append("apply-forward")

    def dump_db(*_args: object, **_kwargs: object) -> object:
        events.append("backup")
        return backup

    with (
        patch(
            "repomap_kg.runtime.schema_upgrade.inspect_owned_postgres_container"
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
            side_effect=[applied, identity_prefix, expected],
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade._repository_identity_target",
            return_value=("repo1:public", "public", "/public/source"),
        ),
        patch(
            "repomap_kg.runtime.schema_decommission.query_repository_identity_state",
            side_effect=[reconcilable, stable],
        ),
        patch(
            "repomap_kg.runtime.schema_decommission."
            "apply_repository_identity_reconciliation",
            side_effect=lambda *args, **kwargs: events.append("reconcile"),
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.dump_database",
            side_effect=dump_db,
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.inspect_backup",
            return_value=inspection,
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.apply_forward_schema",
            side_effect=apply_forward,
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.reconcile_graph_database_roles",
            side_effect=lambda *args, **kwargs: events.append("roles"),
        ),
    ):
        result = upgrade_graph_schema(
            home,
            database="repomap",
            backup_first=True,
            confirmed=True,
            timestamp="20260716T150000Z",
            command_runner=_runner,
        )

    assert forwards == [
        (identity.ordinal - 1, identity.ordinal),
        (identity.ordinal, None),
    ]
    assert events.index("backup") < events.index("reconcile")
    assert events.index("reconcile") < len(events) - 1
    assert events[-1] == "roles"
    assert result.schema_before == "behind"
    assert result.schema_after == "current"
