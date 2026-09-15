"""Stream refusals preserve bounded responses and dispatcher capacity."""

from __future__ import annotations

from collections.abc import Buffer, Callable, Mapping
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from repomap_kg.coordinator import transport
from repomap_kg.coordinator.endpoint import (
    EndpointDescriptorError,
    LoopbackEndpointDescriptor,
)


def _service(
    handler: Callable[[Mapping[str, object]], object],
    *,
    error_writer: Callable[[BytesIO, str], None] | None = None,
) -> SimpleNamespace:
    handlers = {name: handler for name in ("submit", "status", "wait", "cancel", "health", "list")}
    dispatcher = transport.LocalRequestDispatcher("unit-token", handlers, max_in_flight=1)
    return SimpleNamespace(
        _dispatcher=dispatcher,
        _max_frame=128,
        _write_error=error_writer or transport.UnixSocketService._write_error,
    )


def _request(token: str = "unit-token") -> bytes:
    return json.dumps({
        "schema_version": 1, "auth_token": token, "operation": "health", "payload": {},
    }).encode() + b"\n"


@pytest.mark.parametrize(("frame", "category"), [
    (b"{}", "frame_too_large"),
    (b"\xff\n", "invalid_request"),
    (_request("incorrect"), "unauthorized"),
])
def test_stream_refuses_invalid_frames_without_handler_calls(frame: bytes, category: str) -> None:
    calls: list[Mapping[str, object]] = []
    writer = BytesIO()
    transport._handle_stream(_service(lambda payload: calls.append(payload)), BytesIO(frame), writer)
    assert json.loads(writer.getvalue()) == {
        "schema_version": 1, "ok": False, "error_category": category,
    }
    assert calls == []


def test_eof_has_no_response_or_dispatch() -> None:
    calls: list[Mapping[str, object]] = []
    writer = BytesIO()
    transport._handle_stream(_service(lambda payload: calls.append(payload)), BytesIO(), writer)
    assert writer.getvalue() == b""
    assert calls == []


def test_oversized_response_is_replaced_with_bounded_error() -> None:
    writer = BytesIO()
    transport._handle_stream(_service(lambda _: "x" * 256), BytesIO(_request()), writer)
    assert json.loads(writer.getvalue()) == {
        "schema_version": 1, "ok": False, "error_category": "invalid_response",
    }
    assert len(writer.getvalue()) <= 129


def test_handler_failure_releases_capacity_and_hides_private_cause() -> None:
    calls = 0

    def handler(_: Mapping[str, object]) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("private handler detail")
        return {"status": "ready"}

    service = _service(handler)
    first, second = BytesIO(), BytesIO()
    transport._handle_stream(service, BytesIO(_request()), first)
    transport._handle_stream(service, BytesIO(_request()), second)
    assert json.loads(first.getvalue()) == {
        "schema_version": 1, "ok": False, "error_category": "internal",
    }
    assert b"private" not in first.getvalue()
    assert json.loads(second.getvalue()) == {
        "schema_version": 1, "ok": True, "result": {"status": "ready"},
    }
    assert calls == 2


@pytest.mark.parametrize("error_type", [BrokenPipeError, ConnectionResetError])
def test_peer_disconnect_does_not_write_a_second_response(error_type: type[OSError]) -> None:
    class DisconnectedWriter:
        calls = 0

        def write(self, data: Buffer, /) -> int:
            self.calls += 1
            raise error_type("peer gone")

    writer = DisconnectedWriter()
    transport._handle_stream(_service(lambda _: {}), BytesIO(_request()), writer)
    assert writer.calls == 1


def test_loopback_tcp_service_write_error() -> None:
    writer = BytesIO()
    transport.LoopbackTcpService._write_error(writer, "custom_error")
    assert json.loads(writer.getvalue()) == {
        "schema_version": 1, "ok": False, "error_category": "custom_error",
    }
    service = _service(lambda _: {}, error_writer=transport.LoopbackTcpService._write_error)
    stream_writer = BytesIO()
    transport._handle_stream(service, BytesIO(b"bad-json\n"), stream_writer)
    assert json.loads(stream_writer.getvalue()) == {
        "schema_version": 1, "ok": False, "error_category": "invalid_request",
    }


