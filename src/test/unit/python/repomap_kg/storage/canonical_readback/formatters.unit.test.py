import unittest

from repomap_kg.storage import (
    CanonicalEdgeRecord,
    CanonicalEdgeEvidenceRecord,
    CanonicalEdgeExplanationRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    canonical_edge_records_to_jsonable,
    canonical_node_records_to_jsonable,
    format_canonical_edge_table,
    format_canonical_edge_explanation_table,
    format_canonical_neighborhood_table,
    format_canonical_node_table,
)

class StorageCanonicalFormatterUnitTests(unittest.TestCase):
    def test_canonical_node_records_to_jsonable_preserves_public_fields(self):
        records = (
            CanonicalNodeRecord(
                canonical_key="file:bin/tool",
                graph_key_version=1,
                kind="file",
                display_name="bin/tool",
                confidence="extracted",
                conflict=False,
                metadata={"role": "entrypoint"},
                first_seen_run_id=10,
                last_seen_run_id=None,
            ),
        )

        self.assertEqual(
            canonical_node_records_to_jsonable(records),
            [
                {
                    "canonical_key": "file:bin/tool",
                    "graph_key_version": 1,
                    "kind": "file",
                    "display_name": "bin/tool",
                    "confidence": "extracted",
                    "conflict": False,
                    "metadata": {"role": "entrypoint"},
                    "first_seen_run_id": 10,
                    "last_seen_run_id": None,
                }
            ],
        )
    def test_canonical_edge_records_to_jsonable_preserves_public_fields(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        records = (
            CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash=hash_text,
                metadata={"commands": ["nix"]},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=10,
                last_seen_run_id=12,
            ),
        )

        self.assertEqual(
            canonical_edge_records_to_jsonable(records),
            [
                {
                    "source_key": "file:bin/tool",
                    "edge_kind": "executes",
                    "target_key": "tool:nix",
                    "graph_key_version": 1,
                    "identity_metadata": {},
                    "identity_metadata_hash": hash_text,
                    "metadata": {"commands": ["nix"]},
                    "confidence": "extracted",
                    "conflict": False,
                    "first_seen_run_id": 10,
                    "last_seen_run_id": 12,
                }
            ],
        )
    def test_format_canonical_node_table_uses_contract_columns(self):
        records = (
            CanonicalNodeRecord(
                canonical_key="tool:nix",
                graph_key_version=1,
                kind="tool",
                display_name="nix",
                confidence="manual",
                conflict=False,
                metadata={"omitted": True},
                first_seen_run_id=None,
                last_seen_run_id=12,
            ),
        )

        table = format_canonical_node_table(records)

        self.assertIn("canonical_key", table)
        self.assertIn("display_name", table)
        self.assertIn("first_seen_run_id", table)
        self.assertIn("tool:nix", table)
        self.assertIn("12", table)
        self.assertNotIn("metadata", table)
        self.assertNotIn("omitted", table)
    def test_format_canonical_edge_table_uses_contract_columns(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        records = (
            CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash=hash_text,
                metadata={"omitted": True},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=None,
                last_seen_run_id=12,
            ),
        )

        table = format_canonical_edge_table(records)

        self.assertIn("source_key", table)
        self.assertIn("edge_kind", table)
        self.assertIn("target_key", table)
        self.assertIn("identity_metadata_hash", table)
        self.assertIn("first_seen_run_id", table)
        self.assertIn("file:bin/tool", table)
        self.assertIn("tool:nix", table)
        self.assertIn(hash_text, table)
        self.assertIn("12", table)
        self.assertNotIn("omitted", table)
    def test_format_canonical_neighborhood_table_uses_contract_sections(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        record = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
                canonical_key="tool:nix",
                graph_key_version=1,
                kind="tool",
                display_name="nix",
                confidence="manual",
                conflict=False,
                metadata={"omitted": True},
                first_seen_run_id=None,
                last_seen_run_id=12,
            ),
            nodes=(
                CanonicalNodeRecord(
                    canonical_key="file:bin/tool",
                    graph_key_version=1,
                    kind="file",
                    display_name="bin/tool",
                    confidence="extracted",
                    conflict=False,
                    metadata={},
                    first_seen_run_id=10,
                    last_seen_run_id=12,
                ),
            ),
            edges=(
                CanonicalEdgeRecord(
                    source_key="file:bin/tool",
                    edge_kind="executes",
                    target_key="tool:nix",
                    graph_key_version=1,
                    identity_metadata={},
                    identity_metadata_hash=hash_text,
                    metadata={"commands": ["nix"]},
                    confidence="extracted",
                    conflict=False,
                    first_seen_run_id=10,
                    last_seen_run_id=12,
                ),
            ),
        )

        table = format_canonical_neighborhood_table(record)

        self.assertIn("center: tool:nix", table)
        self.assertIn("Nodes:", table)
        self.assertIn("canonical_key", table)
        self.assertIn("file:bin/tool", table)
        self.assertIn("Edges:", table)
        self.assertIn("identity_metadata_hash", table)
        self.assertIn(hash_text, table)
        self.assertNotIn("omitted", table)
        self.assertNotIn("commands", table)
    def test_format_canonical_neighborhood_table_reports_missing_center(self):
        table = format_canonical_neighborhood_table(
            CanonicalNeighborhoodRecord(center=None, nodes=(), edges=())
        )

        self.assertIn("center: <not found>", table)
        self.assertIn("Nodes:", table)
        self.assertIn("Edges:", table)
    def test_format_canonical_edge_explanation_table_uses_contract_sections(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        record = CanonicalEdgeExplanationRecord(
            edge=CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash=hash_text,
                metadata={"commands": ["nix"]},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=10,
                last_seen_run_id=12,
            ),
            evidence=(
                CanonicalEdgeEvidenceRecord(
                    evidence_key="evidence:bin/tool:1-1:repo-shell:nix",
                    link_kind="supports",
                    raw_observation={
                        "run_id": 10,
                        "ordinal": 0,
                        "payload_hash": (
                            "abcdef0123456789abcdef0123456789"
                            "abcdef0123456789abcdef0123456789"
                        ),
                        "kind": "shell.command",
                        "source_id": "bin/tool#call:nix",
                    },
                    path="bin/tool",
                    start_line=1,
                    end_line=1,
                    extractor="repo-shell",
                    extractor_version="0.1.0",
                    confidence="extracted",
                    metadata={"argv": ["nix", "build"]},
                ),
            ),
        )

        table = format_canonical_edge_explanation_table(record)

        self.assertIn("edge:", table)
        self.assertIn("evidence:", table)
        self.assertIn("source_key", table)
        self.assertIn("identity_metadata_hash", table)
        self.assertIn(hash_text, table)
        self.assertIn("raw_observation.run_id", table)
        self.assertIn("raw_observation.ordinal", table)
        self.assertIn("raw_observation.kind", table)
        self.assertIn("raw_observation.source_id", table)
        self.assertIn("bin/tool", table)
        self.assertIn("repo-shell", table)
        self.assertNotIn("commands", table)
        self.assertNotIn("argv", table)
    def test_format_canonical_edge_explanation_table_reports_missing_edge(self):
        table = format_canonical_edge_explanation_table(
            CanonicalEdgeExplanationRecord(edge=None, evidence=())
        )

        self.assertIn("edge: <not found>", table)
        self.assertIn("evidence:", table)
        self.assertIn("raw_observation.run_id", table)
