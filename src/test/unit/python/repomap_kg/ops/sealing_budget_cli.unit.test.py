"""CLI budget options, pre-configuration refusals, error branches and API guards."""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from typing import Any, cast

import pytest

import common_lore_index.cli._ops_refresh_dispatch as refresh_dispatch
import common_lore_index.cli._ops_sqlite_dispatch as sqlite_dispatch
from common_lore_index.artifacts.sealing_governance import SealingBudget, SealingBudgetExceeded
from common_lore_index.cli._sealing_budget_options import (
    sealing_budget_from_args,
    sealing_budget_kwargs,
)
from common_lore_index.cli.main import main
from common_lore_index.cli.parser import build_parser
from common_lore_index.ops._refresh_outcome import classify_refresh_failure, refresh_failure_code
from common_lore_index.ops.local_refresh import refresh_local_graph
from common_lore_index.ops.refresh import refresh_graph
from common_lore_index.ops.resource_view import ResourceObserver
from common_lore_index.storage.publication_phase_witness import PublicationPhase

REFRESH = ("ops", "refresh-graph", "--graph", "g")


def _parse(*argv: str) -> argparse.Namespace:
    return build_parser().parse_args(list(argv))


def test_budget_options_parse_into_one_budget_and_absent_options_forward_nothing() -> None:
    args = _parse(*REFRESH, "--sealing-max-read-bytes", "10", "--sealing-max-write-bytes", "0",
                  "--sealing-max-opens", "3", "--sealing-max-entries", "4", "--sealing-max-elapsed-ms", "86400000")
    assert sealing_budget_from_args(args) == SealingBudget(10, 0, 3, 4, 86_400_000)
    plain = _parse(*REFRESH)
    assert sealing_budget_kwargs(plain) == {} and plain.resource_report_schema is None


