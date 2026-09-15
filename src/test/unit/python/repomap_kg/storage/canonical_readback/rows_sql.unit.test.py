import unittest
import hashlib
import json

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage import (
    StorageSchemaError,
    build_explain_canonical_edge_query_sql,
    build_canonical_edge_query_sql,
    build_canonical_node_query_sql,
    build_canonical_neighborhood_query_sql,
    file_rows_from_observations,
    build_canonical_ingest_sql,
    canonical_file_path_prefix,
    canonical_rows_from_result,
    identity_metadata_hash,
    raw_observation_payload_hash,
    raw_observation_rows_from_observations,
)

class StorageCanonicalRowsSqlUnitTests(unittest.TestCase):
    def test_file_rows_from_observations_preserves_file_metadata(self):
        observation = RawObservation(
            kind="file",
            source_id="src/app.py",
            path="src/app.py",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "python",
                "role": "source",
                "content_hash": "a" * 64,
                "generated": False,
                "executable": False,
            },
        )
        non_file = RawObservation(
            kind="shell.command",
            source_id="scripts/build.sh#call:echo",
            path="scripts/build.sh",
            confidence="heuristic",
            extractor="fixture-shell",
            extractor_version="0.1.0",
            target="tool:echo",
        )

        rows = file_rows_from_observations([non_file, observation])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].path, "src/app.py")
        self.assertEqual(rows[0].content_hash, "a" * 64)
        self.assertEqual(rows[0].metadata_json["confidence"], "manual")
        self.assertEqual(rows[0].metadata_json["raw_source_id"], "src/app.py")
    def test_raw_observation_payload_hash_uses_canonical_json(self):
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={"role": "documentation", "language": "markdown"},
        )

        digest = raw_observation_payload_hash(observation)

        expected = hashlib.sha256(
            json.dumps(
                observation.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(digest, expected)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
    def test_identity_metadata_hash_is_stable_for_key_order(self):
        left = {"b": ["two", "values"], "a": {"nested": True}}
        right = {"a": {"nested": True}, "b": ["two", "values"]}

        self.assertEqual(identity_metadata_hash(left), identity_metadata_hash(right))
        self.assertRegex(identity_metadata_hash(left), r"^[0-9a-f]{64}$")
    def test_canonical_rows_from_result_resolves_edge_links_by_identity(self):
        observations = [
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:nix-build",
                path="bin/tool",
                start_line=2,
                end_line=2,
                name="nix build",
                target="tool:nix",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={"command": "nix", "argv": ["nix", "build"]},
            )
        ]
        result = canonicalize_observations(observations)

        rows = canonical_rows_from_result(result)

        self.assertEqual(len(rows.nodes), 2)
        self.assertEqual(len(rows.edges), 1)
        self.assertEqual(rows.edges[0].source_key, "file:bin/tool")
        self.assertEqual(rows.edges[0].edge_kind, "executes")
        self.assertEqual(rows.edges[0].target_key, "tool:nix")
        self.assertEqual(rows.edge_evidence_links[0].source_key, "file:bin/tool")
        self.assertEqual(rows.edge_evidence_links[0].edge_kind, "executes")
        self.assertEqual(rows.edge_evidence_links[0].target_key, "tool:nix")
        self.assertEqual(
            rows.edge_evidence_links[0].identity_metadata_hash,
            rows.edges[0].identity_metadata_hash,
        )
    def test_build_canonical_ingest_sql_uses_raw_and_canonical_tables(self):
        observations = [
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:nix-build",
                path="bin/tool",
                start_line=2,
                end_line=2,
                name="nix build",
                target="tool:nix",
                confidence="heuristic",
                extractor="fixture-shell",
                extractor_version="0.1.0",
                metadata={"command": "nix", "argv": ["nix", "build"]},
            )
        ]
        raw_rows = raw_observation_rows_from_observations(observations)
        canonical_rows = canonical_rows_from_result(canonicalize_observations(observations))

        sql = build_canonical_ingest_sql(
            raw_rows,
            canonical_rows,
            repository_name="fixture",
            root_path="/tmp/fixture",
            git_commit="abc123",
        )

        self.assertIn("INSERT INTO raw_observations(", sql)
        self.assertIn("raw observation payload hash mismatch", sql)
        self.assertIn("INSERT INTO canonical_nodes(", sql)
        self.assertIn("INSERT INTO canonical_edges(", sql)
        self.assertIn("INSERT INTO canonical_evidence(", sql)
        self.assertIn("INSERT INTO canonical_edge_evidence(", sql)
        self.assertIn("source_canonical_key = 'file:bin/tool'", sql)
        self.assertNotIn("canonical_edge_id = 'canonical-edge:", sql)
        self.assertIn("SET finished_at = now()", sql)
        self.assertLess(sql.index("SET finished_at = now()"), sql.index("COMMIT;"))

        failed_sql = build_canonical_ingest_sql(
            raw_rows,
            canonical_rows,
            repository_name="fixture",
            root_path="/tmp/fixture",
            run_status="failed",
        )

        self.assertNotIn("SET finished_at = now()", failed_sql)
    def test_build_canonical_node_query_sql_filters_and_orders(self):
        sql = build_canonical_node_query_sql(
            "/tmp/fixture",
            kind="file",
            canonical_key="file:bin/tool",
            path_prefix="bin/",
            graph_key_version=1,
        )

        self.assertIn("FROM canonical_nodes", sql)
        self.assertIn("repositories.root_path = '/tmp/fixture'", sql)
        self.assertIn("canonical_nodes.graph_key_version = 1", sql)
        self.assertIn("canonical_nodes.kind = 'file'", sql)
        self.assertIn("canonical_nodes.canonical_key = 'file:bin/tool'", sql)
        self.assertIn("canonical_nodes.canonical_key LIKE 'file:bin/%'", sql)
        self.assertIn("ORDER BY canonical_nodes.canonical_key", sql)
        self.assertIn("'metadata', canonical_nodes.metadata_json", sql)
    def test_canonical_file_path_prefix_uses_subtree_semantics(self):
        self.assertEqual(
            canonical_file_path_prefix("bin"),
            canonical_file_path_prefix("bin/"),
        )
        self.assertEqual(canonical_file_path_prefix("bin"), "file:bin/")

        sql = build_canonical_node_query_sql(
            "/tmp/fixture",
            kind="file",
            path_prefix="bin",
        )

        self.assertIn("canonical_nodes.canonical_key LIKE 'file:bin/%'", sql)
    def test_canonical_file_path_prefix_does_not_match_sibling_file_prefixes(self):
        prefix = canonical_file_path_prefix("bin")

        self.assertTrue("file:bin/tool".startswith(prefix))
        self.assertFalse("file:binary".startswith(prefix))
    def test_canonical_file_path_prefix_rejects_repo_escaping_prefix(self):
        with self.assertRaisesRegex(
            StorageSchemaError,
            "invalid canonical file path prefix",
        ):
            canonical_file_path_prefix("../bin")
    def test_canonical_file_path_prefix_root_matches_all_file_nodes(self):
        self.assertEqual(canonical_file_path_prefix("."), "file:")
        self.assertEqual(canonical_file_path_prefix(""), "file:")

        sql = build_canonical_node_query_sql(
            "/tmp/fixture",
            kind="file",
            path_prefix=".",
        )

        self.assertIn("canonical_nodes.canonical_key LIKE 'file:%'", sql)
    def test_build_canonical_edge_query_sql_filters_and_orders(self):
        sql = build_canonical_edge_query_sql(
            "/tmp/fixture",
            kind="executes",
            source_key="file:bin/tool",
            target_key="tool:nix",
            graph_key_version=1,
        )

        self.assertIn("FROM canonical_edges", sql)
        self.assertIn("repositories.root_path = '/tmp/fixture'", sql)
        self.assertIn("canonical_edges.graph_key_version = 1", sql)
        self.assertIn("canonical_edges.edge_kind = 'executes'", sql)
        self.assertIn("canonical_edges.source_canonical_key = 'file:bin/tool'", sql)
        self.assertIn("canonical_edges.target_canonical_key = 'tool:nix'", sql)
        self.assertIn(
            "ORDER BY canonical_edges.source_canonical_key, "
            "canonical_edges.edge_kind, "
            "canonical_edges.target_canonical_key, "
            "canonical_edges.identity_metadata_hash",
            sql,
        )
        self.assertIn("'identity_metadata', canonical_edges.identity_metadata_json", sql)
    def test_build_explain_canonical_edge_query_sql_filters_by_identity(self):
        hash_text = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

        sql = build_explain_canonical_edge_query_sql(
            "/tmp/fixture",
            source_key="file:bin/tool",
            kind="executes",
            target_key="tool:nix",
            identity_metadata_hash=hash_text,
            graph_key_version=1,
        )

        self.assertIn("FROM canonical_edges", sql)
        self.assertIn("JOIN canonical_edge_evidence", sql)
        self.assertIn("JOIN canonical_evidence", sql)
        self.assertIn("LEFT JOIN raw_observations", sql)
        self.assertIn("repositories.root_path = '/tmp/fixture'", sql)
        self.assertIn("canonical_edges.graph_key_version = 1", sql)
        self.assertIn("canonical_edges.source_canonical_key = 'file:bin/tool'", sql)
        self.assertIn("canonical_edges.edge_kind = 'executes'", sql)
        self.assertIn("canonical_edges.target_canonical_key = 'tool:nix'", sql)
        self.assertIn(f"canonical_edges.identity_metadata_hash = '{hash_text}'", sql)
    def test_build_canonical_neighborhood_query_sql_filters_and_orders(self):
        sql = build_canonical_neighborhood_query_sql(
            "/tmp/fixture",
            node="tool:nix",
            direction="both",
            graph_key_version=1,
        )

        self.assertIn("FROM canonical_nodes", sql)
        self.assertIn("FROM canonical_edges", sql)
        self.assertIn("repositories.root_path = '/tmp/fixture'", sql)
        self.assertIn("canonical_nodes.graph_key_version = 1", sql)
        self.assertIn("canonical_nodes.canonical_key = 'tool:nix'", sql)
        self.assertIn("canonical_edges.source_canonical_key = 'tool:nix'", sql)
        self.assertIn("canonical_edges.target_canonical_key = 'tool:nix'", sql)
        self.assertIn("ORDER BY canonical_nodes.canonical_key", sql)
        self.assertIn(
            "ORDER BY canonical_edges.source_canonical_key, "
            "canonical_edges.edge_kind, "
            "canonical_edges.target_canonical_key, "
            "canonical_edges.identity_metadata_hash",
            sql,
        )
    def test_build_canonical_neighborhood_query_sql_honors_direction(self):
        in_sql = build_canonical_neighborhood_query_sql(
            "/tmp/fixture",
            node="tool:nix",
            direction="in",
        )
        out_sql = build_canonical_neighborhood_query_sql(
            "/tmp/fixture",
            node="tool:nix",
            direction="out",
        )

        self.assertIn("canonical_edges.target_canonical_key = 'tool:nix'", in_sql)
        self.assertNotIn("canonical_edges.source_canonical_key = 'tool:nix'", in_sql)
        self.assertIn("canonical_edges.source_canonical_key = 'tool:nix'", out_sql)
        self.assertNotIn("canonical_edges.target_canonical_key = 'tool:nix'", out_sql)
