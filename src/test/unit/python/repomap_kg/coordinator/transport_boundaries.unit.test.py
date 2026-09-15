"""Unit tests for coordinator transport validation, payload bounds, and prohibited authority guards."""

from __future__ import annotations

from collections.abc import Callable, Mapping

import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from repomap_kg.coordinator import transport
from repomap_kg.coordinator import _transport_validation as validation
from repomap_kg.coordinator.transport import TransportError


def _make_dispatcher(auth_token="secret-token", handlers=None, max_in_flight=4):
    default_handlers = {
        "submit": lambda p: {"job_id": "job-new"},
        "status": lambda p: {"job_id": p.get("job_id", "j1"), "state": "running"},
        "wait": lambda p: {"job_id": p.get("job_id", "j1"), "state": "succeeded"},
        "cancel": lambda p: {"job_id": p.get("job_id", "j1"), "state": "cancelled"},
        "health": lambda p: {"status": "ready"},
        "list": lambda p: {"jobs": []},
    }
    merged = dict(default_handlers)
    if handlers:
        merged.update(handlers)
    return transport.LocalRequestDispatcher(auth_token, merged, max_in_flight=max_in_flight)


class ValidPublicResultUnitTests(unittest.TestCase):
    """Test _valid_public_result depth, type, and bounds branches."""

    def test_primitive_and_bounds_validation(self):
        self.assertTrue(transport.validate_public_result(None))
        self.assertTrue(transport.validate_public_result(True))
        self.assertTrue(transport.validate_public_result(False))
        self.assertTrue(transport.validate_public_result(12345))
        self.assertTrue(transport.validate_public_result(2**63 - 1))
        # Exceeding integer bounds
        self.assertFalse(validation._valid_public_result(2**63))
        self.assertFalse(validation._valid_public_result(-(2**63)))
        # Floating point numbers are not valid public transport results
        self.assertFalse(transport.validate_public_result(12.34))
        self.assertFalse(transport.validate_public_result(object()))

    def test_recursion_depth_limit(self):
        nested: dict[str, object] = {"level": 1}
        cur = nested
        for _ in range(10):
            nxt: dict[str, object] = {"child": 1}
            cur["inner"] = nxt
            cur = nxt
        self.assertFalse(validation._valid_public_result(nested, depth=9))

    def test_string_content_bounds(self):
        self.assertTrue(transport.validate_public_result("safe-plain-text"))
        # Exceeds maximum 4096
        self.assertFalse(transport.validate_public_result("a" * 4097))

    def test_list_and_dict_bounds(self):
        # List bounds: max 32 items
        self.assertTrue(transport.validate_public_result([1, 2, 3]))
        self.assertFalse(transport.validate_public_result([1] * 33))

        # Dict bounds: max 32 items, key length bounds
        self.assertTrue(transport.validate_public_result({"key": "val"}))
        self.assertFalse(transport.validate_public_result({f"k{i}": i for i in range(33)}))
        self.assertFalse(transport.validate_public_result({"": "empty-key"}))
        self.assertFalse(transport.validate_public_result({"a" * 129: "too-long-key"}))
        self.assertFalse(transport.validate_public_result({123: "non-string-key"}))


class ProhibitedAuthorityUnitTests(unittest.TestCase):
    """Test _contains_prohibited_authority detection."""

    def test_prohibited_dict_keys(self):
        for key in ("root", "database", "sql", "command", "connector", "credential", "backup"):
            with self.subTest(key=key):
                self.assertTrue(validation._contains_prohibited_authority({key: "val"}))
                self.assertTrue(validation._contains_prohibited_authority({"nested": {key: "val"}}))

    def test_prohibited_string_characters_and_urls(self):
        self.assertTrue(validation._contains_prohibited_authority("/path/to/file"))
        self.assertTrue(validation._contains_prohibited_authority("C:\\path\\file"))
        self.assertTrue(validation._contains_prohibited_authority("http://example.com"))
        self.assertTrue(validation._contains_prohibited_authority(["safe", "nested/path"]))
        self.assertFalse(validation._contains_prohibited_authority("plain-safe-text"))
        self.assertFalse(validation._contains_prohibited_authority(12345))
        self.assertFalse(validation._contains_prohibited_authority(None))


