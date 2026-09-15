from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from repomap_kg.runtime.backup_commands import CommandRunner

import repomap_kg.runtime.backup_commands as backup_commands
from repomap_kg.runtime.backup import inspect_owned_postgres_container
from repomap_kg.runtime.backup_commands import (
    backup_root,
    planned_pg_restore_command,
    planned_psql_command,
)
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.plan import build_local_runtime_plan
from repomap_kg.runtime.release import PACKAGED_PG_RESTORE, PACKAGED_PSQL


def test_lifecycle_admin_backup_root_uses_private_admin_volume(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configuration_home = tmp_path / "configuration"
    admin_root = tmp_path / "admin"
    marker = tmp_path / "release-container"
    marker.touch()
    monkeypatch.setattr(backup_commands, "CONTAINER_INTERNAL_MARKER", marker)
    monkeypatch.setenv("REPOMAP_CONTAINER_INTERNAL", "1")
    monkeypatch.setenv("REPOMAP_ADMIN_ROOT", str(admin_root))

    assert backup_root(configuration_home) == admin_root / "backups"


def test_host_backup_root_ignores_admin_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configuration_home = tmp_path / "configuration"
    admin_root = tmp_path / "admin"
    monkeypatch.setenv("REPOMAP_ADMIN_ROOT", str(admin_root))

    assert backup_root(configuration_home) == configuration_home / "backups"


def test_lifecycle_admin_uses_packaged_clients_without_nested_docker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    setup_local_runtime(tmp_path)
    plan = build_local_runtime_plan(tmp_path)
    marker = tmp_path / "release-container"
    marker.touch()
    monkeypatch.setattr(backup_commands, "CONTAINER_INTERNAL_MARKER", marker)
    monkeypatch.setenv("REPOMAP_CONTAINER_INTERNAL", "1")

    psql = planned_psql_command(plan, "postgres", "-tAc", "SELECT 1")
    restore = planned_pg_restore_command(plan, "graph_a")

    assert psql[:5] == (
        PACKAGED_PSQL,
        "-h",
        "postgres",
        "-p",
        "5432",
    )
    assert restore[:5] == (
        PACKAGED_PG_RESTORE,
        "-h",
        "postgres",
        "-p",
        "5432",
    )
    assert "docker" not in psql
    assert "docker" not in restore


def test_lifecycle_admin_internal_ownership_requires_exact_home_hash(
    monkeypatch,
    tmp_path: Path,
) -> None:
    setup_local_runtime(tmp_path)
    plan = build_local_runtime_plan(tmp_path)
    marker = tmp_path / "release-container"
    marker.touch()
    monkeypatch.setattr(backup_commands, "CONTAINER_INTERNAL_MARKER", marker)
    monkeypatch.setenv("REPOMAP_CONTAINER_INTERNAL", "1")
    mismatched_hash = "0123456789ab"
    assert mismatched_hash != plan.identity.home_hash
    monkeypatch.setenv("REPOMAP_RUNTIME_HOME_HASH", mismatched_hash)

    with pytest.raises(LocalDbBackupError, match="owned"):
        inspect_owned_postgres_container(plan, cast("CommandRunner", lambda *_args, **_kwargs: None))

    assert (
        f"REPOMAP_RUNTIME_HOME_HASH={plan.identity.home_hash}"
        in plan.env_file.read_text(encoding="utf-8").splitlines()
    )
    monkeypatch.setenv("REPOMAP_RUNTIME_HOME_HASH", plan.identity.home_hash)
    metadata = inspect_owned_postgres_container(plan, cast("CommandRunner", lambda *_args, **_kwargs: None))
    assert metadata.name == plan.identity.postgres_container
    assert metadata.labels == plan.identity.labels("postgres")


def test_release_cluster_projects_internal_lifecycle_capability(tmp_path: Path) -> None:
    setup_local_runtime(tmp_path)
    plan = build_local_runtime_plan(tmp_path)
    compose = plan.compose_file.read_text(encoding="utf-8")

    assert compose.count('REPOMAP_CONTAINER_INTERNAL: "1"') == 2
    assert compose.count(f"REPOMAP_RUNTIME_HOME_HASH: {plan.identity.home_hash}") == 2
    assert "install -m 0444 /dev/null /etc/repomap-release-container" in (
        plan.dockerfile.read_text(encoding="utf-8")
    )
