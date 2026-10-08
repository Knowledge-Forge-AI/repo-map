"""Unit tests for BoundedTestPeer staging transport test harness."""

from __future__ import annotations

import socket
import struct
import unittest

from repomap_test_support.staging_transport_test_harness import (
    BoundedTestPeer,
    HarnessTruncatedFrameError,
)


class StagingTransportTestHarnessUnitTests(unittest.TestCase):
    """Verify harness mechanics: framing, error propagation, truncation, and teardown."""

    def test_harness_normal_frame_exchange_and_ack(self) -> None:
        left, right = socket.socketpair()
        with BoundedTestPeer(right) as peer:
            body = b'{"msg": "test_payload"}'
            left.sendall(struct.pack("!I", len(body)) + body)

            flen, rcvd = peer.recv_frame(timeout_seconds=1.0)
            self.assertEqual(flen, len(body))
            self.assertEqual(rcvd, body)

            peer.send_ack()
            left.settimeout(1.0)
            ack = left.recv(1)
            self.assertEqual(ack, b"\x06")

            peer.assert_no_ack_received(timeout_seconds=0.05)
        left.close()

    def test_harness_peer_exception_propagated_to_parent(self) -> None:
        left, right = socket.socketpair()

        def failing_worker() -> None:
            raise ValueError("simulated peer worker crash")

        with self.assertRaises(ValueError) as cm:
            with BoundedTestPeer(right) as peer:
                peer.start_worker(failing_worker)
        self.assertIn("simulated peer worker crash", str(cm.exception))
        left.close()

    def test_harness_truncated_stream_and_clean_eof_refusal(self) -> None:
        # Case 1: clean EOF at start
        left1, right1 = socket.socketpair()
        with BoundedTestPeer(right1) as peer1:
            left1.close()
            with self.assertRaises(EOFError):
                peer1.recv_frame(timeout_seconds=1.0)

        # Case 2: truncated header (< 4 bytes)
        left2, right2 = socket.socketpair()
        with BoundedTestPeer(right2) as peer2:
            left2.sendall(b"\x00\x00")
            left2.close()
            with self.assertRaises(HarnessTruncatedFrameError) as cm_hdr:
                peer2.recv_frame(timeout_seconds=1.0)
            self.assertIn("stream truncated", str(cm_hdr.exception))

        # Case 3: truncated body (< declared length)
        left3, right3 = socket.socketpair()
        with BoundedTestPeer(right3) as peer3:
            left3.sendall(struct.pack("!I", 10) + b"abc")
            left3.close()
            with self.assertRaises(HarnessTruncatedFrameError) as cm_body:
                peer3.recv_frame(timeout_seconds=1.0)
            self.assertIn("stream truncated", str(cm_body.exception))

    def test_harness_main_thread_assertion_failure_cleans_up_peer(self) -> None:
        left, right = socket.socketpair()
        peer_ref: list[BoundedTestPeer] = []

        def blocking_worker() -> None:
            peer_ref[0].recv_frame(timeout_seconds=5.0)

        with self.assertRaises(AssertionError) as cm:
            with BoundedTestPeer(right) as peer:
                peer_ref.append(peer)
                peer.start_worker(blocking_worker)
                raise AssertionError("primary main thread assertion failed")

        self.assertIn("primary main thread assertion failed", str(cm.exception))
        # Ensure worker thread settled cleanly without leaking
        thread = peer_ref[0].thread
        self.assertIsNotNone(thread)
        assert thread is not None
        self.assertFalse(thread.is_alive())
        left.close()

    def test_harness_expected_worker_error_suppressed(self) -> None:
        left, right = socket.socketpair()

        def intentional_failure() -> None:
            raise TimeoutError("worker timed out intentionally")

        with BoundedTestPeer(right) as peer:
            peer.start_worker(intentional_failure)
            peer.expect_worker_error()

        errors = peer.take_errors()
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], TimeoutError)
        left.close()


if __name__ == "__main__":
    unittest.main()
