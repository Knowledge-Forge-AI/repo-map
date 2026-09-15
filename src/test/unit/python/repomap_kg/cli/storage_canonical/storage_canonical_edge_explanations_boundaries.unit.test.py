import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.storage import StorageSchemaError


class CliStorageCanonicalEdgeExplanationBoundariesUnitTests(unittest.TestCase):
    def test_storage_explain_canonical_edge_validates_source_key(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_explanation") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "explain-canonical-edge",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool#line:12",
                        "--kind",
                        "executes",
                        "--target-key",
                        "tool:nix",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid source canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_explain_canonical_edge_validates_target_key(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_explanation") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "explain-canonical-edge",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool",
                        "--kind",
                        "executes",
                        "--target-key",
                        "tool:nix#line:12",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid target canonical key", stderr.getvalue())
        query.assert_not_called()

    def test_storage_explain_canonical_edge_rejects_unsupported_kind(self):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_explanation") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "explain-canonical-edge",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool",
                        "--kind",
                        "invokes",
                        "--target-key",
                        "tool:nix",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("unsupported canonical edge kind", stderr.getvalue())
        query.assert_not_called()

    def test_storage_explain_canonical_edge_rejects_identity_metadata_non_object(
        self,
    ):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_explanation") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "explain-canonical-edge",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool",
                        "--kind",
                        "executes",
                        "--target-key",
                        "tool:nix",
                        "--identity-metadata-json",
                        "[]",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("identity-metadata-json must be a JSON object", stderr.getvalue())
        query.assert_not_called()

    def test_storage_explain_canonical_edge_rejects_malformed_identity_metadata_json(
        self,
    ):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_explanation") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "explain-canonical-edge",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool",
                        "--kind",
                        "executes",
                        "--target-key",
                        "tool:nix",
                        "--identity-metadata-json",
                        "{",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("identity-metadata-json must be a JSON object", stderr.getvalue())
        query.assert_not_called()

    def test_storage_explain_canonical_edge_rejects_unsupported_graph_key_version(
        self,
    ):
        stderr = io.StringIO()

        with patch("repomap_kg.cli.query_canonical_edge_explanation") as query:
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "explain-canonical-edge",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool",
                        "--kind",
                        "executes",
                        "--target-key",
                        "tool:nix",
                        "--graph-key-version",
                        "2",
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("unsupported graph key version", stderr.getvalue())
        query.assert_not_called()

    def test_storage_explain_canonical_edge_reports_query_errors(self):
        stderr = io.StringIO()

        with patch(
            "repomap_kg.cli.query_canonical_edge_explanation",
            side_effect=StorageSchemaError(
                "psql did not return canonical edge explanation"
            ),
        ):
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "storage",
                        "explain-canonical-edge",
                        "--root-path",
                        "/tmp/fixture",
                        "--source-key",
                        "file:bin/tool",
                        "--kind",
                        "executes",
                        "--target-key",
                        "tool:nix",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "psql did not return canonical edge explanation",
            stderr.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
