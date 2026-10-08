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
        from repomap_kg.coordinator._refresh_execution import SYSTEM_TEST_CONTROL_READBACK_TIMEOUT_SECONDS
        assert control_call.kwargs["timeout"] == SYSTEM_TEST_CONTROL_READBACK_TIMEOUT_SECONDS
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
        "source_generation": "sg1:source", "config_generation": "cg1:config",
        "extractor_generation": "eg1:extractor", "canonicalizer_generation": "kg1:canonicalizer",
    }
    recovered_control = {
        "job_id": "job-999", "graph_id": "fixture", "state": "succeeded", "current_attempt": 2,
        "coordinator_instance_id": "inst-2", "singleton_fencing_epoch": 11, "graph_lease_fencing_epoch": None,
        "attempt_history": [{"attempt": 1, "publication_state": "not_started", "instance_id": "inst-1", "singleton_epoch": 10}],
    }
    authority = {
        "repository_id": 1, "job_id": "job-999", "attempt": 2, "coordinator_instance_id": "inst-2",
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
            if "execute_final_transaction(connection, handoff)" in kw.get("stdin_input", ""):
                res.returncode = 1
                res.stderr = "SCALE5 stale publication fence"
            if "FROM graph_publication_authority AS gpa" in kw.get("stdin_input", ""):
                res.stdout = json.dumps({**authority, "files_count": 1, "runs_count": 1})
            elif any("system_pause_trigger.ready" in str(arg) for arg in args):
                res.stdout = 'job_id=job-999\nattempt=1\nhandoff={"repository_id":1,"stage_id":"stage-old","run_id":1,"receipt":{"publication_job_id":"job-999","publication_attempt":1}}\n'
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
        assert evidence["orphan_publication_fence_rejected"] is True
        assert evidence["prior_attempt_reconciliation"]["publication_state"] == "not_started"
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


def test_marker_consumer_observes_marker_before_producer_timeout(tmp_path: Path) -> None:
    from tools.system.scenario_publication import _wait_for_marker
    timer = MonotonicTimer(total_budget_seconds=100.0, cleanup_reserve_seconds=20.0)
    mock_compose = MagicMock(returncode=0, stdout="job_id=job-obs-1\nattempt=1\n")
    runner = MagicMock(return_value=mock_compose)

    job_id, attempt, handoff = _wait_for_marker(tmp_path, {}, timer, runner)
    assert job_id == "job-obs-1"
    assert attempt == 1
    assert handoff == {}
    assert runner.call_count == 1
    call_kwargs = runner.call_args.kwargs
    from repomap_kg.coordinator._refresh_execution import SYSTEM_TEST_CONSUMER_EXEC_TIMEOUT_SECONDS
    assert call_kwargs["timeout"] == SYSTEM_TEST_CONSUMER_EXEC_TIMEOUT_SECONDS


def test_missing_marker_times_out_before_producer_window_closes(tmp_path: Path) -> None:
    from tools.system.scenario_publication import _wait_for_marker
    timer = MonotonicTimer(total_budget_seconds=100.0, cleanup_reserve_seconds=20.0)
    mock_compose = MagicMock(returncode=1, stdout="")
    runner = MagicMock(return_value=mock_compose)

    job_id, attempt, handoff = _wait_for_marker(tmp_path, {}, timer, runner)
    assert job_id == ""
    assert attempt is None
    assert handoff == {}
    from repomap_kg.coordinator._refresh_execution import SYSTEM_TEST_CONSUMER_EXEC_TIMEOUT_SECONDS
    call_kwargs = runner.call_args.kwargs
    assert call_kwargs.get("timeout", 0.0) <= SYSTEM_TEST_CONSUMER_EXEC_TIMEOUT_SECONDS


def test_pause_window_contract_invariants() -> None:
    from repomap_kg.runtime import system_test_pause as bounds
    bounds.validate_pause_window_contract()
    protected = (bounds.SYSTEM_TEST_CONSUMER_EXEC_TIMEOUT_SECONDS
                 + bounds.SYSTEM_TEST_STATUS_TIMEOUT_SECONDS
                 + bounds.SYSTEM_TEST_CONTROL_READBACK_TIMEOUT_SECONDS
                 + 2 * bounds.SYSTEM_TEST_SUBMISSION_REAP_TIMEOUT_SECONDS
                 + bounds.SYSTEM_TEST_INTERRUPTION_TIMEOUT_SECONDS
                 + bounds.SYSTEM_TEST_PAUSE_SAFETY_MARGIN_SECONDS)
    assert protected < bounds.SYSTEM_TEST_PRODUCER_PAUSE_SECONDS
    for field in ("status_timeout", "control_readback_timeout", "submission_reap_timeout", "interruption_timeout"):
        with pytest.raises(ValueError, match="Total window budget"):
            bounds.validate_pause_window_contract(**{field: bounds.SYSTEM_TEST_PRODUCER_PAUSE_SECONDS})
    with pytest.raises(ValueError, match="Total window budget"):
        bounds.validate_pause_window_contract(producer_pause=protected)
    with pytest.raises(ValueError, match="execution timeout must exceed"):
        bounds.validate_pause_window_contract(consumer_deadline=25, consumer_exec_timeout=25)


def test_pause_contract_refuses_before_launching_scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tools.system import scenario_publication

    from repomap_kg.runtime import system_test_pause
    monkeypatch.setattr(system_test_pause, "SYSTEM_TEST_PRODUCER_PAUSE_SECONDS", 1.0)
    runner, popen = MagicMock(), MagicMock()
    timer = MonotonicTimer(total_budget_seconds=100.0, cleanup_reserve_seconds=20.0)
    with pytest.raises(ValueError, match="Total window budget"):
        scenario_publication.step_2_durable_coordinator_execution(
            tmp_path, tmp_path, MagicMock(), timer, run_compose=runner,
            load_plan_env=MagicMock(), control_job_evidence=MagicMock(),
            token_hex=MagicMock(), popen=popen,
        )
    runner.assert_not_called()
    popen.assert_not_called()


def test_producer_refuses_invalid_pause_contract_before_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from repomap_kg.coordinator import _refresh_execution

    tmp_path.chmod(0o700)
    trigger = tmp_path / "pause"
    trigger.write_text("pause")
    monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_PAUSE_PATH", str(trigger))
    from repomap_kg.runtime import system_test_pause
    monkeypatch.setattr(system_test_pause, "SYSTEM_TEST_PRODUCER_PAUSE_SECONDS", 1.0)
    with pytest.raises(ValueError, match="Total window budget"):
        _refresh_execution._run_system_test_pause(SimpleNamespace(job_id="job-1", attempt=1))
    assert not Path(f"{trigger}.ready").exists()


def test_exact_job_id_attempt_parsing_and_durable_row_fence_matching(tmp_path: Path) -> None:
    from tools.system.scenario_publication import _wait_for_marker
    timer = MonotonicTimer(total_budget_seconds=100.0, cleanup_reserve_seconds=20.0)

    bad_marker = MagicMock(returncode=0, stdout="job_id=job-1\nattempt=not-an-int\n")
    with pytest.raises(SystemTestError, match="invalid attempt"):
        _wait_for_marker(tmp_path, {}, timer, MagicMock(return_value=bad_marker))

    plan = MagicMock()
    plan.env_file.exists.return_value = False
    mismatched_control = {
        "job_id": "job-999", "graph_id": "fixture", "state": "failed", "current_attempt": 1,
        "idempotency_digest": hashlib.sha256(b"sys0-idemp-deadbeef").hexdigest(),
    }
    with patch("subprocess.Popen") as mock_popen, \
         patch("tools.system.scenario._run_compose") as mock_compose, \
         patch("tools.system.scenario.secrets.token_hex", return_value="deadbeef"), \
         patch("tools.system.scenario._control_job_evidence", return_value=mismatched_control):
        proc = MagicMock()
        proc.poll.side_effect = [None, None, -15]
        mock_popen.return_value = proc
        def compose_side_effect(compose_dir, args, *a, **kw):
            res = MagicMock(returncode=0, stdout="")
            if any("system_pause_trigger.ready" in str(arg) for arg in args):
                res.stdout = 'job_id=job-999\nattempt=1\nhandoff={"repository_id":1,"stage_id":"stage-old","run_id":1,"receipt":{"publication_job_id":"job-999","publication_attempt":1}}\n'
            elif "coordinator-job-status" in args:
                res.stdout = json.dumps({"job": {"job_id": "job-999", "graph_id": "fixture", "state": "claimed", "attempt_count": 1}})
            return res
        mock_compose.side_effect = compose_side_effect
        with pytest.raises(SystemTestError, match="durable coordinator row did not match"):
            step_2_durable_coordinator_execution(tmp_path, tmp_path / "home", plan, timer)
