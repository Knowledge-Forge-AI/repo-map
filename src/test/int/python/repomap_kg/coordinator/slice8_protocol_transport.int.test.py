"""Integration tests for Slice 8 Group S8-A: Transport and Protocol Refusal and Recovery."""

from __future__ import annotations

import json
import socket
import struct
import unittest

from repomap_kg.coordinator._protocol_session import ProtocolSession
from repomap_kg.coordinator._protocol_validation import PROTOCOL_VERSION, ProtocolError
from repomap_kg.storage.staging_event_transport import (
    StagingEventChannel,
    StagingEventTransportError,
)
from repomap_test_support.staging_transport_test_harness import BoundedTestPeer


class Slice8ProtocolTransportIntegrationTests(unittest.TestCase):
    """Integration scenarios for transport framing, socket settlement, and protocol sessions."""

    def test_s8_a01_transport_receiver_validator_rejection_no_ack_and_replay_recovery(self) -> None:
        """Validator rejection suppresses ACK and sequence increment; replaying over clean channel succeeds."""
        s_raw, c_raw = socket.socketpair()
        try:
            sender = StagingEventChannel(s_raw, acknowledgement_timeout_seconds=0.05)
            receiver = StagingEventChannel(c_raw)

            with BoundedTestPeer(s_raw) as send_peer:
                send_peer.start_worker(lambda: sender.send("authority", {"event_category": "rejected_action"}))

                # Receiver validator callback rejects the frame semantically
                with self.assertRaises(ValueError) as cm_val:
                    receiver.receive(
                        timeout_seconds=1.0,
                        validator=lambda _frame: (_ for _ in ()).throw(ValueError("semantic validation failure")),
                    )
                self.assertIn("semantic validation failure", str(cm_val.exception))
                send_peer.expect_worker_error()

            # Sequence was not advanced on refusal
            self.assertEqual(receiver._receive_sequence, 0)
            # Sender experienced acknowledgement timeout because no ACK was sent
            errors = send_peer.take_errors()
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], TimeoutError)

            sender.close()
            receiver.close()
        finally:
            s_raw.close()
            c_raw.close()

        # Recovery: valid exchange succeeds once validator accepts
        s2, c2 = socket.socketpair()
        try:
            sender2 = StagingEventChannel(s2)
            receiver2 = StagingEventChannel(c2)
            with BoundedTestPeer(s2) as send_peer2:
                send_peer2.start_worker(lambda: sender2.send("authority", {"event_category": "accepted_action"}))
                frame = receiver2.receive(timeout_seconds=1.0, validator=lambda _f: None)

            self.assertEqual(frame.sequence, 1)
            self.assertEqual(receiver2._receive_sequence, 1)
            self.assertEqual(frame.payload, {"event_category": "accepted_action"})
            sender2.close()
            receiver2.close()
        finally:
            s2.close()
            c2.close()

    def test_s8_a02_transport_truncated_frame_and_clean_peer_eof_refusal(self) -> None:
        """Clean EOF raises EOFError, while truncated header or body raises StagingEventTransportError."""
        # 1. Clean EOF at start of frame
        s1, c1 = socket.socketpair()
        try:
            chan1 = StagingEventChannel(s1)
            c1.close()
            with self.assertRaises(EOFError) as cm_eof:
                chan1.receive(timeout_seconds=1.0)
            self.assertIn("closed", str(cm_eof.exception))
            chan1.close()
        finally:
            s1.close()

        # 2. Truncated header (< 4 bytes)
        s2, c2 = socket.socketpair()
        try:
            chan2 = StagingEventChannel(s2)
            c2.sendall(b"\x00\x00")  # Only 2 bytes of 4-byte header
            c2.close()
            with self.assertRaises(StagingEventTransportError) as cm_trunc_hdr:
                chan2.receive(timeout_seconds=1.0)
            self.assertIn("early EOF", str(cm_trunc_hdr.exception))
            chan2.close()
        finally:
            s2.close()

        # 3. Truncated body (< declared size)
        s3, c3 = socket.socketpair()
        try:
            chan3 = StagingEventChannel(s3)
            c3.sendall(struct.pack("!I", 40) + b'{"schema": 1}')  # Declared 40 bytes, sent 13
            c3.close()
            with self.assertRaises(StagingEventTransportError) as cm_trunc_body:
                chan3.receive(timeout_seconds=1.0)
            self.assertIn("early EOF", str(cm_trunc_body.exception))
            chan3.close()
        finally:
            s3.close()

    def test_s8_a03_transport_malformed_encoding_and_illegal_schema_refusal(self) -> None:
        """Malformed UTF-8, illegal schema versions, and invalid categories produce bounded refusal."""
        s, c = socket.socketpair()
        try:
            chan = StagingEventChannel(s)

            # 1. Non-UTF-8 body
            bad_bytes = b"\xff\xfe\xfd"
            c.sendall(struct.pack("!I", len(bad_bytes)) + bad_bytes)
            with self.assertRaises(StagingEventTransportError) as cm_utf:
                chan.receive(timeout_seconds=1.0)
            self.assertIn("staging event frame is invalid", str(cm_utf.exception))

            # 2. Schema version unsupported (version 99)
            bad_schema = json.dumps({
                "schema_version": 99,
                "frame_sequence": 1,
                "frame_category": "phase",
                "payload": {},
            }).encode("utf-8")
            c.sendall(struct.pack("!I", len(bad_schema)) + bad_schema)
            with self.assertRaises(StagingEventTransportError) as cm_schema:
                chan.receive(timeout_seconds=1.0)
            self.assertIn("staging event schema is invalid", str(cm_schema.exception))

            # 3. Illegal category
            bad_cat = json.dumps({
                "schema_version": 1,
                "frame_sequence": 1,
                "frame_category": "unregistered_category",
                "payload": {},
            }).encode("utf-8")
            c.sendall(struct.pack("!I", len(bad_cat)) + bad_cat)
            with self.assertRaises(StagingEventTransportError) as cm_cat:
                chan.receive(timeout_seconds=1.0)
            self.assertIn("staging event category is invalid", str(cm_cat.exception))

            chan.close()
        finally:
            s.close()
            c.close()

        # Channel recovery over fresh connection
        s2, c2 = socket.socketpair()
        try:
            s_chan = StagingEventChannel(s2)
            c_chan = StagingEventChannel(c2)
            with BoundedTestPeer(s2) as sender_peer:
                sender_peer.start_worker(lambda: s_chan.send("phase", {"phase_code": "recovered"}))
                rec = c_chan.receive(timeout_seconds=1.0)
            self.assertEqual(rec.sequence, 1)
            self.assertEqual(rec.payload, {"phase_code": "recovered"})
            s_chan.close()
            c_chan.close()
        finally:
            s2.close()
            c2.close()

    def test_s8_a04_transport_ack_timeout_and_broken_sender_settlement(self) -> None:
        """ACK timeout raises builtin TimeoutError and breaks outgoing channel without thread leakage."""
        s, c = socket.socketpair()
        try:
            sender = StagingEventChannel(s, acknowledgement_timeout_seconds=0.05)
            with BoundedTestPeer(c) as peer:
                # Peer receives the frame but intentionally does not acknowledge
                def peer_no_ack() -> None:
                    _flen, _body = peer.recv_frame(timeout_seconds=1.0)

                peer.start_worker(peer_no_ack)
                with self.assertRaises(TimeoutError) as cm_timeout:
                    sender.send("authority", {"event_category": "bound"})
                self.assertIn("staging event acknowledgement timed out", str(cm_timeout.exception))

            # Outgoing channel state is now permanently broken
            with self.assertRaises(StagingEventTransportError) as cm_broken:
                sender.send("authority", {"event_category": "retry"})
            self.assertIn("outgoing channel is broken", str(cm_broken.exception))

            sender.close()
        finally:
            s.close()
            c.close()

    def test_s8_a05_transport_fragmented_valid_frame_assembly_and_acknowledgement(self) -> None:
        """Frame delivered in 1-byte slices is reassembled across recv calls with verified ACK."""
        s, c = socket.socketpair()
        try:
            chan = StagingEventChannel(s)
            body = json.dumps({
                "schema_version": 1,
                "frame_sequence": 1,
                "frame_category": "phase",
                "payload": {"status": "in_progress"},
            }).encode("utf-8")
            wire = struct.pack("!I", len(body)) + body

            # Deliver wire data in small 2-byte fragments
            def stream_fragments() -> None:
                for i in range(0, len(wire), 2):
                    c.sendall(wire[i:i + 2])

            with BoundedTestPeer(c) as peer:
                peer.start_worker(stream_fragments)
                received = chan.receive(timeout_seconds=1.0)
                peer.assert_ack_received(timeout_seconds=1.0)

            self.assertEqual(received.sequence, 1)
            self.assertEqual(received.category, "phase")
            self.assertEqual(received.payload, {"status": "in_progress"})
            chan.close()
        finally:
            s.close()
            c.close()

    def test_s8_a06_protocol_session_capability_and_snapshot_extension_validation(self) -> None:
        """ProtocolSession enforces identity, capabilities, ordering transitions, and fresh session recovery."""
        identity = {"job_id": "job-slice8-01", "attempt": 1}
        session = ProtocolSession(identity)
        self.assertEqual(session.state, "awaiting_hello")

        # 1. Capability mismatch in worker_hello
        unsupported_hello = {
            "schema_version": PROTOCOL_VERSION,
            "message_type": "worker_hello",
            "protocol_versions": [PROTOCOL_VERSION],
            "worker_generation": "wg-01",
            "process_nonce": "nonce-01",
            "capabilities": ["unsupported_capability"],
        }
        with self.assertRaises(ProtocolError) as cm_cap:
            session.accept_worker(unsupported_hello)
        self.assertEqual(cm_cap.exception.code, "negotiation_failed")

        # Valid worker_hello advances state to awaiting_start
        valid_hello = {
            "schema_version": PROTOCOL_VERSION,
            "message_type": "worker_hello",
            "protocol_versions": [PROTOCOL_VERSION],
            "worker_generation": "wg-01",
            "process_nonce": "nonce-01",
            "capabilities": ["refresh_graph"],
        }
        session.accept_worker(valid_hello)
        self.assertEqual(session.state, "awaiting_start")

        # 2. Identity mismatch in job_start
        mismatched_start = {
            "schema_version": PROTOCOL_VERSION,
            "message_type": "job_start",
            "job_id": "wrong-job-id",
            "attempt": 1,
            "job_kind": "refresh_graph",
            "graph_id": "default",
            "source_generation": "sg1:src",
            "config_generation": "cg1:cfg",
        }
        with self.assertRaises(ProtocolError) as cm_start_id:
            session.accept_coordinator(mismatched_start)
        self.assertEqual(cm_start_id.exception.code, "identity_mismatch")

        # Valid job_start advances to running
        valid_start = {
            "schema_version": PROTOCOL_VERSION,
            "message_type": "job_start",
            "job_id": "job-slice8-01",
            "attempt": 1,
            "job_kind": "refresh_graph",
            "graph_id": "default",
            "source_generation": "sg1:src",
            "config_generation": "cg1:cfg",
        }
        session.accept_coordinator(valid_start)
        self.assertEqual(session.state, "running")

        # 3. Cancel and cancel_ack transitions
        cancel_msg = {
            "schema_version": PROTOCOL_VERSION,
            "message_type": "cancel",
            "job_id": "job-slice8-01",
            "attempt": 1,
        }
        session.accept_coordinator(cancel_msg)
        self.assertEqual(session.state, "cancel_requested")

        cancel_ack_msg = {
            "schema_version": PROTOCOL_VERSION,
            "message_type": "cancel_ack",
            "job_id": "job-slice8-01",
            "attempt": 1,
            "status": "accepted",
        }
        session.accept_worker(cancel_ack_msg)
        self.assertEqual(session.state, "cancelling")

        # 4. Terminal identity mismatch
        mismatched_result = {
            "schema_version": PROTOCOL_VERSION,
            "message_type": "result",
            "job_id": "job-slice8-01",
            "attempt": 2,
            "job_kind": "refresh_graph",
            "graph_id": "default",
            "status": "cancelled",
            "started_at": "2026-09-21T00:00:00Z",
            "finished_at": "2026-09-21T00:01:00Z",
            "phase": "cleanup",
            "files": 0,
            "observations": 0,
            "canonical_nodes": 0,
            "canonical_edges": 0,
            "warnings": [],
            "diagnostics": [],
            "publication_state": "rolled_back",
            "latest_run_identity": None,
            "source_generation": "sg1:src",
            "config_generation": "cg1:cfg",
            "extractor_generation": "eg-01",
            "canonicalizer_generation": "cg-01",
            "retryable": False,
            "error_category": None,
        }
        with self.assertRaises(ProtocolError) as cm_term_id:
            session.accept_worker(mismatched_result)
        self.assertEqual(cm_term_id.exception.code, "identity_mismatch")

        # Valid cancelled terminal transitions state to terminal
        valid_cancelled_result = {
            "schema_version": PROTOCOL_VERSION,
            "message_type": "result",
            "job_id": "job-slice8-01",
            "attempt": 1,
            "job_kind": "refresh_graph",
            "graph_id": "default",
            "status": "cancelled",
            "started_at": "2026-09-21T00:00:00Z",
            "finished_at": "2026-09-21T00:01:00Z",
            "phase": "cleanup",
            "files": 0,
            "observations": 0,
            "canonical_nodes": 0,
            "canonical_edges": 0,
            "warnings": [],
            "diagnostics": [],
            "publication_state": "rolled_back",
            "latest_run_identity": None,
            "source_generation": "sg1:src",
            "config_generation": "cg1:cfg",
            "extractor_generation": "eg-01",
            "canonicalizer_generation": "cg-01",
            "retryable": False,
            "error_category": None,
        }
        session.accept_worker(valid_cancelled_result)
        self.assertEqual(session.state, "terminal")

        # 5. Duplicate terminal and message after terminal
        with self.assertRaises(ProtocolError) as cm_dup:
            session.accept_worker(valid_cancelled_result)
        self.assertEqual(cm_dup.exception.code, "duplicate_terminal")

        with self.assertRaises(ProtocolError) as cm_after:
            session.accept_coordinator(cancel_msg)
        self.assertEqual(cm_after.exception.code, "message_after_terminal")

        # 6. Fresh session executes clean session lifecycle
        session_fresh = ProtocolSession(identity)
        session_fresh.accept_worker(valid_hello)
        session_fresh.accept_coordinator(valid_start)
        self.assertEqual(session_fresh.state, "running")


if __name__ == "__main__":
    import sys
    sys.exit('Direct execution unsupported; use tools/run_tests.py for container sandbox admission.')
