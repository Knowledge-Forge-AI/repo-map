from unittest.mock import patch

from repomap_kg.storage import (
    CanonicalEdgeEvidenceRecord,
    CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    identity_metadata_hash,
)

from repomap_test_support.mcp_server import McpServerTestSupport



class McpServerStorageCanonicalToolUnitTests(McpServerTestSupport):
    def test_canonical_nodes_resolves_patchable_facade_dependencies(self):
        from repomap_kg.server.mcp import repomap_canonical_nodes

        records = (object(),)
        expected = [{"canonical_key": "patched"}]
        with (
            patch(
                "repomap_kg.server.mcp.query_canonical_node_records",
                return_value=records,
            ) as query,
            patch(
                "repomap_kg.server.mcp.canonical_node_records_to_jsonable",
                return_value=expected,
            ) as to_jsonable,
        ):
            payload = repomap_canonical_nodes(
                root_path="/tmp/fixture",
                pg_database="postgres",
                kind="python.module",
            )

        assert isinstance(payload, dict)
        self.assertEqual(payload["items"], expected)
        query.assert_called_once()
        to_jsonable.assert_called_once_with(records)

    def test_canonical_nodes_validates_args_and_calls_storage_helper(self):
        from repomap_kg.server.mcp import repomap_canonical_nodes

        record = CanonicalNodeRecord(
            canonical_key="python.module:repomap_kg.cli",
            graph_key_version=1,
            kind="python.module",
            display_name="repomap_kg.cli",
            confidence="extracted",
            conflict=False,
            metadata={"path": "src/main/python/repomap_kg/cli.py"},
            first_seen_run_id=1,
            last_seen_run_id=2,
        )
        with patch(
            "repomap_kg.server.mcp.query_canonical_node_records",
            return_value=(record,),
        ) as query:
            payload = repomap_canonical_nodes(
                root_path="/tmp/fixture",
                pg_database="postgres",
                kind="python.module",
                canonical_key="python.module:repomap_kg.cli",
            )

        assert isinstance(payload, dict)
        self.assertEqual(
            payload["items"][0]["canonical_key"],
            "python.module:repomap_kg.cli",
        )
        self.assertIn("metadata", payload["items"][0])
        self.assertEqual(query.call_args.kwargs["kind"], "python.module")
        self.assertEqual(
            query.call_args.kwargs["canonical_key"],
            "python.module:repomap_kg.cli",
        )
        self.assertEqual(query.call_args.kwargs["graph_key_version"], 1)

    def test_canonical_nodes_rejects_invalid_key_before_query(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_canonical_nodes

        with patch("repomap_kg.server.mcp.query_canonical_node_records") as query:
            with self.assertRaisesRegex(RepoMapMcpError, "invalid canonical key"):
                repomap_canonical_nodes(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    canonical_key="python.module:bad#line",
                )

        query.assert_not_called()

    def test_canonical_nodes_rejects_path_prefix_for_non_file_kind(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_canonical_nodes

        with patch("repomap_kg.server.mcp.query_canonical_node_records") as query:
            with self.assertRaisesRegex(
                RepoMapMcpError,
                "path-prefix only applies to file canonical nodes",
            ):
                repomap_canonical_nodes(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    kind="python.module",
                    path_prefix="src/main/python",
                )

        query.assert_not_called()

    def test_canonical_edges_rejects_unsupported_kind_before_query(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_canonical_edges

        with patch("repomap_kg.server.mcp.query_canonical_edge_records") as query:
            with self.assertRaisesRegex(
                RepoMapMcpError,
                "unsupported canonical edge kind",
            ):
                repomap_canonical_edges(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    kind="invokes",
                )

        query.assert_not_called()

    def test_canonical_edges_returns_existing_cli_json_shape(self):
        from repomap_kg.server.mcp import repomap_canonical_edges

        hash_text = identity_metadata_hash({})
        record = CanonicalEdgeRecord(
            source_key="python.module:repomap_kg.cli",
            edge_kind="imports",
            target_key="python.module:repomap_kg.storage",
            graph_key_version=1,
            identity_metadata={},
            identity_metadata_hash=hash_text,
            metadata={},
            confidence="extracted",
            conflict=False,
            first_seen_run_id=1,
            last_seen_run_id=2,
        )
        with patch(
            "repomap_kg.server.mcp.query_canonical_edge_records",
            return_value=(record,),
        ) as query:
            payload = repomap_canonical_edges(
                root_path="/tmp/fixture",
                pg_database="postgres",
                kind="imports",
                source_key="python.module:repomap_kg.cli",
                target_key="python.module:repomap_kg.storage",
            )

        assert isinstance(payload, dict)
        self.assertEqual(payload["items"][0]["edge_kind"], "imports")
        self.assertEqual(payload["items"][0]["identity_metadata_hash"], hash_text)
        self.assertEqual(query.call_args.kwargs["source_key"], "python.module:repomap_kg.cli")
        self.assertEqual(query.call_args.kwargs["target_key"], "python.module:repomap_kg.storage")

    def test_explain_canonical_edge_hashes_identity_metadata(self):
        from repomap_kg.server.mcp import repomap_explain_canonical_edge

        metadata = {"scope": "fixture", "order": [2, 1]}
        hash_text = identity_metadata_hash(metadata)
        record = CanonicalEdgeExplanationRecord(
            edge=CanonicalEdgeRecord(
                source_key="python.module:repomap_kg.cli",
                edge_kind="imports",
                target_key="python.module:repomap_kg.storage",
                graph_key_version=1,
                identity_metadata=metadata,
                identity_metadata_hash=hash_text,
                metadata={},
                confidence="extracted",
                conflict=False,
                first_seen_run_id=1,
                last_seen_run_id=2,
            ),
            evidence=(
                CanonicalEdgeEvidenceRecord(
                    evidence_key="evidence:1",
                    link_kind="supports",
                    raw_observation={
                        "run_id": 1,
                        "ordinal": 0,
                        "payload_hash": "0" * 64,
                        "kind": "python.import",
                        "source_id": "src/main/python/repomap_kg/cli.py#import:storage",
                    },
                    path="src/main/python/repomap_kg/cli.py",
                    start_line=20,
                    end_line=20,
                    extractor="repo-python-ast",
                    extractor_version="0.1.0",
                    confidence="extracted",
                    metadata={},
                ),
            ),
        )
        with patch(
            "repomap_kg.server.mcp.query_canonical_edge_explanation",
            return_value=record,
        ) as query:
            payload = repomap_explain_canonical_edge(
                root_path="/tmp/fixture",
                pg_database="postgres",
                source_key="python.module:repomap_kg.cli",
                kind="imports",
                target_key="python.module:repomap_kg.storage",
                identity_metadata=metadata,
            )

        self.assertEqual(
            payload["result"]["edge"]["identity_metadata_hash"],
            hash_text,
        )
        self.assertEqual(
            payload["result"]["evidence"][0]["path"],
            "src/main/python/repomap_kg/cli.py",
        )
        self.assertEqual(payload["collections"]["evidence"]["returned"], 1)
        self.assertEqual(query.call_args.kwargs["identity_metadata_hash"], hash_text)
        self.assertEqual(query.call_args.kwargs["evidence_limit"], 51)
        self.assertEqual(query.call_args.kwargs["evidence_offset"], 0)

    def test_explain_canonical_edge_rejects_non_object_identity_metadata(self):
        from repomap_kg.server.mcp import (
            RepoMapMcpError,
            repomap_explain_canonical_edge,
        )

        import json

        raw_metadata = json.loads("[]")
        with patch("repomap_kg.server.mcp.query_canonical_edge_explanation") as query:
            with self.assertRaisesRegex(
                RepoMapMcpError,
                "identity_metadata must be a JSON object",
            ):
                repomap_explain_canonical_edge(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    source_key="python.module:repomap_kg.cli",
                    kind="imports",
                    target_key="python.module:repomap_kg.storage",
                    identity_metadata=raw_metadata,
                )

        query.assert_not_called()

    def test_canonical_neighborhood_validates_args_and_returns_json_shape(self):
        from repomap_kg.server.mcp import repomap_canonical_neighborhood

        hash_text = identity_metadata_hash({})
        record = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
                canonical_key="python.module:repomap_kg.cli",
                graph_key_version=1,
                kind="python.module",
                display_name="repomap_kg.cli",
                confidence="extracted",
                conflict=False,
                metadata={},
                first_seen_run_id=1,
                last_seen_run_id=2,
            ),
            nodes=(
                CanonicalNodeRecord(
                    canonical_key="python.module:repomap_kg.storage",
                    graph_key_version=1,
                    kind="python.module",
                    display_name="repomap_kg.storage",
                    confidence="extracted",
                    conflict=False,
                    metadata={},
                    first_seen_run_id=1,
                    last_seen_run_id=2,
                ),
            ),
            edges=(
                CanonicalEdgeRecord(
                    source_key="python.module:repomap_kg.cli",
                    edge_kind="imports",
                    target_key="python.module:repomap_kg.storage",
                    graph_key_version=1,
                    identity_metadata={},
                    identity_metadata_hash=hash_text,
                    metadata={},
                    confidence="extracted",
                    conflict=False,
                    first_seen_run_id=1,
                    last_seen_run_id=2,
                ),
            ),
        )
        with patch(
            "repomap_kg.server.mcp.query_canonical_neighborhood",
            return_value=record,
        ) as query:
            payload = repomap_canonical_neighborhood(
                root_path="/tmp/fixture",
                pg_database="postgres",
                node="python.module:repomap_kg.cli",
                direction="out",
            )

        self.assertEqual(
            payload["result"]["center"]["canonical_key"],
            "python.module:repomap_kg.cli",
        )
        self.assertEqual(
            payload["result"]["nodes"][0]["canonical_key"],
            "python.module:repomap_kg.storage",
        )
        self.assertEqual(payload["result"]["edges"][0]["edge_kind"], "imports")
        self.assertEqual(payload["collections"]["nodes"]["returned"], 1)
        self.assertEqual(payload["collections"]["edges"]["returned"], 1)
        self.assertEqual(query.call_args.kwargs["direction"], "out")
        self.assertEqual(query.call_args.kwargs["depth"], 1)
        self.assertEqual(query.call_args.kwargs["node_limit"], 51)
        self.assertEqual(query.call_args.kwargs["edge_limit"], 51)

    def test_canonical_neighborhood_rejects_depth_and_direction_before_query(self):
        from repomap_kg.server.mcp import (
            RepoMapMcpError,
            repomap_canonical_neighborhood,
        )

        with patch("repomap_kg.server.mcp.query_canonical_neighborhood") as query:
            with self.assertRaisesRegex(
                RepoMapMcpError,
                "neighborhood only supports depth 1",
            ):
                repomap_canonical_neighborhood(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    node="python.module:repomap_kg.cli",
                    depth=2,
                )

            with self.assertRaisesRegex(
                RepoMapMcpError,
                "direction must be one of both, in, out",
            ):
                repomap_canonical_neighborhood(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                    node="python.module:repomap_kg.cli",
                    direction="sideways",
                )

        query.assert_not_called()
