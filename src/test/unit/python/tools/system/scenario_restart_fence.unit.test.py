"""Restart evidence must bind the prior attempt and reject its storage fence."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.system.config import SystemTestError
from tools.system.scenario_restart_fence import verify_restart_fence


@pytest.mark.parametrize(
    ("returncode", "stderr", "failure_match"),
    [
        (0, "", "not rejected"),
        (1, "unrelated failure", "probe failed before proving"),
        (2, "probe rejection: ValueError", "probe failed before proving"),
        (2, "SCALE5 stale publication fence", "probe failed before proving"),
        (137, "SCALE5 stale publication fence", "probe failed before proving"),
        (1, "SCALE5 stale publication fence", None),
    ],
)
def test_storage_probe_requires_the_actual_stale_fence_refusal(returncode, stderr, failure_match, tmp_path):
    prior = {
        "attempt": 1,
        "publication_state": "not_started",
        "instance_id": "prior",
        "singleton_epoch": 1,
    }
    evidence = {
        "initial_attempt": 1,
        "initial_instance_id": "prior",
        "initial_singleton_fencing_epoch": 1,
        "initial_graph_lease_fencing_epoch": 7,
        "initial_publication_handoff": {"repository_id": 1, "stage_id": "stage-old", "run_id": 1, "receipt": {}},
        "initial_generations": {
            "source_generation": "sg1:source",
            "config_generation": "cg1:config",
            "extractor_generation": "eg1:extractor",
            "canonicalizer_generation": "kg1:canonicalizer",
        },
    }
    authority = {
        "repository_id": 1,
        "attempt": 2,
        "singleton_fencing_epoch": 2,
        "coordinator_instance_id": "coord-2",
        "latest_run_id": 2,
    }
    readback_payload = json.dumps({
        "attempt": 2,
        "singleton_fencing_epoch": 2,
        "coordinator_instance_id": "coord-2",
        "latest_run_id": 2,
        "files_count": 5,
        "runs_count": 1,
    })

    def fake_compose(_dir, cmd, **kwargs):
        if "coordinator" in cmd:
            return SimpleNamespace(returncode=returncode, stderr=stderr, stdout="")
        return SimpleNamespace(returncode=0, stderr="", stdout=readback_payload)

    runner = MagicMock(side_effect=fake_compose)
    args = (tmp_path, SimpleNamespace(user="fixture", database="fixture"), MagicMock())
    kwargs: dict[str, Any] = dict(
        job_id="job-1",
        coordinator_evidence=evidence,
        durable={"attempt_history": [prior], "graph_id": "fixture"},
        authority=authority,
        env={},
        run_compose=runner,
    )
    if failure_match is None:
        result = verify_restart_fence(*args, **kwargs)
        assert result["orphan_publication_fence_rejected"] is True
        assert result["prior_attempt_reconciliation"] == prior
        assert result["durable_publication_unchanged"] is True
        assert result["publication_counts"]["files_count"] == 5
        assert result["publication_counts"]["runs_count"] == 1

        probe_call = runner.call_args_list[1]
        assert probe_call.args[1] == ["exec", "-T", "coordinator", "python", "-"]
        probe_code = probe_call.kwargs["stdin_input"]
        ast.parse(probe_code, filename="stale-probe", mode="exec")
        assert "execute_final_transaction(connection, handoff)" in probe_code
        assert "execute_refresh_attempt" not in probe_code
        assert "ConfiguredRefreshResolver" in probe_code
        assert "publication_receipt_from_mapping" in probe_code
        assert "attempt=AttemptNumber(1)" in probe_code
        assert "singleton_fencing_epoch=1" in probe_code
        assert "graph_lease_fencing_epoch=7" in probe_code
        assert "SCALE5 stale publication fence" in probe_code
        assert "postgres_password" not in probe_call.args[1]
    else:
        with pytest.raises(SystemTestError, match=failure_match):
            verify_restart_fence(*args, **kwargs)
        assert len(runner.call_args_list) == 2


def test_missing_reconciliation_evidence_refuses_storage_probe(tmp_path):
    runner = MagicMock()
    with pytest.raises(SystemTestError, match="did not durably reconcile"):
        verify_restart_fence(
            tmp_path,
            MagicMock(),
            MagicMock(),
            job_id="job-1",
            coordinator_evidence={
                "initial_attempt": 1,
                "initial_instance_id": "prior",
                "initial_singleton_fencing_epoch": 1,
            },
            durable={"attempt_history": []},
            authority={},
            env={},
            run_compose=runner,
        )
    runner.assert_not_called()


def test_restart_fence_orchestration_actualpath_invoked_and_counts_unchanged(tmp_path):
    prior = {
        "attempt": 1,
        "publication_state": "not_started",
        "instance_id": "inst-crashed",
        "singleton_epoch": 3,
    }
    evidence = {
        "initial_attempt": 1,
        "initial_instance_id": "inst-crashed",
        "initial_singleton_fencing_epoch": 3,
        "initial_graph_lease_fencing_epoch": 11,
        "initial_publication_handoff": {"repository_id": 42, "stage_id": "stage-old", "run_id": 6, "receipt": {}},
        "initial_generations": {
            "source_generation": "sg-prior",
            "config_generation": "cg-prior",
            "extractor_generation": "eg-prior",
            "canonicalizer_generation": "kg-prior",
        },
    }
    authority = {
        "repository_id": 42,
        "attempt": 2,
        "singleton_fencing_epoch": 4,
        "coordinator_instance_id": "inst-recovered",
        "latest_run_id": 7,
    }
    unchanged_readback = json.dumps({
        "attempt": 2,
        "singleton_fencing_epoch": 4,
        "coordinator_instance_id": "inst-recovered",
        "latest_run_id": 7,
        "files_count": 42,
        "runs_count": 2,
    })

    def fake_compose(_dir, cmd, **kwargs):
        if "coordinator" in cmd:
            return SimpleNamespace(
                returncode=1,
                stderr="SCALE5 stale publication fence\n",
                stdout="",
            )
        return SimpleNamespace(returncode=0, stderr="", stdout=unchanged_readback)

    runner = MagicMock(side_effect=fake_compose)
    plan = SimpleNamespace(user="testuser", database="testdb")
    timer = MagicMock()
    result = verify_restart_fence(
        tmp_path,
        plan,
        timer,
        job_id="job-42",
        coordinator_evidence=evidence,
        durable={"attempt_history": [prior], "graph_id": "g-test"},
        authority=authority,
        env={"TEST": "1"},
        run_compose=runner,
    )
    assert result["orphan_publication_fence_rejected"] is True
    assert result["durable_publication_unchanged"] is True
    assert result["prior_attempt_reconciliation"] == prior
    assert result["publication_counts"] == {"files_count": 42, "runs_count": 2}

    # The probe resumes the interrupted final transaction with its original handoff.
    assert len(runner.call_args_list) == 3
    before_call, probe_call, readback_call = runner.call_args_list
    script = probe_call.kwargs["stdin_input"]
    assert before_call.kwargs["stdin_input"] == readback_call.kwargs["stdin_input"]
    assert probe_call.args[1] == ["exec", "-T", "coordinator", "python", "-"]
    assert (
        "from repomap_kg.storage.staged_publication import execute_final_transaction"
        in script
    )
    assert (
        "from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver"
        in script
    )
    assert (
        "from repomap_kg.storage.publication import publication_receipt_from_mapping"
        in script
    )
    assert "execute_final_transaction(connection, handoff)" in script
    assert "attempt=AttemptNumber(1)" in script
    assert "coordinator_instance_id='inst-crashed'" in script
    assert "singleton_fencing_epoch=3" in script
    assert "graph_lease_fencing_epoch=11" in script

    # Verify readback queried postgres and verified counts unchanged
    assert readback_call.args[1][:5] == ["exec", "-T", "postgres", "psql", "-XAt"]
    readback_sql = readback_call.kwargs["stdin_input"]
    assert "WHERE gpa.repository_id = 42" in readback_sql

    # If publication readback is mutated, SystemTestError is raised
    mutated_readback = json.dumps({
        "attempt": 1,
        "singleton_fencing_epoch": 3,
        "coordinator_instance_id": "inst-crashed",
        "latest_run_id": 7,
        "files_count": 42,
        "runs_count": 2,
    })
    mutated_runner = MagicMock(side_effect=[
        SimpleNamespace(returncode=0, stderr="", stdout=unchanged_readback),
        SimpleNamespace(returncode=1, stderr="SCALE5 stale publication fence\n", stdout=""),
        SimpleNamespace(returncode=0, stderr="", stdout=mutated_readback),
    ])
    with pytest.raises(SystemTestError, match="durable publication was mutated"):
        verify_restart_fence(
            tmp_path,
            plan,
            timer,
            job_id="job-42",
            coordinator_evidence=evidence,
            durable={"attempt_history": [prior], "graph_id": "g-test"},
            authority=authority,
            env={"TEST": "1"},
            run_compose=mutated_runner,
        )
