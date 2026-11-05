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


@pytest.mark.parametrize("available", [True, False])
def test_discovery_only_probe_uses_signal_seam_without_changing_config(tmp_path, monkeypatch, available):
    from repomap_test_support import resource_run
    from repomap_test_support.resource_admission import decide_host_admission
    from repomap_test_support.resource_hygiene_policy import HygieneConfig, HygieneProfile
    from repomap_test_support.runner_recovery_probe import RecoveryResourceRun

    config = HygieneConfig()
    calls = []

    def admit(cls, layout, **kwargs):
        calls.append((cls, layout, kwargs))
        return None

    monkeypatch.setattr(resource_run, "admit_resource_run", admit)
    monkeypatch.setattr(RecoveryResourceRun, "capacity_available", available)
    assert RecoveryResourceRun.start(tmp_path, config=config, profile=HygieneProfile.INTEGRATION) is None
    cls, layout, kwargs = calls.pop()
    assert cls is RecoveryResourceRun and layout is tmp_path and kwargs["config"] is config
    decision = decide_host_admission(HygieneProfile.INTEGRATION, config, kwargs["host_signals"])
    assert decision.admitted is available
    assert decision.reason == ("integration" if available else "free_disk_reserve")
    assert kwargs["quota_override"] is None and kwargs["declared_complete_gates"] == 0


def test_discovery_probe_refuses_conflicting_inputs_and_workload(tmp_path):
    from repomap_test_support.runner_recovery_probe import RecoveryResourceRun, refuse_workload, run_probe, probe_command

    with pytest.raises(ValueError, match="conflicting host signals"):
        RecoveryResourceRun.start(tmp_path, host_signals=None)
    for call in (lambda: run_probe(tmp_path, capacity_available=json.loads("1")),
                 lambda: probe_command(tmp_path, tmp_path, capacity_available=json.loads("1"))):
        with pytest.raises(ValueError, match="explicit capacity fixture"):
            call()
    with pytest.raises(AssertionError, match="must never execute tests"):
        refuse_workload()


@pytest.mark.parametrize("available", [True, False])
def test_probe_invokes_canonical_entrypoint_with_workload_refusal_and_restores(tmp_path, monkeypatch, available):
    import run_tests
    from repomap_test_support import runner_recovery_probe
    from repomap_test_support.runner_recovery_probe import MISSING_SELECTOR, RecoveryResourceRun, refuse_workload, run_probe

    original = run_tests.TestResourceRun, run_tests.run_pytest, run_tests.run_pytest_with_coverage
    monkeypatch.setattr(runner_recovery_probe, "active_sandbox", lambda: True)

    def main(args):
        assert args == ["--suite", "int", "--no-coverage", "--jobs", "1", "--report-dir", str(tmp_path), "--", MISSING_SELECTOR]
        assert run_tests.TestResourceRun is RecoveryResourceRun
        assert RecoveryResourceRun.capacity_available is available
        assert run_tests.run_pytest is refuse_workload and run_tests.run_pytest_with_coverage is refuse_workload
        with pytest.raises(AssertionError, match="must never execute tests"):
            run_tests.run_pytest(None, [], None)
        return 17

    monkeypatch.setattr(run_tests, "main", main)
    assert run_probe(tmp_path, capacity_available=available) == 17
    assert (run_tests.TestResourceRun, run_tests.run_pytest, run_tests.run_pytest_with_coverage) == original


def test_discovery_probe_refuses_outside_sandbox_before_dispatch(tmp_path, monkeypatch):
    import run_tests
    from repomap_test_support import runner_recovery_probe

    monkeypatch.setattr(runner_recovery_probe, "active_sandbox", lambda: False)
    monkeypatch.setattr(run_tests, "main", lambda args: pytest.fail("unexpected canonical re-dispatch"))
    with pytest.raises(RuntimeError, match="requires the active integration sandbox"):
        runner_recovery_probe.run_probe(tmp_path, capacity_available=True)
