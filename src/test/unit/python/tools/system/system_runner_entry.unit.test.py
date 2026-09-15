"""Unit tests for hosted qualification and local rehearsal runner modes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from tools.system.candidate_image import CandidateImageMetadata
from tools.system.config import SystemTestError
from tools.system.runner_entry import run_system_suite


def _args(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "gate_request_json": None,
        "gate_kind": "main-system",
        "candidate_sha": "a" * 40,
        "candidate_tree": "b" * 40,
        "candidate_base_parent": "",
        "candidate_head_parent": "",
        "approval_id": "",
        "pr_number": "",
        "repository": "",
        "system_timeout": 1500,
        "report_dir": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_explicit_empty_gate_request_path_is_a_hard_refusal() -> None:
    with patch("tools.system.runner_entry.get_current_tree_sha", return_value="b" * 40):
        with pytest.raises(SystemTestError, match="gate request JSON path is empty"):
            run_system_suite(_args(gate_request_json=""), None, None)


def test_explicit_missing_gate_request_path_is_a_hard_refusal(tmp_path: Path) -> None:
    missing = tmp_path / "missing-request.json"
    with patch("tools.system.runner_entry.get_current_tree_sha", return_value="b" * 40):
        with pytest.raises(SystemTestError, match="gate request JSON file not found"):
            run_system_suite(_args(gate_request_json=str(missing)), None, None)


def test_hosted_request_rejects_mismatched_candidate_parent(tmp_path: Path) -> None:
    request_path = tmp_path / "gate-request.json"
    request_path.write_text(
        json.dumps(
            {
                "schema": "repomap-ci-gate-request-v1",
                "gate_kind": "main-system",
                "pr_number": 21,
                "base_branch": "main",
                "base_sha": "c" * 40,
                "head_branch": "staging",
                "head_sha": "d" * 40,
                "approval_id": "approval-1",
                "repository": "owner/repository",
            }
        ),
        encoding="utf-8",
    )
    with patch("tools.system.runner_entry.get_current_tree_sha", return_value="b" * 40):
        with pytest.raises(SystemTestError, match="candidate base parent mismatch"):
            run_system_suite(
                _args(
                    gate_request_json=str(request_path),
                    candidate_base_parent="e" * 40,
                    candidate_head_parent="d" * 40,
                ),
                None,
                None,
            )


def test_successful_local_rehearsal_never_authorizes_merge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_root = tmp_path / "run"
    plan = SimpleNamespace(env_file=tmp_path / "missing.env")
    metadata = CandidateImageMetadata(
        image_id="sha256:" + "1" * 64,
        image_tag="repomap-system-candidate:test",
        image_digest="sha256:" + "2" * 64,
        labels={},
        release_versions={},
    )
    cleanup = {
        "success": True,
        "terminal_absence_verified": True,
        "errors": [],
    }
    boundary = SimpleNamespace(client=object(), projection=lambda: {})

    with (
        patch("tools.system.runner_entry.get_current_tree_sha", return_value="b" * 40),
        patch("tools.system.runner_entry.materialize_fixture_repository"),
        patch(
            "tools.system.runner_entry.build_and_verify_candidate_image",
            return_value=metadata,
        ),
        patch(
            "tools.system.runner_entry.prepare_system_compose_topology",
            return_value=(plan, tmp_path / "compose.yml", tmp_path / "override.yml", {}),
        ),
        patch(
            "tools.system.runner_entry.execute_all_scenarios",
            return_value=((), {}, {}, "a" * 64),
        ),
        patch("tools.system.runner_entry.perform_system_cleanup", return_value=cleanup),
        patch("tools.system.runner_entry.write_system_report") as write_report,
    ):
        status = run_system_suite(
            _args(),
            SimpleNamespace(run_root=run_root, run_id="unit-run"),
            boundary,
        )

    assert status == 0
    report = write_report.call_args.args[0]
    assert report.execution_mode == "local_rehearsal"
    assert report.to_dict()["merge_authorized"] is False
    assert "local rehearsal" in capsys.readouterr().out.lower()


def test_early_failure_preserves_system_diagnostic(tmp_path: Path) -> None:
    report_dir = tmp_path / "system-report"
    missing = tmp_path / "missing-request.json"
    with patch("tools.system.runner_entry.get_current_tree_sha", return_value="b" * 40):
        with pytest.raises(SystemTestError, match="gate request JSON file not found"):
            run_system_suite(
                _args(gate_request_json=str(missing), report_dir=report_dir),
                None,
                None,
            )

    diag_path = report_dir / "repomap-system-gate-diagnostic.json"
    assert diag_path.exists()
    diag = json.loads(diag_path.read_text(encoding="utf-8"))
    assert diag["schema"] == "repomap-system-gate-diagnostic-v1"
    assert diag["phase"] == "setup"
    assert diag["error_category"] == "setup_failure"
    assert "not found" in diag["error_message"]
    assert diag["conclusion"] == "failure"
    assert diag["merge_authorized"] is False


def test_execute_system_run_cleans_up_when_load_plan_env_raises(tmp_path: Path) -> None:
    from tools.system.config import SystemDeadline, SystemTestConfig
    from tools.system.report import SystemSuiteResult
    from tools.system.runner_execution import execute_system_run
    from tools.system.scenario import MonotonicTimer

    config = SystemTestConfig.create(
        candidate_tree_sha="b" * 40,
        run_id="unit-run",
        execution_mode="local_rehearsal",
        report_dir=tmp_path / "report",
    )
    deadline = SystemDeadline(100.0, cleanup_reserve_seconds=20.0)
    timer = MonotonicTimer(total_budget_seconds=100.0, cleanup_reserve_seconds=20.0)
    cleanup_mock = MagicMock(return_value={"success": True, "errors": []})
    write_report_mock = MagicMock()
    plan_mock = SimpleNamespace(database="repomap", user="repomap")

    metadata = CandidateImageMetadata(
        image_id="sha256:" + "1" * 64,
        image_tag="repomap-system-candidate:test",
        image_digest="sha256:" + "2" * 64,
        labels={},
        release_versions={},
    )

    status = execute_system_run(
        repo_root=tmp_path,
        candidate_tree_sha="b" * 40,
        execution_mode="local_rehearsal",
        config=config,
        deadline=deadline,
        timer=timer,
        docker_boundary=SimpleNamespace(client=MagicMock(), projection=lambda: {}),
        fixture_dir=tmp_path / "fixture",
        compose_dir=tmp_path / "compose",
        repo_map_home=tmp_path / "home",
        evidence_dir=tmp_path / "evidence",
        system_start_epoch_env="1700000000.0",
        system_suite_result_cls=SystemSuiteResult,
        materialize_fixture_repository_fn=MagicMock(),
        build_and_verify_candidate_image_fn=MagicMock(return_value=metadata),
        prepare_system_compose_topology_fn=MagicMock(return_value=(plan_mock, tmp_path / "compose.yml", tmp_path / "override.yml", {})),
        execute_all_scenarios_fn=MagicMock(return_value=((), {}, {}, "digest")),
        load_plan_env_fn=MagicMock(side_effect=RuntimeError("env load failure")),
        perform_system_cleanup_fn=cleanup_mock,
        write_system_report_fn=write_report_mock,
    )
    assert status == 1
    cleanup_mock.assert_called_once()
    assert write_report_mock.called
    report = write_report_mock.call_args[0][0]
    assert report.passed is False


def test_execute_system_run_cleans_up_when_preserve_diagnostics_raises(tmp_path: Path) -> None:
    from tools.system.config import SystemDeadline, SystemTestConfig
    from tools.system.report import SystemSuiteResult
    from tools.system.runner_execution import execute_system_run
    from tools.system.scenario import MonotonicTimer

    config = SystemTestConfig.create(
        candidate_tree_sha="b" * 40,
        run_id="unit-run",
        execution_mode="local_rehearsal",
        report_dir=tmp_path / "report",
    )
    deadline = SystemDeadline(100.0, cleanup_reserve_seconds=20.0)
    timer = MonotonicTimer(total_budget_seconds=100.0, cleanup_reserve_seconds=20.0)
    cleanup_mock = MagicMock(return_value={"success": True, "errors": []})
    write_report_mock = MagicMock()
    plan_mock = SimpleNamespace(database="repomap", user="repomap")

    metadata = CandidateImageMetadata(
        image_id="sha256:" + "1" * 64,
        image_tag="repomap-system-candidate:test",
        image_digest="sha256:" + "2" * 64,
        labels={},
        release_versions={},
    )

    with patch("tools.system.runner_execution.ScenarioJournal.preserve_diagnostics", side_effect=RuntimeError("diag preserve explosion")):
        status = execute_system_run(
            repo_root=tmp_path,
            candidate_tree_sha="b" * 40,
            execution_mode="local_rehearsal",
            config=config,
            deadline=deadline,
            timer=timer,
            docker_boundary=SimpleNamespace(client=MagicMock(), projection=lambda: {}),
            fixture_dir=tmp_path / "fixture",
            compose_dir=tmp_path / "compose",
            repo_map_home=tmp_path / "home",
            evidence_dir=tmp_path / "evidence",
            system_start_epoch_env="1700000000.0",
            system_suite_result_cls=SystemSuiteResult,
            materialize_fixture_repository_fn=MagicMock(),
            build_and_verify_candidate_image_fn=MagicMock(return_value=metadata),
            prepare_system_compose_topology_fn=MagicMock(return_value=(plan_mock, tmp_path / "compose.yml", tmp_path / "override.yml", {})),
            execute_all_scenarios_fn=MagicMock(side_effect=RuntimeError("scenario failure")),
            load_plan_env_fn=MagicMock(return_value={}),
            perform_system_cleanup_fn=cleanup_mock,
            write_system_report_fn=write_report_mock,
        )
    assert status == 1
    cleanup_mock.assert_called_once()
    assert write_report_mock.called
    report = write_report_mock.call_args[0][0]
    assert report.passed is False
    assert "diagnostic preservation failed" in report.coordinator_evidence.get("secondary_diagnostic_error", "")


def test_execute_system_run_cleans_up_when_container_inventory_exhausts_budget(tmp_path: Path) -> None:
    from tools.system.config import SystemDeadline, SystemTestConfig
    from tools.system.report import SystemSuiteResult
    from tools.system.runner_execution import execute_system_run
    from tools.system.scenario import MonotonicTimer

    config = SystemTestConfig.create(
        candidate_tree_sha="b" * 40,
        run_id="unit-run",
        execution_mode="local_rehearsal",
        report_dir=tmp_path / "report",
    )
    current_time = [1000.0]

    def fake_clock() -> float:
        return current_time[0]

    deadline = SystemDeadline(total_budget_seconds=10.0, cleanup_reserve_seconds=2.0, clock=fake_clock)
    timer = MonotonicTimer(total_budget_seconds=10.0, cleanup_reserve_seconds=2.0, clock=fake_clock)
    cleanup_mock = MagicMock(return_value={"success": True, "errors": []})
    write_report_mock = MagicMock()
    plan_mock = SimpleNamespace(database="repomap", user="repomap")

    metadata = CandidateImageMetadata(
        image_id="sha256:" + "1" * 64,
        image_tag="repomap-system-candidate:test",
        image_digest="sha256:" + "2" * 64,
        labels={},
        release_versions={},
    )

    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()

    def advance_time(*_args: object, **_kwargs: object) -> tuple[tuple[()], dict[str, str], dict[str, str], str]:
        current_time[0] = 2000.0
        return ((), {}, {}, "digest")

    status = execute_system_run(
        repo_root=tmp_path,
        candidate_tree_sha="b" * 40,
        execution_mode="local_rehearsal",
        config=config,
        deadline=deadline,
        timer=timer,
        docker_boundary=SimpleNamespace(client=MagicMock(), projection=lambda: {}),
        fixture_dir=tmp_path / "fixture",
        compose_dir=compose_dir,
        repo_map_home=tmp_path / "home",
        evidence_dir=tmp_path / "evidence",
        system_start_epoch_env="1700000000.0",
        system_suite_result_cls=SystemSuiteResult,
        materialize_fixture_repository_fn=MagicMock(),
        build_and_verify_candidate_image_fn=MagicMock(return_value=metadata),
        prepare_system_compose_topology_fn=MagicMock(return_value=(plan_mock, tmp_path / "compose.yml", tmp_path / "override.yml", {})),
        execute_all_scenarios_fn=advance_time,
        load_plan_env_fn=MagicMock(return_value={}),
        perform_system_cleanup_fn=cleanup_mock,
        write_system_report_fn=write_report_mock,
    )
    assert status == 1
    cleanup_mock.assert_called_once()
    assert write_report_mock.called
    report = write_report_mock.call_args[0][0]
    assert report.passed is False
    assert "cleanup reserve budget exhausted before container inventory" in report.error_message
