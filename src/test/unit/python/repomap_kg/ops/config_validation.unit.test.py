import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.ops.config import (
    OpsConfigError,
    OpsGraphStorageStatus,
    build_graph_storage_status_sql,
    check_ops_graph_storage_status,
    check_ops_postgres_status,
    format_ops_graph_registry_table,
    format_ops_config_status_table,
    load_ops_config,
    ops_graph_registry_status_to_jsonable,
    ops_config_status_to_jsonable,
)


VALID_CONFIG = (
    "schema_version = 1\n\n"
    "[service]\nmode = \"local\"\nmcp_transport = \"stdio\"\nlog_level = \"info\"\n\n"
    "[postgres]\nhost = \"127.0.0.1\"\nport = 5432\ndatabase = \"repomap\"\nuser = \"admin\"\npassword_env = \"REPOMAP_PG_PASSWORD\"\n\n"
    "[[graphs]]\nid = \"repo-map\"\nname = \"RepoMap\"\nroot_path = \"/placeholder/repo-map\"\nrepository_name = \"repo-map\"\n"
    "privacy = \"public-dev\"\nenabled = true\nmcp_visible = true\nextractor_profile = \"default\"\nrefresh_policy = \"manual\"\ndatabase = \"repomap_repo_map\"\n\n"
    "[server_memory]\nenabled = false\npath = \"~/.codex/codex-vc/mcp/server-memory\"\nmode = \"read_only\"\n\n"
    "[[sources.feed]]\nid = \"example-feed\"\ngraph_id = \"repo-map\"\nurl = \"https://example.invalid/feed.xml\"\nenabled = false\n\n"
    "[[sources.github]]\nid = \"example-github\"\ngraph_id = \"repo-map\"\nowner = \"example\"\nrepo = \"repo\"\nmode = \"public_readonly\"\nenabled = false\n\n"
    "[[sources.api]]\nid = \"example-api\"\ngraph_id = \"repo-map\"\nsource_class = \"api.rest\"\nenabled = false\n"
)


