"""First runner infrastructure failure survives later cleanup failure (ADR 0115)."""
from pathlib import Path
import errno
import json
from typing import Any

import go_runner_coverage
import pytest
import runner_integration_execution as execution
from src.test.unit.python.tools import staging_execution_fixtures as fixtures
from staging_report_contract import execution_succeeded, qualifies


@pytest.mark.parametrize("first", ["identity", "discovery"])
def test_first_cause_survives_secondary_go_restore_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], first: str,
) -> None:
    marker = "opaque-sensitive-fixture"
    original_install = fixtures._install_fakes

    def bad_identity(_root: Path) -> dict[str, str]:
        raise FileNotFoundError(errno.ENOENT, marker)

    def install(*args: Any, **kwargs: Any) -> Any:
        values = original_install(*args, **kwargs)
        if first == "identity":
            monkeypatch.setattr(execution, "candidate_identity", bad_identity)
        return values

    def bad_restore() -> None:
        raise OSError(errno.EIO, marker)

    monkeypatch.setattr(fixtures, "_install_fakes", install)
    monkeypatch.setattr(go_runner_coverage, "restore_go_environment", bad_restore)
    result, path, order, _environment, _sessions = fixtures._execute(
        monkeypatch, tmp_path, no_coverage=True, collection_exit=2,
    )
    assert result == 1
    assert order == ([] if first == "identity" else ["collect"])
    records = list(path.parent.glob("runner_failure_report.*.json"))
    assert len(records) == 1
    evidence = json.loads(records[0].read_text())
    assert evidence["primary"]["type"] == ("FileNotFoundError" if first == "identity" else "RuntimeError")
    assert evidence["primary"]["stage"] == ("candidate_identity" if first == "identity" else "discovery_collection")
    assert any(item["stage"] == "go_cleanup" and item["type"] == "OSError" for item in evidence["secondary"])
    assert evidence["execution_succeeded"] is False
    assert evidence["partition_state"] == "not_established"
    if first == "identity":
        assert evidence["candidate_at_start"] is None
    report = json.loads(path.read_text())
    assert report["partition"] == {}
    assert not execution_succeeded(report) and not qualifies(report)
    assert marker not in records[0].read_text() + capsys.readouterr().err


@pytest.mark.parametrize("signal", [None, KeyboardInterrupt, SystemExit])
def test_session_cleanup_continues_after_first_failure(tmp_path, monkeypatch, signal):
    cleaned = []

    def cleanup(session):
        cleaned.append(session.session_dir.name)
        if len(cleaned) == 1:
            raise (signal() if signal else OSError(errno.EIO, "opaque-fixture"))
        session.cleaned = True

    monkeypatch.setattr(fixtures.FakeSession, "cleanup", cleanup)
    if signal:
        with pytest.raises(signal):
            fixtures._execute(monkeypatch, tmp_path)
        path = tmp_path / "reports/int/latest/staging_contract_report.json"
    else:
        result, path, _order, _env, sessions = fixtures._execute(monkeypatch, tmp_path)
        assert result == 1 and sessions[-1].cleaned
    assert len(cleaned) == 2
    report = json.loads(path.read_text())
    assert not execution_succeeded(report)
    evidence = json.loads(next(path.parent.glob("runner_failure_report.*.json")).read_text())
    assert evidence["primary"]["stage"] == "measurement_cleanup"


def test_smoke_identity_refusal_persists_candidate_null_and_own_diagnostic(tmp_path, monkeypatch):
    def refuse(_root):
        raise PermissionError(errno.EACCES, "opaque-fixture")

    monkeypatch.setattr(execution, "candidate_identity", refuse)
    execution.record_smoke_refusal(fixtures._args(tmp_path, no_coverage=True))
    root = tmp_path / "reports/staging/latest"
    report = json.loads((root / "staging_contract_report.json").read_text())
    diagnostic = json.loads(next(root.glob("runner_failure_report.*.json")).read_text())
    assert report["candidate"] is None and report["partition"] == {}
    assert diagnostic["invocation_id"] == report["invocation_id"]
    assert diagnostic["primary"]["type"] == "PermissionError"
    assert not execution_succeeded(report) and not qualifies(diagnostic)


def test_ordinary_test_failure_has_no_invented_exception_diagnostic(tmp_path, monkeypatch):
    result, path, _order, _env, _sessions = fixtures._execute(monkeypatch, tmp_path, failure_leg="M")
    assert result == 1 and not execution_succeeded(json.loads(path.read_text()))
    assert not list(path.parent.glob("runner_failure_report.*.json"))


def test_abrupt_failure_after_successful_source_callback_keeps_execution_stage(tmp_path, monkeypatch):
    original = fixtures._install_fakes

    def install(*args, **kwargs):
        values = list(original(*args, **kwargs))
        run = values[3]

        def fail_abrupt(module, pytest_args, plugin):
            if plugin.leg == "A":
                plugin.abrupt_context.verify_source()
                raise LookupError("opaque-fixture")
            return run(module, pytest_args, plugin)

        values[3] = fail_abrupt
        return values

    monkeypatch.setattr(fixtures, "_install_fakes", install)
    result, path, _order, _env, _sessions = fixtures._execute(monkeypatch, tmp_path, no_coverage=True)
    diagnostic = json.loads(next(path.parent.glob("runner_failure_report.*.json")).read_text())
    assert result == 1
    assert diagnostic["primary"]["stage"] == "execute_A" and diagnostic["primary"]["type"] == "LookupError"


def test_non_exception_measurement_flag_retains_only_actual_validation_exception(tmp_path, monkeypatch):
    result, path, _order, _env, _sessions = fixtures._execute(
        monkeypatch, tmp_path, incomplete_leg="M", instrumentation_value=True,
    )
    report = json.loads(path.read_text())
    diagnostic = json.loads(next(path.parent.glob("runner_failure_report.*.json")).read_text())
    assert result == 1 and report["legs"]["M"]["measurement"]["state"] == "incomplete"
    assert "M: ordinary measurement incomplete" in report["errors"]
    assert diagnostic["primary"]["stage"] == "report_validation"
    assert diagnostic["primary"]["type"] == "StagingReportValidationError"
    assert not any(item["stage"].startswith("measurement_") for item in diagnostic["secondary"])
