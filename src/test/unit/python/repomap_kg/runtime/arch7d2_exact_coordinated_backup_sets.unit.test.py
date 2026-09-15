import hashlib
import io
import json
import subprocess
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.cli import main
from repomap_kg.coordinator.local_lifecycle import (
    maintenance_window_for_coordinated_backup,
)
from repomap_kg.runtime.backup import dump_all_databases
from repomap_kg.runtime.backup_commands import backup_root
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.runtime.plan import LocalRuntimeIdentity, build_local_runtime_plan


TIMESTAMP = "20260717T130000Z"


class _Authority:
    graph_databases = ("graph_b", "graph_a")

    def __init__(self, events: list[tuple[str, tuple[str, ...]]]) -> None:
        self.events = events

    @contextmanager
    def maintenance_window(self, *, graph_databases: tuple[str, ...] = ()):
        self.events.append(("enter", graph_databases))
        try:
            yield
        finally:
            self.events.append(("exit", graph_databases))


def _container_result(identity: LocalRuntimeIdentity, command):
    return subprocess.CompletedProcess(
        command,
        0,
        stdout=json.dumps(
            [
                {
                    "Id": "container-123",
                    "Config": {
                        "Image": "postgres:16-alpine",
                        "Labels": identity.labels("postgres"),
                    },
                }
            ]
        ),
        stderr="",
    )


def test_dump_all_captures_exact_owned_set_with_stable_manifest(tmp_path: Path) -> None:
    home = tmp_path / "repo-map-home"
    setup_local_runtime(home)
    plan = build_local_runtime_plan(home)
    identity = LocalRuntimeIdentity.from_home(home)
    dumped: list[str] = []

    def runner(command, **kwargs):
        if command[:2] == ["docker", "inspect"]:
            return _container_result(identity, command)
        if command[:2] == ["docker", "exec"] and "/usr/bin/pg_dump" in command:
            database = command[-1]
            dumped.append(database)
            content = f"dump:{database}".encode()
            kwargs["stdout"].write(content)
            return subprocess.CompletedProcess(command, 0, stdout=None, stderr=b"")
        raise AssertionError(command)

    result = dump_all_databases(
        home,
        timestamp=TIMESTAMP,
        command_runner=runner,
        stable_recovery_point=True,
    )

    assert len(plan.owned_databases) >= 2
    assert result.plan.databases == plan.owned_databases
    assert dumped == list(plan.owned_databases)
    manifest = json.loads(result.plan.manifest_path.read_text(encoding="utf-8"))
    assert manifest["scope"] == "exact-configured-graph-control-databases"
    assert manifest["databases"] == list(plan.owned_databases)
    assert manifest["recovery_point"] == {
        "held_through": "atomic-backup-publication",
        "method": "control-then-graph-maintenance-exclusion",
        "status": "stable",
    }
    assert manifest["dump_files"] == [
        {
            "name": f"{database}.pgcustom",
            "sha256": hashlib.sha256(f"dump:{database}".encode()).hexdigest(),
            "size_bytes": len(f"dump:{database}".encode()),
        }
        for database in plan.owned_databases
    ]


def test_coordinated_backup_window_holds_every_graph_in_authority_order() -> None:
    events: list[tuple[str, tuple[str, ...]]] = []
    with patch(
        "repomap_kg.coordinator.local_lifecycle.LocalControlAuthority",
        return_value=_Authority(events),
    ):
        with maintenance_window_for_coordinated_backup("/tmp/repo-map-home"):
            assert events == [("enter", ("graph_b", "graph_a"))]

    assert events == [
        ("enter", ("graph_b", "graph_a")),
        ("exit", ("graph_b", "graph_a")),
    ]


