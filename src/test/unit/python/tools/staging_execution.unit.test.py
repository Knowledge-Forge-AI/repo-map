from dataclasses import replace
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import runner_integration_execution as execution
import json
from typing import Any
from staging_report_contract import SCHEMA, SCHEMA_V1, execution_succeeded, load_report, qualifies, validate_report
from src.test.unit.python.tools.staging_execution_fixtures import (
    IDENTITY, _args, _execute, _install_fakes, _summary,
)


def test_pass_pass_runs_measured_then_abrupt_once_and_qualifies(monkeypatch, tmp_path):
    result, path, order, _coverage_env, sessions = _execute(monkeypatch, tmp_path, staging=True)
    report = load_report(path)

    validate_report(report)
    assert result == 0
    assert order == ["collect", "M", "A"]
    assert execution_succeeded(report)
    assert qualifies(report)
    assert all(session.cleaned for session in sessions)
    optional = report["partition"]["optional"]  # persisted beside, never inside, deferred debt
    assert optional["count"] == 1 and optional["raw_count"] == len(report["partition"]["collected"]) + 1
    assert report["partition"]["deferred"] == []
    assert optional["excluded"][0]["nodeid"] not in report["partition"]["collected"]


def test_report_refuses_an_unreconciled_or_missing_optional_owner_record(monkeypatch, tmp_path):
    _result, path, _order, _coverage_env, _sessions = _execute(monkeypatch, tmp_path, staging=True)
    report = load_report(path)
    changes: tuple[dict[str, Any] | None, ...] = ({"count": 0}, {"raw_count": 1}, {"excluded": []}, None, {})
    for change in changes:
        broken = json.loads(json.dumps(report))
        broken["partition"]["optional"] = None if change is None else {**broken["partition"]["optional"], **change}
        if change == {}:  # a pre-ADR 0088 v1 report has no record at all
            del broken["partition"]["optional"]
        with pytest.raises(ValueError, match=r"optional-owner|partition missing \['optional'\]"):
            validate_report(broken)
        assert not qualifies(broken) and not execution_succeeded(broken)


def test_v2_pins_the_registered_owner_and_v1_reports_keep_their_own_rules(monkeypatch, tmp_path):
    _result, path, _order, _coverage_env, _sessions = _execute(monkeypatch, tmp_path, staging=True)
    report = load_report(path)
    assert report["schema"] == SCHEMA == "repomap-staging-obligations-v2", report["schema"]
    entry = report["partition"]["optional"]["excluded"][0]
    for change in ({"reason": "optional owner"},
                   {"excluded": [{**entry, "nodeid": "src/test/int/python/other.int.test.py::test_t"}]}):
        broken = json.loads(json.dumps(report))
        broken["partition"]["optional"].update(change)
        with pytest.raises(ValueError, match="unregistered reason or node ID"):
            validate_report(broken)
    legacy = json.loads(json.dumps({**report, "schema": SCHEMA_V1}))  # a relabelled current report
    for current in (validate_report, lambda value: validate_report(value, legacy_v1=True)):
        with pytest.raises(ValueError, match=r"only by explicit legacy v1|unknown fields \['optional'\]"):
            current(legacy)  # current rules refuse the label; v1 rules refuse the v2-only record
    del legacy["partition"]["optional"]
    validate_report(legacy, legacy_v1=True)
    assert qualifies(legacy, legacy_v1=True) and not qualifies(legacy) and not execution_succeeded(legacy)
    with pytest.raises(ValueError, match="accepts only a v1 report"):
        validate_report(report, legacy_v1=True)


@pytest.mark.parametrize("failure_leg", ["M", "A"])
def test_assertion_failure_keeps_other_safe_leg_evidence(monkeypatch, tmp_path, failure_leg):
    result, path, order, _coverage_env, _sessions = _execute(
        monkeypatch, tmp_path, failure_leg=failure_leg
    )
    report = load_report(path)

    validate_report(report)
    assert result == 1
    assert order == ["collect", "M", "A"]
    assert not execution_succeeded(report)
    assert report["legs"][failure_leg]["status"] == "failed"


def test_incomplete_measured_coverage_fails_without_erasing_abrupt_evidence(monkeypatch, tmp_path):
    result, path, order, _coverage_env, _sessions = _execute(
        monkeypatch, tmp_path, incomplete_leg="M"
    )
    report = load_report(path)

    assert result == 1
    assert order == ["collect", "M"]
    assert report["legs"]["M"]["measurement"]["state"] == "incomplete"
    assert report["legs"]["A"]["status"] == "blocked"
    assert not execution_succeeded(report)


@pytest.mark.parametrize("unsafe", ["interrupt", "teardown"])
def test_unsafe_measured_leg_blocks_abrupt_leg(monkeypatch, tmp_path, unsafe):
    kwargs = {"interrupt_leg": "M"} if unsafe == "interrupt" else {"teardown_leg": "M"}
    result, path, order, _coverage_env, _sessions = _execute(monkeypatch, tmp_path, **kwargs)
    report = load_report(path)

    assert result == 1
    assert order == ["collect", "M"]
    assert report["legs"]["A"]["status"] == "blocked"
    assert not execution_succeeded(report)


def test_missing_collection_is_reported_without_running_a_leg(monkeypatch, tmp_path):
    result, path, order, _coverage_env, _sessions = _execute(
        monkeypatch, tmp_path, collection_exit=2
    )
    report = load_report(path)

    assert result == 1
    assert order == ["collect"]
    assert report["partition"] == {}
    assert "discovery collection: RuntimeError" in report["errors"]
    assert not execution_succeeded(report)


