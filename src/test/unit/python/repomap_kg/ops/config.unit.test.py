import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_kg.ops.config import (
    OpsConfigError,
    load_ops_config,
    load_ops_config_home,
    ops_config_status_to_jsonable,
    ops_graph_registry_status_to_jsonable,
    resolve_repo_map_home,
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


class OpsConfigUnitTests(unittest.TestCase):
    def write_config(self, content: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "repomap.local.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def write_home_config(self, files: dict[str, str]) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        home = Path(tmpdir.name)
        for name, content in files.items():
            path = home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return home

    def test_repo_map_home_defaults_and_env_override_without_creation(self):
        with patch.dict("os.environ", {}, clear=True):
            default_home = resolve_repo_map_home()
        self.assertEqual(default_home, Path("~/.repo-map").expanduser())

        with tempfile.TemporaryDirectory() as tmpdir:
            env_home = Path(tmpdir) / "configured-home"
            with patch.dict("os.environ", {"REPOMAP_HOME": str(env_home)}):
                resolved = resolve_repo_map_home()

            self.assertEqual(resolved, env_home)
            self.assertFalse(env_home.exists())

    def test_legacy_repo_map_home_env_is_not_honored(self):
        legacy_env = "REPO" + "_MAP_HOME"
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_home = Path(tmpdir) / "legacy-home"
            with patch.dict("os.environ", {legacy_env: str(legacy_home)}, clear=True):
                resolved = resolve_repo_map_home()

        self.assertEqual(resolved, Path("~/.repo-map").expanduser())
        self.assertNotEqual(resolved, legacy_home)

    def test_config_home_discovers_rp_and_rpl_files_with_overlay(self):
        home = self.write_home_config(
            {
                "00-project.rp.toml": VALID_CONFIG.replace(
                    'root_path = "/placeholder/repo-map"',
                    'root_path = "./project-repo"',
                ),
                "90-local.rpl.toml": """\
schema_version = 1

[[graphs]]
id = "repo-map"
root_path = "./local-repo-map"
enabled = false
mcp_visible = false
exclude_paths = [".git", "node_modules", "result-*"]

[[graphs]]
id = "codex-vc"
name = "Codex VC"
root_path = "./private-placeholder/codex-vc"
repository_name = "codex-vc"
privacy = "private-ops"
enabled = false
mcp_visible = false
extractor_profile = "private-ops"
refresh_policy = "manual"
exclude_paths = [".git", ".serena"]

[server_memory]
enabled = true
path = "./memory.jsonl"
mode = "read_only"
""",
                "ignored.toml": "not = 'loaded'\n",
                "nested/99-local.rpl.toml": "schema_version = 1\n",
            }
        )

        config = load_ops_config_home(home)

        self.assertEqual(config.config_path, str(home))
        self.assertEqual(config.config_files, ("00-project.rp.toml", "90-local.rpl.toml"))
        self.assertEqual([graph.id for graph in config.graphs], ["repo-map", "codex-vc"])
        repo_graph = config.graphs[0]
        self.assertEqual(repo_graph.root_path, "./local-repo-map")
        self.assertFalse(repo_graph.enabled)
        self.assertEqual(repo_graph.exclude_paths, (".git", "node_modules", "result-*"))
        self.assertEqual(config.server_memory.path, "./memory.jsonl")
        codes = [diagnostic.code for diagnostic in config.diagnostics]
        self.assertIn("config-file-ignored", codes)
        self.assertIn("graph-overlay", codes)

    def test_config_home_merge_order_is_deterministic(self):
        home = self.write_home_config(
            {
                "10-project.rp.toml": VALID_CONFIG.replace(
                    'root_path = "/placeholder/repo-map"',
                    'root_path = "./ten"',
                ),
                "00-project.rp.toml": """\
schema_version = 1

[[graphs]]
id = "repo-map"
root_path = "./zero"
""",
                "80-local.rpl.toml": """\
schema_version = 1

[[graphs]]
id = "repo-map"
root_path = "./local-eighty"
""",
                "90-local.rpl.toml": """\
schema_version = 1

[[graphs]]
id = "repo-map"
root_path = "./local-ninety"
""",
            }
        )

        config = load_ops_config_home(home)

        self.assertEqual(
            config.config_files,
            (
                "00-project.rp.toml",
                "10-project.rp.toml",
                "80-local.rpl.toml",
                "90-local.rpl.toml",
            ),
        )
        self.assertEqual(config.graphs[0].root_path, "./local-ninety")

    def test_config_home_reports_duplicate_graphs_and_sources(self):
        home = self.write_home_config(
            {
                "00-project.rp.toml": VALID_CONFIG
                + """

[[graphs]]
id = "repo-map"
name = "RepoMap Duplicate"
root_path = "./duplicate"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[[sources.feed]]
id = "example-feed"
graph_id = "repo-map"
url = "https://example.invalid/other.xml"
enabled = false
""",
                "90-local.rpl.toml": """\
schema_version = 1

[[sources.feed]]
id = "example-feed"
enabled = true
""",
            }
        )

        config = load_ops_config_home(home)
        codes = [diagnostic.code for diagnostic in config.diagnostics]

        self.assertIn("duplicate-graph-id", codes)
        self.assertIn("source-overlay", codes)
        self.assertEqual(len(config.sources.feed), 1)
        self.assertTrue(config.sources.feed[0].enabled)

    def test_config_home_rejects_missing_and_unsupported_schema_versions(self):
        with self.assertRaises(OpsConfigError) as missing:
            load_ops_config_home(self.write_home_config({"00-project.rp.toml": "[service]\n"}))
        self.assertEqual(missing.exception.diagnostics[0].code, "missing-schema-version")

        with self.assertRaises(OpsConfigError) as unsupported:
            load_ops_config_home(
                self.write_home_config({"00-project.rp.toml": "schema_version = 2\n"})
            )
        self.assertEqual(unsupported.exception.diagnostics[0].code, "unsupported-schema-version")

    def test_graph_exclude_paths_validate_relative_safe_strings(self):
        config = load_ops_config(
            self.write_config(
                VALID_CONFIG.replace(
                    'refresh_policy = "manual"',
                    'refresh_policy = "manual"\nexclude_paths = [".git", ".serena", "result-*"]',
                    1,
                )
            )
        )

        self.assertEqual(config.graphs[0].exclude_paths, (".git", ".serena", "result-*"))
        payload = ops_graph_registry_status_to_jsonable(config)
        self.assertEqual(payload["graphs"][0]["exclude_paths_count"], 3)
        self.assertEqual(payload["graphs"][0]["exclude_paths"], [".git", ".serena", "result-*"])
        self.assertTrue(payload["graphs"][0]["exclude_paths_enforced"])

    def test_polling_refresh_policies_are_accepted_as_implemented(self):
        for policy in ("polling", "continuous"):
            with self.subTest(policy=policy):
                config = load_ops_config(
                    self.write_config(
                        VALID_CONFIG.replace(
                            'refresh_policy = "manual"',
                            f'refresh_policy = "{policy}"',
                            1,
                        )
                    )
                )
                graph = config.graphs[0]
                self.assertEqual(graph.refresh_policy, policy)
                self.assertTrue(graph.to_jsonable()["refresh_implemented"])
                payload = ops_graph_registry_status_to_jsonable(config)
                self.assertEqual(
                    payload["graphs"][0]["refresh_policy_status"], "implemented"
                )

    def test_graph_exclude_paths_reject_absolute_and_traversal_paths(self):
        for bad_path in ("../outside", "/private/tmp/secret"):
            with self.subTest(bad_path=bad_path):
                with self.assertRaises(OpsConfigError) as caught:
                    load_ops_config(
                        self.write_config(
                            VALID_CONFIG.replace(
                                'refresh_policy = "manual"',
                                f'refresh_policy = "manual"\nexclude_paths = ["{bad_path}"]',
                                1,
                            )
                        )
                )
                self.assertEqual(caught.exception.diagnostics[0].code, "invalid-graph-exclude-path")

    def test_runtime_container_placeholder_config_parses(self):
        config = load_ops_config(
            self.write_config(
                VALID_CONFIG
                + """

[runtime]
container_runtime = "docker"
postgres_host_port = 55432
server_host_port = 55880
bind_host = "127.0.0.1"
"""
            )
        )

        self.assertEqual(config.runtime.container_runtime, "docker")
        self.assertEqual(config.runtime.postgres_host_port, 55432)
        self.assertEqual(config.runtime.server_host_port, 55880)
        self.assertFalse(config.runtime.postgres.direct_host_port_enabled)
        self.assertEqual(config.runtime.postgres.host_port, 55432)
        self.assertEqual(config.runtime.postgres.bind_host, "127.0.0.1")
        self.assertIn(
            "runtime-postgres-host-port-deprecated",
            [diagnostic.code for diagnostic in config.diagnostics],
        )
        payload = ops_config_status_to_jsonable(config)
        self.assertTrue(payload["runtime"]["containerized_target"])
        self.assertFalse(payload["runtime"]["postgres"]["direct_host_port_enabled"])
        self.assertFalse(payload["runtime"]["containers_started"])
        self.assertFalse(payload["runtime"]["ports_probed"])

    def test_runtime_postgres_direct_db_toggle_parses(self):
        config = load_ops_config(
            self.write_config(
                VALID_CONFIG
                + """

[runtime]
container_runtime = "docker"
server_host_port = 55880

[runtime.postgres]
direct_host_port_enabled = true
host_port = 55444
bind_host = "127.0.0.1"
"""
            )
        )

        self.assertTrue(config.runtime.postgres.direct_host_port_enabled)
        self.assertEqual(config.runtime.postgres.host_port, 55444)
        self.assertEqual(config.runtime.postgres.bind_host, "127.0.0.1")
        payload = ops_config_status_to_jsonable(config)
        self.assertTrue(payload["runtime"]["postgres"]["direct_host_port_enabled"])
        self.assertEqual(payload["runtime"]["postgres"]["host_port"], 55444)

    def test_runtime_postgres_public_bind_is_rejected(self):
        with self.assertRaises(OpsConfigError) as caught:
            load_ops_config(
                self.write_config(
                    VALID_CONFIG
                    + """

[runtime.postgres]
direct_host_port_enabled = true
host_port = 55432
bind_host = "0.0.0.0"
"""
                )
            )

        self.assertEqual(caught.exception.diagnostics[0].code, "unsupported-runtime-bind-host")

    def test_json_ops_config_is_removed_without_removing_json_extraction(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "config.json"
        path.write_text('{"schema_version": 1}', encoding="utf-8")

        with self.assertRaises(OpsConfigError) as caught:
            load_ops_config(path)

        self.assertEqual(caught.exception.diagnostics[0].code, "ops-json-config-removed")

    def test_valid_minimal_unified_toml_config_parses(self):
        config = load_ops_config(self.write_config(VALID_CONFIG))

        self.assertEqual(config.schema_version, 1)
        self.assertEqual(config.service.mode, "local")
        self.assertEqual(config.postgres.host, "127.0.0.1")
        self.assertEqual(config.postgres.port, 5432)
        self.assertEqual(config.postgres.password_env, "REPOMAP_PG_PASSWORD")
        self.assertEqual([graph.id for graph in config.graphs], ["repo-map"])
        self.assertEqual(config.graphs[0].database, "repomap_repo_map")
        self.assertEqual(config.server_memory.mode, "read_only")
        self.assertEqual(len(config.sources.feed), 1)
        self.assertEqual(len(config.sources.github), 1)
        self.assertEqual(len(config.sources.api), 1)
        self.assertEqual(config.diagnostics, ())

    def test_committed_example_config_parses(self):
        config = load_ops_config_home(Path("docs") / "examples" / "repo-map-home")

        self.assertEqual(config.schema_version, 1)
        self.assertEqual(config.config_files, ("00-project.rp.toml", "90-local.rpl.toml"))
        self.assertEqual([graph.id for graph in config.graphs], ["repo-map", "private-ops", "private-notes", "private-config"])
        self.assertFalse(config.graphs[1].enabled)
        self.assertGreater(len(config.graphs[0].exclude_paths), 0)
        payload = json.dumps(ops_config_status_to_jsonable(config), sort_keys=True)
        self.assertNotIn("/Users/", payload)
        self.assertNotIn("admin/admin", payload)

    def test_missing_schema_version_is_diagnostic_error(self):
        with self.assertRaises(OpsConfigError) as caught:
            load_ops_config(self.write_config(VALID_CONFIG.replace("schema_version = 1\n", "")))

        self.assertIn("schema_version is required", str(caught.exception))
        self.assertEqual(caught.exception.diagnostics[0].code, "missing-schema-version")

    def test_unsupported_schema_version_is_diagnostic_error(self):
        with self.assertRaises(OpsConfigError) as caught:
            load_ops_config(self.write_config(VALID_CONFIG.replace("schema_version = 1", "schema_version = 2")))

        self.assertIn("unsupported schema_version", str(caught.exception))
        self.assertEqual(caught.exception.diagnostics[0].code, "unsupported-schema-version")
