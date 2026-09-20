from dataclasses import asdict
import json
import threading

import psycopg
from pathlib import Path
import socket
import stat
from tempfile import TemporaryDirectory
from typing import Callable, Mapping

from repomap_test_support.test_scratch import short_test_directory
from repomap_kg.coordinator.client import CoordinatorClientError, LocalCoordinatorClient
from repomap_kg.coordinator.contracts import normalize_request
from repomap_kg.coordinator.storage import ControlStore
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_kg.coordinator.endpoint import (
    EndpointDescriptorError,
    LoopbackEndpointDescriptor,
    load_endpoint_descriptor,
    write_endpoint_descriptor,
)
from repomap_kg.coordinator.job_control import (
    cancel_coordinator_job,
    wait_for_coordinator_job,
)
from repomap_kg.coordinator.transport import (
    LocalRequestDispatcher,
    LoopbackTcpService,
    UnixSocketService,
)
import pytest


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


def test_authenticated_transport_request_validation_saturation_and_error_propagation():
    entered, release = threading.Event(), threading.Event()
    dispatcher = LocalRequestDispatcher(
        "synthetic-auth-token",
        {
            "health": lambda _: _held_health(entered, release),
            "submit": lambda _payload: {"job_id": "job-1"},
            "status": lambda payload: {"job_id": payload["job_id"], "state": "queued"},
            "wait": lambda payload: {"job_id": payload["job_id"], "state": "queued"},
            "cancel": lambda payload: {"job_id": payload["job_id"], "state": "cancelled"},
            "list": lambda _payload: {"jobs": [], "next_cursor": None},
        },
        max_in_flight=1,
    )
    with short_test_directory("async2-", "coordinator.sock") as directory:
        socket_path = Path(directory) / "coordinator.sock"
        with UnixSocketService(socket_path, dispatcher, max_connections=1):
            def _send(payload: Mapping[str, object]) -> dict[str, object]:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(2)
                    client.connect(str(socket_path))
                    client.sendall(json.dumps(payload).encode() + b"\n")
                    return json.loads(client.makefile("rb").readline())

            bad_ver = _send({"schema_version": 2, "auth_token": "synthetic-auth-token", "operation": "health", "payload": {}})
            assert bad_ver == {"schema_version": 1, "ok": False, "error_category": "incompatible_version"}

            bad_op = _send({"schema_version": 1, "auth_token": "synthetic-auth-token", "operation": "unknown_op", "payload": {}})
            assert bad_op == {"schema_version": 1, "ok": False, "error_category": "unsupported_operation"}

            bad_payload = _send({"schema_version": 1, "auth_token": "synthetic-auth-token", "operation": "health", "payload": {"auth_token": "leak"}})
            assert bad_payload == {"schema_version": 1, "ok": False, "error_category": "invalid_request"}

            bad_limit = _send({"schema_version": 1, "auth_token": "synthetic-auth-token", "operation": "list", "payload": {"limit": True}})
            assert bad_limit == {"schema_version": 1, "ok": False, "error_category": "invalid_request"}
            bad_cursor = _send({"schema_version": 1, "auth_token": "synthetic-auth-token", "operation": "list", "payload": {"limit": 10, "cursor": 123}})
            assert bad_cursor == {"schema_version": 1, "ok": False, "error_category": "invalid_request"}

            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client1:
                client1.settimeout(2)
                client1.connect(str(socket_path))
                try:
                    client1.sendall(_health_frame())
                    assert entered.wait(2)
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client2:
                        client2.settimeout(2)
                        client2.connect(str(socket_path))
                        sat_resp = json.loads(client2.makefile("rb").readline())
                    assert sat_resp == {"schema_version": 1, "ok": False, "error_category": "saturated"}
                finally:
                    release.set()
                assert json.loads(client1.makefile("rb").readline())["ok"] is True

        with pytest.raises(ValueError, match="transport configuration is invalid"):
            UnixSocketService(socket_path, dispatcher, max_connections=0)
        with pytest.raises(ValueError, match="transport configuration is invalid"):
            LoopbackTcpService(socket_path, dispatcher, auth_token="t", instance_id="i", fencing_epoch=1, max_connections=0)


def test_loopback_tcp_service_saturation_and_superseded_descriptor_preservation():
    entered, release = threading.Event(), threading.Event()
    dispatcher = LocalRequestDispatcher(
        "synthetic-auth-token",
        {
            "health": lambda _: _held_health(entered, release),
            "submit": lambda _payload: {"job_id": "job-1"},
            "status": lambda _payload: {"job_id": "job-1", "state": "queued"},
            "wait": lambda _payload: {"job_id": "job-1", "state": "queued"},
            "cancel": lambda _payload: {"accepted": True},
            "list": lambda _payload: {"jobs": [], "next_cursor": None},
        },
        max_in_flight=1,
    )
    with TemporaryDirectory(prefix="async14-") as directory:
        endpoint_path = Path(directory) / "coordinator.endpoint.json"
        service = LoopbackTcpService(
            endpoint_path,
            dispatcher,
            auth_token="synthetic-auth-token",
            instance_id="instance-1",
            fencing_epoch=7,
            max_connections=1,
        )
        with service:
            descriptor = load_endpoint_descriptor(endpoint_path)
            with socket.create_connection((descriptor.host, descriptor.port), timeout=2) as client1:
                try:
                    client1.sendall(_health_frame())
                    assert entered.wait(2)
                    with socket.create_connection((descriptor.host, descriptor.port), timeout=2) as client2:
                        sat_response = json.loads(client2.makefile("rb").readline())
                    assert sat_response["error_category"] == "saturated"
                finally:
                    release.set()
                assert json.loads(client1.makefile("rb").readline())["ok"] is True

            superseded = LoopbackEndpointDescriptor(
                schema_version=1,
                host=descriptor.host,
                port=descriptor.port,
                auth_token="newer-synthetic-token",
                instance_id="instance-2",
                fencing_epoch=8,
            )
            write_endpoint_descriptor(endpoint_path, superseded)

        assert endpoint_path.exists()
        current = load_endpoint_descriptor(endpoint_path)
        assert current.instance_id == "instance-2"
        assert current.fencing_epoch == 8

        with pytest.raises(EndpointDescriptorError, match="endpoint descriptor is invalid"):
            LoopbackEndpointDescriptor(
                schema_version=1, host="127.0.0.1", port=9000,
                auth_token="short-token", instance_id="instance-invalid", fencing_epoch=1,
            ).validate()
        with pytest.raises(EndpointDescriptorError, match="endpoint descriptor is stale"):
            load_endpoint_descriptor(endpoint_path, expected_instance_id="wrong-instance")
        with pytest.raises(EndpointDescriptorError, match="endpoint descriptor is stale"):
            load_endpoint_descriptor(endpoint_path, expected_fencing_epoch=999)
        with pytest.raises(EndpointDescriptorError, match="endpoint descriptor path is invalid"):
            write_endpoint_descriptor(Path("relative.json"), descriptor)



