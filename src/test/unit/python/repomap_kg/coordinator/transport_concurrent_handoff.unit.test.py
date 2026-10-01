import json
import threading
import socketserver
from unittest.mock import patch

import pytest
from repomap_kg.coordinator import transport


@pytest.mark.parametrize("completion_stage", ["handler_finish", "socket_shutdown"])
def test_real_serve_loop_reuses_completed_work_capacity(tmp_path, completion_stage):
    import socket
    from concurrent.futures import ThreadPoolExecutor

    tmp_path.chmod(0o700)
    handlers = {operation: (lambda _: {"status": "ready"}) for operation in transport._OPERATIONS}
    dispatcher = transport.LocalRequestDispatcher("synthetic-fixture-token", handlers, max_in_flight=1)
    service = transport.LoopbackTcpService(
        tmp_path / "endpoint.json", dispatcher, auth_token="synthetic-fixture-token",
        instance_id="fixture-instance", fencing_epoch=1, max_connections=1,
    )
    shutdown_entered = threading.Event()
    allow_shutdown = threading.Event()
    waiting = threading.Event()
    original_shutdown = service._server.shutdown_request
    handler_class = service._server.RequestHandlerClass
    assert isinstance(handler_class, type) and issubclass(handler_class, socketserver.StreamRequestHandler)
    original_finish = handler_class.finish
    shutdown_calls = 0

    class ObservedSlots(threading.BoundedSemaphore):
        def acquire(self, blocking=True, timeout=None):
            if timeout is not None:
                waiting.set()
            return super().acquire(blocking=blocking, timeout=timeout)

    service._server.connection_slots = ObservedSlots(1)

    def delayed_socket_shutdown(request):
        nonlocal shutdown_calls
        shutdown_calls += 1
        if shutdown_calls == 1:
            shutdown_entered.set()
            assert allow_shutdown.wait(5)
        original_shutdown(request)

    def delayed_handler_finish(handler):
        original_finish(handler)
        nonlocal shutdown_calls
        shutdown_calls += 1
        if shutdown_calls == 1:
            shutdown_entered.set()
            assert allow_shutdown.wait(5)

    def call():
        with socket.create_connection(("127.0.0.1", int(service._server.server_address[1])), timeout=3) as client:
            client.sendall(json.dumps({"schema_version": 1, "auth_token": "synthetic-fixture-token",
                                      "operation": "health", "payload": {}}).encode() + b"\n")
            with client.makefile("rb") as stream:
                return json.loads(stream.readline())

    target = service._server if completion_stage == "socket_shutdown" else handler_class
    attribute = "shutdown_request" if completion_stage == "socket_shutdown" else "finish"
    replacement = delayed_socket_shutdown if completion_stage == "socket_shutdown" else delayed_handler_finish
    with patch.object(target, attribute, new=replacement):
        with service:
            try:
                assert call()["ok"] is True
                assert shutdown_entered.wait(3)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    result = pool.submit(call)
                    response = result.result(timeout=3)
                    assert response == {"schema_version": 1, "ok": True, "result": {"status": "ready"}}
                    assert not waiting.is_set()
                    allow_shutdown.set()
                assert service._server.connection_slots.acquire(timeout=3)
                service._server.connection_slots.release()
                # Delayed teardown releases no second capacity slot.
                assert call()["ok"] is True
            finally:
                allow_shutdown.set()
    assert not service._thread.is_alive()
    assert not service._path.exists()
    assert service._server._active_handlers == 0
    assert service._server.connection_slots.acquire(blocking=False)
    assert not service._server.connection_slots.acquire(blocking=False)
    service._server.connection_slots.release()


def test_live_handler_saturation_refuses_without_handoff_wait(tmp_path):
    """An occupied dispatcher must not stall the single accept loop."""
    import socket
    import time
    from concurrent.futures import ThreadPoolExecutor

    tmp_path.chmod(0o700)
    entered = threading.Event()
    release = threading.Event()
    timed_acquire = threading.Event()

    def handler(_):
        entered.set()
        assert release.wait(5)
        return {"status": "ready"}

    handlers = {operation: handler for operation in transport._OPERATIONS}
    dispatcher = transport.LocalRequestDispatcher("synthetic-fixture-token", handlers, max_in_flight=1)
    service = transport.LoopbackTcpService(
        tmp_path / "endpoint.json", dispatcher, auth_token="synthetic-fixture-token",
        instance_id="fixture-instance", fencing_epoch=1, max_connections=1,
    )

    class ObservedSlots(threading.BoundedSemaphore):
        def acquire(self, blocking=True, timeout=None):
            if timeout is not None:
                timed_acquire.set()
            return super().acquire(blocking=blocking, timeout=timeout)

    service._server.connection_slots = ObservedSlots(1)

    def call():
        with socket.create_connection(("127.0.0.1", int(service._server.server_address[1])), timeout=3) as client:
            client.sendall(json.dumps({"schema_version": 1, "auth_token": "synthetic-fixture-token",
                                      "operation": "health", "payload": {}}).encode() + b"\n")
            with client.makefile("rb") as stream:
                return json.loads(stream.readline())

    with service:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(call)
            try:
                assert entered.wait(3)
                started = time.monotonic()
                response = call()
                elapsed = time.monotonic() - started
                assert response == {"schema_version": 1, "ok": False, "error_category": "saturated"}
                assert not timed_acquire.is_set()
                assert elapsed < 0.4
            finally:
                release.set()
            assert first.result(timeout=3)["ok"] is True
        assert service._server.connection_slots.acquire(timeout=3)
        service._server.connection_slots.release()
        assert call()["ok"] is True
    assert not service._thread.is_alive()
    assert not service._path.exists()


def test_client_reuses_capacity_after_response_before_handler_finish(tmp_path):
    """Response visibility ends work; delayed stream teardown owns no work slot."""
    from repomap_kg.coordinator.client import LocalCoordinatorClient

    tmp_path.chmod(0o700)
    dispatcher = transport.LocalRequestDispatcher(
        "synthetic-fixture-token",
        {operation: lambda _: {"status": "ready"} for operation in transport._OPERATIONS},
        max_in_flight=1,
    )
    service = transport.LoopbackTcpService(
        tmp_path / "endpoint.json", dispatcher, auth_token="synthetic-fixture-token",
        instance_id="fixture-instance", fencing_epoch=1, max_connections=1,
    )
    entered, release = threading.Event(), threading.Event()
    handler_class = service._server.RequestHandlerClass
    assert isinstance(handler_class, type) and issubclass(handler_class, socketserver.StreamRequestHandler)
    original_finish = handler_class.finish

    def delayed_finish(handler):
        original_finish(handler)
        if not entered.is_set():
            entered.set()
            assert release.wait(5)

    client = LocalCoordinatorClient(service._path, None)
    with patch.object(handler_class, "finish", delayed_finish), service:
        try:
            assert client.health() == {"status": "ready"}
            assert entered.wait(3)
            assert client.health() == {"status": "ready"}
        finally:
            release.set()
    assert service._server._active_handlers == 0
    assert service._server.connection_slots.acquire(blocking=False)
    assert not service._server.connection_slots.acquire(blocking=False)
    service._server.connection_slots.release()
