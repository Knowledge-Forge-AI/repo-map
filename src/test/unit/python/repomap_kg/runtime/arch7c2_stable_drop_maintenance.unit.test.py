import io
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.cli import main
from repomap_kg.coordinator.local_lifecycle import (
    maintenance_window_for_database_drop,
)
from repomap_kg.runtime.backup_records import (
    LocalDbBackupError,
    LocalRuntimeDiagnostic,
)
from repomap_kg.runtime.maintenance import MaintenanceUnavailableError


class _Authority:
    database_name = "repomap_control"
    graph_databases = ("graph_a", "graph_b")

    def __init__(self, events: list[tuple[str, tuple[str, ...]]]) -> None:
        self.events = events

    @contextmanager
    def maintenance_window(self, *, graph_databases: tuple[str, ...] = ()):
        self.events.append(("enter", graph_databases))
        try:
            yield
        finally:
            self.events.append(("exit", graph_databases))


@pytest.mark.parametrize(
    ("database", "expected_graphs"),
    [
        ("graph_a", ("graph_a",)),
        ("repomap_control", ("graph_a", "graph_b")),
    ],
)
def test_drop_maintenance_scope_is_exact_for_graph_and_control_targets(
    database: str,
    expected_graphs: tuple[str, ...],
) -> None:
    events: list[tuple[str, tuple[str, ...]]] = []
    with patch(
        "repomap_kg.coordinator.local_lifecycle.LocalControlAuthority",
        return_value=_Authority(events),
    ):
        with maintenance_window_for_database_drop("/tmp/repo-map-home", database):
            assert events == [("enter", expected_graphs)]

    assert events == [
        ("enter", expected_graphs),
        ("exit", expected_graphs),
    ]


def test_drop_maintenance_refuses_unrelated_target_before_lock() -> None:
    events: list[tuple[str, tuple[str, ...]]] = []
    with patch(
        "repomap_kg.coordinator.local_lifecycle.LocalControlAuthority",
        return_value=_Authority(events),
    ):
        with pytest.raises(
            MaintenanceUnavailableError,
            match="not an owned database",
        ):
            with maintenance_window_for_database_drop(
                "/tmp/repo-map-home",
                "unrelated_db",
            ):
                pytest.fail("unowned drop maintenance window opened")

    assert events == []


def test_drop_maintenance_bounds_authority_construction_failure() -> None:
    with patch(
        "repomap_kg.coordinator.local_lifecycle.LocalControlAuthority",
        side_effect=RuntimeError("private authority detail"),
    ):
        with pytest.raises(
            MaintenanceUnavailableError,
            match="maintenance authority is unavailable",
        ):
            with maintenance_window_for_database_drop(
                "/tmp/repo-map-home",
                "graph_a",
            ):
                pytest.fail("drop maintenance window opened")


def test_drop_maintenance_preserves_operation_failure_and_releases_lock() -> None:
    events: list[tuple[str, tuple[str, ...]]] = []
    failure = LocalDbBackupError(
        (
            LocalRuntimeDiagnostic(
                "error",
                "synthetic-backup-failure",
                "backup",
                "synthetic backup failure",
            ),
        )
    )
    with patch(
        "repomap_kg.coordinator.local_lifecycle.LocalControlAuthority",
        return_value=_Authority(events),
    ):
        with pytest.raises(LocalDbBackupError, match="synthetic backup failure"):
            with maintenance_window_for_database_drop(
                "/tmp/repo-map-home",
                "graph_a",
            ):
                raise failure

    assert events == [
        ("enter", ("graph_a",)),
        ("exit", ("graph_a",)),
    ]


def test_cli_drop_holds_maintenance_through_operation_and_releases_on_failure() -> None:
    events: list[str] = []
    stderr = io.StringIO()

    @contextmanager
    def maintenance_window(home: str, database: str):
        assert home == "/tmp/repo-map-home"
        assert database == "graph_a"
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    def failed_drop(*args, **kwargs):
        assert events == ["enter"]
        events.extend(("backup-snapshot", "verify-backup", "drop-failed"))
        raise LocalDbBackupError(
            (
                LocalRuntimeDiagnostic(
                    "error",
                    "synthetic-backup-failure",
                    "backup",
                    "synthetic backup failure",
                ),
            )
        )

    with (
        patch(
            "repomap_kg.cli.maintenance_window_for_database_drop",
            side_effect=maintenance_window,
        ),
        patch("repomap_kg.cli.drop_database", side_effect=failed_drop),
        redirect_stdout(io.StringIO()),
        redirect_stderr(stderr),
    ):
        exit_code = main(
            [
                "local",
                "db",
                "drop",
                "--repo-map-home",
                "/tmp/repo-map-home",
                "--database",
                "graph_a",
                "--backup-first",
                "--yes",
                "--json",
            ]
        )

    assert exit_code == 1
    assert events == [
        "enter",
        "backup-snapshot",
        "verify-backup",
        "drop-failed",
        "exit",
    ]
    assert "synthetic backup failure" in stderr.getvalue()
    assert "maintenance authority is unavailable" not in stderr.getvalue()


def test_cli_drop_dry_run_does_not_acquire_maintenance() -> None:
    result = SimpleNamespace(
        to_jsonable=lambda: {"command": "drop", "result": "dry_run"}
    )
    with (
        patch(
            "repomap_kg.cli.maintenance_window_for_database_drop",
            side_effect=AssertionError("dry-run acquired maintenance"),
        ),
        patch("repomap_kg.cli.drop_database", return_value=result) as drop,
        redirect_stdout(io.StringIO()),
    ):
        exit_code = main(
            [
                "local",
                "db",
                "drop",
                "--repo-map-home",
                "/tmp/repo-map-home",
                "--database",
                "graph_a",
                "--backup-first",
                "--dry-run",
                "--json",
            ]
        )

    assert exit_code == 0
    drop.assert_called_once()
