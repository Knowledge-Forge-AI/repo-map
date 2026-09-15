"""Negative, error, and fallback unit tests for decomposed coordinator modules."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import tempfile
from typing import cast
import unittest
from unittest.mock import MagicMock

from repomap_kg.coordinator._protocol_execution import _run_protocol_worker
from repomap_kg.coordinator._protocol_session import ProtocolSession
from repomap_kg.coordinator._protocol_validation import (
    MAX_JSONL_LINE_BYTES,
    MAX_RETAINED_DIAGNOSTIC_BYTES,
    ProtocolError,
    WorkerLaunchError,
    _validate_line_limit,
    decode_jsonl,
    encode_jsonl,
    retain_stderr,
)
from repomap_kg.coordinator._service_endpoints import (
    _endpoint_names,
    _remove_stale_endpoint,
    _validate_runtime_directory,
)


class DecompositionResilienceUnitTests(unittest.TestCase):
    def test_encode_jsonl_negative_and_boundary_cases(self) -> None:
        with self.assertRaises(ProtocolError) as cm:
            encode_jsonl(cast(Mapping[str, object], "not-a-mapping"))
        self.assertEqual(cm.exception.code, "invalid_message")

        with self.assertRaises(ProtocolError) as cm:
            encode_jsonl({"nan": float("nan")})
        self.assertEqual(cm.exception.code, "invalid_message")

        with self.assertRaises(ProtocolError) as cm:
            encode_jsonl({"inf": float("inf")})
        self.assertEqual(cm.exception.code, "invalid_message")

        with self.assertRaises(ProtocolError) as cm:
            encode_jsonl({"a": "x" * 200}, max_line_bytes=100)
        self.assertEqual(cm.exception.code, "frame_too_large")

    def test_decode_jsonl_negative_and_boundary_cases(self) -> None:
        with self.assertRaises(ProtocolError) as cm:
            decode_jsonl(cast(bytes, "not-bytes"))
        self.assertEqual(cm.exception.code, "invalid_frame")

        with self.assertRaises(ProtocolError) as cm:
            decode_jsonl(b"no-newline")
        self.assertEqual(cm.exception.code, "invalid_frame")

        with self.assertRaises(ProtocolError) as cm:
            decode_jsonl(b"two\nlines\n")
        self.assertEqual(cm.exception.code, "invalid_frame")

        with self.assertRaises(ProtocolError) as cm:
            decode_jsonl(b"{\"a\": 1}\n", max_line_bytes=5)
        self.assertEqual(cm.exception.code, "frame_too_large")

        with self.assertRaises(ProtocolError) as cm:
            decode_jsonl(b"{\"a\": 1, \"a\": 2}\n")
        self.assertEqual(cm.exception.code, "invalid_json")

        with self.assertRaises(ProtocolError) as cm:
            decode_jsonl(b"[1, 2, 3]\n")
        self.assertEqual(cm.exception.code, "invalid_message")

    def test_retain_stderr_and_sensitive_redaction(self) -> None:
        with self.assertRaises(ValueError):
            retain_stderr([], max_bytes=-1)

        with self.assertRaises(ValueError):
            retain_stderr([], max_bytes=MAX_RETAINED_DIAGNOSTIC_BYTES + 1)

        with self.assertRaises(TypeError):
            retain_stderr([cast(bytes, "not-bytes")], max_bytes=100)

        sensitive_chunks = [b"Error encountered: password = secret123\n"]
        retained, total, truncated = retain_stderr(sensitive_chunks, max_bytes=4096)
        self.assertEqual(retained, "worker diagnostic redacted\n")
        self.assertFalse(truncated)

        traceback_chunks = [b"Traceback (most recent call last):\n  File foo.py\n"]
        retained_tb, _, _ = retain_stderr(traceback_chunks, max_bytes=4096)
        self.assertEqual(retained_tb, "worker diagnostic redacted\n")

        safe_chunks = [b"chunk1 ", b"chunk2"]
        retained_safe, total_safe, trunc_safe = retain_stderr(safe_chunks, max_bytes=5)
        self.assertEqual(retained_safe, "chunk")
        self.assertEqual(total_safe, 13)
        self.assertTrue(trunc_safe)

    def test_validate_line_limit_boundaries(self) -> None:
        with self.assertRaises(ValueError):
            _validate_line_limit(0)
        with self.assertRaises(ValueError):
            _validate_line_limit(-10)
        with self.assertRaises(ValueError):
            _validate_line_limit(MAX_JSONL_LINE_BYTES + 1)
        _validate_line_limit(MAX_JSONL_LINE_BYTES)

    def test_protocol_session_identity_and_ordering_resilience(self) -> None:
        with self.assertRaises(ProtocolError) as cm:
            ProtocolSession({"job_id": "job1"})
        self.assertEqual(cm.exception.code, "invalid_identity")

        with self.assertRaises(ProtocolError) as cm:
            ProtocolSession({"job_id": "job1", "attempt": 0})
        self.assertEqual(cm.exception.code, "invalid_identity")

        with self.assertRaises(ProtocolError) as cm:
            ProtocolSession({"job_id": "/etc/shadow", "attempt": 1})
        self.assertEqual(cm.exception.code, "invalid_identity")

        session = ProtocolSession({"job_id": "job-1", "attempt": 1})

        # Wrong direction: coordinator sending worker_hello
        with self.assertRaises(ProtocolError) as cm:
            session.accept_coordinator({"schema_version": 1, "message_type": "worker_hello"})
        self.assertEqual(cm.exception.code, "wrong_direction")

        # Out of order: worker sending progress before worker_hello
        with self.assertRaises(ProtocolError) as cm:
            session.accept_worker({
                "schema_version": 1,
                "message_type": "progress",
                "job_id": "job-1",
                "attempt": 1,
                "completed": 0,
                "total": 10,
                "phase": "discovery",
                "unit": "files",
                "message_category": "files-discovered",
                "heartbeat_at": "2026-09-09T00:00:00Z",
            })
        self.assertEqual(cm.exception.code, "out_of_order")

        # Unsupported schema version
        with self.assertRaises(ProtocolError) as cm:
            session.accept_worker({
                "schema_version": 99,
                "message_type": "worker_hello",
                "protocol_versions": [1],
                "worker_generation": "wg1",
                "capabilities": ["refresh_graph"],
                "process_nonce": "nonce-1",
            })
        self.assertEqual(cm.exception.code, "unsupported_version")

    def test_protocol_execution_worker_launch_negative(self) -> None:
        failing_launcher = MagicMock(side_effect=OSError("Exec format error"))

        with self.assertRaises(WorkerLaunchError) as cm:
            _run_protocol_worker(
                argv=("nonexistent_cmd",),
                environment={},
                working_directory=Path(tempfile.gettempdir()),
                automatic_cancellation=False,
                identity={"job_id": "job-exec-fail", "attempt": 1},
                limits={
                    "process_deadline_seconds": 1.0,
                    "heartbeat_seconds": 0.5,
                },
                job_context=None,
                cancel_event=None,
                _launch_process=failing_launcher,
            )
        self.assertEqual(cm.exception.code, "worker_launch_failed")
        self.assertTrue(cm.exception.no_process_owned)

    def test_protocol_execution_invalid_time_and_diagnostic_limits(self) -> None:
        with self.assertRaises(ValueError) as cm:
            _run_protocol_worker(
                argv=("echo",),
                environment={},
                working_directory=Path(tempfile.gettempdir()),
                automatic_cancellation=False,
                identity={"job_id": "job-limits", "attempt": 1},
                limits={"process_deadline_seconds": -1.0},
                job_context=None,
                cancel_event=None,
            )
        self.assertIn("worker time limits must be positive", str(cm.exception))

        with self.assertRaises(ValueError) as cm:
            _run_protocol_worker(
                argv=("echo",),
                environment={},
                working_directory=Path(tempfile.gettempdir()),
                automatic_cancellation=False,
                identity={"job_id": "job-limits", "attempt": 1},
                limits={
                    "process_deadline_seconds": 1.0,
                    "max_diagnostic_bytes": MAX_RETAINED_DIAGNOSTIC_BYTES + 1,
                },
                job_context=None,
                cancel_event=None,
            )
        self.assertIn("diagnostic limit exceeds", str(cm.exception))

    def test_service_endpoints_resilience(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            file_path = temp_path / "not_a_dir.txt"
            file_path.write_text("hello", encoding="utf-8")

            with self.assertRaises(ValueError):
                _validate_runtime_directory(file_path)

            sock_name, token_name = _endpoint_names("posix")
            self.assertEqual(sock_name, "coordinator.sock")
            self.assertEqual(token_name, "coordinator.token")

            # Non-existent endpoint removal succeeds cleanly
            non_existent = temp_path / "stale_endpoint.sock"
            _remove_stale_endpoint(non_existent)
