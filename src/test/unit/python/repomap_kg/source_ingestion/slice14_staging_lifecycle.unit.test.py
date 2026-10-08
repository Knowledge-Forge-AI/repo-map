"""Migrated Slice14 isolated controls; zero new integration credit."""

from __future__ import annotations
import io
import struct
import unittest
from repomap_kg.storage.backend_ownership import ConnectionRole
from repomap_kg.storage.backend_telemetry_contracts import (
    ConnectionTelemetryError,
    TelemetryEventKind,
    make_telemetry_event,
)
from repomap_kg.storage.backend_telemetry_events import (
    MAX_TELEMETRY_FRAME_BYTES,
    frame_telemetry_event,
    parse_telemetry_frame,
    read_telemetry_event,
)
from repomap_kg.storage.staging_family_catalog import family_privacy_classifications
from repomap_kg.storage.staging_family_contracts import STAGING_FAMILY_DESCRIPTORS


class Slice14StagingLifecycleUnitTests(unittest.TestCase):
    def test_s14_c04_staging_family_catalog_verification(self) -> None:
        """Staging family descriptors contain all required staging tables and privacy classifications."""
        required_families = {
            "files",
            "raw_observations",
            "canonical_nodes",
            "canonical_edges",
            "canonical_evidence",
            "canonical_node_evidence",
            "canonical_edge_evidence",
        }
        self.assertTrue(required_families.issubset(STAGING_FAMILY_DESCRIPTORS.keys()))

        classifications = family_privacy_classifications()
        for descriptor in STAGING_FAMILY_DESCRIPTORS.values():
            self.assertIsNotNone(descriptor.stage_table)
            self.assertIsNotNone(descriptor.duplicate_policy)
            self.assertIsNotNone(descriptor.proposal_policy)
            self.assertIsNotNone(descriptor.privacy_classification)
            self.assertIn(descriptor.family, classifications)


    def test_s14_c05_backend_telemetry_event_round_trip(self) -> None:
        """ConnectionTelemetryEvent serializes to wire frame and round-trips correctly."""
        event = make_telemetry_event(
            TelemetryEventKind.CONNECTION_READY,
            sequence=1,
            generation=1,
            role=ConnectionRole.DIRECT_STAGED_REFRESH,
            backend_pid=12345,
            monotonic_ns=1_000_000_000,
        )
        frame = frame_telemetry_event(event)
        self.assertIsInstance(frame, bytes)
        self.assertGreater(len(frame), 4)

        parsed = parse_telemetry_frame(frame)
        self.assertEqual(parsed, event)


    def test_s14_c06_backend_telemetry_undersized_frame_rejection(self) -> None:
        """Undersized telemetry frames or frame length mismatches raise ConnectionTelemetryError."""
        with self.assertRaises(ConnectionTelemetryError):
            parse_telemetry_frame(b"")

        with self.assertRaises(ConnectionTelemetryError):
            parse_telemetry_frame(b"abc")

        # Header says length is 10, but only 3 bytes of payload follow
        corrupt_frame = struct.pack("!I", 10) + b"abc"
        with self.assertRaises(ConnectionTelemetryError):
            parse_telemetry_frame(corrupt_frame)


    def test_s14_c07_backend_telemetry_oversized_payload_rejection(self) -> None:
        """Payload exceeding MAX_TELEMETRY_FRAME_BYTES is rejected upon parsing and reading."""
        oversized_len = MAX_TELEMETRY_FRAME_BYTES + 1
        header = struct.pack("!I", oversized_len)
        data = header + b"x" * oversized_len

        with self.assertRaises(ConnectionTelemetryError):
            parse_telemetry_frame(data)

        with self.assertRaises(ConnectionTelemetryError):
            read_telemetry_event(io.BytesIO(header + b"x" * 10))


    def test_s14_c08_backend_telemetry_read_event_eof(self) -> None:
        """read_telemetry_event returns None on EOF and executes readiness callback when supplied."""
        readiness_invoked = False

        def _mark_ready() -> None:
            nonlocal readiness_invoked
            readiness_invoked = True

        result = read_telemetry_event(io.BytesIO(b""), readiness=_mark_ready)
        self.assertIsNone(result)
        self.assertTrue(readiness_invoked)