def test_threaded_unix_server_process_request_saturation_and_recovery() -> None:
    server = transport._ThreadedUnixServer.__new__(transport._ThreadedUnixServer)
    server.connection_slots = threading.BoundedSemaphore(1)
    server.connection_slots.acquire()
    mock_req = Mock()
    shutdown_mock = Mock()
    setattr(server, "shutdown_request", shutdown_mock)
    server.process_request(mock_req, None)
    mock_req.sendall.assert_called_once_with(
        b'{"error_category":"saturated","ok":false,"schema_version":1}\n'
    )
    shutdown_mock.assert_called_once_with(mock_req)

    server.connection_slots = threading.BoundedSemaphore(1)
    with patch("socketserver.ThreadingMixIn.process_request", side_effect=RuntimeError("thread fail")):
        server.process_request(mock_req, None)
    assert server.connection_slots.acquire(blocking=False) is True


class _ControlledTcpServer(transport._ThreadedTcpServer):
    connection_slots: threading.BoundedSemaphore


def test_threaded_tcp_server_process_request_saturation_and_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _ControlledTcpServer.__new__(_ControlledTcpServer)
    server.connection_slots = threading.BoundedSemaphore(1)
    server.connection_slots.acquire()
    mock_req = Mock()
    shutdown_request = Mock()
    monkeypatch.setattr(server, "shutdown_request", shutdown_request)
    server.process_request(mock_req, ("127.0.0.1", 1234))
    mock_req.sendall.assert_called_once_with(
        b'{"error_category":"saturated","ok":false,"schema_version":1}\n'
    )
    shutdown_request.assert_called_once_with(mock_req)

    server.connection_slots = threading.BoundedSemaphore(1)
    with patch("socketserver.ThreadingMixIn.process_request", side_effect=RuntimeError("thread fail")):
        with pytest.raises(RuntimeError, match="thread fail"):
            server.process_request(mock_req, ("127.0.0.1", 1234))
    assert server.connection_slots.acquire(blocking=False) is True


def test_unix_socket_handler_stream_protocol() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        parent = Path(tmp_dir)
        parent.chmod(0o700)
        sock_path = parent / "u.sock"
        handlers = {
            "submit": lambda _: {"data": "x" * 200},
            "status": lambda _: 1 / 0,
            "wait": lambda _: {},
            "cancel": lambda _: {},
            "health": lambda _: {"status": "ok"},
            "list": lambda _: {},
        }
        disp = transport.LocalRequestDispatcher("tok", handlers, max_in_flight=1)
        server = Mock()
        with (
            patch.object(transport, "os", SimpleNamespace(name="posix", chmod=Mock())),
            patch.object(transport.socketserver, "UnixStreamServer", create=True),
            patch.object(transport, "_validate_socket_parent"),
            patch.object(transport, "_ThreadedUnixServer", return_value=server) as build,
        ):
            transport.UnixSocketService(sock_path, disp, max_connections=1, max_frame_bytes=128)
        handler_cls = build.call_args.args[1]
        server.RequestHandlerClass = handler_cls

        h = handler_cls.__new__(handler_cls)
        h.rfile, h.wfile = BytesIO(b""), BytesIO()
        h.handle()
        assert h.wfile.getvalue() == b""

        h = handler_cls.__new__(handler_cls)
        bad_req = json.dumps({"schema_version": 1, "auth_token": "bad", "operation": "health", "payload": {}}).encode() + b"\n"
        h.rfile, h.wfile = BytesIO(bad_req), BytesIO()
        h.handle()
        assert json.loads(h.wfile.getvalue())["error_category"] == "unauthorized"

        h = handler_cls.__new__(handler_cls)
        large_req = json.dumps({"schema_version": 1, "auth_token": "tok", "operation": "submit", "payload": {"request": {}}}).encode() + b"\n"
        h.rfile, h.wfile = BytesIO(large_req), BytesIO()
        h.handle()
        assert json.loads(h.wfile.getvalue())["error_category"] == "invalid_response"

        class BrokenWriter(BytesIO):
            def write(self, data: Buffer, /) -> int:
                raise BrokenPipeError("broken")

        h = handler_cls.__new__(handler_cls)
        ok_req = json.dumps({"schema_version": 1, "auth_token": "tok", "operation": "health", "payload": {}}).encode() + b"\n"
        h.rfile, h.wfile = BytesIO(ok_req), BrokenWriter()
        h.handle()

        h = handler_cls.__new__(handler_cls)
        err_req = json.dumps({"schema_version": 1, "auth_token": "tok", "operation": "status", "payload": {"job_id": "j1"}}).encode() + b"\n"
        h.rfile, h.wfile = BytesIO(err_req), BytesIO()
        h.handle()
        assert json.loads(h.wfile.getvalue())["error_category"] == "internal"


