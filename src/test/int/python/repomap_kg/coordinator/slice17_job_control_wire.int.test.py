"""Existing-job CLI control validates real authenticated peer responses."""
import json
from pathlib import Path
import secrets
import socket
import threading

import pytest

from repomap_kg.coordinator.job_listing import JobListCursor, encode_job_cursor
from repomap_kg.coordinator.local_mode import coordinator_runtime_paths
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.test_scratch import short_test_directory


def _job(state="cancelled"):
    return dict(job_id="wire-job", graph_id="wire-graph", state=state,
                submitted_at="2026-09-23T12:00:00.000000Z")


def _health(status="ready"):
    return dict(health_schema_version=1, status=status, **{
        name: {"status": "ready"} for name in (
            "service", "ownership", "queue", "workers", "publication", "polling", "transport", "storage")})


def _cli_peer(command, payload, *, options=(), as_json=True):
    with short_test_directory("s17-", "coordinator/coordinator.sock") as directory:
        home = Path(directory)
        _, endpoint, credential = coordinator_runtime_paths(home, create=True)
        token = secrets.token_hex(16)
        credential.write_text(token)
        credential.chmod(0o600)
        errors, requests = [], []
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.settimeout(3.0)
            server.bind(str(endpoint))
            server.listen(1)

            def respond():
                try:
                    connection, _ = server.accept()
                    with connection:
                        connection.settimeout(3.0)
                        with connection.makefile("rb") as stream:
                            request = json.loads(stream.readline())
                        assert request.pop("auth_token") == token
                        requests.append(request)
                        connection.sendall(json.dumps({"schema_version": 1, "ok": True,
                                                       "result": payload}).encode() + b"\n")
                except Exception as error:
                    errors.append(type(error).__name__)

            thread = threading.Thread(target=respond)
            thread.start()
            try:
                args = ["ops", command, "--repo-map-home", str(home), *options]
                if command.startswith("coordinator-job-"):
                    args += ["--job-id", "wire-job"]
                if as_json:
                    args.append("--json")
                result = run_repo_map_in_process(*args)
            finally:
                thread.join(4.0)
            assert not thread.is_alive() and not errors, errors
            assert len(requests) == 1
        endpoint.unlink()
        return result, requests[0]


@pytest.mark.parametrize("as_json", [True, False])
@pytest.mark.parametrize(("command", "operation", "state", "exit_code"), [
    ("coordinator-job-status", "status", "running", 0),
    ("coordinator-job-cancel", "cancel", "cancel_requested", 0),
    ("coordinator-job-wait", "wait", "cancelled", 1),
    ("coordinator-job-wait", "wait", "succeeded", 0),
])
def test_existing_job_control_preserves_terminal_and_cancellation_meaning(command, operation, state, exit_code, as_json):
    (code, stdout, stderr), request = _cli_peer(command, _job(state), as_json=as_json)
    assert code == exit_code and stderr == ""
    assert request["operation"] == operation and request["payload"]["job_id"] == "wire-job"
    if as_json:
        assert json.loads(stdout)["job"]["state"] == state
    else:
        assert f"state | {state}" in stdout and "wire-job" in stdout


@pytest.mark.parametrize("as_json", [True, False])
@pytest.mark.parametrize("status", ["ready", "degraded"])
def test_health_cli_retains_ready_vs_degraded(as_json, status):
    (code, stdout, stderr), request = _cli_peer("coordinator-health", _health(status), as_json=as_json)
    assert code == (0 if status == "ready" else 1) and stderr == ""
    assert request["operation"] == "health"
    if as_json:
        assert json.loads(stdout)["result"] == status
    else:
        assert f"status | {status}" in stdout


@pytest.mark.parametrize("as_json", [True, False])
def test_job_listing_preserves_verified_continuation_cursor(as_json):
    job = _job()
    cursor = encode_job_cursor(JobListCursor(job["submitted_at"], job["job_id"]))
    (code, stdout, stderr), request = _cli_peer(
        "coordinator-jobs", {"jobs": [job], "next_cursor": cursor},
        options=("--graph-id", "wire-graph", "--limit", "1"), as_json=as_json)
    assert code == 0 and stderr == "" and request["operation"] == "list"
    if as_json:
        assert json.loads(stdout)["next_cursor"] == cursor
    else:
        assert f"next_cursor | {cursor}" in stdout


@pytest.mark.parametrize("damage", [
    "cancel-state", "job-id", "job-state", "job-empty", "health-shape", "health-version",
    "health-status", "health-section", "health-section-status", "list-shape", "list-count",
    "list-item-shape", "list-graph", "list-time", "list-cursor-type", "list-cursor-mismatch",
])
def test_invalid_job_or_health_claim_is_not_printed_as_a_valid_result(damage):
    command, payload = "coordinator-job-status", _job()
    options: tuple[str, ...] = ()
    if damage == "cancel-state":
        command, payload = "coordinator-job-cancel", _job("succeeded")
    elif damage == "job-id":
        payload["job_id"] = "other-job"
    elif damage == "job-state":
        payload["state"] = "unknown"
    elif damage == "job-empty":
        payload["state"] = ""
    elif damage.startswith("health"):
        command, payload = "coordinator-health", _health()
        if damage == "health-shape":
            del payload["storage"]
        elif damage == "health-version":
            payload["health_schema_version"] = 2
        elif damage == "health-status":
            payload["status"] = "unknown"
        elif damage == "health-section":
            payload["storage"] = []
        else:
            payload["storage"] = {"status": "unknown"}
    else:
        command, payload = "coordinator-jobs", {"jobs": [_job()], "next_cursor": None}
        if damage == "list-shape":
            del payload["next_cursor"]
        elif damage == "list-count":
            options = ("--limit", "1")
            payload["jobs"].append(_job())
        elif damage == "list-item-shape":
            payload["jobs"][0]["unexpected"] = "value"
        elif damage == "list-graph":
            options = ("--graph-id", "different-graph")
        elif damage == "list-time":
            payload["jobs"][0]["submitted_at"] = "invalid"
        elif damage == "list-cursor-type":
            payload["next_cursor"] = 1
        else:
            payload["next_cursor"] = encode_job_cursor(JobListCursor(_job()["submitted_at"], "other-job"))
    (code, stdout, stderr), _ = _cli_peer(command, payload, options=options)
    assert code == 1 and stdout == ""
    assert ("invalid_response" if damage == "job-empty" else "coordinator_response_invalid") in stderr