class OpsConfigValidationUnitTests(unittest.TestCase):
    def write_config(self, content: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "repomap.local.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_unknown_sections_and_fields_are_warnings(self):
        config = load_ops_config(
            self.write_config(
                VALID_CONFIG
                + "\n[experimental]\nsecret_token = \"mcp-ops1-fake-token\"\n"
                + "\n[service.extra]\nignored = true\n"
            )
        )

        codes = [diagnostic.code for diagnostic in config.diagnostics]
        self.assertIn("unknown-top-level-section", codes)
        self.assertIn("unknown-service-field", codes)
        payload = json.dumps(ops_config_status_to_jsonable(config), sort_keys=True)
        self.assertNotIn("mcp-ops1-fake-token", payload)

    def test_service_section_validates_supported_values(self):
        for old, new, code in (
            ("mode = \"local\"", "mode = \"cloud\"", "unsupported-service-mode"),
            (
                "mcp_transport = \"stdio\"",
                "mcp_transport = \"tunnel\"",
                "unsupported-mcp-transport",
            ),
            ("log_level = \"info\"", "log_level = \"trace\"", "unsupported-log-level"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(OpsConfigError) as caught:
                    load_ops_config(self.write_config(VALID_CONFIG.replace(old, new)))
                self.assertEqual(caught.exception.diagnostics[0].code, code)

    def test_postgres_section_validates_and_redacts_literal_password(self):
        config = load_ops_config(
            self.write_config(
                VALID_CONFIG.replace(
                    'password_env = "REPOMAP_PG_PASSWORD"',
                    'password = "mcp-ops1-fake-password"',
                )
            )
        )

        codes = [diagnostic.code for diagnostic in config.diagnostics]
        self.assertIn("literal-postgres-password", codes)
        payload = ops_config_status_to_jsonable(config)
        self.assertEqual(payload["postgres"]["password"], "[REDACTED]")
        self.assertNotIn("mcp-ops1-fake-password", json.dumps(payload))

    def test_graph_registry_parsing_and_private_enable_warning(self):
        config = load_ops_config(
            self.write_config(
                VALID_CONFIG
                + """

[[graphs]]
id = "codex-vc"
name = "Codex VC"
root_path = "~/.codex/codex-vc"
repository_name = "codex-vc"
privacy = "private-ops"
enabled = true
mcp_visible = false
extractor_profile = "private-ops"
refresh_policy = "manual"
"""
            )
        )

        self.assertEqual(config.graphs[1].root_path, "~/.codex/codex-vc")
        self.assertTrue(config.graphs[1].root_path_expanded.endswith(".codex/codex-vc"))
        self.assertIn(
            "private-graph-enabled",
            [diagnostic.code for diagnostic in config.diagnostics],
        )

    def test_graph_id_validation_rejects_non_slug_values(self):
        for graph_id in ("RepoMap", "repo map", "repo/map", "../repo-map"):
            with self.subTest(graph_id=graph_id):
                with self.assertRaises(OpsConfigError) as caught:
                    load_ops_config(
                        self.write_config(
                            VALID_CONFIG.replace('id = "repo-map"', f'id = "{graph_id}"', 1)
                        )
                    )
                self.assertEqual(caught.exception.diagnostics[0].code, "invalid-graph-id")

    def test_duplicate_graph_id_is_validation_error(self):
        with self.assertRaises(OpsConfigError) as caught:
            load_ops_config(
                self.write_config(
                    VALID_CONFIG
                    + """

[[graphs]]
id = "repo-map"
name = "Duplicate RepoMap"
root_path = "/placeholder/other"
repository_name = "repo-map-copy"
privacy = "public-dev"
enabled = false
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
"""
                )
            )

        self.assertEqual(caught.exception.diagnostics[0].code, "duplicate-graph-id")

    def test_graph_visibility_warnings_are_reported(self):
        config = load_ops_config(
            self.write_config(
                VALID_CONFIG.replace("enabled = true\nmcp_visible = true", "enabled = false\nmcp_visible = true")
                + """

[[graphs]]
id = "codex-vc"
name = "Codex VC"
root_path = "~/.codex/codex-vc"
repository_name = "codex-vc"
privacy = "private-ops"
enabled = false
mcp_visible = true
extractor_profile = "private-ops"
refresh_policy = "watch"
"""
            )
        )

        codes = [diagnostic.code for diagnostic in config.diagnostics]
        self.assertIn("mcp-visible-disabled-graph", codes)
        self.assertIn("private-graph-mcp-visible", codes)
        self.assertIn("refresh-policy-deferred", codes)

    def test_graph_privacy_and_refresh_policy_validation(self):
        for old, new, code in (
            ("privacy = \"public-dev\"", "privacy = \"secret-cloud\"", "unsupported-graph-privacy"),
            ("refresh_policy = \"manual\"", "refresh_policy = \"wipe\"", "unsupported-refresh-policy"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(OpsConfigError) as caught:
                    load_ops_config(self.write_config(VALID_CONFIG.replace(old, new, 1)))
                self.assertEqual(caught.exception.diagnostics[0].code, code)

    def test_server_memory_section_is_shape_only_and_does_not_read_path(self):
        config_path = self.write_config(VALID_CONFIG)

        with patch("pathlib.Path.exists", side_effect=AssertionError("private read")):
            config = load_ops_config(config_path)

        self.assertEqual(config.server_memory.path, "~/.codex/codex-vc/mcp/server-memory")
        self.assertFalse(config.server_memory.enabled)

    def test_status_json_defaults_to_no_db_check_and_safety_markers(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))
        payload = ops_config_status_to_jsonable(config)

        self.assertTrue(payload["valid"])
        self.assertFalse(payload["postgres_status"]["db_checked"])
        self.assertIsNone(payload["postgres_status"]["schema_available"])
        self.assertTrue(payload["safety"]["local_only"])
        self.assertTrue(payload["safety"]["no_public_tunnel"])
        self.assertTrue(payload["safety"]["no_destructive_operations"])
        self.assertFalse(payload["compatibility"]["legacy_json_mcp_config_supported"])
        self.assertTrue(payload["compatibility"]["ops_json_config_removed"])
        self.assertTrue(payload["compatibility"]["json_extraction_preserved"])
        self.assertTrue(payload["compatibility"]["legacy_source_toml_supported"])

    def test_graph_registry_status_json_defaults_to_no_db_check(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))
        payload = ops_graph_registry_status_to_jsonable(config)

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["graph_count"], 1)
        self.assertEqual(payload["enabled_graph_count"], 1)
        self.assertEqual(payload["mcp_visible_graph_count"], 1)
        self.assertEqual(payload["private_graph_count"], 0)
        self.assertFalse(payload["db_checked"])
        self.assertTrue(payload["security"]["private_roots_read"] is False)
        self.assertTrue(payload["security"]["destructive_db_actions"] is False)
        graph = payload["graphs"][0]
        self.assertEqual(graph["id"], "repo-map")
        self.assertEqual(graph["repository_name"], "repo-map")
        self.assertEqual(graph["database"], "repomap_repo_map")
        self.assertEqual(graph["database_source"], "graph")
        self.assertEqual(graph["refresh_policy_status"], "implemented")
        self.assertEqual(graph["root_path_display"], "/placeholder/repo-map")
        self.assertFalse(graph["root_path_checked"])
        self.assertIsNone(graph["storage_status"])

    def test_graph_registry_status_json_can_include_db_status(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))
        storage_status = {
            "repo-map": OpsGraphStorageStatus(
                db_checked=True,
                repository_name="repo-map",
                schema_available=True,
                repository_exists=True,
                raw_observations=3,
                canonical_nodes=2,
                canonical_edges=1,
            )
        }

        payload = ops_graph_registry_status_to_jsonable(
            config, graph_storage_status=storage_status
        )

        graph_status = payload["graphs"][0]["storage_status"]
        self.assertTrue(payload["db_checked"])
        self.assertTrue(graph_status["db_checked"])
        self.assertTrue(graph_status["repository_exists"])
        self.assertEqual(graph_status["raw_observations"], 3)
        self.assertEqual(graph_status["canonical_nodes"], 2)
        self.assertEqual(graph_status["canonical_edges"], 1)

    def test_graph_database_falls_back_and_validates_safe_identifier(self):
        fallback_config = load_ops_config(
            self.write_config(VALID_CONFIG.replace('database = "repomap_repo_map"\n', ""))
        )
        payload = ops_graph_registry_status_to_jsonable(fallback_config)

        self.assertIsNone(fallback_config.graphs[0].database)
        self.assertEqual(payload["graphs"][0]["database"], "repomap")
        self.assertEqual(payload["graphs"][0]["database_source"], "postgres-default")

        with self.assertRaises(OpsConfigError) as caught:
            load_ops_config(
                self.write_config(
                    VALID_CONFIG.replace(
                        'database = "repomap_repo_map"',
                        'database = "repo-map;drop"',
                    )
                )
            )
        self.assertEqual(caught.exception.diagnostics[0].code, "invalid-graph-database")

    def test_graph_registry_table_summarizes_graphs(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))

        table = format_ops_graph_registry_table(config)

        self.assertIn("RepoMap ops graph registry", table)
        self.assertIn(
            "id | repository | database | privacy | enabled | mcp_visible | refresh | db | warnings",
            table,
        )
        self.assertIn(
            "repo-map | repo-map | repomap_repo_map | public-dev | true | true | manual/implemented | unchecked | 0",
            table,
        )
        self.assertIn("security: private_roots_read=false", table)

    def test_status_table_redacts_and_summarizes_counts(self):
        config = load_ops_config(
            self.write_config(
                VALID_CONFIG.replace(
                    'password_env = "REPOMAP_PG_PASSWORD"',
                    'password = "mcp-ops1-fake-password"',
                )
            )
        )

        table = format_ops_config_status_table(config)

        self.assertIn("RepoMap ops config status", table)
        self.assertIn("graphs: total=1 enabled=1 private_enabled=0", table)
        self.assertIn("db_checked=false", table)
        self.assertIn("[REDACTED]", table)
        self.assertNotIn("mcp-ops1-fake-password", table)

    def test_check_db_status_uses_read_only_schema_probe(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))

        with patch("repomap_kg.ops.config.execute_ops_json_readback") as readback:
            readback.return_value = {
                "connected": True,
                "schema_available": True,
                "required_tables": {"repositories": True},
            }
            db_status = check_ops_postgres_status(config, psql_command="/bin/psql")

        self.assertTrue(db_status.connected)
        self.assertTrue(db_status.schema_available)
        self.assertEqual(readback.call_args.kwargs["psql_command"], "/bin/psql")
        sql = readback.call_args.kwargs["sql"]
        self.assertIn("to_regclass", sql)
        self.assertNotIn("DROP", sql.upper())
        self.assertNotIn("CREATE", sql.upper())

    def test_graph_storage_status_sql_is_read_only(self):
        sql = build_graph_storage_status_sql(["repo-map", "codex-vc"])

        self.assertIn("SELECT json_build_object", sql)
        self.assertIn("'repo-map'", sql)
        self.assertIn("'codex-vc'", sql)
        for destructive in ("DROP", "CREATE", "DELETE", "INSERT", "UPDATE", "TRUNCATE"):
            self.assertNotIn(destructive, sql.upper())

    def test_check_graph_storage_status_uses_read_only_queries(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))

        with patch("repomap_kg.ops.config.execute_ops_json_readback") as readback:
            readback.side_effect = (
                {
                    "connected": True,
                    "schema_available": True,
                    "required_tables": {
                        "repositories": True,
                        "raw_observations": True,
                        "canonical_nodes": True,
                        "canonical_edges": True,
                    },
                },
                {
                    "graphs": [
                        {
                            "repository_name": "repo-map",
                            "repository_exists": True,
                            "raw_observations": 4,
                            "canonical_nodes": 3,
                            "canonical_edges": 2,
                        }
                    ]
                },
            )
            status = check_ops_graph_storage_status(
                config,
                psql_command="/bin/psql",
            )

        self.assertTrue(status["repo-map"].db_checked)
        self.assertTrue(status["repo-map"].repository_exists)
        self.assertEqual(status["repo-map"].raw_observations, 4)
        self.assertEqual(status["repo-map"].canonical_nodes, 3)
        self.assertEqual(status["repo-map"].canonical_edges, 2)
        self.assertEqual(readback.call_count, 2)
        self.assertTrue(
            all(
                call.kwargs["psql_command"] == "/bin/psql"
                for call in readback.call_args_list
            )
        )
        sql = readback.call_args_list[1].kwargs["sql"]
        self.assertNotIn("DROP", sql.upper())
