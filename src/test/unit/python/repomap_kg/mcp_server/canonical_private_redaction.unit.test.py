import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from repomap_test_support.mcp_server import McpServerTestSupport
from repomap_kg.storage import (
    CanonicalEdgeExplanationRecord,
    CanonicalNeighborhoodRecord,
)


class McpServerCanonicalPrivateRedactionUnitTests(McpServerTestSupport):
    def test_private_canonical_payloads_redact_configured_path_markers(self):
        from repomap_kg.server.mcp import (
            repomap_canonical_edges,
            repomap_canonical_neighborhood,
            repomap_canonical_nodes,
            repomap_explain_canonical_edge,
        )

        config_path = self.write_visible_ops_config()
        private_root = str(Path.home() / "private-visible")
        private_value = f"{private_root}/bin/tool"
        node_key = "python.module:target"
        source_key = f"python.module:{Path.home().name}-source"
        edge_kind = "imports"
        edge = {
            "source_key": source_key,
            "edge_kind": edge_kind,
            "target_key": node_key,
            "graph_key_version": 1,
            "identity_metadata": {},
            "identity_metadata_hash": "0" * 64,
            "metadata": {"values": [private_value], "stable": "keep"},
            "confidence": "extracted",
            "conflict": False,
            "first_seen_run_id": 1,
            "last_seen_run_id": 1,
        }
        node = {
            "canonical_key": node_key,
            "graph_key_version": 1,
            "kind": "python.module",
            "display_name": "private-path",
            "confidence": "extracted",
            "conflict": False,
            "metadata": {"value": private_value, "stable": "keep"},
            "first_seen_run_id": 1,
            "last_seen_run_id": 1,
        }
        explanation = {
            "edge": edge,
            "evidence": [
                {
                    "evidence_key": "evidence:1",
                    "link_kind": "supports",
                    "metadata": {
                        "raw": private_value,
                        "value": private_value,
                        "stable": "keep",
                    },
                }
            ],
        }
        neighborhood = {
            "center": node,
            "nodes": [node],
            "edges": [edge],
        }
        cases = (
            (
                "nodes",
                "repomap_kg.server.mcp.query_canonical_node_records",
                "repomap_kg.server.mcp.canonical_node_records_to_jsonable",
                (object(),),
                [node],
                lambda: repomap_canonical_nodes(
                    project="private-visible",
                    kind="python.module",
                    canonical_key=node_key,
                ),
            ),
            (
                "edges",
                "repomap_kg.server.mcp.query_canonical_edge_records",
                "repomap_kg.server.mcp.canonical_edge_records_to_jsonable",
                (object(),),
                [edge],
                lambda: repomap_canonical_edges(
                    project="private-visible",
                    kind=edge_kind,
                    source_key=source_key,
                    target_key=node_key,
                ),
            ),
            (
                "explanation",
                "repomap_kg.server.mcp.query_canonical_edge_explanation",
                "repomap_kg.server.mcp.canonical_edge_explanation_to_jsonable",
                CanonicalEdgeExplanationRecord(edge=None, evidence=cast(Any, (object(),))),
                explanation,
                lambda: repomap_explain_canonical_edge(
                    project="private-visible",
                    source_key=source_key,
                    kind=edge_kind,
                    target_key=node_key,
                ),
            ),
            (
                "neighborhood",
                "repomap_kg.server.mcp.query_canonical_neighborhood",
                "repomap_kg.server.mcp.canonical_neighborhood_to_jsonable",
                CanonicalNeighborhoodRecord(
                    center=None,
                    nodes=cast(Any, (object(),)),
                    edges=cast(Any, (object(),)),
                ),
                neighborhood,
                lambda: repomap_canonical_neighborhood(
                    project="private-visible",
                    node=node_key,
                ),
            ),
        )

        with self.patch_ops_config(config_path):
            for (
                label,
                query_target,
                serializer_target,
                query_result,
                serialized,
                call,
            ) in cases:
                with self.subTest(tool=label):
                    with (
                        patch(query_target, return_value=query_result),
                        patch(serializer_target, return_value=serialized),
                    ):
                        payload = call()

                    rendered = json.dumps(payload, sort_keys=True)
                    self.assertNotIn(private_root, rendered)
                    self.assertNotIn(private_value, rendered)
                    self.assertIn("[private-path]", rendered)
                    self.assertIn("keep", rendered)

        self.assertEqual(node["canonical_key"], node_key)
        self.assertEqual(edge["source_key"], source_key)
        self.assertEqual(edge["target_key"], node_key)

    def test_public_graph_canonical_payload_preserves_non_sensitive_metadata(self):
        from repomap_kg.server.mcp import repomap_canonical_edges

        config_path = self.write_visible_ops_config()
        public_value = "/tmp/fixture/bin/tool"
        edge = {
            "source_key": "python.module:source",
            "edge_kind": "imports",
            "target_key": "python.module:target",
            "metadata": {"values": [public_value], "stable": "keep"},
        }
        with self.patch_ops_config(config_path):
            with (
                patch(
                    "repomap_kg.server.mcp.query_canonical_edge_records",
                    return_value=(object(),),
                ),
                patch(
                    "repomap_kg.server.mcp.canonical_edge_records_to_jsonable",
                    return_value=[edge],
                ),
            ):
                payload = repomap_canonical_edges(
                    project="repo-map",
                    kind="imports",
                    source_key="python.module:source",
                    target_key="python.module:target",
                )

        assert isinstance(payload, dict)
        self.assertEqual(payload["items"][0]["metadata"]["values"], [public_value])
