from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest

from repomap_kg.runtime.local import LocalRuntimePlan, setup_local_runtime
from repomap_kg.runtime.schema_upgrade import (
    RepositoryIdentityState,
    _repository_identity_target,
    query_repository_identity_state,
    upgrade_graph_schema,
)
from repomap_kg.storage import discover_migrations


def test_exact_current_path_keyed_state_reconciles_after_verified_backup(
    tmp_path: Path,
) -> None:
    home = tmp_path / "repo-map-home"
    setup_local_runtime(home)
    expected_ledger = tuple(
        (
            migration.ordinal,
            migration.changeset_id,
            migration.relative_path,
            migration.checksum,
        )
        for migration in discover_migrations()
    )
    path_keyed = RepositoryIdentityState(2, 0, 0, 1)
    stable = RepositoryIdentityState(1, 1, 0, 1)
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
        patch("repomap_kg.runtime.schema_upgrade.inspect_owned_postgres_container"),
        patch("repomap_kg.runtime.schema_upgrade.database_exists", return_value=True),
        patch("repomap_kg.runtime.schema_upgrade.schema_ledger_exists", return_value=True),
        patch(
            "repomap_kg.runtime.schema_upgrade.query_schema_ledger",
            return_value=expected_ledger,
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade._repository_identity_target",
            return_value=(
                "repo1:public-fixture",
                "public-fixture",
                "/workspace/current",
            ),
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.query_repository_identity_state",
            side_effect=[path_keyed, stable],
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
                "repomap_kg.runtime.schema_upgrade.apply_repository_identity_reconciliation",
                record("reconcile"),
            ),
            patch(
                "repomap_kg.runtime.schema_upgrade.reconcile_graph_database_roles",
                record("roles"),
            ),
        ):
        result = upgrade_graph_schema(
            home,
            database="repomap",
            backup_first=True,
            confirmed=True,
            timestamp="20260716T150000Z",
            command_runner=lambda *args, **kwargs: pytest.fail(str(args)),
        )

    assert result.schema_before == "current-path-keyed"
    assert result.schema_after == "current-stable-identity"
    assert result.backup_verified is True
    assert result.rollback_available is True
    assert events.index("verify-backup") < events.index("reconcile")


def test_conflicting_stable_identity_is_refused_before_backup(
    tmp_path: Path,
) -> None:
    home = tmp_path / "repo-map-home"
    setup_local_runtime(home)
    expected_ledger = tuple(
        (
            migration.ordinal,
            migration.changeset_id,
            migration.relative_path,
            migration.checksum,
        )
        for migration in discover_migrations()
    )
    with (
        patch("repomap_kg.runtime.schema_upgrade.inspect_owned_postgres_container"),
        patch("repomap_kg.runtime.schema_upgrade.database_exists", return_value=True),
        patch("repomap_kg.runtime.schema_upgrade.schema_ledger_exists", return_value=True),
        patch(
            "repomap_kg.runtime.schema_upgrade.query_schema_ledger",
            return_value=expected_ledger,
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade._repository_identity_target",
            return_value=(
                "repo1:public-fixture",
                "public-fixture",
                "/workspace/current",
            ),
        ),
        patch(
            "repomap_kg.runtime.schema_upgrade.query_repository_identity_state",
            return_value=RepositoryIdentityState(2, 0, 1, 1),
        ),
        patch("repomap_kg.runtime.schema_upgrade.dump_database") as backup,
    ):
        with pytest.raises(Exception, match="repository identity is diverged"):
            upgrade_graph_schema(
                home,
                database="repomap",
                backup_first=True,
                confirmed=True,
                command_runner=lambda *args, **kwargs: pytest.fail(str(args)),
            )

    backup.assert_not_called()


def test_identity_state_parser_and_configured_target_are_bounded() -> None:
    plan = cast(
        LocalRuntimePlan,
        SimpleNamespace(
            container_runtime="docker",
            identity=SimpleNamespace(postgres_container="postgres"),
            user="repo_map_test",
            config=object(),
        ),
    )
    with patch(
        "repomap_kg.runtime.repository_identity_migration.run_container_command",
        return_value=subprocess.CompletedProcess(
            [], 0, stdout=b"2\t0\t0\t1\n", stderr=b""
        ),
    ):
        state = query_repository_identity_state(
            plan,
            "repomap",
            "repo1:public-fixture",
            "/workspace/current",
            lambda *args, **kwargs: pytest.fail(str(args)),
        )
    assert state == RepositoryIdentityState(2, 0, 0, 1)
    assert state.reconcilable
    assert not state.stable

    graph = SimpleNamespace(
        database="repomap",
        repository_identity="repo1:public-fixture",
        source=SimpleNamespace(
            repository_name="public-fixture",
            root_path_expanded="/workspace/current",
        ),
    )
    with patch(
        "repomap_kg.runtime.repository_identity_migration.resolve_ops_config",
        return_value=SimpleNamespace(graphs=(graph,)),
    ):
        assert _repository_identity_target(plan, "repomap") == (
            "repo1:public-fixture",
            "public-fixture",
            "/workspace/current",
        )
        assert _repository_identity_target(plan, "repomap_other") is None
