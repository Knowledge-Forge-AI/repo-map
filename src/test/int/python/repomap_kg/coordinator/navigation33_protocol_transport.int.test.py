"""Integration contracts for Order 2: coordinator protocol session, transport, contracts, limits, and semantics."""

from __future__ import annotations

from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from typing import Any, cast
import unittest

from common_lore_index.coordinator._protocol_session import ProtocolSession
from common_lore_index.coordinator._protocol_validation import (
    ProtocolError,
    decode_jsonl,
    encode_jsonl,
)
from common_lore_index.coordinator.client import CoordinatorClientError, LocalCoordinatorClient
from common_lore_index.coordinator.contracts import normalize_request
from common_lore_index.coordinator.limits import (
    SUBMIT_ADMISSION_CEILING_SECONDS,
    AdmissionDeadline,
    CoordinatorLimits,
)
from common_lore_index.coordinator.protocol import WorkerLaunchSpec, run_worker_spec
from common_lore_index.coordinator.transport import (
    LocalRequestDispatcher,
    LoopbackTcpService,
    TransportError,
    UnixSocketService,
)
from repomap_test_support.portable_worker_scenarios import make_missing_manifest_reference
from repomap_test_support.test_scratch import short_test_directory


def _hello(*, portable: bool = False) -> dict[str, object]:
    caps = ["refresh_graph", "portable_snapshot_v1"] if portable else ["refresh_graph"]
    return {
        "schema_version": 1,
        "message_type": "worker_hello",
        "protocol_versions": [1],
        "worker_generation": "wg1",
        "process_nonce": "nonce1",
        "capabilities": caps,
    }


def _start(*, portable_ext: dict[str, object] | None = None) -> dict[str, object]:
    msg: dict[str, object] = {
        "schema_version": 1,
        "message_type": "job_start",
        "job_id": "job_nav33",
        "attempt": 1,
        "job_kind": "refresh_graph",
        "graph_id": "graph-a",
        "source_generation": "sg1:a",
        "config_generation": "cg1:a",
    }
    if portable_ext is not None:
        msg["portable_snapshot"] = portable_ext
    return msg


def _terminal(*, message_type: str = "result", **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": 1,
        "message_type": message_type,
        "job_id": "job_nav33",
        "attempt": 1,
        "job_kind": "refresh_graph",
        "graph_id": "graph-a",
        "status": "succeeded" if message_type == "result" else "failed",
        "publication_state": "committed" if message_type == "result" else "not_started",
        "latest_run_identity": "run_1" if message_type == "result" else None,
        "source_generation": "sg1:a",
        "config_generation": "cg1:a",
        "extractor_generation": "eg1:a",
        "canonicalizer_generation": "kg1:a",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:01Z",
        "phase": "complete",
        "files": 1,
        "observations": 1,
        "canonical_nodes": 1,
        "canonical_edges": 1,
        "warnings": [],
        "diagnostics": [],
        "retryable": False,
        "error_category": None if message_type == "result" else "permanent",
    }
    base.update(overrides)
    return base


