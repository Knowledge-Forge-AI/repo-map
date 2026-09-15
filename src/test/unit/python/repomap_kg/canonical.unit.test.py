import json
import unittest

from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
    CanonicalizationResult,
    canonical_edge_key,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic


class CanonicalUnitTests(unittest.TestCase):
    def test_canonical_edge_key_is_stable_for_identity_metadata_order(self):
        first = canonical_edge_key(
            graph_key_version=1,
            source_key="file:bin/tool",
            kind="executes",
            target_key="tool:nix",
            identity_metadata={"b": 2, "a": 1},
        )
        second = canonical_edge_key(
            graph_key_version=1,
            source_key="file:bin/tool",
            kind="executes",
            target_key="tool:nix",
            identity_metadata={"a": 1, "b": 2},
        )

        self.assertEqual(first, second)
        self.assertRegex(first, r"^canonical-edge:[0-9a-f]{64}$")

    def test_result_serialization_sorts_records_and_counts_diagnostics(self):
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="file:bin/tool",
            kind="executes",
            target_key="tool:nix",
            identity_metadata={},
        )
        graph = CanonicalGraph(
            graph_key_version=1,
            nodes=(
                CanonicalNode(
                    canonical_key="tool:nix",
                    graph_key_version=1,
                    kind="tool",
                    display_name="nix",
                    metadata={},
                    confidence="heuristic",
                    conflict=False,
                ),
                CanonicalNode(
                    canonical_key="file:bin/tool",
                    graph_key_version=1,
                    kind="file",
                    display_name="bin/tool",
                    metadata={"role": "entrypoint"},
                    confidence="manual",
                    conflict=False,
                ),
            ),
            edges=(
                CanonicalEdge(
                    edge_key=edge_key,
                    graph_key_version=1,
                    source_key="file:bin/tool",
                    kind="executes",
                    target_key="tool:nix",
                    identity_metadata={},
                    metadata={"commands": ["nix"]},
                    confidence="heuristic",
                    conflict=False,
                ),
            ),
            evidence=(
                CanonicalEvidence(
                    evidence_key="evidence:1",
                    raw_observation_ordinal=1,
                    raw_schema_version=1,
                    raw_kind="shell.command",
                    raw_source_id="bin/tool#call:2:nix",
                    path="bin/tool",
                    start_line=2,
                    end_line=2,
                    extractor="repo-shell",
                    extractor_version="0.1.0",
                    confidence="manual",
                    metadata={"raw": "nix flake check"},
                ),
                CanonicalEvidence(
                    evidence_key="evidence:0",
                    raw_observation_ordinal=0,
                    raw_schema_version=1,
                    raw_kind="file",
                    raw_source_id="bin/tool",
                    path="bin/tool",
                    start_line=None,
                    end_line=None,
                    extractor="repo-discovery",
                    extractor_version="0.1.0",
                    confidence="manual",
                    metadata={},
                ),
            ),
            node_evidence_links=(
                CanonicalNodeEvidenceLink(
                    canonical_key="tool:nix",
                    evidence_key="evidence:1",
                    link_kind="inferred_from_edge",
                ),
                CanonicalNodeEvidenceLink(
                    canonical_key="file:bin/tool",
                    evidence_key="evidence:0",
                    link_kind="observed",
                ),
            ),
            edge_evidence_links=(
                CanonicalEdgeEvidenceLink(
                    edge_key=edge_key,
                    evidence_key="evidence:1",
                    link_kind="supports",
                ),
            ),
            raw_observation_count=2,
        )
        result = CanonicalizationResult(
            graph=graph,
            diagnostics=(
                CanonicalizationDiagnostic(
                    severity="warning",
                    category="dynamic_target",
                    message="dynamic target represented by placeholder",
                    raw_observation_ordinal=1,
                    raw_source_id="bin/tool#call:2:nix",
                    path="bin/tool",
                    field="target",
                    value="$RUNNER",
                    placeholder_key="dynamic:tool:shell-variable-command",
                ),
                CanonicalizationDiagnostic(
                    severity="error",
                    category="canonicalization_bug",
                    message="edge references missing node",
                ),
            ),
        )

        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["summary"]["raw_observations"], 2)
        self.assertEqual(payload["summary"]["nodes"], 2)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["summary"]["evidence"], 2)
        self.assertEqual(payload["summary"]["node_evidence_links"], 2)
        self.assertEqual(payload["summary"]["edge_evidence_links"], 1)
        self.assertEqual(payload["summary"]["diagnostics"], 2)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["summary"]["infos"], 0)
        self.assertEqual(payload["nodes"][0]["canonical_key"], "file:bin/tool")
        self.assertEqual(payload["nodes"][1]["canonical_key"], "tool:nix")
        self.assertEqual(payload["evidence"][0]["evidence_key"], "evidence:0")
        self.assertEqual(
            payload["node_evidence_links"][0]["canonical_key"],
            "file:bin/tool",
        )
        self.assertEqual(payload["diagnostics"][0]["severity"], "warning")
        self.assertEqual(payload["diagnostics"][1]["severity"], "error")

        serialized = result.to_json()
        self.assertEqual(serialized, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def test_warning_only_result_is_ok(self):
        result = CanonicalizationResult(
            graph=CanonicalGraph.empty(raw_observation_count=1),
            diagnostics=(
                CanonicalizationDiagnostic(
                    severity="warning",
                    category="unsupported_raw_observation_kind",
                    message="unsupported kind skipped",
                    raw_observation_ordinal=0,
                ),
            ),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.to_dict()["summary"]["warnings"], 1)


if __name__ == "__main__":
    unittest.main()
