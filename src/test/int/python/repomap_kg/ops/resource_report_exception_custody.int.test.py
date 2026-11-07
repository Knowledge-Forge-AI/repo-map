"""Exact report exception custody and warning-sink failure boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

import pytest

import common_lore_index.ops.resource_reports._delivery as delivery
from common_lore_index.cli.main import main
from common_lore_index.coordinator.local_lifecycle import initialize_coordinator_control
from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home, local_graph_binding
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.storage import apply_migrations, default_rdbms_root
from common_lore_index.storage.sqlite_local import investigation_queries
from common_lore_index.storage.sqlite_local.connection import read_transaction
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.resource_report_cli_files import (
    TEMP_PREFIX, private_directory, report_leftovers, report_payload,
)
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, binding_id_for_alias, materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home


GRAPH = "report-exception-int"


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
    return ["ops", "refresh-graph", "--repo-map-home", str(home), "--graph", GRAPH,
            "--json", "--resource-report", str(target)]


def _fd_count() -> int:
    return len(os.listdir("/dev/fd"))


def _interrupt_after_install(
    monkeypatch: pytest.MonkeyPatch, reports: Path,
    delivery_interrupt: KeyboardInterrupt, close_interrupt: BaseException,
) -> None:
    identity = (os.stat(reports).st_dev, os.stat(reports).st_ino)
    real_fsync = delivery.os.fsync

    def fsync(descriptor: int) -> None:
        details = os.fstat(descriptor)
        real_fsync(descriptor)
        if (details.st_dev, details.st_ino) == identity:
            raise delivery_interrupt

    real_close = delivery.os.close

    def close(descriptor: int) -> None:
        try:
            details = os.fstat(descriptor)
        except OSError:
            return real_close(descriptor)
        real_close(descriptor)
        if (details.st_dev, details.st_ino) == identity:
            raise close_interrupt

    monkeypatch.setattr(delivery.os, "fsync", fsync)
    monkeypatch.setattr(delivery.os, "close", close)


def _fail_report_link(monkeypatch: pytest.MonkeyPatch) -> None:
    real_link = delivery.os.link

    def link(source: Any, target: Any, *args: Any, **kwargs: Any) -> Any:
        if str(source).startswith(TEMP_PREFIX):
            raise OSError(5, "injected report install failure")
        return real_link(source, target, *args, **kwargs)

    monkeypatch.setattr(delivery.os, "link", link)


class _BrokenWarningSink:
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def write(self, text: str) -> int:
        self.attempts.append(text)
        raise OSError("stderr sink")

    def flush(self) -> None:
        return None


def test_local_post_commit_delivery_interrupt_keeps_original_and_installed_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, reports, config = _local(tmp_path, capsys)
    target = reports / "installed.json"
    delivery_interrupt = KeyboardInterrupt()
    _interrupt_after_install(monkeypatch, reports, delivery_interrupt, SystemExit(19))
    before = _fd_count()
    with pytest.raises(BaseException) as raised:
        main(_refresh(home, target))
    captured = capsys.readouterr()
    assert raised.value is delivery_interrupt
    result = json.loads(captured.out)
    assert (result["graph_id"], result["accepted_generation"]) == (GRAPH, 1)
    report_payload(target, operation="local_refresh", backend="sqlite", outcome="published",
                   forbidden=(home, GRAPH, tmp_path))
    assert report_leftovers(reports) == []
    assert _latest_run(config) == 1 and _fd_count() == before


def test_local_link_failure_and_warning_sink_preserve_code_stdout_and_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, reports, config = _local(tmp_path, capsys)
    target = reports / "warning.json"
    sink = _BrokenWarningSink()
    _fail_report_link(monkeypatch)
    monkeypatch.setattr(sys, "stderr", sink)
    before = _fd_count()
    code = main(_refresh(home, target))
    captured = capsys.readouterr()
    assert code == 0
    result = json.loads(captured.out)
    assert (result["graph_id"], result["accepted_generation"]) == (GRAPH, 1)
    assert sink.attempts and not target.exists()
    assert report_leftovers(reports) == []
    assert _latest_run(config) == 1 and _fd_count() == before


def _server_home(tmp_path: Path, postgres: Any) -> tuple[Path, Path]:
    working_copy = materialize_mixed_v1_working_copy(tmp_path / "working-copy")
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
    return home, working_copy


def test_server_post_commit_delivery_interrupt_keeps_publication_and_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    reports = private_directory(tmp_path / "reports")
    target = reports / "server-installed.json"
    with temporary_postgres() as postgres:
        home, working_copy = _server_home(tmp_path, postgres)
        delivery_interrupt = KeyboardInterrupt()
        _interrupt_after_install(monkeypatch, reports, delivery_interrupt, RuntimeError("close"))
        before = _fd_count()
        with pytest.raises(BaseException) as raised:
            main([
                "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
                "--psql-command", postgres.psql_command, "--json", "--resource-report", str(target),
            ])
        captured = capsys.readouterr()
        assert raised.value is delivery_interrupt
        assert json.loads(captured.out)["result"] == "success"
        report_payload(
            target, operation="server_refresh", backend="postgresql", outcome="committed",
            forbidden=(home, working_copy, postgres.password, MIXED_V1_GRAPH_ID,
                       binding_id_for_alias("core"), binding_id_for_alias("companion")),
        )
        assert report_leftovers(reports) == [] and _fd_count() == before
        monkeypatch.undo()
        assert main([
            "ops", "graph-summary", "--repo-map-home", str(home), "--graph", MIXED_V1_GRAPH_ID,
            "--psql-command", postgres.psql_command, "--json",
        ]) == 0
        assert isinstance(json.loads(capsys.readouterr().out), dict)
