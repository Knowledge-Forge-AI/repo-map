import json
from pathlib import Path
import socket
import stat
from tempfile import TemporaryDirectory
from typing import Callable, Mapping

from repomap_test_support.test_scratch import short_test_directory
from repomap_kg.coordinator.client import LocalCoordinatorClient
from repomap_kg.coordinator.endpoint import load_endpoint_descriptor
from repomap_kg.coordinator.transport import (
    LocalRequestDispatcher,
    LoopbackTcpService,
    UnixSocketService,
)


def test_unix_socket_health_authentication_and_disconnect_are_bounded():
    cancellations: list[object] = []

    def _cancel(payload: Mapping[str, object]) -> dict[str, bool]:
        cancellations.append(payload["job_id"])
        return {"accepted": True}

    dispatcher = LocalRequestDispatcher(
        "synthetic-auth-token",
        {
            "health": lambda _payload: {"status": "ready"},
            "submit": lambda _payload: {"job_id": "job-1"},
            "status": lambda payload: {"job_id": payload["job_id"], "state": "queued"},
            "wait": lambda payload: {"job_id": payload["job_id"], "state": "queued"},
            "cancel": _cancel,
            "list": lambda _payload: {"jobs": [], "next_cursor": None},
        },
        max_in_flight=2,
    )
    with short_test_directory("async2-", "coordinator.sock") as directory:
        socket_path = Path(directory) / "coordinator.sock"
        with UnixSocketService(socket_path, dispatcher, max_connections=2):
            assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(socket_path))
                client.sendall(json.dumps({
                    "schema_version": 1,
                    "auth_token": "synthetic-auth-token",
                    "operation": "health",
                    "payload": {},
                }).encode() + b"\n")
                response = json.loads(client.makefile("rb").readline())
            assert response == {
                "schema_version": 1,
                "ok": True,
                "result": {"status": "ready"},
            }

            disconnected = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            disconnected.connect(str(socket_path))
            disconnected.close()
        assert cancellations == []
        assert not socket_path.exists()


def test_unix_socket_rejects_oversized_frames():
    dispatcher = LocalRequestDispatcher(
        "synthetic-auth-token", {name: (lambda _payload: {}) for name in
        ("health", "submit", "status", "wait", "cancel", "list")}, max_in_flight=1
    )
    with short_test_directory("async2-", "coordinator.sock") as directory:
        socket_path = Path(directory) / "coordinator.sock"
        with UnixSocketService(
            socket_path, dispatcher, max_connections=1, max_frame_bytes=256
        ):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(socket_path))
                client.sendall(b"x" * 257 + b"\n")
                response = json.loads(client.makefile("rb").readline())
    assert response == {
        "schema_version": 1,
        "ok": False,
        "error_category": "frame_too_large",
    }


def test_unix_socket_bounds_handler_failures_to_public_error():
    handlers: dict[str, Callable[[Mapping[str, object]], object]] = {
        name: (lambda _payload: {}) for name in
        ("health", "submit", "status", "wait", "cancel", "list")
    }
    handlers["health"] = lambda _payload: (_ for _ in ()).throw(
        RuntimeError("private detail")
    )
    dispatcher = LocalRequestDispatcher(
        "synthetic-auth-token", handlers, max_in_flight=1
    )
    with short_test_directory("async2-", "coordinator.sock") as directory:
        socket_path = Path(directory) / "coordinator.sock"
        with UnixSocketService(socket_path, dispatcher, max_connections=1):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(socket_path))
                client.sendall(json.dumps({
                    "schema_version": 1,
                    "auth_token": "synthetic-auth-token",
                    "operation": "health",
                    "payload": {},
                }).encode() + b"\n")
                response = json.loads(client.makefile("rb").readline())
    assert response == {
        "schema_version": 1,
        "ok": False,
        "error_category": "internal",
    }


def test_unstarted_unix_socket_service_can_be_closed_without_leaking_endpoint():
    dispatcher = LocalRequestDispatcher(
        "synthetic-auth-token", {name: (lambda _payload: {}) for name in
        ("health", "submit", "status", "wait", "cancel", "list")}, max_in_flight=1
    )
    with short_test_directory("async3-", "coordinator.sock") as directory:
        socket_path = Path(directory) / "coordinator.sock"
        service = UnixSocketService(socket_path, dispatcher, max_connections=1)
        assert socket_path.exists()
        service.__exit__(None, None, None)
        assert not socket_path.exists()


def test_loopback_tcp_service_rotates_private_descriptor_and_authenticates():
    dispatcher = LocalRequestDispatcher(
        "synthetic-auth-token",
        {
            "health": lambda _payload: {"status": "ready"},
            "submit": lambda _payload: {"job_id": "job-1"},
            "status": lambda _payload: {"job_id": "job-1", "state": "queued"},
            "wait": lambda _payload: {"job_id": "job-1", "state": "queued"},
            "cancel": lambda _payload: {"accepted": True},
            "list": lambda _payload: {"jobs": [], "next_cursor": None},
        },
        max_in_flight=2,
    )
    with TemporaryDirectory(prefix="async14-") as directory:
        endpoint_path = Path(directory) / "coordinator.endpoint.json"
        service = LoopbackTcpService(
            endpoint_path,
            dispatcher,
            auth_token="synthetic-auth-token",
            instance_id="instance-1",
            fencing_epoch=7,
            max_connections=2,
        )
        with service:
            descriptor = load_endpoint_descriptor(endpoint_path)
            assert descriptor.host == "127.0.0.1"
            assert descriptor.port > 0
            assert descriptor.instance_id == "instance-1"
            assert descriptor.fencing_epoch == 7
            assert LocalCoordinatorClient(
                endpoint_path, endpoint_path, timeout_seconds=2
            ).health() == {"status": "ready"}
            with socket.create_connection((descriptor.host, descriptor.port)) as client:
                client.sendall(
                    b'{"schema_version":1,"auth_token":"wrong-token",'
                    b'"operation":"health","payload":{}}\n'
                )
                response = json.loads(client.makefile("rb").readline())
            assert response["error_category"] == "unauthorized"
        assert not endpoint_path.exists()
