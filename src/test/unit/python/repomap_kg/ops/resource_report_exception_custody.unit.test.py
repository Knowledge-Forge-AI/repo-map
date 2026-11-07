"""Exact report exception custody and warning-sink failure boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Callable

import pytest

import common_lore_index.cli._ops_sqlite_dispatch as sqlite_dispatch
import common_lore_index.cli._resource_report_session as session_module
import common_lore_index.ops.resource_reports._delivery as delivery
from common_lore_index.cli.main import main
from common_lore_index.ops.resource_reports._delivery import DeliveryError
from common_lore_index.ops.resource_view import begin, finish_local
from repomap_test_support.resource_report_cli_files import private_directory, report_leftovers
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home


GRAPH = "report-exception"


def _home(tmp_path: Path) -> tuple[Path, Path]:
    source = write_shell_source(tmp_path / "src")
    return write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, source)), private_directory(tmp_path / "reports")


def _refresh(home: Path, target: Path) -> list[str]:
    return ["ops", "refresh-graph", "--repo-map-home", str(home), "--graph", GRAPH,
            "--json", "--resource-report", str(target)]


def _fake_refresh(raises: BaseException | None = None) -> Callable[..., Any]:
    def refresh(_config: Any, graph_id: str, **kwargs: Any) -> Any:
        observer = kwargs.get("resource_observer")
        begin(observer, "local_refresh", "sqlite")
        if raises is not None:
            raise raises
        result = SimpleNamespace(
            graph_id=graph_id, generation=1, reconciled=False,
            publication={"publication_bundle_id": "bundle1:fixture"},
            to_jsonable=lambda: {"accepted_generation": 1, "graph_id": graph_id, "result": "success"},
        )
        return finish_local(observer, result)
    return refresh


def _fd_count() -> int:
    return len(os.listdir("/dev/fd"))


def _raise_after_real_directory_close(
    monkeypatch: pytest.MonkeyPatch, reports: Path, secondary: BaseException,
) -> None:
    identity = (os.stat(reports).st_dev, os.stat(reports).st_ino)
    real_close = delivery.os.close

    def close(descriptor: int) -> None:
        try:
            details = os.fstat(descriptor)
        except OSError:
            return real_close(descriptor)
        if (details.st_dev, details.st_ino) == identity:
            real_close(descriptor)
            raise secondary
        real_close(descriptor)

    monkeypatch.setattr(delivery.os, "close", close)


@pytest.mark.parametrize("primary_kind", ("runtime", "keyboard", "system-exit"))
@pytest.mark.parametrize("secondary_kind", ("runtime", "keyboard", "system-exit"))
def test_uncaught_subject_identity_survives_distinct_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, primary_kind: str, secondary_kind: str,
) -> None:
    home, reports = _home(tmp_path)
    primary = {
        "runtime": RuntimeError("subject"), "keyboard": KeyboardInterrupt(),
        "system-exit": SystemExit(9),
    }[primary_kind]
    secondary = {
        "runtime": RuntimeError("cleanup"), "keyboard": KeyboardInterrupt(),
        "system-exit": SystemExit(17),
    }[secondary_kind]
    _raise_after_real_directory_close(monkeypatch, reports, secondary)
    monkeypatch.setattr(sqlite_dispatch, "refresh_local_graph", _fake_refresh(primary))
    before = _fd_count()
    target = reports / "never.json"
    with pytest.raises(BaseException) as raised:
        main(_refresh(home, target))
    assert raised.value is primary
    assert not target.exists() and report_leftovers(reports) == []
    assert _fd_count() == before


def test_delivery_interrupt_survives_cleanup_failure_after_real_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, reports = _home(tmp_path)
    target = reports / "installed.json"
    delivery_interrupt = KeyboardInterrupt()
    secondary = SystemExit(19)
    identity = (os.stat(reports).st_dev, os.stat(reports).st_ino)
    real_fsync = delivery.os.fsync

    def fsync(descriptor: int) -> None:
        details = os.fstat(descriptor)
        real_fsync(descriptor)
        if (details.st_dev, details.st_ino) == identity:
            raise delivery_interrupt

    monkeypatch.setattr(delivery.os, "fsync", fsync)
    _raise_after_real_directory_close(monkeypatch, reports, secondary)
    monkeypatch.setattr(sqlite_dispatch, "refresh_local_graph", _fake_refresh())
    before = _fd_count()
    with pytest.raises(BaseException) as raised:
        main(_refresh(home, target))
    assert raised.value is delivery_interrupt
    assert '"accepted_generation": 1' in capsys.readouterr().out
    assert target.exists() and target.read_bytes().endswith(b"\n")
    assert report_leftovers(reports) == [] and _fd_count() == before


class _BrokenWarningSink:
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def write(self, text: str) -> int:
        self.attempts.append(text)
        raise OSError("stderr sink")

    def flush(self) -> None:
        return None


def test_warning_sink_failure_preserves_subject_code_and_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, reports = _home(tmp_path)
    target = reports / "warning.json"
    sink = _BrokenWarningSink()
    monkeypatch.setattr(sqlite_dispatch, "refresh_local_graph", _fake_refresh())
    monkeypatch.setattr(
        session_module, "deliver",
        lambda *_args: (_ for _ in ()).throw(DeliveryError("install_failed")),
    )
    monkeypatch.setattr(sys, "stderr", sink)
    code = main(_refresh(home, target))
    captured = capsys.readouterr()
    assert code == 0 and '"accepted_generation": 1' in captured.out
    assert sink.attempts and not target.exists() and report_leftovers(reports) == []
    assert json.loads(captured.out)["graph_id"] == GRAPH
