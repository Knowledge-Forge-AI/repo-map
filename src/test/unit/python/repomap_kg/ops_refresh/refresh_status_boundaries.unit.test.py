import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.ops_refresh import (
    OpsRefreshUnitTestCase,
    VALID_REFRESH_CONFIG,
)

from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.refresh import (
    OpsRefreshGraphStatus,
    query_refresh_status,
)
from repomap_kg.storage import StorageSchemaError


class OpsRefreshStatusBoundariesUnitTests(OpsRefreshUnitTestCase):
    def test_query_refresh_status_redacts_private_root_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            private_root = Path(tmpdir) / "private"
            root.mkdir()
            private_root.mkdir()
            config = load_ops_config(
                self.write_config(
                    VALID_REFRESH_CONFIG.format(
                        repo_root=root,
                        private_root=private_root,
                    ).replace("enabled = false\nmcp_visible = false", "enabled = true\nmcp_visible = false")
                )
            )

            with (
                patch(
                    "repomap_kg.ops.refresh.execute_ops_json_readback"
                ) as execute_readback,
                patch("pathlib.Path.exists", side_effect=AssertionError("root read")),
            ):
                execute_readback.side_effect = [
                    {"connected": True, "schema_available": True},
                    {"graphs": [{"graph_id": "codex-vc", "repository_name": "codex-vc", "repository_exists": True, "latest_run_id": 12, "latest_run_status": "complete", "raw_observations": 5, "canonical_nodes": 4, "canonical_edges": 3}]},
                ]
                statuses = query_refresh_status(
                    config,
                    graph_ids=["codex-vc"],
                    psql_command="/bin/psql",
                )

        payload = json.dumps(statuses["codex-vc"].to_jsonable(), sort_keys=True)
        self.assertEqual(statuses["codex-vc"].root_path_display, "[private-root]")
        self.assertEqual(statuses["codex-vc"].root_path_expanded, "[private-root]")
        self.assertNotIn(str(private_root), payload)

    def test_query_refresh_status_filters_graph_before_read_only_sql(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with patch(
                "repomap_kg.ops.refresh.execute_ops_json_readback"
            ) as execute_readback:
                execute_readback.side_effect = [
                    {"connected": True, "schema_available": True},
                    {"graphs": [{"graph_id": "repo-map", "repository_name": "repo-map", "repository_exists": True, "latest_run_id": 11, "latest_run_status": "complete", "raw_observations": 3, "canonical_nodes": 2, "canonical_edges": 1}]},
                ]
                statuses = query_refresh_status(
                    config,
                    graph_ids=["repo-map"],
                    psql_command="/bin/psql",
                )

        self.assertEqual(tuple(statuses), ("repo-map",))
        self.assertEqual(execute_readback.call_count, 2)
        status_sql = execute_readback.call_args_list[1].kwargs["sql"]
        self.assertIn("'repo-map'", status_sql)
        self.assertNotIn("'codex-vc'", status_sql)

    def test_query_refresh_status_reports_schema_errors_without_root_reads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with (
                patch(
                    "repomap_kg.ops.refresh.execute_ops_json_readback",
                    side_effect=StorageSchemaError("password=fake-secret"),
                ),
                patch("pathlib.Path.exists", side_effect=AssertionError("root read")),
            ):
                statuses = query_refresh_status(config, psql_command="/bin/psql")

        payload = json.dumps(statuses["repo-map"].to_jsonable(), sort_keys=True)
        self.assertTrue(statuses["repo-map"].db_checked)
        self.assertIn("[REDACTED]", payload)
        self.assertNotIn("fake-secret", payload)

    def test_refresh_status_redacts_error_payloads(self):
        status = OpsRefreshGraphStatus(
            graph_id="repo-map",
            repository_name="repo-map",
            privacy="public-dev",
            enabled=True,
            mcp_visible=True,
            refresh_policy="manual",
            root_path_display="/repo",
            root_path_expanded="/repo",
            db_checked=True,
            error="password=mcp-ops3-fake-password",
        )

        payload = json.dumps(status.to_jsonable(), sort_keys=True)

        self.assertIn("[REDACTED]", payload)
        self.assertNotIn("mcp-ops3-fake-password", payload)
