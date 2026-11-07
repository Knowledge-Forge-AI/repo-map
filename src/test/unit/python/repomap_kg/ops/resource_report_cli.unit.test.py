"""CLI attachment, offline inspection and result custody for ``--resource-report``."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import common_lore_index.cli._ops_refresh_dispatch as refresh_dispatch
import common_lore_index.cli._ops_sqlite_dispatch as sqlite_dispatch
import common_lore_index.cli._resource_report_session as session_module
import common_lore_index.cli.ops_context_commands as context_commands
from common_lore_index.cli.main import build_parser, main
from common_lore_index.ops.local_refresh import LocalRefreshError
from common_lore_index.ops.resource_reports._codec import encode_report
from common_lore_index.ops.resource_reports._delivery import DeliveryError
from common_lore_index.ops.resource_view import begin, finish_local
from common_lore_index.ops.resource_view._context_projection import unfinished_compact_context
from repomap_test_support.resource_report_cli_files import (
    limit, private_directory, report_leftovers, report_payload,
)
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_shell_source, write_sqlite_home

GRAPH = "report-local"


def _home(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = write_shell_source(tmp_path / "src")
    other = write_shell_source(tmp_path / "src2")
    home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, source) + graph_toml("other", other))
    return home, source, private_directory(tmp_path / "reports")


def _fake_refresh(calls: list[dict[str, Any]], *, raises: BaseException | None = None) -> Any:
    def refresh(_config: Any, graph_id: str, **kwargs: Any) -> Any:
        calls.append(kwargs)
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


def _refresh(home: Path, *extra: str) -> list[str]:
    return ["ops", "refresh-graph", "--repo-map-home", str(home), "--graph", GRAPH, "--json", *extra]


def _fd_count() -> int:
    return len(os.listdir("/dev/fd"))


def test_absent_option_is_byte_identical_and_forwards_no_observer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, source, reports = _home(tmp_path)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sqlite_dispatch, "refresh_local_graph", _fake_refresh(calls))
    plain_code = main(_refresh(home))
    plain = capsys.readouterr()
    target = reports / "refresh.json"
    observed_code = main(_refresh(home, "--resource-report", str(target)))
    observed = capsys.readouterr()
    assert (observed_code, observed.out, observed.err) == (plain_code, plain.out, plain.err)
    assert calls[0] == {} and set(calls[1]) == {"resource_observer"}
    payload = report_payload(
        target, operation="local_refresh", backend="sqlite", outcome="published",
        forbidden=(home, source, GRAPH, "bundle1:fixture"),
    )
    assert payload["instrumentation"] == "complete"
    assert {item["reason"] for item in payload["metrics"][2:6]} == {"not_started"}  # stages never entered
    assert report_leftovers(reports) == []


def test_caught_subject_failure_keeps_its_diagnostic_and_reports_unfinished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, _source, reports = _home(tmp_path)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        sqlite_dispatch, "refresh_local_graph", _fake_refresh(calls, raises=LocalRefreshError("graph-refused")),
    )
    target = reports / "failed.json"
    assert main(_refresh(home, "--resource-report", str(target))) == 1
    captured = capsys.readouterr()
    lines = captured.err.splitlines()
    assert "ERROR: graph-refused" in lines and not any("resource-report" in line for line in lines)
    report_payload(target, operation="local_refresh", backend="sqlite", outcome="not_recorded",
                   instrumentation="incomplete")


@pytest.mark.parametrize("error", (KeyboardInterrupt(), SystemExit(9), RuntimeError("uncaught")))
def test_uncaught_subject_exceptions_keep_exact_custody_and_leave_no_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException,
) -> None:
    home, _source, reports = _home(tmp_path)
    monkeypatch.setattr(sqlite_dispatch, "refresh_local_graph", _fake_refresh([], raises=error))
    before = _fd_count()
    with pytest.raises(type(error)) as raised:
        main(_refresh(home, "--resource-report", str(reports / "never.json")))
    assert raised.value is error
    assert os.listdir(reports) == []
    assert _fd_count() == before, "the held report directory must be closed"


def test_delivery_errors_warn_without_paths_and_preserve_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, _source, reports = _home(tmp_path)
    monkeypatch.setattr(sqlite_dispatch, "refresh_local_graph", _fake_refresh([]))
    plain_code = main(_refresh(home))
    plain = capsys.readouterr()
    monkeypatch.setattr(session_module, "deliver", lambda *_args: (_ for _ in ()).throw(DeliveryError("install_failed")))
    assert main(_refresh(home, "--resource-report", str(reports / "r.json"))) == plain_code
    captured = capsys.readouterr()
    assert captured.out == plain.out
    assert captured.err == plain.err + "WARNING: resource-report-not-delivered: install_failed\n"
    monkeypatch.setattr(session_module, "encode_report", lambda _report: (_ for _ in ()).throw(TypeError("x")))
    assert main(_refresh(home, "--resource-report", str(reports / "r2.json"))) == plain_code
    assert capsys.readouterr().err.endswith("WARNING: resource-report-not-delivered: report_unavailable\n")


def test_delivery_only_interrupt_propagates_after_stdout_is_fixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, _source, reports = _home(tmp_path)
    monkeypatch.setattr(sqlite_dispatch, "refresh_local_graph", _fake_refresh([]))
    interrupt = KeyboardInterrupt()
    monkeypatch.setattr(session_module, "deliver", lambda *_args: (_ for _ in ()).throw(interrupt))
    with pytest.raises(KeyboardInterrupt) as raised:
        main(_refresh(home, "--resource-report", str(reports / "r.json")))
    assert raised.value is interrupt
    assert '"accepted_generation": 1' in capsys.readouterr().out


def test_admission_refusals_precede_the_subject_and_name_no_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, source, reports = _home(tmp_path)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sqlite_dispatch, "refresh_local_graph", _fake_refresh(calls))
    existing = reports / "existing.json"
    existing.write_text("keep", encoding="utf-8")
    other_source = private_directory(tmp_path / "src2" / "out")
    cases = {
        str(existing): "destination_exists",
        str(private_directory(source / "out") / "r.json"): "protected_root_overlap",
        str(other_source / "r.json"): "protected_root_overlap",  # another graph's root
        str(private_directory(home / "state") / "r.json"): "protected_root_overlap",
        str(tmp_path / "absent" / "r.json"): "parent_missing",
    }
    for destination, category in cases.items():
        assert main(_refresh(home, "--resource-report", destination)) == 1
        err = capsys.readouterr().err
        assert err.endswith(f"ERROR: resource-report-refused: {category}\n"), err
        assert str(tmp_path) not in err
    assert calls == [] and existing.read_text(encoding="utf-8") == "keep"


def test_existing_cheap_refusals_precede_destination_admission(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    home, _source, reports = _home(tmp_path)
    existing = reports / "existing.json"
    existing.write_text("keep", encoding="utf-8")
    for extra, refusal in (
        (("--mode", "coordinator"), "sqlite-local-refresh-rejects-coordinator-mode"),
        (("--psql-command", "psql"), "sqlite-local-refresh-rejects-psql-command"),
    ):
        assert main(_refresh(home, *extra, "--resource-report", str(existing))) == 1
        err = capsys.readouterr().err
        assert refusal in err and "resource-report" not in err


def test_postgres_coordinator_refresh_refuses_report_attachment() -> None:
    printed: list[str] = []
    started: list[object] = []

    class CoordinatorModeError(ValueError):
        pass

    commands: Any = SimpleNamespace(
        CoordinatorModeError=CoordinatorModeError,
        run_coordinator_refresh=lambda *args, **kwargs: started.append(args),
    )
    args = argparse.Namespace(
        mode="coordinator", repo_map_home="home", config=None, idempotency_key="key",
        psql_command=None, backend_telemetry_fd=None, backend_telemetry_ack_fd=None,
        staging_event_fd=None, resource_report="report.json",
    )
    code = refresh_dispatch._refresh_graph(args, commands, lambda error, **_kw: printed.append(str(error)))
    assert code == 1 and started == []
    assert printed == ["resource-report-refused: coordinator_mode_unsupported"]


def test_ineligible_commands_have_no_report_option() -> None:
    for argv in (
        ["ops", "refresh-enabled", "--resource-report", "x"],
        ["ops", "context-select", "--graph", "g", "--binding", "b", "--output", "o", "--resource-report", "x"],
        ["--resource-report", "x", "ops", "graphs"],
    ):
        with pytest.raises(SystemExit):
            build_parser().parse_args(argv)


def test_one_namespace_owns_one_session_and_one_admission(tmp_path: Path) -> None:
    reports = private_directory(tmp_path / "reports")
    args = argparse.Namespace(resource_report=str(reports / "r.json"))
    session = session_module.report_session(args)
    assert session is session_module.report_session(args)
    assert session_module.report_observer_kwargs(session) == {}
    config = SimpleNamespace(config_home=str(tmp_path / "home"), config_path=None, graphs=())
    session_module.admit_report(args, config)
    assert set(session_module.report_observer_kwargs(session)) == {"resource_observer"}
    with pytest.raises(session_module.ResourceReportRefusal, match="already_admitted"):
        session_module.admit_report(args, config)
    session_module.release_report_session(args)
    assert session is not None and not session.admitted
    assert session_module.report_session(argparse.Namespace()) is None


class _Adapter:
    def __init__(self, **_kwargs: Any) -> None:
        pass

    def __enter__(self) -> Any:
        return SimpleNamespace(backend="sqlite")

    def __exit__(self, *_exc: object) -> None:
        return None


def test_context_pack_projects_the_returned_packet_without_injecting_a_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, source, reports = _home(tmp_path)
    ledgers: list[Any] = []

    def build(_request: Any, port: Any, *, freshness: Any, **kwargs: Any) -> dict[str, Any]:
        ledger = kwargs.get("work_ledger")
        ledgers.append(ledger)
        if ledger is not None:
            assert ledger.backend == port.backend
            ledger.sql_statements_executed = 2
        return {"status": "complete", "scope": {"backend": "sqlite"},
                "work_ledger": {"sql_statements_executed": 2}, "request": {"budget_bytes": 16384}}

    monkeypatch.setattr(context_commands, "SqliteContextReadAdapter", _Adapter)
    monkeypatch.setattr(context_commands, "build_compact_context", build)
    argv = ["ops", "context-pack", "--repo-map-home", str(home), "--graph", GRAPH,
            "--mode", "ranked_discovery", "--query", "q"]
    assert main(argv) == 0
    plain = capsys.readouterr()
    target = reports / "context.json"
    assert main([*argv, "--resource-report", str(target)]) == 0
    observed = capsys.readouterr()
    assert (observed.out, observed.err) == (plain.out, plain.err)
    assert ledgers == [None, None]
    payload = report_payload(target, operation="compact_context", backend="sqlite", outcome="complete",
                             forbidden=(home, source, GRAPH))
    assert limit(payload, "wall_clock_deadline")["applies_this_call"] is None


def test_context_early_placeholder_packets_never_attach_a_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    home, source, _reports = _home(tmp_path)
    inside_source = private_directory(source / "out") / "r.json"
    code = main(["ops", "context-pack", "--repo-map-home", str(home), "--graph", GRAPH,
                 "--mode", "literal_captured_text", "--query", "q", "--resource-report", str(inside_source)])
    assert code == 1
    assert '"capability_not_admitted"' in capsys.readouterr().out
    assert not inside_source.exists()


def test_context_owner_failure_after_admission_reports_no_guessed_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    home, _source, reports = _home(tmp_path)

    def failing(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("adapter-unavailable")

    monkeypatch.setattr(context_commands, "SqliteContextReadAdapter", failing)
    target = reports / "context.json"
    assert main(["ops", "context-pack", "--repo-map-home", str(home), "--graph", GRAPH,
                 "--mode", "ranked_discovery", "--query", "q", "--resource-report", str(target)]) == 1
    assert capsys.readouterr().err.startswith("ERROR: adapter-unavailable")
    payload = report_payload(target, operation="compact_context", backend=None, outcome="not_recorded")
    assert {item["reason"] for item in payload["metrics"]} == {"not_reached"}


def _write_report(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def test_offline_check_and_show_open_no_home_config_or_product_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    reports = private_directory(tmp_path / "reports")
    data = encode_report(unfinished_compact_context())
    valid = _write_report(reports / "valid.json", data)
    for name in ("_resolve_home_selection", "dispatch_command", "dispatch_ops_sqlite_command",
                 "dispatch_config_migration", "load_ops_config_home"):
        assert name in main.__globals__
        monkeypatch.setitem(main.__globals__, name, lambda *_a, **_k: (_ for _ in ()).throw(AssertionError(name)))
    monkeypatch.setenv("CLOE_HOME", str(tmp_path / "missing-home"))
    assert main(["ops", "resource-report", "check", "--input", str(valid)]) == 0
    assert capsys.readouterr().out.startswith("valid cloe-resource-view-v1: operation compact_context")
    assert main(["ops", "resource-report", "show", "--input", str(valid), "--json"]) == 0
    assert capsys.readouterr().out.encode("utf-8") == data
    assert main(["ops", "resource-report", "show", "--input", str(valid)]) == 0
    assert "outcome: not_recorded" in capsys.readouterr().out
    invalid = _write_report(reports / "invalid.json", data[:-1] + b"\r\n")
    assert main(["ops", "resource-report", "check", "--input", str(invalid)]) == 1
    captured = capsys.readouterr()
    assert captured.err == "ERROR: resource-report-invalid: not_canonical\n" and captured.out == ""
    assert main(["ops", "resource-report", "show", "--input", str(reports / "absent.json")]) == 1
    assert capsys.readouterr().err == "ERROR: resource-report-invalid: unreadable\n"