def test_rendering_failure_retains_machine_readable_records(monkeypatch, tmp_path):
    go_tmp = tmp_path / "go"
    go_tmp.mkdir()
    run_order, _coverage_env, _sessions, fake_run, fake_cov, environment, fake_discovery = _install_fakes(
        monkeypatch, report=True, go_tmp=go_tmp
    )

    def raising_writer(**_kwargs):
        raise RuntimeError("synthetic renderer failure")

    args = _args(tmp_path, report=True)
    result = execution.execute_staging_decision_b(
        args, ("int",), [], source_root=tmp_path, test_support_root=tmp_path,
        repo_root=tmp_path, pytest_module=SimpleNamespace(), pytest_args=[],
        pytest_environment_for_fn=environment, run_pytest_fn=fake_run,
        import_coverage_fn=lambda: object(), run_pytest_with_coverage_fn=fake_cov,
        coverage_policy=None, collect_coverage_summary_fn=lambda *_a, **_k: _summary(),
        report_coverage_fn=lambda _c: True, write_html_report_fn=raising_writer,
        forwarded_selection_args_fn=lambda _a: (),
        discovery_fn=fake_discovery,
    )
    report = load_report(args.report_dir / "int" / "latest" / "staging_contract_report.json")
    assert result == 1
    assert run_order == ["collect", "M", "A"]
    assert report["legs"]["M"]["records"]
    assert any("rendering" in error for error in report["errors"])


def test_source_drift_blocks_next_leg(monkeypatch, tmp_path):
    changed = {"commit": "f" * 40, "source_sha256": "a" * 64}
    result, path, order, _coverage_env, _sessions = _execute(
        monkeypatch, tmp_path, source_values=[IDENTITY.copy(), IDENTITY.copy(), IDENTITY.copy(), changed]
    )
    report = load_report(path)

    assert result == 1
    assert order == ["collect", "M"]
    assert report["legs"]["A"]["status"] == "blocked"
    assert "source verify: RuntimeError" in report["errors"]


def test_abrupt_go_directory_is_separate_and_restored(monkeypatch, tmp_path):
    go_tmp = tmp_path / "go"
    go_tmp.mkdir()
    result, path, order, coverage_env, _sessions = _execute(
        monkeypatch, tmp_path, go_tmp=go_tmp
    )
    report = load_report(path)

    assert result == 0
    assert order == ["collect", "M", "A"]
    assert coverage_env[0] == ("M", None)
    assert coverage_env[1][0] == "A"
    assert Path(coverage_env[1][1]).parent == go_tmp
    assert os.environ.get("GOCOVERDIR") is None
    assert execution_succeeded(report)


def test_no_coverage_is_diagnostic_and_does_not_qualify(monkeypatch, tmp_path):
    result, path, order, _coverage_env, _sessions = _execute(
        monkeypatch, tmp_path, no_coverage=True
    )
    report = load_report(path)

    assert result == 0
    assert order == ["collect", "M", "A"]
    assert execution_succeeded(report)
    assert not qualifies(report)


def test_contract_failure_has_actionable_report_diagnostic(monkeypatch, tmp_path, capsys):
    from dataclasses import replace
    summary = replace(_summary(), branch_percent=50.0)
    result, path, _, _, sessions = _execute(monkeypatch, tmp_path, coverage_summary=summary)
    report = load_report(path)
    assert result == 1
    assert "report validation: StagingReportValidationError" in report["errors"]
    assert "report validation" in capsys.readouterr().err
    assert all(session.cleaned for session in sessions)


@pytest.mark.parametrize("dimension", ["line", "branch"])
def test_independent_coverage_floor_failure_is_permanent(monkeypatch, tmp_path, dimension):
    summary = _summary()
    record = summary.files[0]
    if dimension == "line":
        summary = replace(summary, covered_lines=79, line_percent=79.0,
                          files=(replace(record, covered_lines=79, line_percent=79.0),))
    else:
        summary = replace(summary, covered_branches=79, branch_percent=79.0,
                          files=(replace(record, covered_branches=79, branch_percent=79.0),))
    result, path, order, _, sessions = _execute(monkeypatch, tmp_path, coverage_summary=summary)
    report = load_report(path)
    validate_report(report)
    assert result == 1 and order == ["collect", "M", "A"]
    assert report["legs"]["M"]["pytest_exit"] == 0
    assert report["legs"]["A"]["pytest_exit"] == 0
    assert not execution_succeeded(report) and not qualifies(report)
    assert all(session.cleaned for session in sessions)
    measured = report["legs"]["M"]["measurement"]["summary"]
    assert measured[f"{dimension}_percent"] == 79.0
    assert measured["branch_percent" if dimension == "line" else "line_percent"] == 100.0


def test_type_error_rendering_preserves_original_validation_failure(monkeypatch, tmp_path, capsys):
    def broken_renderer(**_kwargs):
        raise TypeError("synthetic renderer input error")

    summary = replace(_summary(), branch_percent=50.0)
    result, path, order, _, sessions = _execute(
        monkeypatch, tmp_path, coverage_summary=summary, report=True,
        report_writer=broken_renderer,
    )
    report = load_report(path)
    assert result == 1 and order == ["collect", "M", "A"]
    assert "report validation: StagingReportValidationError" in report["errors"]
    assert "report rendering: TypeError" in report["errors"]
    assert "StagingReportValidationError" in capsys.readouterr().err
    assert report["legs"]["M"]["records"] and report["legs"]["A"]["records"]
    assert all(session.cleaned for session in sessions)
