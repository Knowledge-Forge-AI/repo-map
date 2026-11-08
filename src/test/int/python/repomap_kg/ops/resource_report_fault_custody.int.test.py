"""Report-writer faults after real accepted publications preserve publication custody.

Faults are injected only at the actual report-writer boundary: system calls
on the report's own temporary name or held directory. Subject publication runs
for real against SQLite Local or core PostgreSQL and is read back afterwards.
"""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
from typing import Any

import pytest

import common_lore_index.cli._ops_sqlite_dispatch as sqlite_dispatch
import common_lore_index.ops.resource_reports._delivery as delivery
from common_lore_index.cli.main import main
from common_lore_index.coordinator.local_lifecycle import initialize_coordinator_control
from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home, local_graph_binding
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.local_refresh import refresh_local_graph
from common_lore_index.storage import apply_migrations, default_rdbms_root
from common_lore_index.storage.sqlite_local import investigation_queries
from common_lore_index.storage.sqlite_local.connection import read_transaction
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.resource_report_cli_files import (
    TEMP_PREFIX, private_directory, report_leftovers, report_payload,
)
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, materialize_mixed_v1_working_copy, write_mixed_v1_postgres_home,
)
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home

GRAPH = "report-fault"


def _local(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[Path, Path, LocalSqliteConfig]:
    source = write_shell_source(tmp_path / "source")
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, source))
    assert main(["ops", "sqlite-init", "--repo-map-home", str(home), "--graph", GRAPH]) == 0
    capsys.readouterr()
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    return home, private_directory(tmp_path / "reports"), config


def _latest_run(config: LocalSqliteConfig) -> int:
    graph = next(item for item in config.graphs if item.id == GRAPH)
    path = config.graph_store_root / f"{GRAPH}.sqlite3"
    with read_transaction(path, local_graph_binding(graph)) as connection:
        return int(investigation_queries.status_fields(connection)["latest_run_id"])


def _refresh(home: Path, target: Path) -> list[str]:
    return ["ops", "refresh-graph", "--repo-map-home", str(home), "--graph", GRAPH, "--json",
            "--resource-report", str(target)]


def _fail_report_link(monkeypatch: pytest.MonkeyPatch) -> None:
    real_link = os.link

    def link(source: Any, target: Any, *args: Any, **kwargs: Any) -> None:
        if str(source).startswith(TEMP_PREFIX):
            raise OSError(errno.EIO, "injected report install failure")
        real_link(source, target, *args, **kwargs)

    monkeypatch.setattr(delivery.os, "link", link)


def test_local_install_failure_after_commit_warns_and_keeps_the_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, reports, config = _local(tmp_path, capsys)
    _fail_report_link(monkeypatch)
    assert main(_refresh(home, reports / "r.json")) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["accepted_generation"] == 1
    assert captured.err.endswith("WARNING: resource-report-not-delivered: install_failed\n")
    assert str(tmp_path) not in captured.err
    assert os.listdir(reports) == []
    assert _latest_run(config) == 1, "a delivery failure never relabels the committed generation"


def test_local_directory_sync_failure_keeps_the_complete_installed_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, reports, config = _local(tmp_path, capsys)
    identity = (os.stat(reports).st_dev, os.stat(reports).st_ino)
    real_fsync = os.fsync

    def fsync(descriptor: int) -> None:
        details = os.fstat(descriptor)
        if (details.st_dev, details.st_ino) == identity:
            raise OSError(errno.EIO, "injected directory sync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(delivery.os, "fsync", fsync)
    assert main(_refresh(home, reports / "r.json")) == 0
    captured = capsys.readouterr()
    assert captured.err.endswith("WARNING: resource-report-incomplete: directory_sync_failed\n")
    report_payload(reports / "r.json", operation="local_refresh", backend="sqlite", outcome="published")
    assert report_leftovers(reports) == []
    assert _latest_run(config) == 1


def test_target_race_during_the_real_subject_is_refused_without_clobbering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, reports, config = _local(tmp_path, capsys)
    target = reports / "r.json"

    def racing_refresh(local_config: Any, graph_id: str, **kwargs: Any) -> Any:
        target.write_bytes(b"foreign")  # appears after the non-reserving fast-fail
        return refresh_local_graph(local_config, graph_id, **kwargs)

    monkeypatch.setattr(sqlite_dispatch, "refresh_local_graph", racing_refresh)
    assert main(_refresh(home, target)) == 0
    captured = capsys.readouterr()
    assert captured.err.endswith("WARNING: resource-report-not-delivered: destination_exists\n")
    assert target.read_bytes() == b"foreign" and report_leftovers(reports) == []
    assert _latest_run(config) == 1


def test_server_install_failure_after_commit_keeps_the_committed_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    reports = private_directory(tmp_path / "reports")
    working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
    with temporary_postgres() as postgres:
        home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home", working_copy,
            host=postgres.host, port=postgres.port, database=postgres.database,
            user=postgres.user, password=postgres.password, declared_aliases=("core", "companion"),
        )
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        apply_migrations(
            default_rdbms_root(), config.postgres.psql_args_for_database(postgres.database),
            psql_command=postgres.psql_command,
        )
        assert initialize_coordinator_control(home)["result"] == "ready"
        _fail_report_link(monkeypatch)
        code = main([
            "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
            "--psql-command", postgres.psql_command, "--json", "--resource-report", str(reports / "r.json"),
        ])
        captured = capsys.readouterr()
        assert code == 0 and json.loads(captured.out)["result"] == "success"
        assert captured.err.endswith("WARNING: resource-report-not-delivered: install_failed\n")
        assert os.listdir(reports) == []
        monkeypatch.undo()
        assert main([
            "ops", "graph-summary", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
            "--psql-command", postgres.psql_command, "--json",
        ]) == 0, "the accepted Server publication remains readable (exit 0 only on success)"
        assert isinstance(json.loads(capsys.readouterr().out), dict)