def test_authenticated_transport_paginates_and_cancels_durable_queued_jobs():
    require_postgres_binaries()
    with temporary_postgres() as postgres, short_test_directory("r2-wire-", "coordinator.sock") as directory:
        def connect():
            return psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user,
                                  dbname=postgres.database, password=postgres.password)

        store = ControlStore(connect)
        store.initialize_schema()
        def submit(payload):
            request = normalize_request(payload["request"], source_generation="sg1:wire", config_generation="cg1:wire")
            return asdict(store.submit(request))

        def status(payload):
            return asdict(store.status(payload["job_id"]))

        def cancel(payload):
            store.request_cancellation(payload["job_id"])
            return status(payload)

        def page(payload):
            p = store.list_recent_jobs(**payload)
            return {"jobs": [asdict(job) for job in p.jobs], "next_cursor": p.next_cursor}

        dispatcher = LocalRequestDispatcher("wire-token", {
            "health": lambda _: {"status": "ready"}, "submit": submit,
            "status": status, "wait": status, "cancel": cancel,
            "list": page,
        }, max_in_flight=2)
        root = Path(directory)
        socket_path, token_path = root / "coordinator.sock", root / "coordinator.token"
        token_path.write_text("wire-token", encoding="utf-8")
        token_path.chmod(0o600)
        with UnixSocketService(socket_path, dispatcher, max_connections=2):
            client = LocalCoordinatorClient(socket_path, token_path, timeout_seconds=2)
            requests = [{
                "schema_version": 1, "job_kind": "refresh_graph", "graph_id": "synthetic-wire",
                "request_id": f"request-{i}", "idempotency_key": f"wire-{i}",
                "priority": "manual", "operation_options": {"reason": "wire-lifecycle"},
            } for i in range(3)]
            submitted = [client.submit(request) for request in requests]
            replay = client.submit(requests[0])
            assert replay["replayed"] is True and replay["job_id"] == submitted[0]["job_id"]
            first = client.list_jobs(limit=2, graph_id="synthetic-wire")
            cursor = first["next_cursor"]
            assert isinstance(cursor, str)
            second = client.list_jobs(limit=2, graph_id="synthetic-wire", cursor=cursor)
            jobs, rest = first["jobs"], second["jobs"]
            assert isinstance(jobs, list) and isinstance(rest, list)
            assert len(jobs) == 2 and len(rest) == 1 and second["next_cursor"] is None
            assert {job["job_id"] for job in (*jobs, *rest)} == {item["job_id"] for item in submitted}
            empty = client.list_jobs(limit=2, graph_id="absent-graph")
            assert empty == {"jobs": [], "next_cursor": None}
            job_id = str(submitted[0]["job_id"])
            factory = lambda _sock, _token: client
            cancelled = cancel_coordinator_job(root, job_id, client_factory=factory)
            assert cancelled["result"] == "accepted"
            waited = wait_for_coordinator_job(root, job_id, wait_timeout_seconds=2, client_factory=factory)
            assert waited["result"] == "failure"
            durable = store.status(job_id)
            assert (durable.state, durable.attempt, durable.publication_state) == ("cancelled", 0, "not_started")
            with connect() as connection:
                assert connection.execute("SELECT count(*) FROM job_attempts").fetchone() == (0,)
                assert connection.execute("SELECT count(*) FROM graph_leases").fetchone() == (0,)
            # A stale client cannot authenticate after credentials rotate across restart.
        assert not socket_path.exists()
        replacement = LocalRequestDispatcher("new-wire-token", {
            name: (lambda _: {"status": "ready"}) for name in ("health", "submit", "status", "wait", "cancel", "list")
        }, max_in_flight=1)
        with UnixSocketService(socket_path, replacement, max_connections=1):
            with pytest.raises(CoordinatorClientError, match="unauthorized"):
                client.health()
        token_path.unlink()
        assert not socket_path.exists() and not token_path.exists()


def _held_health(entered, release):
    entered.set()
    if not release.wait(5):
        raise RuntimeError("test did not release health request")
    return {"status": "ready"}


def _health_frame():
    return b'{"schema_version":1,"auth_token":"synthetic-auth-token","operation":"health","payload":{}}\n'
