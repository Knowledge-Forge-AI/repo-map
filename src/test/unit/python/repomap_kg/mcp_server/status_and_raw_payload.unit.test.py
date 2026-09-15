from pathlib import Path
import tempfile
from unittest.mock import patch

from repomap_kg.storage import StorageSchemaError

from repomap_test_support.mcp_server import McpServerTestSupport


class McpServerStatusAndRawPayloadUnitTests(McpServerTestSupport):
    def test_mcp_smoke3_refresh_status_flags_complete_without_finished_at(
        self,
    ):
        from repomap_kg.server.mcp import repomap_refresh_status

        config_path = self.write_visible_ops_config()
        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_refresh_status",
                return_value={
                    "repo-map": self.synthetic_refresh_status(
                        latest_run_status="complete",
                        latest_run_finished_at=None,
                        raw_observations=9,
                        canonical_nodes=8,
                        canonical_edges=7,
                    )
                },
            ):
                payload = repomap_refresh_status()

        self.assertEqual(payload["graphs"][0]["latest_run_status"], "complete")
        self.assertIsNone(payload["graphs"][0]["latest_run_finished_at"])
        self.assertEqual(
            payload["graphs"][0]["latest_run_consistency"],
            {
                "complete_without_finished_at": True,
                "diagnostic": "complete run has no finished timestamp in storage",
            },
        )
        self.assert_read_only_payload(payload)

    def test_mcp_smoke3_graph_status_flags_complete_without_finished_at(
        self,
    ):
        from repomap_kg.server.mcp import repomap_graph_status

        config_path = self.write_visible_ops_config()
        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_refresh_status",
                return_value={
                    "repo-map": self.synthetic_refresh_status(
                        latest_run_status="complete",
                        latest_run_finished_at=None,
                    )
                },
            ):
                payload = repomap_graph_status(graph_id="repo-map")

        self.assertEqual(payload["storage"]["latest_run_status"], "complete")
        self.assertIsNone(payload["storage"]["latest_run_finished_at"])
        self.assertEqual(
            payload["storage"]["latest_run_consistency"],
            {
                "complete_without_finished_at": True,
                "diagnostic": "complete run has no finished timestamp in storage",
            },
        )
        self.assert_read_only_payload(payload)

    def test_live_ops3_mcp_graph_status_missing_database_error_is_safe(self):
        from repomap_kg.server.mcp import repomap_graph_status

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            (home / "repomap.rpl.toml").write_text(
                self.visible_ops_config().replace(
                    'host = "127.0.0.1"',
                    'host = "postgres"',
                ),
                encoding="utf-8",
            )
            private_path = str(Path.home() / "private-live-ops3")

            class ContainerStatus:
                exists = True
                owned = True
                status = "running"
                diagnostic = None

            def fake_run_psql(command, **kwargs):
                if command[0] == "psql":
                    raise StorageSchemaError(
                        'could not translate host name "postgres" to address'
                    )
                raise StorageSchemaError(
                    "psql failed: FATAL: database "
                    '"repomap_live_ops3" does not exist '
                    f"while reading {private_path} via docker exec psql"
                )

            with (
                patch.dict(
                    "os.environ",
                    {"REPOMAP_OPS_CONFIG": str(home)},
                    clear=True,
                ),
                patch(
                    "repomap_kg.ops.refresh.run_psql",
                    side_effect=fake_run_psql,
                ),
                patch(
                    "repomap_kg.ops.readback.execute_json_readback_with_driver",
                    side_effect=lambda sql, **kwargs: (
                        fake_run_psql([kwargs["psql_command"]], input_text=sql)
                    ),
                ),
                patch(
                    "repomap_kg.ops.readback.selected_json_readback_driver",
                    return_value="psql",
                ),
                patch(
                    "repomap_kg.ops.readback.shutil.which",
                    return_value="/usr/bin/docker",
                    create=True,
                ),
                patch(
                    "repomap_kg.runtime.local.inspect_container",
                    return_value=ContainerStatus(),
                    create=True,
                ),
            ):
                payload = repomap_graph_status(graph_id="repo-map")

        message = payload["storage"]["error"]
        self.assertIn("graph database is missing or not initialized", message)
        self.assertNotIn("no running RepoMap-owned Postgres container", message)
        self.assertNotIn("Postgres container", message)
        self.assertNotIn(private_path, message)
        self.assertNotIn("docker exec", message)
        self.assert_read_only_payload(payload)

    def test_mcp_smoke3_complete_with_finished_at_has_no_timestamp_warning(self):
        from repomap_kg.server.mcp import repomap_refresh_status

        config_path = self.write_visible_ops_config()
        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_refresh_status",
                return_value={
                    "repo-map": self.synthetic_refresh_status(
                        latest_run_id=78,
                        latest_run_status="complete",
                        latest_run_finished_at="2026-07-01T00:01:00Z",
                    )
                },
            ):
                payload = repomap_refresh_status()

        self.assertEqual(
            payload["graphs"][0]["latest_run_consistency"],
            {"complete_without_finished_at": False},
        )

    def test_mcp_smoke3_non_complete_null_finished_at_has_no_complete_warning(self):
        from repomap_kg.server.mcp import repomap_refresh_status

        config_path = self.write_visible_ops_config()
        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_refresh_status",
                return_value={
                    "repo-map": self.synthetic_refresh_status(
                        latest_run_id=79,
                        latest_run_status="running",
                        latest_run_finished_at=None,
                    )
                },
            ):
                payload = repomap_refresh_status()

        self.assertEqual(
            payload["graphs"][0]["latest_run_consistency"],
            {"complete_without_finished_at": False},
        )

    def test_mcp_smoke4_include_raw_false_documents_metadata_semantics(self):
        from repomap_kg.server.mcp import repomap_search_observations

        config_path = self.write_visible_ops_config()
        observation_payload = {
            "results": [
                {
                    "ordinal": 1,
                    "kind": "command.reference",
                    "path": "synthetic/config.txt",
                    "source_id": "synthetic/config.txt#command:1",
                    "metadata": {"raw": "synthetic command text"},
                }
            ],
            "total": 1,
        }

        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_mcp_search",
                return_value=observation_payload,
            ) as query:
                payload = repomap_search_observations(
                    graph_id="repo-map",
                    query="command",
                    include_raw=False,
                )

        self.assertFalse(query.call_args.kwargs["include_raw"])
        self.assertNotIn("payload", payload["results"][0])
        self.assert_raw_payload_policy(payload, include_raw=False)
        self.assertEqual(
            payload["results"][0]["metadata"]["raw"],
            "synthetic command text",
        )
        self.assert_read_only_payload(payload)

    def test_mcp_smoke4_include_raw_true_reports_payload_included(self):
        from repomap_kg.server.mcp import repomap_search_observations

        config_path = self.write_visible_ops_config()
        observation_payload = {
            "results": [
                {
                    "ordinal": 1,
                    "kind": "command.reference",
                    "path": "synthetic/config.txt",
                    "source_id": "synthetic/config.txt#command:1",
                    "metadata": {"raw": "synthetic command text"},
                    "payload": {
                        "kind": "command.reference",
                        "metadata": {"raw": "synthetic command text"},
                    },
                }
            ],
            "total": 1,
        }

        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_mcp_search",
                return_value=observation_payload,
            ) as query:
                payload = repomap_search_observations(
                    graph_id="repo-map",
                    query="command",
                    include_raw=True,
                )

        self.assertTrue(query.call_args.kwargs["include_raw"])
        self.assertIn("payload", payload["results"][0])
        self.assert_raw_payload_policy(payload, include_raw=True)
        self.assert_read_only_payload(payload)
