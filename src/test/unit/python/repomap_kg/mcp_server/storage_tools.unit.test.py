from unittest.mock import patch

from repomap_kg.storage import CanonicalStorageSummaryRecord
from repomap_test_support.mcp_server import McpServerTestSupport


class McpServerStorageToolUnitTests(McpServerTestSupport):
    def test_missing_project_and_default_are_rejected_before_query(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_status

        config_path = self.write_mcp_config(
            {
                "projects": {
                    "repo-map": {
                        "root_path": "/workspace/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                },
            }
        )
        ops_config_path = self.write_visible_ops_config()

        with self.patch_mcp_and_ops_config(config_path, ops_config_path):
            with patch("repomap_kg.server.mcp.query_canonical_storage_summary") as query:
                with self.assertRaisesRegex(
                    RepoMapMcpError,
                    "unknown legacy MCP project or graph-registry graph_id",
                ):
                    repomap_status(project="missing")
                with self.assertRaisesRegex(RepoMapMcpError, "root_path is required"):
                    repomap_status()

        query.assert_not_called()

    def test_project_and_explicit_overrides_are_rejected_unless_allowed(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_status

        config_path = self.write_mcp_config(
            {
                "projects": {
                    "repo-map": {
                        "root_path": "/workspace/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                },
            }
        )

        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            with patch("repomap_kg.server.mcp.query_canonical_storage_summary") as query:
                with self.assertRaisesRegex(
                    RepoMapMcpError,
                    "project cannot be combined with explicit",
                ):
                    repomap_status(
                        project="repo-map",
                        root_path="/tmp/other",
                    )
                with self.assertRaisesRegex(
                    RepoMapMcpError,
                    "project cannot be combined with explicit",
                ):
                    repomap_status(
                        project="repo-map",
                        pg_database="other",
                    )

        query.assert_not_called()

        allowed_config_path = self.write_mcp_config(
            {
                "allow_project_overrides": True,
                "projects": {
                    "repo-map": {
                        "root_path": "/workspace/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                },
            }
        )
        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(allowed_config_path)}):
            with patch(
                "repomap_kg.server.mcp.query_canonical_storage_summary",
                return_value=CanonicalStorageSummaryRecord(
                    root_path="/tmp/other",
                    repository_name="other",
                    latest_run_id=22,
                    runs=2,
                    files=3,
                    raw_observations=13,
                    canonical_nodes=5,
                    canonical_edges=7,
                    canonical_evidence=11,
                ),
            ) as query:
                payload = repomap_status(
                    project="repo-map",
                    root_path="/tmp/other",
                    pg_database="other_db",
                )

        self.assertEqual(payload["root_path"], "[project-root]")
        self.assertEqual(query.call_args.args[0], ["-d", "other_db"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/other")

    def test_explicit_mode_wins_over_default_project_for_development(self):
        from repomap_kg.server.mcp import repomap_status

        config_path = self.write_mcp_config(
            {
                "default_project": "repo-map",
                "projects": {
                    "repo-map": {
                        "root_path": "/workspace/repo-map",
                        "pg_database": "repomap_repo_map",
                    },
                },
            }
        )

        with patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(config_path)}):
            with patch(
                "repomap_kg.server.mcp.query_canonical_storage_summary",
                return_value=CanonicalStorageSummaryRecord(
                    root_path="/tmp/fixture",
                    repository_name="fixture",
                    latest_run_id=22,
                    runs=2,
                    files=3,
                    raw_observations=13,
                    canonical_nodes=5,
                    canonical_edges=7,
                    canonical_evidence=11,
                ),
            ) as query:
                payload = repomap_status(
                    root_path="/tmp/fixture",
                    pg_database="postgres",
                )

        self.assertNotIn("project", payload)
        self.assertEqual(payload["root_path"], "[explicit-root]")
        self.assertEqual(query.call_args.args[0], ["-d", "postgres"])
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")

    def test_status_requires_explicit_root_path_and_database(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_status

        with self.assertRaisesRegex(RepoMapMcpError, "root_path is required"):
            repomap_status(root_path="", pg_database="postgres")

        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RepoMapMcpError, "pg_database is required"):
                repomap_status(root_path="/tmp/fixture")

    def test_status_rejects_non_psql_command_names(self):
        from repomap_kg.server.mcp import RepoMapMcpError, repomap_status

        with self.assertRaisesRegex(
            RepoMapMcpError,
            "psql_command must name a psql executable",
        ):
            repomap_status(
                root_path="/tmp/fixture",
                pg_database="postgres",
                psql_command="/usr/bin/not-psql",
            )

        with self.assertRaisesRegex(
            RepoMapMcpError,
            "psql_command must not contain whitespace",
        ):
            repomap_status(
                root_path="/tmp/fixture",
                pg_database="postgres",
                psql_command="psql --echo-all",
            )

    def test_status_reads_postgres_connection_defaults_from_environment(self):
        from repomap_kg.server.mcp import repomap_status

        with patch.dict(
            "os.environ",
            {
                "REPOMAP_PG_HOST": "/tmp/pg",
                "REPOMAP_PG_PORT": "5433",
                "REPOMAP_PG_USER": "slair",
                "REPOMAP_PG_DATABASE": "repomap",
                "REPOMAP_PSQL_COMMAND": "/opt/postgres/bin/psql",
            },
            clear=False,
        ):
            with patch(
                "repomap_kg.server.mcp.query_canonical_storage_summary",
                return_value=CanonicalStorageSummaryRecord(
                    root_path="/tmp/fixture",
                    repository_name="fixture",
                    latest_run_id=22,
                    runs=2,
                    files=3,
                    raw_observations=13,
                    canonical_nodes=5,
                    canonical_edges=7,
                    canonical_evidence=11,
                ),
            ) as query:
                payload = repomap_status(root_path="/tmp/fixture")

        self.assertEqual(payload["repository_name"], "fixture")
        self.assertEqual(
            query.call_args.args[0],
            ["-h", "/tmp/pg", "-p", "5433", "-U", "slair", "-d", "repomap"],
        )
        self.assertEqual(
            query.call_args.kwargs["psql_command"],
            "/opt/postgres/bin/psql",
        )

    def test_status_returns_read_only_summary_without_database_ids(self):
        from repomap_kg.server.mcp import repomap_status

        with patch(
            "repomap_kg.server.mcp.query_canonical_storage_summary",
            return_value=CanonicalStorageSummaryRecord(
                root_path="/tmp/fixture",
                repository_name="fixture",
                latest_run_id=22,
                runs=2,
                files=3,
                raw_observations=13,
                canonical_nodes=5,
                canonical_edges=7,
                canonical_evidence=11,
            ),
        ) as query:
            payload = repomap_status(
                root_path="/tmp/fixture",
                pg_host="/tmp/pg",
                pg_port="5432",
                pg_user="slair",
                pg_database="postgres",
                psql_command="/usr/bin/psql",
            )

        self.assertEqual(
            query.call_args.args[0],
            ["-h", "/tmp/pg", "-p", "5432", "-U", "slair", "-d", "postgres"],
        )
        self.assertEqual(query.call_args.kwargs["root_path"], "/tmp/fixture")
        self.assertEqual(query.call_args.kwargs["psql_command"], "/usr/bin/psql")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["graph_key_version"], 1)
        self.assertEqual(payload["repository_name"], "fixture")
        self.assertEqual(payload["storage_model"], "canonical")
        self.assertEqual(payload["counts"]["canonical_edges"], 7)
        self.assertNotIn("repository_id", payload)
        self.assertNotIn("latest_run_id", payload)