@pytest.mark.parametrize("change", ["missing", "replaced", "shared"])
def test_destination_parent_change_after_publication_preserves_both_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], change: str,
) -> None:
    home, reports, config = _local(tmp_path, capsys)
    held = reports.with_name("held-reports")

    def changing_refresh(local_config: Any, graph_id: str, **kwargs: Any) -> Any:
        outcome = refresh_local_graph(local_config, graph_id, **kwargs)
        if change == "shared":
            reports.chmod(0o755)
        else:
            reports.rename(held)
            if change == "replaced":
                reports.mkdir(mode=0o700)
        return outcome

    monkeypatch.setattr(sqlite_dispatch, "refresh_local_graph", changing_refresh)
    assert main(_refresh(home, reports / "r.json")) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["accepted_generation"] == 1
    assert captured.err.endswith("WARNING: resource-report-not-delivered: parent_changed\n")
    assert str(tmp_path) not in captured.err
    assert _latest_run(config) == 1
    for directory in (reports, held):
        if directory.exists():
            assert list(directory.iterdir()) == []


@pytest.mark.parametrize("fault", ["short-write", "file-sync", "file-mode", "close-oserror", "close-interrupt"])
def test_owned_report_write_and_cleanup_faults_never_undo_the_real_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], fault: str,
) -> None:
    home, reports, config = _local(tmp_path, capsys)
    real_write, real_sync, real_mode = os.write, os.fsync, os.fchmod
    real_close, real_stat = os.close, os.fstat
    interrupt = KeyboardInterrupt("injected report cleanup interrupt")

    def owned(descriptor: int) -> bool:
        details = real_stat(descriptor)
        identity = details.st_dev, details.st_ino
        return any(
            (p.stat().st_dev, p.stat().st_ino) == identity
            for p in reports.iterdir() if p.name.startswith(TEMP_PREFIX)
        )

    def write(descriptor: int, data: Any) -> int:
        if fault in {"short-write", "close-oserror", "close-interrupt"} and owned(descriptor):
            return 0
        return real_write(descriptor, data)

    def sync(descriptor: int) -> None:
        if fault == "file-sync" and owned(descriptor):
            raise OSError(errno.EIO, "injected report file sync")
        real_sync(descriptor)

    def mode(descriptor: int, permissions: int) -> None:
        if fault == "file-mode" and owned(descriptor):
            raise OSError(errno.EIO, "injected report file mode")
        real_mode(descriptor, permissions)

    def close(descriptor: int) -> None:
        if fault in {"close-oserror", "close-interrupt"} and owned(descriptor):
            real_close(descriptor)
            if fault == "close-interrupt":
                raise interrupt
            raise OSError(errno.EIO, "injected report descriptor close")
        real_close(descriptor)

    monkeypatch.setattr(delivery.os, "write", write)
    monkeypatch.setattr(delivery.os, "fsync", sync)
    monkeypatch.setattr(delivery.os, "fchmod", mode)
    monkeypatch.setattr(delivery.os, "close", close)
    if fault == "close-interrupt":
        with pytest.raises(KeyboardInterrupt) as caught:
            main(_refresh(home, reports / "r.json"))
        assert caught.value is interrupt
        capsys.readouterr()
    else:
        assert main(_refresh(home, reports / "r.json")) == 0
        captured = capsys.readouterr()
        assert json.loads(captured.out)["accepted_generation"] == 1
        category = {"file-sync": "file_sync_failed", "file-mode": "temp_create_failed"}.get(fault, "short_write")
        assert captured.err.endswith(f"WARNING: resource-report-not-delivered: {category}\n")
        assert str(tmp_path) not in captured.err
    assert _latest_run(config) == 1
    assert list(reports.iterdir()) == []