class ValidOperationPayloadUnitTests(unittest.TestCase):
    """Test _valid_operation_payload schema validation per operation."""

    def test_health_payload(self):
        self.assertTrue(validation._valid_operation_payload("health", {}))
        self.assertFalse(validation._valid_operation_payload("health", {"extra": 1}))

    def test_submit_payload(self):
        self.assertTrue(validation._valid_operation_payload("submit", {"request": {}}))
        self.assertFalse(validation._valid_operation_payload("submit", {"request": "not-dict"}))
        self.assertFalse(validation._valid_operation_payload("submit", {}))
        self.assertFalse(validation._valid_operation_payload("submit", {"request": {}, "extra": 1}))

    def test_status_wait_cancel_payload(self):
        for op in ("status", "wait", "cancel"):
            with self.subTest(op=op):
                self.assertTrue(validation._valid_operation_payload(op, {"job_id": "job-1"}))
                self.assertFalse(validation._valid_operation_payload(op, {"job_id": ""}))
                self.assertFalse(validation._valid_operation_payload(op, {"job_id": "j" * 129}))
                self.assertFalse(validation._valid_operation_payload(op, {"job_id": 123}))
                self.assertFalse(validation._valid_operation_payload(op, {"job_id": "job-1", "extra": 1}))

    def test_list_payload(self):
        self.assertTrue(validation._valid_operation_payload("list", {"limit": 10}))
        self.assertTrue(validation._valid_operation_payload("list", {"limit": 10, "graph_id": "g1"}))
        self.assertFalse(validation._valid_operation_payload("list", {}))  # limit missing
        self.assertFalse(validation._valid_operation_payload("list", {"limit": 10, "unknown": "key"}))
        self.assertFalse(validation._valid_operation_payload("list", {"limit": -1}))  # invalid limit
        for bad in ({"limit": True}, {"limit": False}, {"limit": "10"}, {"limit": 10, "graph_id": 1}, {"limit": 10, "cursor": 1}):
            self.assertFalse(validation._valid_operation_payload("list", bad))

    def test_unsupported_operation_returns_false(self):
        self.assertFalse(validation._valid_operation_payload("unknown_op", {}))


class DispatcherConfigAndErrorUnitTests(unittest.TestCase):
    """Test LocalRequestDispatcher init validation and error helpers."""

    def test_dispatcher_init_validation(self):
        handlers: dict[str, Callable[[Mapping[str, object]], object]] = {
            op: lambda _: {} for op in transport._OPERATIONS
        }
        # Empty auth_token
        with self.assertRaises(ValueError):
            transport.LocalRequestDispatcher("", handlers, max_in_flight=1)
        # Missing operation in handlers
        partial = dict(handlers)
        del partial["health"]
        with self.assertRaises(ValueError):
            transport.LocalRequestDispatcher("tok", partial, max_in_flight=1)
        # Invalid max_in_flight
        with self.assertRaises(ValueError):
            transport.LocalRequestDispatcher("tok", handlers, max_in_flight=0)

    def test_error_response_and_encode(self):
        err = transport._error_response("custom_error")
        self.assertEqual(err, {"schema_version": 1, "ok": False, "error_category": "custom_error"})
        encoded = transport._encode_response(err)
        self.assertTrue(encoded.endswith(b"\n"))