def test_unix_socket_service_exit_lifecycle() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        parent = Path(tmp_dir)
        parent.chmod(0o700)

        svc1 = transport.UnixSocketService.__new__(transport.UnixSocketService)
        svc1._server = Mock()
        svc1._thread = Mock()
        svc1._thread.is_alive.return_value = False
        svc1._thread.ident = None
        svc1._path = parent / "u1.sock"
        svc1.__exit__(None, None, None)
        svc1._server.server_close.assert_called_once_with()
        svc1._server.shutdown.assert_not_called()
        svc1._thread.join.assert_not_called()

        svc2 = transport.UnixSocketService.__new__(transport.UnixSocketService)
        svc2._server = Mock()
        svc2._thread = Mock()
        svc2._thread.is_alive.return_value = True
        svc2._thread.ident = 123
        svc2._path = parent / "u2.sock"
        svc2._path.write_text("still-owned")
        with pytest.raises(RuntimeError, match="transport did not stop"):
            svc2.__exit__(None, None, None)
        svc2._server.shutdown.assert_called_once_with()
        svc2._server.server_close.assert_called_once_with()
        svc2._thread.join.assert_called_once_with(timeout=5)
        assert svc2._path.read_text() == "still-owned"


def test_loopback_tcp_service_descriptor_errors_and_exit_lifecycle() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        parent = Path(tmp_dir)
        parent.chmod(0o700)
        valid_tok = "tcp-token-12345678"
        disp = transport.LocalRequestDispatcher(valid_tok, {op: lambda _: {} for op in transport._OPERATIONS}, max_in_flight=1)

        ep_fail = parent / "fail.json"
        with patch("repomap_kg.coordinator.transport.write_endpoint_descriptor", side_effect=OSError("write err")):
            with pytest.raises(transport.TransportError, match="endpoint_descriptor_failed"):
                transport.LoopbackTcpService(ep_fail, disp, auth_token=valid_tok, instance_id="inst", fencing_epoch=1, max_connections=1)

        with patch("repomap_kg.coordinator.transport._ThreadedTcpServer", side_effect=OSError("bind err")):
            with pytest.raises(transport.TransportError, match="endpoint_descriptor_failed"):
                transport.LoopbackTcpService(ep_fail, disp, auth_token=valid_tok, instance_id="inst", fencing_epoch=1, max_connections=1)

        ep1 = parent / "ep1.json"
        svc1 = transport.LoopbackTcpService(ep1, disp, auth_token=valid_tok, instance_id="inst-1", fencing_epoch=1, max_connections=1)
        svc1.__exit__(None, None, None)

        ep2 = parent / "ep2.json"
        svc2 = transport.LoopbackTcpService(ep2, disp, auth_token=valid_tok, instance_id="inst-2", fencing_epoch=1, max_connections=1)
        svc2.__enter__()
        with patch.object(svc2._thread, "is_alive", side_effect=[True, True]):
            with pytest.raises(RuntimeError, match="transport did not stop"):
                svc2.__exit__(None, None, None)

        ep3 = parent / "ep3.json"
        svc3 = transport.LoopbackTcpService(ep3, disp, auth_token=valid_tok, instance_id="inst-3", fencing_epoch=1, max_connections=1)
        with patch("repomap_kg.coordinator.transport.load_endpoint_descriptor", side_effect=EndpointDescriptorError("corrupt")):
            svc3.__exit__(None, None, None)

        ep4 = parent / "ep4.json"
        svc4 = transport.LoopbackTcpService(ep4, disp, auth_token=valid_tok, instance_id="inst-4", fencing_epoch=1, max_connections=1)
        other = LoopbackEndpointDescriptor(
            schema_version=1, host="127.0.0.1", port=9999,
            instance_id="other", fencing_epoch=2, auth_token=valid_tok,
        )
        with patch("repomap_kg.coordinator.transport.load_endpoint_descriptor", return_value=other):
            svc4.__exit__(None, None, None)
            assert ep4.exists()