@pytest.mark.parametrize(("option", "value"), [
    ("--sealing-max-read-bytes", "-1"), ("--sealing-max-read-bytes", "1.5"),
    ("--sealing-max-read-bytes", "١"), ("--sealing-max-read-bytes", "9" * 20),
    ("--sealing-max-read-bytes", "9223372036854775808"), ("--sealing-max-elapsed-ms", "86400001"),
    ("--sealing-max-opens", ""), ("--sealing-max-entries", "+5"),
])
def test_invalid_budget_values_are_bounded_usage_errors(option: str, value: str, capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        _parse(*REFRESH, f"{option}={value}")
    assert raised.value.code == 2
    assert f"invalid sealing budget: {option}" in capsys.readouterr().err


@pytest.mark.parametrize(("argv", "code"), [
    ((*REFRESH, "--resource-report-schema", "2"), "resource-report-schema-requires-report"),
    (("ops", "lexical-query", "--graph", "g", "--query", "q", "--resource-report-schema", "1"),
     "resource-report-schema-requires-report"),
    ((*REFRESH, "--sealing-max-opens", "1", "--mode", "coordinator"), "sealing-budget-unsupported-mode"),
    ((*REFRESH, "--sealing-max-opens", "1", "--resource-report", "r.json"),
     "sealing-budget-requires-report-schema-2"),
    ((*REFRESH, "--sealing-max-opens", "1", "--resource-report", "r.json", "--resource-report-schema", "1"),
     "sealing-budget-requires-report-schema-2"),
])
def test_conflicts_refuse_before_any_configuration(argv, code: str, capsys, monkeypatch) -> None:
    def no_config(*args: object, **kwargs: object) -> None:
        raise AssertionError("configuration was read before the usage refusal")

    monkeypatch.setattr(sqlite_dispatch, "declared_storage_backend", no_config)
    with pytest.raises(SystemExit) as raised:
        main(list(argv))
    assert raised.value.code == 2 and code in capsys.readouterr().err


def test_schema_option_is_available_on_every_report_seam() -> None:
    for argv in (
        ("ops", "lexical-build", "--graph", "g"), ("ops", "lexical-query", "--graph", "g", "--query", "q"),
        ("ops", "lexical-revoke", "--graph", "g"), ("ops", "context-pack", "--graph", "g", "--mode", "ranked_discovery", "--query", "q"),
        REFRESH,
    ):
        args = _parse(*argv, "--resource-report", "r", "--resource-report-schema", "2")
        assert args.resource_report_schema == 2
    with pytest.raises(SystemExit):
        _parse(*REFRESH, "--resource-report", "r", "--resource-report-schema", "3")
    with pytest.raises(SystemExit):
        _parse("ops", "refresh-enabled", "--sealing-max-opens", "1")


def test_budget_without_a_report_and_budget_with_explicit_schema_two_are_admitted() -> None:
    from common_lore_index.cli._sealing_budget_options import refuse_sealing_conflicts

    parser = build_parser()
    for argv in ((*REFRESH, "--sealing-max-opens", "1"),
                 (*REFRESH, "--sealing-max-opens", "1", "--resource-report", "r", "--resource-report-schema", "2"),
                 (*REFRESH, "--resource-report", "r", "--resource-report-schema", "1"), REFRESH):
        refuse_sealing_conflicts(parser.parse_args(list(argv)), parser)


def test_local_dispatch_forwards_the_budget_only_when_selected_and_prints_the_limit(monkeypatch, capsys) -> None:
    seen: list[dict] = []

    def fake_refresh(config, graph, **kwargs):
        seen.append(kwargs)
        raise SealingBudgetExceeded("read_bytes")

    monkeypatch.setattr(sqlite_dispatch, "_local_config", lambda args: object())
    monkeypatch.setattr(sqlite_dispatch, "refresh_local_graph", fake_refresh)
    printed: list[str] = []

    def print_error(error: Exception, *, file: object) -> None:
        printed.append(str(error))

    args = _parse(*REFRESH, "--sealing-max-read-bytes", "5")
    assert sqlite_dispatch._handle_routed(args, print_error) == 1
    assert seen == [{"sealing_budget": SealingBudget(max_read_bytes=5)}]
    assert printed == ["sealing-budget-exceeded:read_bytes"]
    assert sqlite_dispatch._handle_routed(_parse(*REFRESH), print_error) == 1
    assert seen[-1] == {}


def test_server_dispatch_forwards_the_budget_only_when_selected(monkeypatch) -> None:
    calls: list[dict] = []

    class Commands(SimpleNamespace):
        def refresh_graph(self, config, graph, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace()

    commands = Commands(
        load_ops_config_from_args=lambda args: SimpleNamespace(),
        maintenance_activity_for_home=None, ConnectionTelemetryError=type("A", (Exception,), {}),
        MaintenanceUnavailableError=type("B", (Exception,), {}), OpsConfigError=type("C", (Exception,), {}),
        OpsRefreshError=type("D", (Exception,), {}), StagingEventTransportError=type("E", (Exception,), {}),
        StagingMeasurements=lambda: None, staging_event_channel_from_inherited_fd=lambda fd: None,
        refresh_result_to_jsonable=lambda config, results, command: {"result": "success"},
    )
    for argv, expected in (((*REFRESH, "--json"), {}),
                           ((*REFRESH, "--json", "--sealing-max-opens", "2"),
                            {"sealing_budget": SealingBudget(max_opens=2)})):
        assert refresh_dispatch._refresh_graph(_parse(*argv), cast(Any, commands), lambda *a, **k: None) == 0
        forwarded = {key: value for key, value in calls[-1].items() if key == "sealing_budget"}
        assert forwarded == expected


def test_classifier_gives_budget_refusals_positive_not_started_only() -> None:
    refusal = SealingBudgetExceeded("opens")
    assert classify_refresh_failure(PublicationPhase.NOT_ENTERED, refusal) == (
        "not_started", "resource_budget_exceeded",
    )
    assert classify_refresh_failure(PublicationPhase.ROLLED_BACK, refusal) == ("rolled_back", "worker_crash")
    assert classify_refresh_failure(PublicationPhase.FINAL_TRANSACTION, refusal) == (
        "commit_unknown", "publication_unknown",
    )
    interrupted = SealingBudgetExceeded("opens")
    interrupted.__cause__ = KeyboardInterrupt()
    assert classify_refresh_failure(PublicationPhase.NOT_ENTERED, interrupted)[1] == "cancelled"
    assert classify_refresh_failure(PublicationPhase.NOT_ENTERED, ValueError("x")) == ("not_started", "worker_crash")
    assert refresh_failure_code("resource_budget_exceeded") == "sealing-budget-exceeded"
    assert refresh_failure_code("worker_crash") == "refresh-failed"


@pytest.mark.parametrize("refresh", [refresh_local_graph, refresh_graph])
def test_python_api_refuses_a_budget_with_a_v1_observer_before_any_operation(refresh) -> None:
    observer = ResourceObserver()
    with pytest.raises(ValueError, match="sealing-budget-requires-report-schema-2"):
        refresh(object(), "g", resource_observer=observer, sealing_budget=SealingBudget(max_opens=1))
    assert observer.report().operation is None, "the observer never began"