class LocalRequestDispatcherUnitTests(unittest.TestCase):
    """Test LocalRequestDispatcher dispatch validation, saturation, and lifecycle."""

    def setUp(self):
        self.dispatcher = _make_dispatcher("auth-tok")

    def test_dispatch_structure_and_version_refusal(self):
        for bad in (None, "string", [1, 2], 123):
            with self.assertRaises(TransportError) as ctx:
                self.dispatcher.dispatch(bad)
            self.assertEqual(str(ctx.exception), "invalid_request")

        valid = {
            "schema_version": 1,
            "auth_token": "auth-tok",
            "operation": "health",
            "payload": {},
        }
        with self.assertRaises(TransportError) as ctx:
            self.dispatcher.dispatch({k: v for k, v in valid.items() if k != "operation"})
        self.assertEqual(str(ctx.exception), "invalid_request")

        with self.assertRaises(TransportError) as ctx:
            self.dispatcher.dispatch({**valid, "extra": 1})
        self.assertEqual(str(ctx.exception), "invalid_request")

        with self.assertRaises(TransportError) as ctx:
            self.dispatcher.dispatch({**valid, "schema_version": 2})
        self.assertEqual(str(ctx.exception), "incompatible_version")

    def test_dispatch_authorization_refusal(self):
        base = {
            "schema_version": 1,
            "auth_token": "wrong-token",
            "operation": "health",
            "payload": {},
        }
        with self.assertRaises(TransportError) as ctx:
            self.dispatcher.dispatch(base)
        self.assertEqual(str(ctx.exception), "unauthorized")

        with self.assertRaises(TransportError) as ctx:
            self.dispatcher.dispatch({**base, "auth_token": 1234})
        self.assertEqual(str(ctx.exception), "unauthorized")

    def test_dispatch_operation_and_payload_refusal(self):
        base = {
            "schema_version": 1,
            "auth_token": "auth-tok",
            "operation": "unsupported_op",
            "payload": {},
        }
        with self.assertRaises(TransportError) as ctx:
            self.dispatcher.dispatch(base)
        self.assertEqual(str(ctx.exception), "unsupported_operation")

        for bad_payload in (
            "not-a-dict",
            {"root": "/prohibited"},
            {"sql": "SELECT 1"},
        ):
            with self.assertRaises(TransportError) as ctx:
                self.dispatcher.dispatch({**base, "operation": "health", "payload": bad_payload})
            self.assertEqual(str(ctx.exception), "invalid_request")

    def test_dispatch_saturation_and_response_validation(self):
        ev = threading.Event()

        def blocking_health(_):
            ev.wait(timeout=2)
            return {"status": "ready"}

        disp = _make_dispatcher("auth-tok", {"health": blocking_health}, max_in_flight=1)
        req = {
            "schema_version": 1,
            "auth_token": "auth-tok",
            "operation": "health",
            "payload": {},
        }
        t = threading.Thread(target=disp.dispatch, args=(req,))
        t.start()
        try:
            time.sleep(0.05)
            with self.assertRaises(TransportError) as ctx:
                disp.dispatch(req)
            self.assertEqual(str(ctx.exception), "saturated")
        finally:
            ev.set()
            t.join(timeout=2)

        bad_disp = _make_dispatcher("auth-tok", {"health": lambda _: {"root": "/bad"}})
        with self.assertRaises(TransportError) as ctx:
            bad_disp.dispatch(req)
        self.assertEqual(str(ctx.exception), "invalid_response")

    def test_dispatch_success_lifecycle(self):
        req = {
            "schema_version": 1,
            "auth_token": "auth-tok",
            "operation": "health",
            "payload": {},
        }
        res = self.dispatcher.dispatch(req)
        self.assertEqual(res, {"schema_version": 1, "ok": True, "result": {"status": "ready"}})


