import json
import socket

import pytest

from repomap_kg.coordinator.client import CoordinatorClientError, LocalCoordinatorClient


def test_client_fails_explicitly_without_endpoint_and_never_falls_back(tmp_path):
    token_path = tmp_path / "coordinator.token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    token_path.chmod(0o600)
    client = LocalCoordinatorClient(tmp_path / "missing.sock", token_path)
    with pytest.raises(CoordinatorClientError, match="unavailable"):
        client.health()


def test_client_rejects_unsafe_token_permissions(tmp_path):
    token_path = tmp_path / "coordinator.token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    token_path.chmod(0o644)
    with pytest.raises(CoordinatorClientError, match="unsafe_credentials"):
        LocalCoordinatorClient(tmp_path / "coordinator.sock", token_path)


def test_client_uses_strict_frames_and_bounds_remote_errors(tmp_path, monkeypatch):
    token_path = tmp_path / "coordinator.token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    token_path.chmod(0o600)
    observed = {}

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def settimeout(self, timeout):
            observed["timeout"] = timeout

        def connect(self, path):
            observed["path"] = path

        def sendall(self, frame):
            observed["request"] = json.loads(frame)

        def makefile(self, _mode):
            class Reader:
                def readline(self, _limit):
                    return b'{"schema_version":1,"ok":false,"error_category":"saturated"}\n'
            return Reader()

    monkeypatch.setattr(socket, "socket", lambda *_args: FakeSocket())
    client = LocalCoordinatorClient(tmp_path / "coordinator.sock", token_path)
    with pytest.raises(CoordinatorClientError, match="saturated"):
        client.status("job-1")
    assert observed["request"] == {
        "schema_version": 1,
        "auth_token": "synthetic-token",
        "operation": "status",
        "payload": {"job_id": "job-1"},
    }


def test_client_bounds_non_json_request_values(tmp_path):
    token_path = tmp_path / "coordinator.token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    token_path.chmod(0o600)
    client = LocalCoordinatorClient(tmp_path / "coordinator.sock", token_path)
    with pytest.raises(CoordinatorClientError, match="invalid_request"):
        client.submit({"unsupported": object()})


def test_client_timeout_validation(tmp_path):
    token_path = tmp_path / "coordinator.token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    token_path.chmod(0o600)
    for bad_timeout in (0.0, -1.0, 61.0):
        with pytest.raises(ValueError, match="timeout is invalid"):
            LocalCoordinatorClient(tmp_path / "coordinator.sock", token_path, timeout_seconds=bad_timeout)


def test_client_token_from_endpoint_descriptor(tmp_path, monkeypatch):
    endpoint_path = tmp_path / "coordinator.endpoint.json"
    from repomap_kg.coordinator.endpoint import LoopbackEndpointDescriptor, write_endpoint_descriptor

    desc = LoopbackEndpointDescriptor(
        schema_version=1,
        host="127.0.0.1",
        port=55555,
        instance_id="inst-1",
        fencing_epoch=1,
        auth_token="endpoint-auth-token-12345",
    )
    write_endpoint_descriptor(endpoint_path, desc)

    observed = {}

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def settimeout(self, t):
            pass

        def sendall(self, frame):
            observed["request"] = json.loads(frame)

        def makefile(self, _mode):
            class Reader:
                def readline(self, _limit):
                    return b'{"schema_version":1,"ok":true,"result":{"status":"ok"}}\n'
            return Reader()

    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout: FakeConn())
    client = LocalCoordinatorClient(endpoint_path, None)
    res = client.health()
    assert res == {"status": "ok"}
    assert observed["request"]["auth_token"] == "endpoint-auth-token-12345"


@pytest.mark.parametrize(
    "raw_frame,expected_error",
    [
        (b"", "invalid_response"),
        (b"not-json\n", "invalid_response"),
        (b'{"schema_version":2,"ok":true,"result":{}}\n', "invalid_response"),
        (b'{"schema_version":1,"ok":false,"unknown_cat":"foo"}\n', "invalid_response"),
        (b'{"schema_version":1,"ok":false,"error_category":"unknown_not_allowed"}\n', "invalid_response"),
        (b'{"schema_version":1,"ok":true,"result":"not-a-dict"}\n', "invalid_response"),
        (b'{"schema_version":1,"ok":true,"result":{"database":"val"}}\n', "invalid_response"),
    ],
)
def test_client_response_decoding_boundaries(tmp_path, monkeypatch, raw_frame, expected_error):
    token_path = tmp_path / "coordinator.token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    token_path.chmod(0o600)

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def settimeout(self, _t):
            pass

        def connect(self, _path):
            pass

        def sendall(self, _frame):
            pass

        def makefile(self, _mode):
            class Reader:
                def readline(self, _limit):
                    return raw_frame
            return Reader()

    monkeypatch.setattr(socket, "socket", lambda *_args: FakeSocket())
    client = LocalCoordinatorClient(tmp_path / "coordinator.sock", token_path)
    with pytest.raises(CoordinatorClientError, match=expected_error):
        client.health()


def test_client_convenience_methods(tmp_path, monkeypatch):
    token_path = tmp_path / "coordinator.token"
    token_path.write_text("synthetic-token", encoding="utf-8")
    token_path.chmod(0o600)
    requests = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def settimeout(self, _t):
            pass

        def connect(self, _path):
            pass

        def sendall(self, frame):
            requests.append(json.loads(frame))

        def makefile(self, _mode):
            class Reader:
                def readline(self, _limit):
                    return b'{"schema_version":1,"ok":true,"result":{"status":"ok"}}\n'
            return Reader()

    monkeypatch.setattr(socket, "socket", lambda *_args: FakeSocket())
    client = LocalCoordinatorClient(tmp_path / "coordinator.sock", token_path)
    client.wait("job-99")
    client.cancel("job-99")
    client.list_jobs(limit=10, graph_id="graph-1", cursor="c1")

    ops = [r["operation"] for r in requests]
    assert ops == ["wait", "cancel", "list"]
    assert requests[2]["payload"] == {"limit": 10, "graph_id": "graph-1", "cursor": "c1"}
