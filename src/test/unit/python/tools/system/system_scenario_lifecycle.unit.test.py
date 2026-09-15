"""Unit tests for system scenario monotonic timer and lifecycle behaviors."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from tools.system.config import SystemTestError, SystemTimeoutError
from tools.system.scenario import (
    MonotonicTimer,
    _control_job_evidence,
    _publication_authority_evidence,
    _run_compose,
    _singleton_owner_evidence,
    execute_all_scenarios,
    step_1_packaged_cluster_readiness,
    step_2_durable_coordinator_execution,
    step_3_controlled_coordinator_interruption_recovery,
    step_4_idempotency_and_fencing,
    step_5_mcp_public_readback,
)


def test_monotonic_timer_budget_remaining() -> None:
    timer = MonotonicTimer(total_budget_seconds=100.0, cleanup_reserve_seconds=20.0)
    assert timer.remaining_for_test() > 0 and timer.elapsed() >= 0.0
    assert timer.clamp_timeout(30.0) == 30.0 and timer.clamp_timeout(200.0) <= 80.0


def test_monotonic_timer_raises_on_exhaustion() -> None:
    timer = MonotonicTimer(total_budget_seconds=10.0, cleanup_reserve_seconds=20.0)
    with pytest.raises(SystemTimeoutError, match="budget exhausted"):
        timer.check_budget()


def test_run_compose_success(tmp_path: Path) -> None:
    timer = MonotonicTimer(total_budget_seconds=100.0, cleanup_reserve_seconds=20.0)
    with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="output", stderr="")):
        assert _run_compose(tmp_path, ["ps"], timer=timer, env={"VAR": "1"}).returncode == 0


def test_run_compose_failure_raises(tmp_path: Path) -> None:
    timer = MonotonicTimer(total_budget_seconds=100.0, cleanup_reserve_seconds=20.0)
    with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="", stderr="compose error")):
        with pytest.raises(SystemTestError, match="compose error"):
            _run_compose(tmp_path, ["up"], timer=timer, check=True)


def test_durable_evidence_queries_use_their_authoritative_databases(tmp_path: Path) -> None:
    timer = MonotonicTimer(total_budget_seconds=100.0, cleanup_reserve_seconds=20.0)
    plan = MagicMock(database="repomap", user="repomap")
    plan.env_file.exists.return_value = False

    with patch("tools.system.scenario._run_compose") as run_compose:
        run_compose.return_value = MagicMock(returncode=0, stdout='{"job_id":"job-1"}\n', stderr="")

        _control_job_evidence(tmp_path, plan, timer, "job-1")
        control_call = run_compose.call_args
        assert control_call.args[1][control_call.args[1].index("--dbname") + 1] == "repomap_control"
        assert control_call.args[1][-2:] == ["--file", "-"]
        assert "WHERE j.job_id = :'job_id'" in control_call.kwargs["stdin_input"]

        _publication_authority_evidence(tmp_path, plan, timer, "job-1")
        graph_call = run_compose.call_args
        assert graph_call.args[1][graph_call.args[1].index("--dbname") + 1] == "repomap"
        assert graph_call.args[1][-2:] == ["--file", "-"]
        assert "WHERE gpa.job_id = :'job_id'" in graph_call.kwargs["stdin_input"]

        _singleton_owner_evidence(tmp_path, plan, timer)
        singleton_call = run_compose.call_args
        assert singleton_call.args[1][singleton_call.args[1].index("--dbname") + 1] == "repomap_control"
        assert "expires_at > now()" in singleton_call.kwargs["stdin_input"]


def test_step_1_packaged_cluster_readiness(tmp_path: Path) -> None:
    timer = MonotonicTimer(total_budget_seconds=500.0, cleanup_reserve_seconds=20.0)
    plan = MagicMock(server_host_port=58180)
    plan.env_file.exists.return_value = False

    with patch("tools.system.scenario._run_compose") as mock_compose, \
         patch("urllib.request.urlopen") as mock_urlopen:

        mock_resp = MagicMock(status=200)
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        mock_coord_health = MagicMock(stdout=json.dumps({"result": "ready", "health": {"status": "ready"}}))
        mock_ps = MagicMock(returncode=0, stdout="\n".join(
            json.dumps({"Service": s, "ID": f"cid-{s}"}) for s in ("postgres", "http", "coordinator")
        ) + "\n")
        mock_compose.side_effect = [MagicMock(returncode=0), MagicMock(returncode=0), MagicMock(returncode=0), mock_coord_health, mock_ps]

        result, service_ids = step_1_packaged_cluster_readiness(tmp_path, plan, timer)
        assert result.status == "passed"
        assert result.step_name == "packaged_cluster_readiness"
        assert service_ids.get("coordinator") == "cid-coordinator"


def test_step_2_and_3_coordinator_flow(tmp_path: Path) -> None:
    timer = MonotonicTimer(total_budget_seconds=500.0, cleanup_reserve_seconds=20.0)
    plan = MagicMock()
    plan.env_file.exists.return_value = False
    repo_map_home = tmp_path / "home"
    repo_map_home.mkdir(parents=True)

    initial_control = {
        "job_id": "job-999", "graph_id": "fixture", "state": "claimed", "current_attempt": 1,
        "idempotency_digest": hashlib.sha256(b"sys0-idemp-deadbeef").hexdigest(),
        "coordinator_instance_id": "inst-1", "singleton_fencing_epoch": 10, "graph_lease_fencing_epoch": 20,
    }
    recovered_control = {
        "job_id": "job-999", "graph_id": "fixture", "state": "succeeded", "current_attempt": 2,
        "coordinator_instance_id": "inst-2", "singleton_fencing_epoch": 11, "graph_lease_fencing_epoch": None,
    }
    authority = {
        "job_id": "job-999", "attempt": 2, "coordinator_instance_id": "inst-2",
        "singleton_fencing_epoch": 11, "graph_lease_fencing_epoch": 21, "latest_run_id": 42,
        "execution_route": "portable-worker-v1", "snapshot_manifest_id": "snapmanifest1:" + "1" * 64,
        "extraction_receipt_id": "receipt1:" + "2" * 64, "publication_bundle_id": "bundle1:" + "3" * 64,
        "graph_candidate_id": "cand1:" + "4" * 64,
    }
    with patch("subprocess.Popen") as mock_popen, \
         patch("tools.system.scenario._run_compose") as mock_compose, \
         patch("tools.system.scenario.secrets.token_hex", return_value="deadbeef"), \
         patch("tools.system.scenario._control_job_evidence", side_effect=[initial_control, recovered_control]), \
         patch("tools.system.scenario._publication_authority_evidence", return_value=authority), \
         patch(
             "tools.system.scenario.wait_for_replacement_coordinator",
             return_value={"instance_id": "inst-2", "fencing_epoch": 11, "status": "active"},
         ) as mock_replacement_readiness:

        def popen_side_effect(*args, **kwargs):
            (repo_map_home / "system_pause_trigger.ready").write_text("job_id=job-999\nattempt=1\n", encoding="utf-8")
            proc = MagicMock()
            proc.poll.side_effect = [None, None, -15]
            return proc

        def compose_side_effect(compose_dir, args, *a, **kw):
            res = MagicMock(returncode=0, stdout="")
            if "cat" in args and "/tmp/system_pause_trigger.ready" in args:
                res.stdout = "job_id=job-999\nattempt=1\n"
            elif "coordinator-job-status" in args:
                state, attempt = ("succeeded", 2) if mock_replacement_readiness.called else ("claimed", 1)
                res.stdout = json.dumps({"job": {"job_id": "job-999", "graph_id": "fixture", "state": state, "attempt_count": attempt}})
            elif "coordinator-health" in args:
                res.stdout = json.dumps({"result": "ready"})
            elif "ps" in args and "--all" in args:
                res.stdout = json.dumps({"Service": "coordinator", "State": "exited"}) + "\n"
            elif "coordinator-job-wait" in args:
                res.stdout = json.dumps({"result": "success", "job": {"job_id": "job-999", "state": "succeeded", "attempt_count": 2}})
            elif "refresh-status" in args:
                res.stdout = json.dumps({"graphs": [{"graph_id": "fixture", "latest_run_status": "complete", "latest_run_id": 42}]})
            return res

        mock_popen.side_effect = popen_side_effect
        mock_compose.side_effect = compose_side_effect

        res2, job_id, idemp_key, evidence = step_2_durable_coordinator_execution(
            tmp_path, repo_map_home, plan, timer
        )
        assert res2.status == "passed"
        assert job_id == "job-999"
        assert evidence["initial_singleton_fencing_epoch"] == 10
        assert evidence["attempt_1"] == 1

        res3, evidence = step_3_controlled_coordinator_interruption_recovery(
            tmp_path, repo_map_home, plan, job_id, idemp_key, evidence, timer
        )
        assert res3.status == "passed"
        assert evidence["publication_receipt"] == "run-42"
        assert evidence["recovered_terminal_state"] == "succeeded"
        assert evidence["latest_run_id"] == 42
        assert evidence["attempt_1"] == 1
        assert evidence["attempt_2"] == 2
        assert evidence["replacement_ready_instance_id"] == "inst-2"
        assert evidence["replacement_ready_singleton_fencing_epoch"] == 11
        readiness_args, readiness_kwargs = mock_replacement_readiness.call_args
        assert readiness_args == (tmp_path, plan, timer)
        assert readiness_kwargs["initial_instance_id"] == "inst-1"
        assert readiness_kwargs["initial_singleton_epoch"] == 10
        assert readiness_kwargs["owner_probe"] is _singleton_owner_evidence


def test_step_4_idempotency_and_fencing(tmp_path: Path) -> None:
    timer = MonotonicTimer(total_budget_seconds=500.0, cleanup_reserve_seconds=20.0)
    plan = MagicMock()
    plan.env_file.exists.return_value = False

    authority = {"job_id": "job-999", "attempt": 2, "coordinator_instance_id": "inst-2",
                 "singleton_fencing_epoch": 11, "graph_lease_fencing_epoch": 21, "latest_run_id": 42}
    with patch("tools.system.scenario._run_compose") as mock_compose, \
         patch("tools.system.scenario._publication_authority_evidence", return_value=authority):
        mock_resubmit = MagicMock(stdout=json.dumps({"result": "success", "replayed": True, "job": {"job_id": "job-999", "state": "succeeded"}}))
        mock_refresh_status = MagicMock(returncode=0, stdout=json.dumps({"graphs": [{"graph_id": "fixture", "latest_run_status": "complete", "latest_run_id": 42}]}))
        mock_compose.side_effect = [mock_resubmit, mock_refresh_status]

        res4, evidence = step_4_idempotency_and_fencing(
            tmp_path, plan, "job-999", "key-999",
            {"latest_run_id": 42, "publication_authority": authority}, timer
        )
        assert res4.status == "passed"
        assert evidence["duplicate_disposition"] == "coalesced_and_replayed"
        assert evidence["replayed"] is True


def test_step_5_mcp_public_readback(tmp_path: Path) -> None:
    timer = MonotonicTimer(total_budget_seconds=500.0, cleanup_reserve_seconds=20.0)
    plan = MagicMock()
    plan.env_file.exists.return_value = False

    rpc_responses = "\n".join(json.dumps(r) for r in (
        {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "repomap-kg", "version": "0.1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 1}},
        {"jsonrpc": "2.0", "id": 3, "result": {"isError": False, "structuredContent": {"graphs": [{"graph_id": "fixture"}]}}},
        {"jsonrpc": "2.0", "id": 4, "result": {"isError": False, "structuredContent": {"graph_id": "fixture", "repository_name": "fixture", "canonical_nodes": 5, "canonical_edges": 3}}},
        {"jsonrpc": "2.0", "id": 5, "result": {"isError": False, "structuredContent": {"matches": [{"canonical_key": "python.function:calc:add"}]}}},
    )) + "\n"

    with patch("tools.system.scenario._run_compose", return_value=MagicMock(returncode=0, stdout=rpc_responses)):
        res5, digest = step_5_mcp_public_readback(tmp_path, plan, timer)
        assert res5.status == "passed"
        assert digest is not None
        assert len(digest) == 64
        assert "canonical_semantic_sha256" in res5.details


def test_execute_all_scenarios_failure_duration(tmp_path: Path) -> None:
    from tools.system.scenario_journal import ScenarioJournal
    timer = MonotonicTimer(total_budget_seconds=500.0, cleanup_reserve_seconds=20.0)
    plan = MagicMock()
    config = MagicMock()
    journal = ScenarioJournal(report_dir=tmp_path)
    with patch("tools.system.scenario.step_1_packaged_cluster_readiness", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            execute_all_scenarios(tmp_path, tmp_path, plan, config, timer, journal=journal)
    results = journal.step_results()
    assert len(results) == 5
    assert results[0].status == "failed"
    assert results[0].duration_seconds >= 0.0
    assert results[1].status == "not_run"

