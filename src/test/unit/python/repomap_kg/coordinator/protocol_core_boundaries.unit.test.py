"""Unit tests for coordinator protocol core boundaries, directions, and content policies."""

from __future__ import annotations

import unittest

from repomap_kg.coordinator import _protocol_core as pc


class ProtocolCoreBoundariesUnitTests(unittest.TestCase):
    def test_protocol_constants_and_direction_mapping(self):
        self.assertEqual(pc.PROTOCOL_VERSION, 1)
        self.assertEqual(pc._DIRECTIONS["worker_hello"], "worker")
        self.assertEqual(pc._DIRECTIONS["job_start"], "coordinator")
        self.assertEqual(pc._DIRECTIONS["progress"], "worker")
        self.assertEqual(pc._DIRECTIONS["heartbeat"], "worker")
        self.assertEqual(pc._DIRECTIONS["cancel"], "coordinator")
        self.assertEqual(pc._DIRECTIONS["cancel_ack"], "worker")
        self.assertEqual(pc._DIRECTIONS["result"], "worker")
        self.assertEqual(pc._DIRECTIONS["error"], "worker")

    def test_prohibited_protocol_content_regex_patterns(self):
        pat = pc._PROHIBITED_PROTOCOL_CONTENT
        # Prohibited credential patterns
        for bad in (
            "password: secret",
            "token=abcd1234efgh",
            "api_key: key999",
            "bearer: token123",
            "select col from table1",
            "drop table sensitive",
            "delete from records",
            "sh -c 'echo 1'",
            "bash -c 'whoami'",
            "/etc/shadow",
            "../parent_dir",
            "; rm -rf /",
            "| ls",
            "`whoami`",
            "$(cat secret)",
            "raw_payload: data",
            "raw_observation: item",
        ):
            with self.subTest(bad=bad):
                self.assertIsNotNone(pat.search(bad), f"Expected prohibited match for: {bad}")

        # Allowed safe content
        for safe in (
            "Normal status message",
            "Processed 42 files cleanly",
            "Discovery phase finished without errors",
            "Heartbeat tick 123",
        ):
            with self.subTest(safe=safe):
                self.assertIsNone(pat.search(safe), f"Safe text incorrectly flagged: {safe}")

    def test_portable_snapshot_result_fields_and_diagnostics(self):
        self.assertIn("receipt_status", pc._PORTABLE_SNAPSHOT_CURRENT_RESULT_FIELDS)
        self.assertIn("receipt_diagnostic", pc._PORTABLE_SNAPSHOT_CURRENT_RESULT_FIELDS)
        for diag in ("store_unavailable", "permission_denied", "receipt_bounds", "write_failed"):
            self.assertIn(diag, pc._RECEIPT_WRITE_DIAGNOSTICS)

        for phase in (
            "waiting", "starting", "preflight", "discovery", "extraction",
            "canonicalization", "storage_prepare", "storage_publish",
            "verification", "cleanup", "complete"
        ):
            self.assertIn(phase, pc._PROGRESS_PHASES)

    def test_graph_and_generation_identifier_patterns(self):
        graph_pat = pc._GRAPH_ID_PATTERN
        self.assertIsNotNone(graph_pat.fullmatch("valid-graph-1"))
        self.assertIsNotNone(graph_pat.fullmatch("a"))
        self.assertIsNone(graph_pat.fullmatch("Invalid_Graph"))
        self.assertIsNone(graph_pat.fullmatch("1startwithdigit"))
        self.assertIsNone(graph_pat.fullmatch("graph with space"))

        gen_pat = pc._GENERATION_PATTERN
        self.assertIsNotNone(gen_pat.fullmatch("gen.1_2-3"))
        self.assertIsNotNone(gen_pat.fullmatch("A123"))
        self.assertIsNone(gen_pat.fullmatch("-startwithdash"))
        self.assertIsNone(gen_pat.fullmatch(""))

        ts_pat = pc._UTC_TIMESTAMP_PATTERN
        self.assertIsNotNone(ts_pat.fullmatch("2026-09-06T12:00:00Z"))
        self.assertIsNotNone(ts_pat.fullmatch("2026-09-06T12:00:00.123456Z"))
        self.assertIsNone(ts_pat.fullmatch("2026-09-06 12:00:00"))
        self.assertIsNone(ts_pat.fullmatch("not-a-timestamp"))

    def test_encode_and_decode_jsonl_framing(self):
        msg = {"schema_version": 1, "message_type": "heartbeat"}
        encoded = pc.encode_jsonl(msg, max_line_bytes=1024)
        self.assertTrue(encoded.endswith(b"\n"))
        decoded = pc.decode_jsonl(encoded, max_line_bytes=1024)
        self.assertEqual(decoded["schema_version"], 1)

        # Line without newline or exceeding limit
        with self.assertRaises(pc.ProtocolError):
            pc.decode_jsonl(b'{"key":"val"}', max_line_bytes=1024)
        with self.assertRaises(pc.ProtocolError):
            pc.decode_jsonl(b'{"key":"val"}\n', max_line_bytes=5)

    def test_retain_stderr_bounded_and_truncated(self):
        chunks = [b"line1\n", b"line2\n", b"line3\n"]
        text, total, truncated = pc.retain_stderr(chunks, max_bytes=12)
        self.assertTrue(truncated)
        self.assertEqual(total, 18)
        self.assertLessEqual(len(text.encode("utf-8")), 12)

        # Non-truncated
        text2, count2, truncated2 = pc.retain_stderr([b"abc\n"], max_bytes=100)
        self.assertFalse(truncated2)
        self.assertEqual(text2, "abc\n")

    def test_unique_object_rejects_duplicate_keys(self):
        with self.assertRaises(ValueError):
            pc._unique_object([("key", 1), ("key", 2)])
        res = pc._unique_object([("a", 1), ("b", 2)])
        self.assertEqual(res, {"a": 1, "b": 2})

    def test_scalar_validation_helpers(self):
        self.assertTrue(pc._is_int(123))
        self.assertFalse(pc._is_int(True))
        self.assertFalse(pc._is_int("123"))

        self.assertTrue(pc._bounded_text("valid", 10))
        self.assertFalse(pc._bounded_text("too-long-text", 5))

        self.assertTrue(pc._valid_generation("gen1:abc", "gen1:"))
        self.assertFalse(pc._valid_generation("other:abc", "gen1:"))

        # limit / int_limit
        limits = {"heartbeat_seconds": 15.5, "max_files": 100}
        self.assertEqual(pc._limit(limits, "heartbeat_seconds", 5.0), 15.5)
        self.assertEqual(pc._limit(limits, "absent", 5.0), 5.0)
        self.assertEqual(pc._int_limit(limits, "max_files", 50), 100)
        self.assertEqual(pc._int_limit(limits, "absent", 50), 50)


if __name__ == "__main__":
    unittest.main()
