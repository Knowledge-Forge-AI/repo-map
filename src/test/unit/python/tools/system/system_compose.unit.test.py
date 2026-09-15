"""Unit tests for system compose topology override generation and inspection."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from tools.system.compose_topology import (
    APPLICATION_SERVICES,
    inspect_and_verify_topology,
    prepare_system_compose_topology,
)
from tools.system.config import SystemTestConfig, SystemTestError


def test_prepare_system_compose_topology_overrides(tmp_path: Path) -> None:
    compose_dir = tmp_path / "compose"
    repo_map_home = tmp_path / "repo_map_home"
    fixture_repo = tmp_path / "fixture_repo"
    fixture_repo.mkdir(parents=True)
    (fixture_repo / "main.py").write_text("print('hello')", encoding="utf-8")

    tree_sha = "c" * 40
    config = SystemTestConfig.create(
        candidate_tree_sha=tree_sha,
        run_id="run-compose-test",
    )

    with patch("tools.system.compose_topology.inspect_and_verify_topology") as mock_inspect:
        plan, base_compose, override_compose, _topology = prepare_system_compose_topology(
            compose_dir=compose_dir,
            repo_map_home=repo_map_home,
            fixture_repo=fixture_repo,
            repo_root=ROOT,
            config=config,
            server_port=58190,
            postgres_port=55440,
        )

        assert base_compose.exists()
        assert override_compose.exists()
        override_text = override_compose.read_text(encoding="utf-8")

        for svc in APPLICATION_SERVICES:
            assert f"image: {config.candidate_tag}" in override_text

        mock_inspect.assert_called_once()


def test_inspect_and_verify_topology_detects_forbidden_mount(tmp_path: Path) -> None:
    all_svcs: dict[str, Any] = {
        svc: {"image": "repomap-system-candidate:cccccccccccc", "volumes": []}
        for svc in APPLICATION_SERVICES
    }
    all_svcs["http"]["volumes"] = [
        {"type": "bind", "source": str((ROOT / "src").resolve()), "target": "/workspace/src"}
    ]
    fake_config = {"services": all_svcs}

    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = str(fake_config).replace("'", '"')
        mock_run.return_value = mock_proc

        with pytest.raises(SystemTestError, match="contains forbidden repository source mount"):
            inspect_and_verify_topology(
                compose_dir=tmp_path,
                repo_root=ROOT,
                candidate_tag="repomap-system-candidate:cccccccccccc",
            )


def test_inspect_and_verify_topology_detects_missing_application_service(tmp_path: Path) -> None:
    # Only 1 service present instead of all 5
    fake_config = {
        "services": {
            "http": {
                "image": "repomap-system-candidate:cccccccccccc",
                "volumes": [],
            }
        }
    }

    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = str(fake_config).replace("'", '"')
        mock_run.return_value = mock_proc

        with pytest.raises(SystemTestError, match="expected application service .* is missing"):
            inspect_and_verify_topology(
                compose_dir=tmp_path,
                repo_root=ROOT,
                candidate_tag="repomap-system-candidate:cccccccccccc",
            )


def test_inspect_and_verify_topology_detects_wrong_service_image(tmp_path: Path) -> None:
    all_svcs = {
        svc: {"image": "repomap-system-candidate:cccccccccccc", "volumes": []}
        for svc in APPLICATION_SERVICES
    }
    all_svcs["coordinator"]["image"] = "wrong-image:tag"
    fake_config = {"services": all_svcs}

    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = str(fake_config).replace("'", '"')
        mock_run.return_value = mock_proc

        with pytest.raises(SystemTestError, match="has image 'wrong-image:tag'"):
            inspect_and_verify_topology(
                compose_dir=tmp_path,
                repo_root=ROOT,
                candidate_tag="repomap-system-candidate:cccccccccccc",
            )


def test_inspect_and_verify_topology_accepts_named_volumes(tmp_path: Path) -> None:
    all_svcs = {
        svc: {
            "image": "repomap-system-candidate:cccccccccccc",
            "volumes": [
                {"type": "volume", "source": "admin-state", "target": "/repo-map-admin"},
                {"type": "tmpfs", "target": "/tmp"},
            ],
        }
        for svc in APPLICATION_SERVICES
    }
    fake_config = {"services": all_svcs}

    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = str(fake_config).replace("'", '"')
        mock_run.return_value = mock_proc

        result = inspect_and_verify_topology(
            compose_dir=ROOT / "tmp-compose",
            repo_root=ROOT,
            candidate_tag="repomap-system-candidate:cccccccccccc",
        )
        assert result == fake_config


def test_inspect_and_verify_topology_rejects_malformed_volume(tmp_path: Path) -> None:
    all_svcs: dict[str, Any] = {
        svc: {"image": "repomap-system-candidate:cccccccccccc", "volumes": []}
        for svc in APPLICATION_SERVICES
    }
    all_svcs["http"]["volumes"] = [{"source": "admin-state"}]  # missing "type"
    fake_config = {"services": all_svcs}

    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = str(fake_config).replace("'", '"')
        mock_run.return_value = mock_proc

        with pytest.raises(SystemTestError, match="malformed volume record"):
            inspect_and_verify_topology(
                compose_dir=tmp_path,
                repo_root=ROOT,
                candidate_tag="repomap-system-candidate:cccccccccccc",
            )


def test_wait_for_recovered_coordinator_job_state_progression_and_evidence(tmp_path: Path) -> None:
    import json
    from tools.system.scenario_recovery_wait import (
        derive_recovery_wait_budget,
        wait_for_recovered_coordinator_job,
    )
    budget = derive_recovery_wait_budget(
        lease_duration_seconds=10.0,
        retry_backoff_seconds=20.0,
        claim_deadline_seconds=5.0,
        execution_margin_seconds=10.0,
    )
    assert budget == 45.0

    timer = MagicMock()
    timer.remaining_for_test.return_value = 100.0

    states = ["starting", "running", "succeeded"]
    call_count = 0

    def fake_compose(*args, **kwargs):
        nonlocal call_count
        state = states[min(call_count, len(states) - 1)]
        call_count += 1
        res = MagicMock()
        res.returncode = 0
        res.stdout = json.dumps({"job": {"job_id": "j1", "state": state, "attempt_count": 2}})
        return res

    simulated_time = 0.0

    def fake_clock():
        nonlocal simulated_time
        return simulated_time

    def fake_sleep(dur):
        nonlocal simulated_time
        simulated_time += dur

    evidence: dict[str, Any] = {}
    job_info, observed_states = wait_for_recovered_coordinator_job(
        tmp_path, {}, timer, "j1",
        run_compose=fake_compose,
        clock=fake_clock,
        sleep=fake_sleep,
        wait_budget_seconds=45.0,
        coordinator_evidence=evidence,
    )
    assert job_info["state"] == "succeeded"
    assert observed_states == ["starting", "running", "succeeded"]
    assert evidence["latest_observed_state"] == "succeeded"
    assert evidence["observed_recovery_states"] == ["starting", "running", "succeeded"]
    assert evidence["effective_wait_budget_seconds"] == 45.0


def test_wait_for_recovered_coordinator_job_terminal_failure(tmp_path: Path) -> None:
    import json
    from tools.system.scenario_recovery_wait import wait_for_recovered_coordinator_job

    timer = MagicMock()
    timer.remaining_for_test.return_value = 100.0

    def fake_compose(*args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stdout = json.dumps({"job": {"job_id": "j1", "state": "failed"}})
        return res

    with pytest.raises(SystemTestError, match="reached non-successful terminal state 'failed'"):
        wait_for_recovered_coordinator_job(
            tmp_path, {}, timer, "j1",
            run_compose=fake_compose,
            clock=time.monotonic,
            sleep=lambda _: None,
            wait_budget_seconds=10.0,
        )


def test_wait_for_recovered_coordinator_job_no_progress_timeout(tmp_path: Path) -> None:
    import json
    from tools.system.config import SystemTimeoutError
    from tools.system.scenario_recovery_wait import wait_for_recovered_coordinator_job

    timer = MagicMock()
    timer.remaining_for_test.return_value = 500.0

    def fake_compose(*args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        res.stdout = json.dumps({"job": {"job_id": "j1", "state": "queued"}})
        return res

    sim_time = 0.0

    def fake_clock():
        return sim_time

    def fake_sleep(dur):
        nonlocal sim_time
        sim_time += dur

    with pytest.raises(SystemTimeoutError, match="stalled without progress"):
        wait_for_recovered_coordinator_job(
            tmp_path, {}, timer, "j1",
            run_compose=fake_compose,
            clock=fake_clock,
            sleep=fake_sleep,
            wait_budget_seconds=300.0,
            no_progress_timeout_seconds=10.0,
            poll_interval_seconds=2.0,
        )

