import json
import tempfile
from pathlib import Path

from repomap_test_support.cli_integration import (
    OPS_CONFIG_TEMPLATE,
    CliIntegrationTestCase,
)


class CliOpsConfigIntegrationTests(CliIntegrationTestCase):
    def test_ops_graphs_reports_graph_specific_database(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            config_path.write_text(
                OPS_CONFIG_TEMPLATE.replace(
                    'refresh_policy = "manual"',
                    'refresh_policy = "manual"\ndatabase = "repomap_repo_map"',
                    1,
                ),
                encoding="utf-8",
            )
            result = self.run_cli("ops", "graphs", "--config", str(config_path), "--json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["graphs"][0]["database"], "repomap_repo_map")
        self.assertEqual(payload["graphs"][0]["database_source"], "graph")
        self.assertFalse(payload["security"]["private_roots_read"])

    def test_ops_config_check_reads_example_without_db_check(self):
        exit_code, stdout, stderr = self.run_module_entrypoint(
            "ops", "config-check", "--repo-map-home", "docs/examples/repo-map-home", "--json"
        )
        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["schema_version"], 1)
        self.assertFalse(payload["postgres_status"]["db_checked"])
        self.assertEqual(payload["graph_counts"]["total"], 4)
        self.assertTrue(payload["safety"]["local_only"])
        self.assertTrue(payload["safety"]["no_destructive_operations"])
        self.assertNotIn("admin/admin", stdout)
        self.assertNotIn("/Users/", stdout)
        self.assertEqual(stderr, "")

    def test_ops_graphs_reads_example_without_db_check(self):
        exit_code, stdout, stderr = self.run_module_entrypoint(
            "ops", "graphs", "--repo-map-home", "docs/examples/repo-map-home", "--json"
        )
        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["graph_count"], 4)
        self.assertEqual(payload["enabled_graph_count"], 1)
        self.assertEqual(payload["mcp_visible_graph_count"], 1)
        self.assertEqual(payload["private_graph_count"], 3)
        self.assertFalse(payload["db_checked"])
        self.assertFalse(payload["security"]["private_roots_read"])
        self.assertFalse(payload["security"]["destructive_db_actions"])
        self.assertEqual(payload["graphs"][0]["id"], "repo-map")
        self.assertFalse(payload["graphs"][1]["enabled"])
        self.assertNotIn("admin/admin", stdout)
        self.assertNotIn("/Users/", stdout)
        self.assertEqual(stderr, "")

    def test_ops_graphs_table_lists_example_graphs(self):
        exit_code, stdout, stderr = self.run_module_entrypoint(
            "ops", "graphs", "--repo-map-home", "docs/examples/repo-map-home"
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("RepoMap ops graph registry", stdout)
        self.assertIn("repo-map | repo-map | repomap_repo_map | public-dev | true | true", stdout)
        self.assertIn("private-ops | private-ops | [private-database] | private-ops | false | false", stdout)
        self.assertNotIn("repomap_private_ops", stdout)
        self.assertIn("private_roots_read=false", stdout)
        self.assertNotIn("/Users/", stdout)
        self.assertEqual(stderr, "")

    def test_ops_config_check_accepts_minimal_config_without_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_ops_config(Path(tmpdir), OPS_CONFIG_TEMPLATE)
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "ops", "config-check", "--config", str(config_path), "--json"
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["sources"]["counts"], {"feed": 0, "github": 0, "api": 0})
        self.assertFalse(payload["compatibility"]["legacy_json_mcp_config_supported"])
        self.assertTrue(payload["compatibility"]["ops_json_config_removed"])
        self.assertTrue(payload["compatibility"]["json_extraction_preserved"])
        self.assertTrue(payload["compatibility"]["legacy_source_toml_supported"])
        self.assertEqual(stderr, "")

    def test_ops_config_check_text_output_redacts_literal_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_ops_config(
                Path(tmpdir),
                OPS_CONFIG_TEMPLATE.replace(
                    'password_env = "REPOMAP_PG_PASSWORD"',
                    'password = "mcp-ops1-fake-password"',
                ),
            )
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "ops", "config-check", "--config", str(config_path)
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("RepoMap ops config status", stdout)
        self.assertIn("password=[REDACTED]", stdout)
        self.assertIn("diagnostics: warning=1", stdout)
        self.assertNotIn("mcp-ops1-fake-password", stdout)
        self.assertEqual(stderr, "")

    def test_ops_config_check_json_reports_deferred_private_sections(self):
        sm_old = '[server_memory]\nenabled = false\npath = "./server-memory"\nmode = "read_only"\n'
        sm_new = '[server_memory]\nenabled = true\npath = "~/.codex/codex-vc/mcp/server-memory"\nmode = "read_only"\n'
        extra = (
            '\n[[graphs]]\nid = "codex-vc"\nname = "Codex VC"\nroot_path = "~/.codex/codex-vc"\n'
            'repository_name = "codex-vc"\ndatabase = "repomap_codex_vc"\nprivacy = "private-ops"\n'
            'enabled = true\nmcp_visible = false\nextractor_profile = "private-ops"\nrefresh_policy = "watch"\n'
            '[[sources.feed]]\nid = "private-feed"\ngraph_id = "repo-map"\n'
            'url = "https://agent:mcp-ops1-fake-token@example.invalid/feed.xml"\nenabled = true\n'
            '[[sources.github]]\nid = "public-github"\ngraph_id = "repo-map"\n'
            'owner = "example"\nrepo = "repo"\nmode = "public_readonly"\nenabled = true\n'
            '[[sources.api]]\nid = "api-placeholder"\ngraph_id = "repo-map"\n'
            'source_class = "api.rest"\ncredential = "mcp-ops1-fake-credential"\nenabled = true\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_ops_config(
                Path(tmpdir),
                OPS_CONFIG_TEMPLATE.replace(sm_old, sm_new) + extra,
            )
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "ops", "config-check", "--config", str(config_path), "--json"
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        for c in ("private-graph-enabled", "refresh-policy-deferred", "source-acquisition-deferred"):
            self.assertIn(c, codes)
        self.assertNotIn("server-memory-bridge-deferred", codes)
        self.assertEqual(payload["graph_counts"]["private_enabled"], 1)
        self.assertTrue(payload["server_memory"]["enabled"])
        self.assertTrue(payload["server_memory"]["bridge_implemented"])
        self.assertFalse(payload["sources"]["feed"][0]["acquisition_implemented"])
        self.assertIn("[REDACTED]", json.dumps(payload["sources"], sort_keys=True))
        self.assertTrue(payload["safety"]["no_server_memory_read"])
        self.assertTrue(payload["safety"]["no_source_acquisition"])
        self.assertNotIn("mcp-ops1-fake-token", stdout)
        self.assertNotIn("mcp-ops1-fake-credential", stdout)
        self.assertEqual(stderr, "")

    def test_ops_config_check_merges_repo_map_home_overlay_diagnostics(self):
        p_extra = (
            '\n[runtime]\ncontainer_runtime = "docker"\npostgres_host_port = 55432\n'
            'server_host_port = 55880\nbind_host = "127.0.0.1"\n'
            '[[graphs]]\nid = "repo-map"\nname = "RepoMap Duplicate"\nroot_path = "./duplicate"\n'
            'repository_name = "repo-map"\nprivacy = "public-dev"\nenabled = true\n'
            'mcp_visible = true\nextractor_profile = "default"\nrefresh_policy = "manual"\n'
            '[[sources.feed]]\nid = "example-feed"\ngraph_id = "repo-map"\n'
            'url = "https://example.invalid/feed.xml"\nenabled = false\n[experimental]\nenabled = true\n'
        )
        l_toml = (
            'schema_version = 1\n\n[runtime]\npostgres_host_port = 55433\n\n[[graphs]]\n'
            'id = "repo-map"\nroot_path = "./local"\nenabled = false\nmcp_visible = false\n'
            'exclude_paths = [".git", ".serena", "result-*"]\n\n[[sources.feed]]\nid = "example-feed"\nenabled = true\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            home.mkdir()
            self.write_fixture(
                home / "00-project.rp.toml",
                OPS_CONFIG_TEMPLATE.replace('log_level = "info"', 'log_level = "info"\nunknown_flag = true') + p_extra,
            )
            self.write_fixture(home / "90-local.rpl.toml", l_toml)
            self.write_fixture(home / "ignored.toml", "schema_version = 1\n")
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "ops", "config-check", "--repo-map-home", str(home), "--json"
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertEqual(payload["config_files"], ["00-project.rp.toml", "90-local.rpl.toml"])
        self.assertEqual(payload["runtime"]["postgres_host_port"], 55433)
        self.assertEqual(payload["graphs"][0]["root_path"], "./local")
        self.assertEqual(payload["graphs"][0]["exclude_paths_count"], 3)
        self.assertTrue(payload["graphs"][0]["exclude_paths_enforced"])
        for c in (
            "config-file-ignored", "duplicate-graph-id", "graph-overlay",
            "runtime-overlay", "source-overlay", "unknown-top-level-section", "unknown-service-field",
        ):
            self.assertIn(c, codes)
        self.assertEqual(stderr, "")

    def test_ops_config_check_rejects_json_ops_registry_without_json_extraction_loss(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text('{"schema_version": 1}', encoding="utf-8")
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "ops", "config-check", "--config", str(config_path), "--json"
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("JSON ops/MCP registry config is removed", stderr)

    def test_ops_config_check_reports_config_home_shape_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            missing_home = base / "missing"
            file_home = base / "not-a-directory"
            file_home.write_text("schema_version = 1\n", encoding="utf-8")
            empty_home = base / "empty"
            empty_home.mkdir()

            m_exit, _, m_err = self.run_module_entrypoint("ops", "config-check", "--repo-map-home", str(missing_home), "--json")
            f_exit, _, f_err = self.run_module_entrypoint("ops", "config-check", "--repo-map-home", str(file_home), "--json")
            e_exit, _, e_err = self.run_module_entrypoint("ops", "config-check", "--repo-map-home", str(empty_home), "--json")

        self.assertEqual((m_exit, f_exit, e_exit), (1, 1, 1))
        self.assertIn("REPOMAP_HOME does not exist", m_err)
        self.assertIn("REPOMAP_HOME must be a directory", f_err)
        self.assertIn("contains no *.rp.toml or *.rpl.toml files", e_err)

    def test_ops_config_check_reports_config_home_schema_and_runtime_errors(self):
        bad_runtime = OPS_CONFIG_TEMPLATE + '\n[runtime]\ncontainer_runtime = "launchd"\npostgres_host_port = 80\nserver_host_port = 70000\nbind_host = "0.0.0.0"\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            missing_schema_home = base / "missing-schema"
            missing_schema_home.mkdir()
            self.write_fixture(missing_schema_home / "00-project.rp.toml", "[service]\n")
            unsupported_schema_home = base / "unsupported-schema"
            unsupported_schema_home.mkdir()
            self.write_fixture(unsupported_schema_home / "00-project.rp.toml", "schema_version = 2\n")
            bad_runtime_home = base / "bad-runtime"
            bad_runtime_home.mkdir()
            self.write_fixture(bad_runtime_home / "00-project.rp.toml", bad_runtime)

            m_exit, _, m_err = self.run_module_entrypoint("ops", "config-check", "--repo-map-home", str(missing_schema_home), "--json")
            u_exit, _, u_err = self.run_module_entrypoint("ops", "config-check", "--repo-map-home", str(unsupported_schema_home), "--json")
            r_exit, _, r_err = self.run_module_entrypoint("ops", "config-check", "--repo-map-home", str(bad_runtime_home), "--json")

        self.assertEqual((m_exit, u_exit, r_exit), (1, 1, 1))
        self.assertIn("schema_version is required", m_err)
        self.assertIn("unsupported schema_version", u_err)
        self.assertIn("container_runtime must be docker or podman", r_err)
        self.assertIn("must be a high localhost port", r_err)
        self.assertIn("bind_host must be localhost-only", r_err)

    def test_ops_config_check_reports_invalid_config_home_exclude_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            home.mkdir()
            self.write_fixture(
                home / "00-project.rp.toml",
                OPS_CONFIG_TEMPLATE.replace(
                    'refresh_policy = "manual"',
                    'refresh_policy = "manual"\nexclude_paths = ["../outside", "/tmp/secret"]',
                ),
            )
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "ops", "config-check", "--repo-map-home", str(home), "--json"
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("graph exclude path must stay relative", stderr)

    def test_ops_config_check_reports_unknown_fields_as_warnings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_ops_config(
                Path(tmpdir),
                OPS_CONFIG_TEMPLATE + '\n[experimental]\nsecret_token = "mcp-ops1-fake-token"\n\n[service.extra]\nignored = true\n',
            )
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "ops", "config-check", "--config", str(config_path), "--json"
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        codes = {diagnostic["code"] for diagnostic in payload["diagnostics"]}
        self.assertIn("unknown-top-level-section", codes)
        self.assertIn("unknown-service-field", codes)
        self.assertNotIn("mcp-ops1-fake-token", stdout)
        self.assertEqual(stderr, "")

    def test_ops_config_check_reports_validation_errors_without_secret_leakage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_ops_config(
                Path(tmpdir),
                OPS_CONFIG_TEMPLATE.replace('mode = "local"', 'mode = "cloud"')
                + '\n[experimental]\nsecret_token = "mcp-ops1-fake-token"\n',
            )
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "ops", "config-check", "--config", str(config_path), "--json"
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("ERROR:", stderr)
        self.assertIn("service.mode", stderr)
        self.assertNotIn("mcp-ops1-fake-token", stderr)

    def test_ops_config_check_reports_missing_and_unsupported_schema_versions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = self.write_ops_config(
                Path(tmpdir), OPS_CONFIG_TEMPLATE.replace("schema_version = 1\n\n", "")
            )
            bad_path = self.write_ops_config(
                Path(tmpdir), OPS_CONFIG_TEMPLATE.replace("schema_version = 1", "schema_version = 2"),
                name="repomap.bad.toml",
            )
            m_exit, _, m_err = self.run_module_entrypoint("ops", "config-check", "--config", str(missing_path), "--json")
            b_exit, _, b_err = self.run_module_entrypoint("ops", "config-check", "--config", str(bad_path), "--json")

        self.assertEqual((m_exit, b_exit), (1, 1))
        self.assertIn("schema_version is required", m_err)
        self.assertIn("unsupported schema_version", b_err)

    def test_ops_config_check_reports_invalid_section_shapes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_sections = self.write_ops_config(
                Path(tmpdir),
                'schema_version = 1\nservice = "bad"\npostgres = "bad"\ngraphs = "bad"\nserver_memory = "bad"\nsources = "bad"\n',
            )
            bad_entries = self.write_ops_config(
                Path(tmpdir),
                OPS_CONFIG_TEMPLATE + '\n[[sources.feed]]\nid = 12\nenabled = "yes"\n',
                name="bad-entries.toml",
            )
            s_exit, _, s_err = self.run_module_entrypoint("ops", "config-check", "--config", str(bad_sections), "--json")
            e_exit, _, e_err = self.run_module_entrypoint("ops", "config-check", "--config", str(bad_entries), "--json")

        self.assertEqual((s_exit, e_exit), (1, 1))
        self.assertIn("service must be a table", s_err)
        self.assertIn("sources.feed[0].id", e_err)
        self.assertIn("sources.feed[0].enabled", e_err)

    def test_ops_config_check_reports_invalid_toml_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            invalid_path = Path(tmpdir) / "repomap.local.toml"
            missing_path = Path(tmpdir) / "missing.toml"
            invalid_path.write_text("schema_version = [", encoding="utf-8")
            i_exit, i_out, i_err = self.run_module_entrypoint("ops", "config-check", "--config", str(invalid_path), "--json")
            m_exit, m_out, m_err = self.run_module_entrypoint("ops", "config-check", "--config", str(missing_path), "--json")

        self.assertEqual((i_exit, m_exit), (1, 1))
        self.assertEqual((i_out, m_out), ("", ""))
        self.assertIn("invalid TOML", i_err)
        self.assertIn("could not read config", m_err)

    def test_ops_config_check_reports_failed_read_only_db_probe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_ops_config(Path(tmpdir), OPS_CONFIG_TEMPLATE)
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "ops", "config-check", "--config", str(config_path), "--check-db", "--psql-command", "/usr/bin/false", "--json"
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        self.assertTrue(payload["postgres_status"]["db_checked"])
        self.assertFalse(payload["postgres_status"]["connected"])
        self.assertFalse(payload["postgres_status"]["schema_available"])
        self.assertIn("psql failed", payload["postgres_status"]["error"])
        self.assertTrue(payload["safety"]["no_destructive_operations"])
        self.assertEqual(stderr, "")