class Navigation33ProtocolTransportIntegrationTests(unittest.TestCase):
    """Integration contracts for protocol session frames, transport bounds, and coordinator semantics."""

    def test_protocol_session_and_jsonl_validation_contracts(self) -> None:
        """ProtocolSession and run_worker_spec reject malformed frames, unnegotiated extensions, and invalid fields."""
        identity = {"job_id": "job_nav33", "attempt": 1}
        limits = CoordinatorLimits()
        manifest_ref = make_missing_manifest_reference().to_mapping()
        with tempfile.TemporaryDirectory() as tmp_d:
            cwd = Path(tmp_d)
            spec_arr = WorkerLaunchSpec(
                argv=(sys.executable, "-c", "import sys; sys.stdout.write('[1, 2, 3]\\n'); sys.stdout.flush()"),
                environment={"LANG": "C.UTF-8"}, cwd=cwd,
            )
            res_arr = run_worker_spec(spec_arr, identity, limits)
            self.assertEqual(res_arr.terminal["reason"], "protocol")
            self.assertEqual(res_arr.protocol_error, "protocol_error:invalid_message")
            self.assertTrue(res_arr.synthesized_terminal and res_arr.waited and res_arr.process_group_cleaned and res_arr.cleanup_error is None)

        s_unneg = ProtocolSession(identity)
        s_unneg.accept_worker(_hello(portable=False))
        with self.assertRaisesRegex(ProtocolError, "negotiation_failed"):
            s_unneg.accept_coordinator(_start(portable_ext={"contract_version": "1.0", "required": True, "snapshot_manifest": manifest_ref}))

        bad_hello = _hello()
        bad_hello["process_nonce"] = ""
        with self.assertRaisesRegex(ProtocolError, "invalid_value"):
            ProtocolSession(identity).accept_worker(bad_hello)

        for field, bad_val in (
            ("job_kind", "other"), ("graph_id", "bad graph!"),
            ("source_generation", "bad:sg"), ("config_generation", "bad:cg"),
        ):
            s = ProtocolSession(identity)
            s.accept_worker(_hello())
            st = _start()
            st[field] = bad_val
            with self.assertRaisesRegex(ProtocolError, "invalid_value"):
                s.accept_coordinator(st)

        s_run = ProtocolSession(identity)
        s_run.accept_worker(_hello())
        s_run.accept_coordinator(_start())
        with self.assertRaisesRegex(ProtocolError, "invalid_value"):
            s_run.accept_worker({
                "schema_version": 1, "message_type": "progress", "job_id": "job_nav33", "attempt": 1,
                "phase": "invalid_phase", "completed": 0, "total": 1, "unit": "files",
                "message_category": "scanning", "heartbeat_at": "2026-01-01T00:00:00Z",
            })
        with self.assertRaisesRegex(ProtocolError, "invalid_value"):
            s_run.accept_worker({
                "schema_version": 1, "message_type": "heartbeat", "job_id": "job_nav33", "attempt": 1,
                "heartbeat_at": "not-a-timestamp",
            })
        s_run.accept_coordinator({"schema_version": 1, "message_type": "cancel", "job_id": "job_nav33", "attempt": 1})
        with self.assertRaisesRegex(ProtocolError, "invalid_value"):
            s_run.accept_worker({
                "schema_version": 1, "message_type": "cancel_ack", "job_id": "job_nav33", "attempt": 1, "status": "unknown_ack",
            })

        for overrides in (
            {"job_kind": "wrong"}, {"files": -1},
            {"status": "succeeded", "publication_state": "not_started", "latest_run_identity": "run_x"},
            {"message_type": "error", "status": "failed", "error_category": "not_in_vocab", "publication_state": "not_started", "latest_run_identity": None},
            {"status": "cancelled", "publication_state": "not_started", "latest_run_identity": "unexpected_run", "error_category": None},
        ):
            s_t = ProtocolSession(identity)
            s_t.accept_worker(_hello())
            s_t.accept_coordinator(_start())
            if overrides.get("status") == "cancelled":
                s_t.accept_coordinator({"schema_version": 1, "message_type": "cancel", "job_id": "job_nav33", "attempt": 1})
            with self.assertRaisesRegex(ProtocolError, "(invalid_value|identity_mismatch)"):
                s_t.accept_worker(_terminal(**overrides))

        s_port = ProtocolSession(identity)
        s_port.accept_worker(_hello(portable=True))
        s_port.accept_coordinator(_start(portable_ext={"contract_version": "1.0", "required": True, "snapshot_manifest": manifest_ref}))
        with self.assertRaisesRegex(ProtocolError, "invalid_value"):
            s_port.accept_worker(_terminal(
                publication_state="not_started", latest_run_identity=None, error_category="permanent",
                portable_snapshot={
                    "contract_version": "1.0", "outcome": "completed",
                    "receipt": {**manifest_ref, "media_type": "application/x-repomap-extraction-receipt-v1+json"},
                    "bundle": {**manifest_ref, "media_type": "application/x-repomap-publication-bundle-v1+jsonl"},
                },
            ))

        with self.assertRaisesRegex(ProtocolError, "frame_too_large"):
            encode_jsonl({"a": "x" * 64}, max_line_bytes=16)
        with self.assertRaises(ValueError):
            decode_jsonl(b"{}\n", max_line_bytes=0)

        for bad_ext, expected_err in (
            ("not-a-dict", "invalid_extension"),
            ({"contract_version": "2.0", "required": True, "snapshot_manifest": {}}, "unsupported_extension"),
            ({"contract_version": "1.0", "required": False, "snapshot_manifest": {}}, "invalid_extension"),
        ):
            s_ext = ProtocolSession(identity)
            s_ext.accept_worker(_hello(portable=True))
            with self.assertRaisesRegex(ProtocolError, expected_err):
                s_ext.accept_coordinator(_start(portable_ext=cast(Any, bad_ext)))

    def test_transport_dispatcher_saturation_oversized_response_and_validation(self) -> None:
        """Transport enforces handler sets, saturation, frame bounds, and public result validation."""
        with self.assertRaisesRegex(ValueError, "transport configuration is invalid"):
            LocalRequestDispatcher("", {}, max_in_flight=1)

        gate = threading.Event()
        release = threading.Event()

        def _slow_health(_p: Any) -> dict[str, object]:
            gate.set()
            release.wait(2.0)
            return {"status": "ready"}

        handlers: dict[str, Any] = {
            "health": _slow_health,
            **{op: (lambda _p: {"status": "ok"}) for op in ("submit", "status", "wait", "cancel", "list")},
        }
        disp = LocalRequestDispatcher("tok-nav33", handlers, max_in_flight=1)
        t = threading.Thread(target=lambda: disp.dispatch({"schema_version": 1, "operation": "health", "auth_token": "tok-nav33", "payload": {}}))
        t.start()
        self.assertTrue(gate.wait(2.0))
        try:
            with self.assertRaisesRegex(TransportError, "saturated"):
                disp.dispatch({"schema_version": 1, "operation": "health", "auth_token": "tok-nav33", "payload": {}})
        finally:
            release.set()
            t.join(2.0)

        nested: Any = "leaf"
        for _ in range(10):
            nested = [nested]
        for bad_result in (nested, {"bad": object()}, {"outer": {"credential": "secret"}}):
            def invalid_health(_payload: Any) -> Any:
                return bad_result

            bad_disp = LocalRequestDispatcher(
                "tok-nav33",
                {
                    "health": invalid_health,
                    **{op: (lambda _p: {"status": "ok"}) for op in ("submit", "status", "wait", "cancel", "list")},
                },
                max_in_flight=1,
            )
            with self.assertRaisesRegex(TransportError, "invalid_response"):
                bad_disp.dispatch({"schema_version": 1, "operation": "health", "auth_token": "tok-nav33", "payload": {}})

        for bad_payload in ({"graph_id": "g1"}, {"limit": 10, "graph_id": 123}):
            with self.assertRaisesRegex(TransportError, "invalid_request"):
                disp.dispatch({"schema_version": 1, "operation": "list", "auth_token": "tok-nav33", "payload": bad_payload})
        with self.assertRaisesRegex(TransportError, "unsupported_operation"):
            disp.dispatch({"schema_version": 1, "operation": "unknown_op", "auth_token": "tok-nav33", "payload": {}})
        self.assertEqual(
            disp.dispatch({"schema_version": 1, "operation": "list", "auth_token": "tok-nav33", "payload": {"limit": 10, "graph_id": "g1"}})["ok"],
            True,
        )

        # Oversized response over LoopbackTcpService and unsafe socket directory
        tcp_token = "tok-nav33-secret-token-01"
        big_disp = LocalRequestDispatcher(
            tcp_token,
            {
                "health": lambda _p: {"blob": "x" * 2048},
                **{op: (lambda _p: {"ok": True}) for op in ("submit", "status", "wait", "cancel", "list")},
            },
            max_in_flight=2,
        )
        with short_test_directory("nav33-tr-", "coord.sock") as d:
            root = Path(d)
            desc_path = root / "endpoint.json"
            with self.assertRaisesRegex(TransportError, "endpoint_descriptor_failed"):
                LoopbackTcpService(
                    desc_path, big_disp, max_connections=1, max_frame_bytes=512,
                    instance_id="inst_t", fencing_epoch=1, auth_token="short",
                )
            with LoopbackTcpService(
                desc_path, big_disp, max_connections=1, max_frame_bytes=512,
                instance_id="inst_t", fencing_epoch=1, auth_token=tcp_token,
            ) as tcp_svc:
                assert tcp_svc._descriptor is not None
                with socket.create_connection(("127.0.0.1", tcp_svc._descriptor.port), timeout=2.0) as sock:
                    req = encode_jsonl({"schema_version": 1, "operation": "health", "auth_token": tcp_token, "payload": {}})
                    sock.sendall(req)
                    reply = cast(dict[str, Any], decode_jsonl(sock.makefile("rb").readline()))
                    self.assertEqual(reply["error_category"], "invalid_response")

            unsafe_dir = root / "unsafe"
            unsafe_dir.mkdir(mode=0o755)
            unsafe_dir.chmod(0o755)
            with self.assertRaisesRegex(TransportError, "unsafe_socket_directory"):
                with UnixSocketService(unsafe_dir / "c.sock", big_disp, max_connections=1):
                    pass

    def test_contracts_limits_and_semantics_decision_edges(self) -> None:
        """UnixSocketService and LocalCoordinatorClient enforce request normalization and admission deadlines over Unix sockets."""
        req_base: dict[str, object] = {
            "schema_version": 1, "job_kind": "refresh_graph", "graph_id": "graph_a",
            "request_id": "req_1", "idempotency_key": "idem_1", "priority": "manual",
            "operation_options": {"reason": "test"},
        }

        def _submit_handler(payload: Any) -> dict[str, object]:
            try:
                deadline = AdmissionDeadline.from_wire(payload["admission_deadline"])
                req = normalize_request(
                    payload["request"],
                    source_generation="sg1:a",
                    config_generation="cg1:a",
                    require_synthetic_graph=False,
                )
                deadline.remaining()
            except (KeyError, ValueError):
                raise TransportError("invalid_request") from None
            return {"job_id": f"job_{req.graph_id}", "state": "queued", "replayed": False}

        with short_test_directory("nav33-cnt-", "coord.sock") as d:
            root = Path(d)
            sock_path = root / "coord.sock"
            tok_path = root / "coord.token"
            tok_path.write_text("tok-cnt-secret-01", encoding="utf-8")
            tok_path.chmod(0o600)
            disp = LocalRequestDispatcher(
                "tok-cnt-secret-01",
                {
                    "submit": _submit_handler,
                    "health": lambda _p: {"status": "ready"},
                    "status": lambda p: {"job_id": p["job_id"], "state": "queued"},
                    "wait": lambda p: {"job_id": p["job_id"], "state": "succeeded"},
                    "cancel": lambda p: {"job_id": p["job_id"], "state": "cancel_requested"},
                    "list": lambda _p: {"jobs": [], "next_cursor": None},
                },
                max_in_flight=2,
            )
            with UnixSocketService(sock_path, disp, max_connections=2):
                client = LocalCoordinatorClient(sock_path, tok_path)
                admitted = client.submit(req_base, admission_budget_seconds=5.0)
                self.assertEqual(admitted["job_id"], "job_graph_a")
                self.assertEqual(client.status("job_graph_a")["state"], "queued")
                self.assertEqual(client.cancel("job_graph_a")["state"], "cancel_requested")
                self.assertEqual(client.list_jobs(limit=5, graph_id="graph_a")["jobs"], [])

                for bad_req in (
                    {**req_base, "schema_version": True},
                    {**req_base, "graph_id": "bad graph!"},
                ):
                    with self.assertRaisesRegex(CoordinatorClientError, "invalid_request"):
                        client.submit(bad_req, admission_budget_seconds=5.0)

                for bad_deadline in (
                    "not-a-number",
                    time.time() + SUBMIT_ADMISSION_CEILING_SECONDS + 100.0,
                ):
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                        s.settimeout(2.0)
                        s.connect(str(sock_path))
                        s.sendall(encode_jsonl({
                            "schema_version": 1,
                            "operation": "submit",
                            "auth_token": "tok-cnt-secret-01",
                            "payload": {"request": req_base, "admission_deadline": bad_deadline},
                        }))
                        reply = cast(dict[str, Any], decode_jsonl(s.makefile("rb").readline()))
                        self.assertEqual((reply["ok"], reply["error_category"]), (False, "invalid_request"))
