import json
from dataclasses import replace
from unittest.mock import patch

from repomap_kg.storage import CanonicalStorageSummaryRecord
from repomap_test_support.mcp_server import McpServerTestSupport


class McpServerMetadataRedactionUnitTests(McpServerTestSupport):
    def test_all_hidden_home_listing_omits_config_locations(self):
        from repomap_kg.server.mcp import repomap_list_graphs

        config_path = self.write_ops_config(
            self.visible_ops_config().replace(
                "mcp_visible = true",
                "mcp_visible = false",
            )
        )
        config_path = config_path.rename(config_path.with_name("local.rpl.toml"))

        with patch.dict(
            "os.environ",
            {"REPOMAP_OPS_CONFIG": str(config_path.parent)},
        ):
            payload = repomap_list_graphs()

        self.assertEqual(payload["graph_count"], 0)
        self.assertEqual(payload["hidden_graph_count"], 4)
        self.assertNotIn("config_path", payload)
        self.assertNotIn("config_home", payload)
        self.assertNotIn("config_files", payload)
        self.assertNotIn(str(config_path.parent), json.dumps(payload, sort_keys=True))

    def test_graph_metadata_uses_path_free_root_and_database_markers(self):
        from repomap_kg.server.mcp import repomap_list_graphs

        config_path = self.write_visible_ops_config()
        with self.patch_ops_config(config_path):
            payload = repomap_list_graphs()

        graphs = {graph["graph_id"]: graph for graph in payload["graphs"]}
        self.assertEqual(graphs["repo-map"]["root_path_display"], "[graph-root]")
        self.assertEqual(graphs["repo-map"]["root_path_expanded"], "[graph-root]")
        self.assertEqual(graphs["repo-map"]["database"], "[graph-database]")
        self.assertEqual(
            graphs["private-visible"]["root_path_display"],
            "[private-root]",
        )
        self.assertEqual(
            graphs["private-visible"]["database"],
            "[private-database]",
        )
        serialized = json.dumps(payload, sort_keys=True)
        for internal_value in (
            "/tmp/fixture",
            "repomap_repo_map",
            str(config_path),
        ):
            self.assertNotIn(internal_value, serialized)

    def test_legacy_projects_mask_connection_metadata(self):
        from repomap_kg.server.mcp import repomap_projects

        config_path = self.write_mcp_config(
            {
                "default_project": "repo-map",
                "projects": {
                    "repo-map": {
                        "root_path": "/synthetic/repo-map",
                        "pg_database": "internal_repo_map",
                        "pg_host": "/private/tmp/postgres.sock",
                        "pg_port": "55432",
                        "pg_user": "local-user",
                    }
                },
            }
        )

        with (
            patch.dict(
                "os.environ",
                {"REPOMAP_MCP_CONFIG": str(config_path)},
                clear=True,
            ),
            patch(
                "repomap_kg.server.mcp.load_mcp_ops_config",
                side_effect=OSError("no operations config"),
            ),
        ):
            payload = repomap_projects()

        project = payload["projects"][0]
        self.assertEqual(project["root_path"], "[project-root]")
        self.assertEqual(project["pg_database"], "[project-database]")
        self.assertNotIn("pg_host", project)
        self.assertNotIn("pg_port", project)
        self.assertNotIn("pg_user", project)
        serialized = json.dumps(payload, sort_keys=True)
        for internal_value in (
            "/synthetic/repo-map",
            "internal_repo_map",
            "/private/tmp/postgres.sock",
            "55432",
            "local-user",
        ):
            self.assertNotIn(internal_value, serialized)

    def test_legacy_status_masks_root_but_preserves_query_routing(self):
        from repomap_kg.server.mcp import repomap_status

        config_path = self.write_mcp_config(
            {
                "projects": {
                    "repo-map": {
                        "root_path": "/synthetic/repo-map",
                        "pg_database": "internal_repo_map",
                    }
                }
            }
        )
        summary = CanonicalStorageSummaryRecord(
            root_path="/synthetic/repo-map",
            repository_name="repo-map",
            latest_run_id=22,
            runs=2,
            files=3,
            raw_observations=13,
            canonical_nodes=5,
            canonical_edges=7,
            canonical_evidence=11,
        )

        with patch.dict(
            "os.environ",
            {"REPOMAP_MCP_CONFIG": str(config_path)},
            clear=True,
        ):
            with patch(
                "repomap_kg.server.mcp.query_canonical_storage_summary",
                return_value=summary,
            ) as query:
                payload = repomap_status(project="repo-map")

        self.assertEqual(payload["root_path"], "[project-root]")
        self.assertEqual(query.call_args.kwargs["root_path"], "/synthetic/repo-map")
        self.assertEqual(query.call_args.args[0], ["-d", "internal_repo_map"])

    def test_legacy_status_labels_legacy_storage_counts(self):
        from repomap_kg.server.mcp import repomap_status

        config_path = self.write_mcp_config(
            {
                "projects": {
                    "repo-map": {
                        "root_path": "/synthetic/repo-map",
                        "pg_database": "internal_repo_map",
                    }
                }
            }
        )
        summary = CanonicalStorageSummaryRecord(
            root_path="/synthetic/repo-map",
            repository_name="repo-map",
            latest_run_id=22,
            runs=2,
            files=3,
            raw_observations=13,
            canonical_nodes=5,
            canonical_edges=7,
            canonical_evidence=11,
        )

        with patch.dict(
            "os.environ",
            {"REPOMAP_MCP_CONFIG": str(config_path)},
            clear=True,
        ):
            with patch(
                "repomap_kg.server.mcp.query_canonical_storage_summary",
                return_value=summary,
            ):
                payload = repomap_status(project="repo-map")

        self.assertEqual(payload["storage_model"], "canonical")
        self.assertEqual(
            payload["counts"],
            {
                "runs": 2,
                "files": 3,
                "raw_observations": 13,
                "canonical_nodes": 5,
                "canonical_edges": 7,
                "canonical_evidence": 11,
            },
        )
        self.assertNotIn("nodes", payload["counts"])
        self.assertNotIn("edges", payload["counts"])
        self.assertNotIn("evidence", payload["counts"])

    def test_storage_errors_omit_operational_topology_from_mcp(self):
        from repomap_kg.server.mcp import (
            RepoMapMcpError,
            handle_jsonrpc_message,
            handle_tool_call,
            ops_payload,
        )
        from repomap_kg.storage import StorageSchemaError

        safe_reason = "unsupported storage readback driver; expected psql or psycopg"
        private_host = "internal-db-host"
        private_container = "generated-runtime-container"
        storage_error = StorageSchemaError(
            f"{safe_reason} Direct DB host-port exposure is disabled and "
            f"configured Postgres host {private_host!r} is container-internal; "
            "no running RepoMap-owned Postgres container "
            f"{private_container!r} was available."
        )

        with patch(
            "repomap_kg.server.mcp.repomap_status",
            side_effect=storage_error,
        ):
            with self.assertRaises(RepoMapMcpError) as raised:
                handle_tool_call("repomap_status", {"project": "fixture"})

        self.assertEqual(str(raised.exception), safe_reason)

        def raise_storage_error():
            raise storage_error

        with self.assertRaises(RepoMapMcpError) as ops_raised:
            ops_payload(raise_storage_error)
        self.assertEqual(str(ops_raised.exception), safe_reason)

        with patch(
            "repomap_kg.server.mcp.repomap_status",
            side_effect=storage_error,
        ):
            response = handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 24,
                    "method": "tools/call",
                    "params": {
                        "name": "repomap_status",
                        "arguments": {"project": "fixture"},
                    },
                }
            )

        assert isinstance(response, dict)
        result = response["result"]
        assert isinstance(result, dict)
        self.assertTrue(result["isError"])
        self.assertEqual(result["content"][0]["text"], safe_reason)
        self.assertEqual(result["structuredContent"]["error"], safe_reason)
        serialized = json.dumps(response, sort_keys=True)
        self.assertNotIn(private_host, serialized)
        self.assertNotIn(private_container, serialized)
        self.assertNotIn("Direct DB host-port exposure", serialized)
        self.assertNotIn("Traceback", serialized)

    def test_graph_status_and_summary_mask_output_but_preserve_query_routing(self):
        from repomap_kg.server.mcp import (
            repomap_project_summary,
            repomap_refresh_status,
            repomap_status,
        )

        mcp_config_path = self.write_empty_mcp_config()
        ops_config_path = self.write_visible_ops_config()
        summary = CanonicalStorageSummaryRecord(
            root_path="/tmp/fixture",
            repository_name="fixture",
            latest_run_id=22,
            runs=2,
            files=3,
            raw_observations=13,
            canonical_nodes=5,
            canonical_edges=7,
            canonical_evidence=11,
        )
        refresh_status = replace(
            self.synthetic_refresh_status(
                latest_run_status="complete",
                latest_run_finished_at="2026-07-01T00:01:00Z",
            ),
            database="repomap_repo_map",
        )

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            with (
                patch(
                    "repomap_kg.server.mcp.query_canonical_storage_summary",
                    return_value=summary,
                ) as legacy_query,
                patch(
                    "repomap_kg.server.ops.query_canonical_storage_summary",
                    return_value=summary,
                ) as summary_query,
                patch(
                    "repomap_kg.server.ops.query_refresh_status",
                    return_value={"repo-map": refresh_status},
                ),
            ):
                legacy = repomap_status(project="repo-map")
                project = repomap_project_summary(graph_id="repo-map")
                refresh = repomap_refresh_status("repo-map")

        self.assertEqual(legacy["root_path"], "[graph-root]")
        self.assertEqual(project["graph"]["root_path_display"], "[graph-root]")
        self.assertEqual(project["graph"]["database"], "[graph-database]")
        self.assertEqual(project["summary"]["root_path"], "[graph-root]")
        self.assertEqual(project["summary"]["storage_model"], "canonical")
        self.assertEqual(
            project["summary"]["counts"],
            {
                "runs": 2,
                "files": 3,
                "raw_observations": 13,
                "canonical_nodes": 5,
                "canonical_edges": 7,
                "canonical_evidence": 11,
            },
        )
        self.assertEqual(refresh["graphs"][0]["root_path_display"], "[graph-root]")
        self.assertEqual(refresh["graphs"][0]["root_path_expanded"], "[graph-root]")
        self.assertEqual(refresh["graphs"][0]["database"], "[graph-database]")
        self.assertEqual(legacy_query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(summary_query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_public_search_masks_configured_paths_but_preserves_query_routing(self):
        from repomap_kg.server.mcp import repomap_search_nodes

        config_path = self.write_visible_ops_config()
        result = {
            "results": [
                {
                    "canonical_key": "python.module:pkg.app",
                    "metadata": {
                        "source_root": "/tmp/fixture",
                        "config_path": str(config_path),
                    },
                }
            ],
            "total": 1,
        }

        with self.patch_ops_config(config_path):
            with patch(
                "repomap_kg.server.ops.query_mcp_search",
                return_value=result,
            ) as query:
                payload = repomap_search_nodes(graph_id="repo-map", query="pkg")

        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("/tmp/fixture", serialized)
        self.assertNotIn(str(config_path), serialized)
        self.assertEqual(
            payload["results"][0]["metadata"]["source_root"],
            "[private-path]",
        )
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
