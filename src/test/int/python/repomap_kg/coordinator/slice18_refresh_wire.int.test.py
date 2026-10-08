"""Refresh callers preserve pending, failed, and invalid authenticated replies."""

from contextlib import contextmanager
import json
from pathlib import Path
import secrets
import socket
from threading import Thread

import pytest

from repomap_kg.coordinator.local_mode import (
    CoordinatorModeError, coordinator_runtime_paths, run_coordinator_refresh,
)
from repomap_test_support.test_scratch import short_test_directory


@contextmanager
def _peer(replies):
    # A wire peer is the external seam; request construction, authentication,
    # transport, response decoding, and refresh orchestration remain real.
    with short_test_directory("s18-", "coordinator/coordinator.sock") as directory:
        home = Path(directory)
        _, endpoint, credential = coordinator_runtime_paths(home, create=True)
        token = secrets.token_hex(16)
        credential.write_text(token)
        credential.chmod(0o600)
        requests, failures = [], []
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.settimeout(3)
            server.bind(str(endpoint))
            server.listen(1)

            def respond():
                try:
                    for reply in replies:
                        connection, _ = server.accept()
                        with connection:
                            connection.settimeout(3)
                            with connection.makefile("rb") as stream:
                                request = json.loads(stream.readline())
                            assert request.pop("auth_token") == token
                            requests.append(request)
                            connection.sendall(json.dumps({
                                "schema_version": 1, "ok": True, "result": reply,
                            }).encode() + b"\n")
                except Exception as error:
                    failures.append(error)

            thread = Thread(target=respond)
            thread.start()
            try:
                yield home, requests
            finally:
                thread.join(4)
            assert not thread.is_alive()
            assert failures == []
        endpoint.unlink()


@pytest.mark.parametrize("state", ["succeeded", "failed"])
def test_pending_refresh_preserves_terminal_result_and_replay(state):
    replies = [{"job_id": "refresh-job", "replayed": True},
               {"job_id": "refresh-job", "state": "running"},
               {"job_id": "refresh-job", "state": state}]
    with _peer(replies) as (home, requests):
        result = run_coordinator_refresh(home, "fixture", "same-request")
    assert result["result"] == ("success" if state == "succeeded" else "failure")
    assert result["replayed"] is True and result["job"] == replies[-1]
    assert [request["operation"] for request in requests] == ["submit", "wait", "wait"]
    assert requests[0]["payload"]["request"]["idempotency_key"] == "same-request"
    assert all(request["payload"] == {"job_id": "refresh-job"} for request in requests[1:])


def test_pending_refresh_exhausts_caller_deadline_without_resubmission():
    ticks = iter((0.0, 1.0))
    with _peer([{"job_id": "refresh-job", "replayed": False},
                {"job_id": "refresh-job", "state": "running"}]) as (home, requests):
        with pytest.raises(CoordinatorModeError, match="coordinator_wait_timeout"):
            run_coordinator_refresh(home, "fixture", "one-request",
                                    wait_timeout_seconds=1, monotonic=lambda: next(ticks))
    assert [request["operation"] for request in requests] == ["submit", "wait"]


def test_invalid_replay_claim_refuses_wait_after_authenticated_submit():
    with _peer([{"job_id": "refresh-job", "replayed": "true"}]) as (home, requests):
        with pytest.raises(CoordinatorModeError, match="coordinator_response_invalid"):
            run_coordinator_refresh(home, "fixture", "one-request")
    assert [request["operation"] for request in requests] == ["submit"]
