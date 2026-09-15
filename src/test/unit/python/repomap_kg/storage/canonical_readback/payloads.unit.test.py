import unittest

from repomap_kg.storage import (
    CanonicalEdgeRecord,
    CanonicalEdgeEvidenceRecord,
    CanonicalEdgeExplanationRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    StorageSchemaError,
    canonical_edge_explanation_to_jsonable,
    canonical_edge_explanation_from_storage_payload,
    canonical_neighborhood_from_storage_payload,
    canonical_neighborhood_to_jsonable,
    canonical_edge_record_from_storage_payload,
    canonical_node_record_from_storage_payload,
)

class StorageCanonicalPayloadUnitTests(unittest.TestCase):
    def test_canonical_node_record_from_storage_payload_preserves_public_fields(self):
        record = canonical_node_record_from_storage_payload(
            {
                "canonical_key": "file:bin/tool",
                "graph_key_version": 1,
                "kind": "file",
                "display_name": "bin/tool",
                "confidence": "extracted",
                "conflict": False,
                "metadata": {"role": "script"},
                "first_seen_run_id": 10,
                "last_seen_run_id": 12,
            }
        )

        self.assertEqual(
            record,
            CanonicalNodeRecord(
                canonical_key="file:bin/tool",
                graph_key_version=1,
                kind="file",
                display_name="bin/tool",
                confidence="extracted",
                conflict=False,
                metadata={"role": "script"},
                first_seen_run_id=10,
                last_seen_run_id=12,
            ),
        )
        self.assertEqual(record.to_dict()["canonical_key"], "file:bin/tool")
    def test_canonical_edge_record_from_storage_payload_preserves_public_fields(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

        record = canonical_edge_record_from_storage_payload(
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
        )

        self.assertEqual(
            record,
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
        self.assertEqual(record.to_dict()["target_key"], "tool:nix")
    def test_canonical_edge_explanation_from_storage_payload_preserves_public_fields(
        self,
    ):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        payload_hash = (
            "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
        )

        record = canonical_edge_explanation_from_storage_payload(
            {
                "edge": {
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
                },
                "evidence": [
                    {
                        "evidence_key": "evidence:bin/tool:1-1:repo-shell:nix",
                        "link_kind": "supports",
                        "raw_observation": {
                            "run_id": 10,
                            "ordinal": 0,
                            "payload_hash": payload_hash,
                            "kind": "shell.command",
                            "source_id": "bin/tool#call:nix",
                        },
                        "path": "bin/tool",
                        "start_line": 1,
                        "end_line": 1,
                        "extractor": "repo-shell",
                        "extractor_version": "0.1.0",
                        "confidence": "extracted",
                        "metadata": {"argv": ["nix", "build"]},
                    }
                ],
            }
        )

        self.assertEqual(
            record,
            CanonicalEdgeExplanationRecord(
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
                            "payload_hash": payload_hash,
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
            ),
        )
        self.assertEqual(
            canonical_edge_explanation_to_jsonable(record)["edge"]["source_key"],
            "file:bin/tool",
        )
    def test_canonical_neighborhood_from_storage_payload_preserves_public_fields(
        self,
    ):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

        record = canonical_neighborhood_from_storage_payload(
            {
                "center": {
                    "canonical_key": "tool:nix",
                    "graph_key_version": 1,
                    "kind": "tool",
                    "display_name": "nix",
                    "confidence": "extracted",
                    "conflict": False,
                    "metadata": {},
                    "first_seen_run_id": 10,
                    "last_seen_run_id": 12,
                },
                "nodes": [
                    {
                        "canonical_key": "file:bin/tool",
                        "graph_key_version": 1,
                        "kind": "file",
                        "display_name": "bin/tool",
                        "confidence": "extracted",
                        "conflict": False,
                        "metadata": {"role": "entrypoint"},
                        "first_seen_run_id": 10,
                        "last_seen_run_id": 12,
                    }
                ],
                "edges": [
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
            }
        )

        self.assertEqual(
            record,
            CanonicalNeighborhoodRecord(
                center=CanonicalNodeRecord(
                    canonical_key="tool:nix",
                    graph_key_version=1,
                    kind="tool",
                    display_name="nix",
                    confidence="extracted",
                    conflict=False,
                    metadata={},
                    first_seen_run_id=10,
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
                        metadata={"role": "entrypoint"},
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
            ),
        )
        self.assertEqual(
            canonical_neighborhood_to_jsonable(record)["center"]["canonical_key"],
            "tool:nix",
        )
    def test_canonical_neighborhood_from_storage_payload_accepts_missing_center(
        self,
    ):
        record = canonical_neighborhood_from_storage_payload(
            {"center": None, "nodes": [], "edges": []}
        )

        self.assertEqual(
            record,
            CanonicalNeighborhoodRecord(center=None, nodes=(), edges=()),
        )
        self.assertEqual(
            canonical_neighborhood_to_jsonable(record),
            {"center": None, "nodes": [], "edges": []},
        )
    def test_canonical_edge_explanation_from_storage_payload_accepts_missing_edge(
        self,
    ):
        record = canonical_edge_explanation_from_storage_payload(
            {"edge": None, "evidence": []}
        )

        self.assertEqual(
            record,
            CanonicalEdgeExplanationRecord(edge=None, evidence=()),
        )
        self.assertEqual(
            canonical_edge_explanation_to_jsonable(record),
            {"edge": None, "evidence": []},
        )
    def test_canonical_node_record_from_storage_payload_accepts_null_run_ids(self):
        record = canonical_node_record_from_storage_payload(
            {
                "canonical_key": "tool:nix",
                "graph_key_version": 1,
                "kind": "tool",
                "display_name": "nix",
                "confidence": "extracted",
                "conflict": False,
                "metadata": {},
                "first_seen_run_id": None,
                "last_seen_run_id": None,
            }
        )

        self.assertEqual(
            record,
            CanonicalNodeRecord(
                canonical_key="tool:nix",
                graph_key_version=1,
                kind="tool",
                display_name="nix",
                confidence="extracted",
                conflict=False,
                metadata={},
                first_seen_run_id=None,
                last_seen_run_id=None,
            ),
        )
        self.assertIsNone(record.to_dict()["first_seen_run_id"])
        self.assertIsNone(record.to_dict()["last_seen_run_id"])
    def test_canonical_edge_record_from_storage_payload_accepts_null_run_ids(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

        record = canonical_edge_record_from_storage_payload(
            {
                "source_key": "file:bin/tool",
                "edge_kind": "executes",
                "target_key": "tool:nix",
                "graph_key_version": 1,
                "identity_metadata": {},
                "identity_metadata_hash": hash_text,
                "metadata": {},
                "confidence": "extracted",
                "conflict": False,
                "first_seen_run_id": None,
                "last_seen_run_id": None,
            }
        )

        self.assertEqual(
            record,
            CanonicalEdgeRecord(
                source_key="file:bin/tool",
                edge_kind="executes",
                target_key="tool:nix",
                graph_key_version=1,
                identity_metadata={},
                identity_metadata_hash=hash_text,
                metadata={},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=None,
                last_seen_run_id=None,
            ),
        )
        self.assertIsNone(record.to_dict()["first_seen_run_id"])
        self.assertIsNone(record.to_dict()["last_seen_run_id"])
    def test_canonical_record_payload_helpers_reject_malformed_payloads(self):
        with self.assertRaisesRegex(StorageSchemaError, "canonical node record"):
            canonical_node_record_from_storage_payload({"canonical_key": ""})
        with self.assertRaisesRegex(StorageSchemaError, "canonical edge record"):
            canonical_edge_record_from_storage_payload({"source_key": ""})
