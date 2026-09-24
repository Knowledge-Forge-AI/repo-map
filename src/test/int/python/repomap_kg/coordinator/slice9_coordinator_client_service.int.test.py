"""Integration tests for Slice 9 Group S9-A: Coordinator Client, Service, and Transport Boundaries."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import tempfile
import threading
from typing import Any
import unittest

from repomap_kg.coordinator.client import (
    CoordinatorClientError,
    LocalCoordinatorClient,
    _decode_response,
)
from repomap_kg.coordinator.job_control import (
    CoordinatorModeError,
    format_coordinator_health_table,
    list_coordinator_jobs,
    wait_for_coordinator_job,
)
from repomap_kg.coordinator.local_mode import (
    _resolve_psql_executable,
    coordinator_runtime_paths,
)
from repomap_kg.coordinator.transport import (
    LocalRequestDispatcher,
    TransportError,
    _handle_stream,
)


class Slice9CoordinatorClientServiceIntegrationTests(unittest.TestCase):
    """Integration scenarios for client request decoding, dispatcher routing, and job control."""

    def test_s9_a08_coordinator_client_frame_size_and_invalid_request_refusal(self) -> None:
        """Timeout boundaries and _MAX_FRAME_BYTES limit refusal before network I/O."""
        with self.assertRaises(ValueError) as cm_zero:
            LocalCoordinatorClient(Path("/tmp/nonexistent.sock"), None, timeout_seconds=0.0)
        self.assertIn("client timeout is invalid", str(cm_zero.exception))

        with self.assertRaises(ValueError) as cm_large:
            LocalCoordinatorClient(Path("/tmp/nonexistent.sock"), None, timeout_seconds=61.0)
        self.assertIn("client timeout is invalid", str(cm_large.exception))

        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "token.txt"
            token_file.write_text("secret_token_12345", encoding="utf-8")
            token_file.chmod(0o600)
            client = LocalCoordinatorClient(Path(temp_dir) / "test.sock", token_file, timeout_seconds=5.0)

            # Exact 64 KiB frame boundary: base envelope is 107 bytes, pad = 65429
            # 65,536 bytes passes frame check and attempts socket connect (raises unavailable)
            exact_boundary_payload = {"k": "x" * 65429}
            with self.assertRaises(CoordinatorClientError) as cm_exact:
                client.submit(exact_boundary_payload)
            self.assertEqual(str(cm_exact.exception), "unavailable")

            # 65,537 bytes fails frame check before connect (raises invalid_request)
            oversized_payload = {"k": "x" * 65430}
            with self.assertRaises(CoordinatorClientError) as cm_req:
                client.submit(oversized_payload)
            self.assertEqual(str(cm_req.exception), "invalid_request")

    def test_s9_a09_coordinator_client_response_decode_refusal_categories(self) -> None:
        """Client decode handles framing errors, schema mismatch, and maps error categories."""
        with self.assertRaises(CoordinatorClientError) as cm_empty:
            _decode_response(b"")
        self.assertEqual(str(cm_empty.exception), "invalid_response")

        with self.assertRaises(CoordinatorClientError) as cm_no_newline:
            _decode_response(b'{"schema_version":1}')
        self.assertEqual(str(cm_no_newline.exception), "invalid_response")

        with self.assertRaises(CoordinatorClientError) as cm_ver:
            _decode_response(b'{"schema_version":2,"ok":true}\n')
        self.assertEqual(str(cm_ver.exception), "invalid_response")

        with self.assertRaises(CoordinatorClientError) as cm_bool_ver:
            _decode_response(b'{"schema_version":true,"ok":true}\n')
        self.assertEqual(str(cm_bool_ver.exception), "invalid_response")

        # Exact 64 KiB + 1 response boundary: 65,537 bytes decodes ok, 65,538 raises invalid_response
        prefix = b'{"ok":true,"result":{"k":"'
        suffix = b'"},"schema_version":1}\n'
        resp_65537 = prefix + b"a" * (65537 - len(prefix) - len(suffix)) + suffix
        self.assertEqual(len(resp_65537), 65537)
        self.assertTrue(_decode_response(resp_65537)["ok"])

        resp_65538 = prefix + b"a" * (65538 - len(prefix) - len(suffix)) + suffix
        self.assertEqual(len(resp_65538), 65538)
        with self.assertRaises(CoordinatorClientError) as cm_resp_over:
            _decode_response(resp_65538)
        self.assertEqual(str(cm_resp_over.exception), "invalid_response")

        # Error category translation tested through client connected to real AF_UNIX socket
        with tempfile.TemporaryDirectory() as temp_dir:
            sock_path = Path(temp_dir) / "server.sock"
            token_file = Path(temp_dir) / "token.txt"
            token_file.write_text("token123", encoding="utf-8")
            token_file.chmod(0o600)
            client = LocalCoordinatorClient(sock_path, token_file)

            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.settimeout(2.0)
            server.bind(str(sock_path))
            server.listen(1)
            try:
                def _serve_response(response_bytes: bytes) -> None:
                    try:
                        conn, _ = server.accept()
                        with conn:
                            conn.settimeout(2.0)
                            conn.makefile("rb").readline()
                            conn.sendall(response_bytes)
                    except Exception:
                        pass

                t1 = threading.Thread(
                    target=_serve_response,
                    args=(b'{"schema_version":1,"ok":false,"error_category":"unauthorized"}\n',),
                )
                t1.start()
                with self.assertRaises(CoordinatorClientError) as cm_unauth:
                    client.health()
                t1.join(timeout=2.0)
                self.assertEqual(str(cm_unauth.exception), "unauthorized")

                t2 = threading.Thread(
                    target=_serve_response,
                    args=(b'{"schema_version":1,"ok":false,"error_category":"unknown_category"}\n',),
                )
                t2.start()
                with self.assertRaises(CoordinatorClientError) as cm_unknown:
                    client.health()
                t2.join(timeout=2.0)
                self.assertEqual(str(cm_unknown.exception), "invalid_response")
            finally:
                if "t1" in locals() and t1.is_alive():
                    t1.join(timeout=2.0)
                if "t2" in locals() and t2.is_alive():
                    t2.join(timeout=2.0)
                server.close()

        decoded = _decode_response(
            b'{"schema_version":1,"ok":true,"result":{"job_id":"j1","graph_id":"g1","state":"running",'
            b'"submitted_at":"2026-09-21T00:00:00Z"}}\n'
        )
        self.assertTrue(decoded["ok"])

    def test_s9_a10_coordinator_client_private_token_file_validation(self) -> None:
        """Private credential token file permissions, directories, and sizes are validated."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            dir_token = temp_path / "dir_token"
            dir_token.mkdir()
            with self.assertRaises(CoordinatorClientError) as cm_dir:
                LocalCoordinatorClient(temp_path / "test.sock", dir_token)
            self.assertEqual(str(cm_dir.exception), "unsafe_credentials")

            perm_token = temp_path / "perm_token"
            perm_token.write_text("valid_token_value", encoding="utf-8")
            perm_token.chmod(0o644)
            with self.assertRaises(CoordinatorClientError) as cm_perm:
                LocalCoordinatorClient(temp_path / "test.sock", perm_token)
            self.assertEqual(str(cm_perm.exception), "unsafe_credentials")

            empty_token = temp_path / "empty_token"
            empty_token.touch()
            empty_token.chmod(0o600)
            with self.assertRaises(CoordinatorClientError) as cm_empty:
                LocalCoordinatorClient(temp_path / "test.sock", empty_token)
            self.assertEqual(str(cm_empty.exception), "unsafe_credentials")

            ws_token = temp_path / "ws_token"
            ws_token.write_text("  token_with_whitespace  ", encoding="utf-8")
            ws_token.chmod(0o600)
            with self.assertRaises(CoordinatorClientError) as cm_ws:
                LocalCoordinatorClient(temp_path / "test.sock", ws_token)
            self.assertEqual(str(cm_ws.exception), "unsafe_credentials")

    def test_s9_a11_coordinator_service_lifecycle_heartbeat_and_degrade(self) -> None:
        """Stream handling dispatches requests and enforces 64KB frame limit refusal."""
        server_sock, client_sock = socket.socketpair()
        server_sock.settimeout(2.0)
        client_sock.settimeout(2.0)
        reader = server_sock.makefile("rb")
        writer = server_sock.makefile("wb")
        t: threading.Thread | None = None
        try:
            class _MockService:
                _max_frame = 64 * 1024
                _dispatcher = LocalRequestDispatcher(
                    "token_s9_a11",
                    {
                        "health": lambda _p: {"service_status": "healthy"},
                        "submit": lambda _p: {"job_id": "j1"},
                        "status": lambda _p: {"job_id": "j1", "state": "running"},
                        "wait": lambda _p: {"job_id": "j1", "state": "succeeded"},
                        "cancel": lambda _p: {"job_id": "j1", "state": "cancelled"},
                        "list": lambda _p: {"jobs": [], "next_cursor": None},
                    },
                    max_in_flight=4,
                )

                def _write_error(self, stream: Any, category: str) -> None:
                    payload = json.dumps({"schema_version": 1, "ok": False, "error_category": category}) + "\n"
                    stream.write(payload.encode("utf-8"))

            req = json.dumps(
                {
                    "schema_version": 1,
                    "auth_token": "token_s9_a11",
                    "operation": "health",
                    "payload": {},
                }
            ).encode("utf-8") + b"\n"
            client_sock.sendall(req)

            _handle_stream(_MockService(), reader, writer)
            writer.flush()

            resp = client_sock.makefile("rb").readline()
            data = json.loads(resp)
            self.assertTrue(data["ok"])
            self.assertEqual(data["result"]["service_status"], "healthy")

            # Oversized frame exceeding 64KB frame limit refusal
            oversized_req = b"x" * (64 * 1024 + 2) + b"\n"
            t = threading.Thread(target=_handle_stream, args=(_MockService(), reader, writer))
            t.start()
            client_sock.sendall(oversized_req)
            t.join(timeout=2.0)
            writer.flush()
            err_resp = json.loads(client_sock.makefile("rb").readline())
            self.assertFalse(err_resp["ok"])
            self.assertEqual(err_resp["error_category"], "frame_too_large")
        finally:
            if t is not None and t.is_alive():
                t.join(timeout=2.0)
            reader.close()
            writer.close()
            server_sock.close()
            client_sock.close()

    def test_s9_a12_coordinator_transport_dispatch_routing_and_error_handling(self) -> None:
        """Dispatcher operation routing, token verification, and error serialization."""
        dispatcher = LocalRequestDispatcher(
            "correct_token_value",
            {
                "health": lambda _p: {"service_status": "healthy"},
                "submit": lambda _p: {"job_id": "j1"},
                "status": lambda _p: {"job_id": "j1", "state": "running"},
                "wait": lambda _p: {"job_id": "j1", "state": "succeeded"},
                "cancel": lambda _p: {"job_id": "j1", "state": "cancelled"},
                "list": lambda _p: {"jobs": [], "next_cursor": None},
            },
            max_in_flight=1,
        )

        with self.assertRaises(TransportError) as cm_field:
            dispatcher.dispatch({"invalid": "request_shape"})
        self.assertEqual(str(cm_field.exception), "invalid_request")

        with self.assertRaises(TransportError) as cm_tok:
            dispatcher.dispatch({
                "schema_version": 1,
                "auth_token": "wrong_token",
                "operation": "health",
                "payload": {},
            })
        self.assertEqual(str(cm_tok.exception), "unauthorized")

        with self.assertRaises(TransportError) as cm_op:
            dispatcher.dispatch({
                "schema_version": 1,
                "auth_token": "correct_token_value",
                "operation": "unsupported_op",
                "payload": {},
            })
        self.assertEqual(str(cm_op.exception), "unsupported_operation")

        res = dispatcher.dispatch({
            "schema_version": 1,
            "auth_token": "correct_token_value",
            "operation": "health",
            "payload": {},
        })
        self.assertTrue(res["ok"])
        self.assertEqual(res["schema_version"], 1)

    def test_s9_a13_coordinator_job_control_wait_and_listing_boundaries(self) -> None:
        """Job control wait polling timeout, pagination cursor, and health table formatting."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            token_path = temp_path / "auth_token"
            token_path.write_text("token123", encoding="utf-8")
            token_path.chmod(0o600)

            class _FakeClient:
                def __init__(self, _s: Path, _t: Path) -> None:
                    pass

                def wait(self, _job_id: str) -> dict[str, object]:
                    return {
                        "job_id": "job_wait_1",
                        "graph_id": "graph_1",
                        "state": "running",
                        "submitted_at": "2026-09-21T00:00:00Z",
                    }

                def list_jobs(self, **_kw: Any) -> dict[str, object]:
                    return {
                        "jobs": [
                            {
                                "job_id": "job_1",
                                "graph_id": "graph_1",
                                "state": "succeeded",
                                "submitted_at": "2026-09-21T00:00:00Z",
                            }
                        ],
                        "next_cursor": "mismatched_invalid_cursor",
                    }

            with self.assertRaises(CoordinatorModeError) as cm_to:
                wait_for_coordinator_job(temp_path, "job_wait_1", wait_timeout_seconds=1, client_factory=_FakeClient)
            self.assertEqual(str(cm_to.exception), "coordinator_wait_timeout")

            with self.assertRaises(CoordinatorModeError) as cm_list:
                list_coordinator_jobs(temp_path, client_factory=_FakeClient)
            self.assertEqual(str(cm_list.exception), "coordinator_response_invalid")

        health_record = {
            "health_schema_version": 1,
            "status": "ready",
            "service": {"status": "ready"},
            "ownership": {"status": "ready"},
            "queue": {"status": "ready"},
            "workers": {"status": "ready"},
            "publication": {"status": "ready"},
            "polling": {"status": "ready"},
            "transport": {"status": "ready"},
            "storage": {"status": "ready"},
        }
        table = format_coordinator_health_table({"command": "coordinator-health", "health": health_record})
        self.assertIn("service", table)
        self.assertIn("ready", table)

    def test_s9_a14_coordinator_local_mode_runtime_paths_and_psql_resolution(self) -> None:
        """Runtime paths preflight and approved psql executable lookup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            runtime_dir, socket_path, _ = coordinator_runtime_paths(temp_path, create=True)
            self.assertTrue(runtime_dir.exists())
            mode = runtime_dir.stat().st_mode & 0o777
            self.assertEqual(mode, 0o700)
            self.assertLessEqual(len(str(socket_path).encode("utf-8")), 103)

        resolved = _resolve_psql_executable(None)
        self.assertIsInstance(resolved, Path)
        self.assertEqual(resolved.name, "psql")
        with self.assertRaises(CoordinatorModeError) as cm_psql:
            _resolve_psql_executable(Path("/tmp/not_psql_binary"))
        self.assertEqual(str(cm_psql.exception), "coordinator_psql_unavailable")


if __name__ == "__main__":
    import sys
    sys.exit('Direct execution unsupported; use tools/run_tests.py for container sandbox admission.')
