"""Integration tests for Slice 12 graph readback composition and error boundaries (Group S12-C).

Covers:
- S12-C01: Edge-explanation transport shape failure
- S12-C02: Neighborhood transport shape failure
- S12-C03: Canonical evidence record shape failure
- S12-C04: Raw-observation evidence reference shape
- S12-C05: Ingested source record readback
- S12-C06: Source run readback alternate
- S12-C07: Public read-window boundary
- S12-C08: Combined edge-filter alternatives
- S12-C09: Multi-source binding caller boundary
- S12-C10: Source snapshot caller boundary
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import unittest

from repomap_kg.graph.multi_source_records import (
    GraphSourceBinding,
    MultiSourceIdentityError,
    SnapshotManifestEntry,
    SourceDefinition,
    SourceKind,
    SourceSnapshot,
)
from repomap_kg.storage.canonical import (
    query_canonical_edge_explanation,
    query_canonical_neighborhood,
)
from repomap_kg.storage.canonical_filters import canonical_edge_filters_from_args
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.read_pages import validate_public_read_window
from repomap_kg.storage.source_readback import (
    query_ingested_source_records,
    query_source_run_records,
)
from repomap_test_support.test_scratch import select_scratch_root


VALID_RAW_OBSERVATION = {
    "run_id": 1,
    "ordinal": 0,
    "payload_hash": "0" * 64,
    "kind": "ast_definition",
    "source_id": "src:1",
}

VALID_EVIDENCE_RECORD = {
    "evidence_key": "ev:1",
    "link_kind": "defines",
    "raw_observation": VALID_RAW_OBSERVATION,
    "path": "src/a.py",
    "start_line": 1,
    "end_line": 10,
    "extractor": "python_ast",
    "extractor_version": "1.0.0",
    "confidence": "extracted",
    "metadata": {},
}

VALID_EDGE_RECORD = {
    "source_key": "file:src/a.py",
    "edge_kind": "references",
    "target_key": "file:src/b.py",
    "graph_key_version": 1,
    "identity_metadata": {},
    "identity_metadata_hash": "0000000000000000000000000000000000000000000000000000000000000001",
    "metadata": {},
    "confidence": "extracted",
    "conflict": False,
    "first_seen_run_id": 1,
    "last_seen_run_id": 1,
}

VALID_NODE_RECORD = {
    "canonical_key": "file:src/a.py",
    "graph_key_version": 1,
    "kind": "file",
    "display_name": "src/a.py",
    "metadata": {"path": "src/a.py"},
    "confidence": "extracted",
    "conflict": False,
    "first_seen_run_id": 1,
    "last_seen_run_id": 1,
}

VALID_SOURCE_RECORD = {
    "source_id": "src1:test", "source_type": "folder", "display_name": "test source",
    "policy_status": "allowed", "latest_source_run_id": "run-01", "latest_artifact_id": None,
    "latest_artifact_path": None, "latest_acquired_at": "2026-09-12T12:00:00Z",
    "feed_observation_count": 0, "canonical_feed_item_count": 0,
}

VALID_RUN_RECORD = {
    "source_run_id": "run-01", "acquired_at": "2026-09-12T12:00:00Z", "artifact_id": None,
    "artifact_path": None, "artifact_byte_length": 100, "artifact_sha256": "0" * 64,
    "http_status": 200, "content_type": "application/json", "observation_count": 5,
    "status_summary": "completed",
}


class Slice12GraphReadbackCompositionIntegrationTests(unittest.TestCase):
    """Slice 12 Group S12-C integration tests for readback decoders, fault seams, and config."""

    def setUp(self) -> None:
        super().setUp()
        self._orig_pg_connector = os.environ.get("REPOMAP_STORAGE_PG_CONNECTOR")
        self._orig_readback_driver = os.environ.get("REPOMAP_STORAGE_READBACK_DRIVER")
        os.environ["REPOMAP_STORAGE_PG_CONNECTOR"] = "psql"
        os.environ["REPOMAP_STORAGE_READBACK_DRIVER"] = "psql"

    def tearDown(self) -> None:
        if self._orig_pg_connector is None:
            os.environ.pop("REPOMAP_STORAGE_PG_CONNECTOR", None)
        else:
            os.environ["REPOMAP_STORAGE_PG_CONNECTOR"] = self._orig_pg_connector
        if self._orig_readback_driver is None:
            os.environ.pop("REPOMAP_STORAGE_READBACK_DRIVER", None)
        else:
            os.environ["REPOMAP_STORAGE_READBACK_DRIVER"] = self._orig_readback_driver
        super().tearDown()

    def _write_fake_psql(self, directory: Path, payload_json: str) -> tuple[str, Path]:
        sql_log = directory / "invoked.sql"
        script = directory / f"fake_psql_{os.urandom(4).hex()}.sh"
        script.write_text(
            f"#!/bin/sh\ncat > {str(sql_log)!r}\ncat <<'EOF'\n{payload_json}\nEOF\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        return str(script), sql_log

    def _query_edge_exp(self, psql_cmd: str):
        return query_canonical_edge_explanation(
            [],
            root_path="/tmp/root",
            source_key="file:src/a.py",
            kind="references",
            target_key="file:src/b.py",
            identity_metadata_hash="0000000000000000000000000000000000000000000000000000000000000001",
            psql_command=psql_cmd,
        )

    def _query_nh(self, psql_cmd: str, node: str = "file:src/a.py"):
        return query_canonical_neighborhood(
            [],
            root_path="/tmp/root",
            node=node,
            psql_command=psql_cmd,
        )

    def test_s12_c01_edge_explanation_transport_shape_failure(self) -> None:
        """Transport returning malformed edge explanation payload raises discriminating StorageSchemaError and recovers."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            tmp_path = Path(tmp)
            psql_cmd, sql_log = self._write_fake_psql(tmp_path, '{"invalid": true}')
            with self.assertRaises(StorageSchemaError) as cm:
                self._query_edge_exp(psql_cmd)
            self.assertIn("canonical edge explanation: evidence", str(cm.exception))
            self.assertTrue(sql_log.exists())
            self.assertIn("SELECT", sql_log.read_text(encoding="utf-8"))

            valid_cmd, _ = self._write_fake_psql(tmp_path, json.dumps({
                "edge": VALID_EDGE_RECORD,
                "evidence": [VALID_EVIDENCE_RECORD],
            }))
            recovered = self._query_edge_exp(valid_cmd)
            self.assertIsNotNone(recovered.edge)
            self.assertEqual(len(recovered.evidence), 1)

    def test_s12_c02_neighborhood_transport_shape_failure(self) -> None:
        """Transport returning malformed neighborhood nodes payload raises discriminating StorageSchemaError and recovers."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            tmp_path = Path(tmp)
            psql_cmd, sql_log = self._write_fake_psql(tmp_path, '{"nodes": "not-a-list", "edges": []}')
            with self.assertRaises(StorageSchemaError) as cm:
                self._query_nh(psql_cmd)
            self.assertIn("canonical neighborhood: nodes", str(cm.exception))
            self.assertTrue(sql_log.exists())
            self.assertIn("SELECT", sql_log.read_text(encoding="utf-8"))

            valid_cmd, _ = self._write_fake_psql(tmp_path, json.dumps({
                "center": VALID_NODE_RECORD,
                "nodes": [VALID_NODE_RECORD],
                "edges": [VALID_EDGE_RECORD],
            }))
            recovered = self._query_nh(valid_cmd)
            self.assertIsNotNone(recovered.center)
            self.assertEqual(len(recovered.nodes), 1)

    def test_s12_c03_canonical_evidence_record_shape_failure(self) -> None:
        """Malformed evidence items in edge explanation payload raise discriminating evidence StorageSchemaError and recovers."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            tmp_path = Path(tmp)
            edge_json = json.dumps({"edge": VALID_EDGE_RECORD, "evidence": ["not-a-dict"]})
            psql_cmd, sql_log = self._write_fake_psql(tmp_path, edge_json)
            with self.assertRaises(StorageSchemaError) as cm:
                self._query_edge_exp(psql_cmd)
            self.assertIn("malformed canonical edge evidence record", str(cm.exception))
            self.assertNotIn("explanation: edge", str(cm.exception))
            self.assertTrue(sql_log.exists())
            self.assertIn("SELECT", sql_log.read_text(encoding="utf-8"))

            valid_cmd, _ = self._write_fake_psql(tmp_path, json.dumps({
                "edge": VALID_EDGE_RECORD,
                "evidence": [VALID_EVIDENCE_RECORD],
            }))
            recovered = self._query_edge_exp(valid_cmd)
            self.assertEqual(len(recovered.evidence), 1)

    def test_s12_c04_raw_observation_evidence_reference_shape(self) -> None:
        """Evidence item with malformed raw observation raises discriminating raw_observation StorageSchemaError and recovers."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            tmp_path = Path(tmp)
            bad_evidence = dict(VALID_EVIDENCE_RECORD)
            bad_evidence["raw_observation"] = "not-a-dict"
            payload_json = json.dumps({"edge": VALID_EDGE_RECORD, "evidence": [bad_evidence]})
            psql_cmd, sql_log = self._write_fake_psql(tmp_path, payload_json)
            with self.assertRaises(StorageSchemaError) as cm:
                self._query_edge_exp(psql_cmd)
            self.assertIn("malformed canonical edge evidence record: raw_observation", str(cm.exception))
            self.assertTrue(sql_log.exists())
            self.assertIn("SELECT", sql_log.read_text(encoding="utf-8"))

            valid_cmd, _ = self._write_fake_psql(tmp_path, json.dumps({
                "edge": VALID_EDGE_RECORD,
                "evidence": [VALID_EVIDENCE_RECORD],
            }))
            recovered = self._query_edge_exp(valid_cmd)
            self.assertEqual(len(recovered.evidence), 1)

    def test_s12_c05_ingested_source_record_readback(self) -> None:
        """Transport returning non-record object in ingested sources raises discriminating StorageSchemaError and recovers."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            tmp_path = Path(tmp)
            psql_cmd, sql_log = self._write_fake_psql(tmp_path, '["not-a-record"]')
            with self.assertRaises(StorageSchemaError) as cm:
                query_ingested_source_records(
                    [],
                    root_path="/tmp/root",
                    psql_command=psql_cmd,
                )
            self.assertIn("malformed ingested source record", str(cm.exception))
            self.assertTrue(sql_log.exists())
            self.assertIn("SELECT", sql_log.read_text(encoding="utf-8"))

            valid_cmd, _ = self._write_fake_psql(tmp_path, json.dumps([VALID_SOURCE_RECORD]))
            recovered = query_ingested_source_records(
                [],
                root_path="/tmp/root",
                psql_command=valid_cmd,
            )
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0].source_id, "src1:test")

    def test_s12_c06_source_run_record_readback_alternate(self) -> None:
        """Transport returning malformed run item in source runs raises discriminating StorageSchemaError and recovers."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            tmp_path = Path(tmp)
            psql_cmd, sql_log = self._write_fake_psql(tmp_path, '["not-a-run-dict"]')
            with self.assertRaises(StorageSchemaError) as cm:
                query_source_run_records(
                    [],
                    root_path="/tmp/root",
                    source_id="src1:test",
                    psql_command=psql_cmd,
                )
            self.assertIn("malformed source run record", str(cm.exception))
            self.assertTrue(sql_log.exists())
            self.assertIn("SELECT", sql_log.read_text(encoding="utf-8"))

            valid_cmd, _ = self._write_fake_psql(tmp_path, json.dumps([VALID_RUN_RECORD]))
            recovered = query_source_run_records(
                [],
                root_path="/tmp/root",
                source_id="src1:test",
                psql_command=valid_cmd,
            )
            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0].source_run_id, "run-01")

    def test_s12_c07_public_read_window_boundary(self) -> None:
        """Negative offset or limit exceeding maximum raises StorageSchemaError."""
        with self.assertRaises(StorageSchemaError):
            validate_public_read_window(limit=50, offset=-5)
        with self.assertRaises(StorageSchemaError):
            validate_public_read_window(limit=2000, offset=0)
        limit, offset = validate_public_read_window(limit=10, offset=20)
        self.assertEqual(limit, 10)
        self.assertEqual(offset, 20)

    def test_s12_c08_combined_edge_filter_alternatives(self) -> None:
        """Validates canonical edge filter arguments across version, kind, and key validation."""
        args_bad_ver = argparse.Namespace(
            graph_key_version=99,
            kind="references",
            source_key=None,
            target_key=None,
        )
        with self.assertRaises(StorageSchemaError):
            canonical_edge_filters_from_args(args_bad_ver)

        args_bad_kind = argparse.Namespace(
            graph_key_version=1,
            kind="unsupported_edge_kind",
            source_key=None,
            target_key=None,
        )
        with self.assertRaises(StorageSchemaError):
            canonical_edge_filters_from_args(args_bad_kind)

        args_valid = argparse.Namespace(
            graph_key_version=1,
            kind="references",
            source_key="file:src/main.py",
            target_key="file:src/util.py",
        )
        canonical_edge_filters_from_args(args_valid)

    def test_s12_c09_multi_source_binding_caller_boundary(self) -> None:
        """Enforces validation on alias whitespace and invalid privacy policies."""
        definition = SourceDefinition.create("src1", SourceKind.FOLDER)
        with self.assertRaises(MultiSourceIdentityError):
            GraphSourceBinding.create(
                graph_id="g1",
                alias="invalid alias with spaces",
                source_definition=definition,
                revision=1,
                logical_root=".",
                privacy_policy="public-dev",
                evidence_retention_policy="inherit",
                extractor_profile="default",
                selection_policy_id="select1:0000000000000000000000000000000000000000000000000000000000000001",
                resolution_policy="isolated",
            )
        with self.assertRaises(MultiSourceIdentityError):
            GraphSourceBinding.create(
                graph_id="g1",
                alias="valid-alias",
                source_definition=definition,
                revision=1,
                logical_root=".",
                privacy_policy="unsupported-privacy",
                evidence_retention_policy="inherit",
                extractor_profile="default",
                selection_policy_id="select1:0000000000000000000000000000000000000000000000000000000000000001",
                resolution_policy="isolated",
            )

    def test_s12_c10_source_snapshot_caller_boundary(self) -> None:
        """Enforces manifest ordering and git commit hash format on snapshot creation."""
        definition = SourceDefinition.create("src1", SourceKind.FOLDER)
        binding = GraphSourceBinding.create(
            graph_id="g1",
            alias="alias1",
            source_definition=definition,
            revision=1,
            logical_root=".",
            privacy_policy="public-dev",
            evidence_retention_policy="inherit",
            extractor_profile="default",
            selection_policy_id="select1:0000000000000000000000000000000000000000000000000000000000000001",
            resolution_policy="isolated",
        )
        with self.assertRaises(MultiSourceIdentityError):
            SourceSnapshot.create(
                binding,
                manifest_entries=(
                    SnapshotManifestEntry("b.py", "digest1", 10, False),
                    SnapshotManifestEntry("a.py", "digest2", 10, False),
                ),
                git_commit="not-a-valid-git-commit-hash",
                git_tree=None,
                ignore_policy_id="ignore1:declared",
                metadata_identity="meta1:fixture",
            )


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