class UnixSocketServiceUnitTests(unittest.TestCase):
    """Test UnixSocketService streaming protocol and lifecycle."""

    def test_unix_socket_validation_and_lifecycle(self):
        if os.name != "posix" or not hasattr(socket, "AF_UNIX"):
            self.skipTest("POSIX Unix domain sockets required")

        with tempfile.TemporaryDirectory() as tmp_dir:
            parent = Path(tmp_dir)
            os.chmod(parent, 0o700)
            sock_path = parent / "test.sock"
            disp = _make_dispatcher()

            with self.assertRaises(ValueError):
                transport.UnixSocketService(sock_path, disp, max_connections=0)
            with self.assertRaises(ValueError):
                transport.UnixSocketService(sock_path, disp, max_connections=1, max_frame_bytes=0)
            with self.assertRaises(ValueError):
                transport.UnixSocketService(
                    sock_path, disp, max_connections=1, max_frame_bytes=2 * 1024 * 1024
                )

            with transport.UnixSocketService(sock_path, disp, max_connections=2):
                self.assertTrue(sock_path.exists())
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.connect(str(sock_path))
                    req = json.dumps({
                        "schema_version": 1,
                        "auth_token": "secret-token",
                        "operation": "health",
                        "payload": {},
                    }).encode() + b"\n"
                    client.sendall(req)
                    resp = json.loads(client.makefile().readline())
                    self.assertTrue(resp["ok"])
                    self.assertEqual(resp["result"]["status"], "ready")

            self.assertFalse(sock_path.exists())

    def test_unix_socket_frame_error_handling(self):
        if os.name != "posix" or not hasattr(socket, "AF_UNIX"):
            self.skipTest("POSIX Unix domain sockets required")

        with tempfile.TemporaryDirectory() as tmp_dir:
            parent = Path(tmp_dir)
            os.chmod(parent, 0o700)
            sock_path = parent / "test.sock"
            disp = _make_dispatcher()

            with transport.UnixSocketService(sock_path, disp, max_connections=2, max_frame_bytes=128):
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.connect(str(sock_path))
                    client.sendall(b"a" * 200 + b"\n")
                    resp = json.loads(client.makefile().readline())
                    self.assertFalse(resp["ok"])
                    self.assertEqual(resp["error_category"], "frame_too_large")

                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.connect(str(sock_path))
                    client.sendall(b"invalid-json\n")
                    resp = json.loads(client.makefile().readline())
                    self.assertFalse(resp["ok"])
                    self.assertEqual(resp["error_category"], "invalid_request")

    def test_unix_socket_platform_and_directory_guards(self):
        disp = _make_dispatcher()
        socket_path = Path("fixture.sock")
        with patch.object(transport.os, "name", "nt"):
            with self.assertRaises(TransportError) as ctx:
                transport.UnixSocketService(socket_path, disp, max_connections=1)
            self.assertEqual(str(ctx.exception), "unsupported_platform")

        with tempfile.TemporaryDirectory() as tmp_dir:
            unsafe_dir = Path(tmp_dir) / "unsafe"
            unsafe_dir.mkdir()
            unsafe_dir.chmod(0o777)
            with self.assertRaises(TransportError) as ctx:
                transport.UnixSocketService(unsafe_dir / "t.sock", disp, max_connections=1)
            self.assertEqual(str(ctx.exception), "unsafe_socket_directory")


class LoopbackTcpServiceUnitTests(unittest.TestCase):
    """Test LoopbackTcpService lifecycle and communication."""

    def test_loopback_tcp_service_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            parent = Path(tmp_dir)
            os.chmod(parent, 0o700)
            ep_path = parent / "endpoint.json"
            valid_tok = "tcp-token-12345678"
            disp = _make_dispatcher(valid_tok)

            with self.assertRaises(ValueError):
                transport.LoopbackTcpService(
                    ep_path,
                    disp,
                    auth_token=valid_tok,
                    instance_id="inst",
                    fencing_epoch=1,
                    max_connections=0,
                )

            with transport.LoopbackTcpService(
                ep_path,
                disp,
                auth_token=valid_tok,
                instance_id="inst-1",
                fencing_epoch=10,
                max_connections=2,
            ):
                self.assertTrue(ep_path.exists())
                ep_data = json.loads(ep_path.read_text(encoding="utf-8"))
                self.assertEqual(ep_data["instance_id"], "inst-1")
                self.assertEqual(ep_data["fencing_epoch"], 10)
                port = ep_data["port"]

                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                    client.connect(("127.0.0.1", port))
                    req = json.dumps({
                        "schema_version": 1,
                        "auth_token": valid_tok,
                        "operation": "health",
                        "payload": {},
                    }).encode() + b"\n"
                    client.sendall(req)
                    resp = json.loads(client.makefile().readline())
                    self.assertTrue(resp["ok"])
                    self.assertEqual(resp["result"]["status"], "ready")

            self.assertFalse(ep_path.exists())


if __name__ == "__main__":
    unittest.main()