def test_cli_dump_all_holds_window_through_atomic_operation() -> None:
    events: list[str] = []

    @contextmanager
    def maintenance_window(home: str):
        assert home == "/tmp/repo-map-home"
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    def dump_all(home: str, **kwargs):
        assert home == "/tmp/repo-map-home"
        assert kwargs["stable_recovery_point"] is True
        assert events == ["enter"]
        events.extend(("dump-every-owned-database", "publish-manifest"))
        return SimpleNamespace(to_jsonable=lambda: {"command": "dump-all"})

    with (
        patch(
            "repomap_kg.cli.maintenance_window_for_coordinated_backup",
            side_effect=maintenance_window,
        ),
        patch("repomap_kg.cli.dump_all_databases", side_effect=dump_all),
        redirect_stdout(io.StringIO()),
    ):
        exit_code = main(
            [
                "local",
                "db",
                "dump-all",
                "--repo-map-home",
                "/tmp/repo-map-home",
                "--json",
            ]
        )

    assert exit_code == 0
    assert events == [
        "enter",
        "dump-every-owned-database",
        "publish-manifest",
        "exit",
    ]


def test_cli_dump_all_failure_releases_window() -> None:
    events: list[str] = []

    @contextmanager
    def maintenance_window(home: str):
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    def failed_dump_all(*args, **kwargs):
        events.append("dump-failed")
        raise LocalDbBackupError(())

    with (
        patch(
            "repomap_kg.cli.maintenance_window_for_coordinated_backup",
            side_effect=maintenance_window,
        ),
        patch("repomap_kg.cli.dump_all_databases", side_effect=failed_dump_all),
        redirect_stdout(io.StringIO()),
    ):
        exit_code = main(
            [
                "local",
                "db",
                "dump-all",
                "--repo-map-home",
                "/tmp/repo-map-home",
                "--json",
            ]
        )

    assert exit_code == 1
    assert events == ["enter", "dump-failed", "exit"]


def test_cli_dump_all_dry_run_does_not_open_window() -> None:
    observed_kwargs: dict[str, object] = {}

    def dry_run(home: str, **kwargs):
        observed_kwargs.update(kwargs)
        return SimpleNamespace(to_jsonable=lambda: {"command": "dump-all"})

    with (
        patch(
            "repomap_kg.cli.maintenance_window_for_coordinated_backup",
            side_effect=AssertionError("dry-run acquired maintenance"),
        ),
        patch("repomap_kg.cli.dump_all_databases", side_effect=dry_run),
        redirect_stdout(io.StringIO()),
    ):
        exit_code = main(
            [
                "local",
                "db",
                "dump-all",
                "--repo-map-home",
                "/tmp/repo-map-home",
                "--dry-run",
                "--json",
            ]
        )

    assert exit_code == 0
    assert observed_kwargs["dry_run"] is True
    assert observed_kwargs["stable_recovery_point"] is False


def test_mid_set_failure_publishes_nothing_and_removes_staging(tmp_path: Path) -> None:
    home = tmp_path / "repo-map-home"
    setup_local_runtime(home)
    plan = build_local_runtime_plan(home)
    identity = LocalRuntimeIdentity.from_home(home)
    calls = 0

    def runner(command, **kwargs):
        nonlocal calls
        if command[:2] == ["docker", "inspect"]:
            return _container_result(identity, command)
        if command[:2] == ["docker", "exec"] and "/usr/bin/pg_dump" in command:
            calls += 1
            kwargs["stdout"].write(b"partial-dump")
            return subprocess.CompletedProcess(
                command,
                0 if calls == 1 else 1,
                stdout=None,
                stderr=b"synthetic mid-set failure",
            )
        raise AssertionError(command)

    final_path = (
        backup_root(home)
        / identity.home_hash
        / "all-databases"
        / TIMESTAMP
    )
    with pytest.raises(LocalDbBackupError, match="synthetic mid-set failure"):
        dump_all_databases(
            home,
            timestamp=TIMESTAMP,
            command_runner=runner,
            stable_recovery_point=True,
        )

    assert len(plan.owned_databases) >= 2
    assert calls == 2
    assert not final_path.exists()
    assert not tuple(final_path.parent.glob(f".{TIMESTAMP}.*.incomplete"))
