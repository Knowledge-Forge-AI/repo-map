import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.cli import main
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.backup_restore_sets import restore_coordinated_backup
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.plan import build_local_runtime_plan


STABLE_RECOVERY_POINT = {
    "held_through": "atomic-backup-publication",
    "method": "control-then-graph-maintenance-exclusion",
    "status": "stable",
}


def _write_backup(home: Path, *, mutate=None) -> tuple[Path, tuple[str, ...]]:
    plan = build_local_runtime_plan(home)
    backup_path = home / "backups" / "coordinated-backup"
    backup_path.mkdir(parents=True)
    dump_files = []
    for database in plan.owned_databases:
        content = f"dump:{database}".encode()
        path = backup_path / f"{database}.pgcustom"
        path.write_bytes(content)
        dump_files.append(
            {
                "name": path.name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        )
    manifest = {
        "backup_format_version": 1,
        "backup_id": "coordinated-backup",
        "backup_kind": "manual-dump-all",
        "databases": list(plan.owned_databases),
        "dump_files": dump_files,
        "dump_format": "pgcustom",
        "recovery_point": dict(STABLE_RECOVERY_POINT),
        "scope": "exact-configured-graph-control-databases",
    }
    if mutate is not None:
        mutate(manifest)
    (backup_path / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return backup_path, plan.owned_databases


def _home_with_backup(tmp_path: Path, *, mutate=None):
    home = tmp_path / "repo-map-home"
    setup_local_runtime(home)
    backup_path, owned = _write_backup(home, mutate=mutate)
    return home, backup_path, owned, build_local_runtime_plan(home)


def test_dry_run_validates_complete_set_and_preflights_every_target(tmp_path: Path) -> None:
    home, backup_path, owned, plan = _home_with_backup(tmp_path)
    checked: list[str] = []

    def absent(_plan, database, _runner):
        checked.append(database)
        return False

    with (
        patch(
            "repomap_kg.runtime.backup_restore_sets.inspect_owned_postgres_container",
            return_value=SimpleNamespace(to_jsonable=lambda: {"labels_verified": True}),
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.database_exists",
            side_effect=absent,
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.create_database",
            side_effect=AssertionError("dry-run created a database"),
        ),
    ):
        result = restore_coordinated_backup(
            home,
            backup=backup_path,
            dry_run=True,
        )

    control = tuple(database for database in owned if database not in plan.graph_databases)
    expected_order = tuple(sorted(plan.graph_databases)) + control
    assert checked == list(expected_order)
    assert result.result == "dry_run"
    assert result.restore_order == expected_order
    assert result.checksum_verified is True
    assert result.databases_created == ()
    assert result.dumps_restored == ()


@pytest.mark.parametrize(
    "mutate,expected_code",
    [
        (
            lambda manifest: manifest.update(recovery_point={"status": "unstable"}),
            "coordinated-backup-unstable",
        ),
        (
            lambda manifest: manifest["databases"].append("unexpected_database"),
            "coordinated-backup-topology-mismatch",
        ),
        (
            lambda manifest: manifest["dump_files"].append(
                dict(manifest["dump_files"][0])
            ),
            "coordinated-backup-dump-set-invalid",
        ),
    ],
)
def test_invalid_set_fails_before_runtime_inspection(
    tmp_path: Path,
    mutate,
    expected_code: str,
) -> None:
    home, backup_path, _, _ = _home_with_backup(tmp_path, mutate=mutate)

    with patch(
        "repomap_kg.runtime.backup_restore_sets.inspect_owned_postgres_container",
        side_effect=AssertionError("invalid backup touched the runtime"),
    ):
        with pytest.raises(LocalDbBackupError) as raised:
            restore_coordinated_backup(home, backup=backup_path)

    assert raised.value.diagnostics[0].code == expected_code


def test_checksum_failure_precedes_runtime_inspection(tmp_path: Path) -> None:
    home, backup_path, owned, _ = _home_with_backup(tmp_path)
    (backup_path / f"{owned[0]}.pgcustom").write_bytes(b"corrupt")

    with patch(
        "repomap_kg.runtime.backup_restore_sets.inspect_owned_postgres_container",
        side_effect=AssertionError("bad checksum touched the runtime"),
    ):
        with pytest.raises(LocalDbBackupError) as raised:
            restore_coordinated_backup(home, backup=backup_path)

    assert raised.value.diagnostics[0].code == "backup-checksum-mismatch"


def test_complete_set_checksum_validation_is_bounded_streaming(tmp_path: Path) -> None:
    home, backup_path, _, _ = _home_with_backup(tmp_path)

    with (
        patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("checksum validation buffered a dump"),
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.inspect_owned_postgres_container",
            return_value=SimpleNamespace(),
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.database_exists",
            return_value=False,
        ),
    ):
        result = restore_coordinated_backup(
            home,
            backup=backup_path,
            dry_run=True,
        )

    assert result.checksum_verified is True


def test_any_existing_target_refuses_before_first_create(tmp_path: Path) -> None:
    home, backup_path, _, plan = _home_with_backup(tmp_path)
    restore_order = tuple(sorted(plan.graph_databases)) + tuple(
        database for database in plan.owned_databases if database not in plan.graph_databases
    )
    checked: list[str] = []

    def existence(_plan, database, _runner):
        checked.append(database)
        return database == restore_order[-1]

    with (
        patch(
            "repomap_kg.runtime.backup_restore_sets.inspect_owned_postgres_container",
            return_value=SimpleNamespace(),
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.database_exists",
            side_effect=existence,
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.create_database",
            side_effect=AssertionError("occupied topology was mutated"),
        ),
    ):
        with pytest.raises(LocalDbBackupError) as raised:
            restore_coordinated_backup(home, backup=backup_path)

    assert checked == list(restore_order)
    assert raised.value.diagnostics[0].code == "coordinated-restore-target-exists"


def test_restore_is_graph_sorted_control_last(tmp_path: Path) -> None:
    home, backup_path, _, plan = _home_with_backup(tmp_path)
    events: list[tuple[str, str]] = []

    with (
        patch(
            "repomap_kg.runtime.backup_restore_sets.inspect_owned_postgres_container",
            return_value=SimpleNamespace(to_jsonable=lambda: {}),
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.database_exists",
            return_value=False,
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.create_database",
            side_effect=lambda _plan, database, _runner: events.append(
                ("create", database)
            ),
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.run_pg_restore",
            side_effect=lambda _plan, database, _path, _command, _runner: events.append(
                ("restore", database)
            ),
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.reconcile_graph_database_roles"
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.reconcile_control_database_roles"
        ),
    ):
        result = restore_coordinated_backup(home, backup=backup_path)

    control = tuple(
        database for database in plan.owned_databases if database not in plan.graph_databases
    )
    expected_order = tuple(sorted(plan.graph_databases)) + control
    assert result.restore_order == expected_order
    assert events == [
        event
        for database in expected_order
        for event in (("create", database), ("restore", database))
    ]
    assert result.databases_created == expected_order
    assert result.dumps_restored == expected_order


def test_mid_restore_failure_cleans_created_targets_in_reverse(tmp_path: Path) -> None:
    home, backup_path, _, plan = _home_with_backup(tmp_path)
    restore_order = tuple(sorted(plan.graph_databases)) + tuple(
        database for database in plan.owned_databases if database not in plan.graph_databases
    )
    created: list[str] = []
    cleaned: list[str] = []

    def restore(_plan, database, _path, _command, _runner):
        if database == restore_order[1]:
            raise LocalDbBackupError(())

    with (
        patch(
            "repomap_kg.runtime.backup_restore_sets.inspect_owned_postgres_container",
            return_value=SimpleNamespace(),
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.database_exists",
            return_value=False,
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.create_database",
            side_effect=lambda _plan, database, _runner: created.append(database),
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.run_pg_restore",
            side_effect=restore,
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.cleanup_created_database",
            side_effect=lambda _plan, database, _runner: cleaned.append(database),
        ),
    ):
        with pytest.raises(LocalDbBackupError):
            restore_coordinated_backup(home, backup=backup_path)

    assert created == list(restore_order[:2])
    assert cleaned == list(reversed(created))


def test_cleanup_failure_is_explicit_and_bounded(tmp_path: Path) -> None:
    home, backup_path, _, plan = _home_with_backup(tmp_path)
    failed_database = sorted(plan.graph_databases)[0]

    with (
        patch(
            "repomap_kg.runtime.backup_restore_sets.inspect_owned_postgres_container",
            return_value=SimpleNamespace(),
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.database_exists",
            return_value=False,
        ),
        patch("repomap_kg.runtime.backup_restore_sets.create_database"),
        patch(
            "repomap_kg.runtime.backup_restore_sets.run_pg_restore",
            side_effect=LocalDbBackupError(()),
        ),
        patch(
            "repomap_kg.runtime.backup_restore_sets.cleanup_created_database",
            side_effect=RuntimeError(f"private failure for {failed_database}"),
        ),
    ):
        with pytest.raises(LocalDbBackupError) as raised:
            restore_coordinated_backup(home, backup=backup_path)

    diagnostic = raised.value.diagnostics[0]
    assert diagnostic.code == "coordinated-restore-cleanup-failed"
    assert failed_database not in diagnostic.message


def test_cli_restore_all_delegates_json_contract() -> None:
    result = SimpleNamespace(
        to_jsonable=lambda: {"command": "restore-all", "result": "dry_run"}
    )
    stdout = io.StringIO()
    with (
        patch("repomap_kg.cli.restore_coordinated_backup", return_value=result) as helper,
        redirect_stdout(stdout),
    ):
        exit_code = main(
            [
                "local",
                "db",
                "restore-all",
                "--repo-map-home",
                "/tmp/repo-map-home",
                "--from-dump",
                "backup-id",
                "--dry-run",
                "--json",
            ]
        )

    assert exit_code == 0
    assert json.loads(stdout.getvalue()) == {
        "command": "restore-all",
        "result": "dry_run",
    }
    helper.assert_called_once_with(
        "/tmp/repo-map-home",
        backup="backup-id",
        dry_run=True,
    )
