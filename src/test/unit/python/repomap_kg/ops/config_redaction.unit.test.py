import json
import tempfile
import unittest
from pathlib import Path

from repomap_kg.ops.config import (
    OpsGraphStorageStatus,
    format_ops_config_status_table,
    format_ops_graph_registry_table,
    load_ops_config,
    load_ops_config_home,
    ops_config_status_to_jsonable,
    ops_graph_registry_status_to_jsonable,
)


PUBLIC_CONFIG = """\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "admin"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "/placeholder/repo-map"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
database = "repomap_repo_map"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
"""

PRIVATE_GRAPH = """

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
database = "repomap_codex_vc"
exclude_paths = ["mcp/secrets.toml"]
"""


EXPECTED_CONFIG_LOADING_PUBLIC_NAMES = frozenset(
    """
    Any DEFAULT_REPOMAP_HOME GRAPH_ID_PATTERN KNOWN_POSTGRES_FIELDS
    KNOWN_RUNTIME_FIELDS KNOWN_RUNTIME_POSTGRES_FIELDS KNOWN_SERVER_MEMORY_FIELDS
    KNOWN_SERVICE_FIELDS KNOWN_TOP_LEVEL_SECTIONS Mapping OpsConfig
    OpsConfigDiagnostic OpsConfigError OpsGraphConfig OpsGraphSourceBindingConfig
    OpsGraphStorageStatus OpsPostgresConfig OpsPostgresStatus OpsRuntimeConfig
    OpsRuntimePostgresConfig OpsServerMemoryConfig OpsServiceConfig
    OpsSourcePlaceholder OpsSourcesConfig PRIVATE_PRIVACY Path REDACTED
    SAFE_POSTGRES_DATABASE_PATTERN SECRET_KEY_PARTS SUPPORTED_CONTAINER_RUNTIMES
    SUPPORTED_LOG_LEVELS SUPPORTED_MCP_TRANSPORTS SUPPORTED_PRIVACY
    SUPPORTED_REFRESH_POLICIES SUPPORTED_SCHEMA_VERSION SUPPORTED_SERVER_MEMORY_MODES
    SUPPORTED_SERVICE_MODES Sequence annotations bool_text build_ops_config_from_payload
    expand_user_path format_counts format_ops_config_status_table
    format_ops_graph_registry_table graph_database graph_database_source graph_psql_args
    graph_storage_label is_credentialed_url is_secret_key json load_ops_config
    load_ops_config_home merge_ops_config_payloads ops_config_status_to_jsonable
    ops_graph_registry_status_to_jsonable optional_bool optional_int optional_text os
    parse_graph_exclude_paths parse_graphs_section parse_postgres_section parse_psql_json
    parse_runtime_section parse_server_memory_section parse_service_section
    parse_source_placeholders parse_sources_section read_toml_payload redact_mapping
    redact_text redact_value require_mapping required_bool required_int required_text
    resolve_ops_config resolve_repo_map_home run_psql tomllib unknown_field_diagnostics
    unknown_file_field_diagnostics unknown_top_level_diagnostics validate_file_schema
    """.split()
)

EXPECTED_CONFIG_EXTRA_PUBLIC_NAMES = frozenset(
    {
        "StorageSchemaError",
        "build_graph_storage_status_sql",
        "build_postgres_status_sql",
        "cast",
        "check_ops_graph_storage_status",
        "check_ops_postgres_status",
        "execute_ops_json_readback",
        "sql_literal",
    }
)


class OpsConfigRedactionUnitTests(unittest.TestCase):
    def test_config_facade_preserves_eager_namespace_identity(self):
        import repomap_kg.ops.config as config
        import repomap_kg.ops.config_loading as loading
        loading_public_names = {
            name for name in vars(loading) if not name.startswith("_")
        }
        config_public_names = {
            name for name in vars(config) if not name.startswith("_")
        }

        self.assertEqual(loading_public_names, EXPECTED_CONFIG_LOADING_PUBLIC_NAMES)
        self.assertEqual(
            config_public_names,
            EXPECTED_CONFIG_LOADING_PUBLIC_NAMES | EXPECTED_CONFIG_EXTRA_PUBLIC_NAMES,
        )
        for name in sorted(loading_public_names):
            self.assertIs(getattr(config, name), getattr(loading, name))

    def write_config(self, content: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "repomap.local.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def write_config_home(self, content: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        home = Path(tmpdir.name)
        (home / "00-project.rp.toml").write_text(content, encoding="utf-8")
        return home

    def test_status_outputs_redact_local_config_and_private_graph_fields(self):
        config = load_ops_config(self.write_config(PUBLIC_CONFIG + PRIVATE_GRAPH))

        status = ops_config_status_to_jsonable(config)
        registry = ops_graph_registry_status_to_jsonable(config)
        private_status = status["graphs"][1]
        private_registry = registry["graphs"][1]

        self.assertEqual(status["config_path"], "[local-config]")
        self.assertIsNone(status["config_home"])
        self.assertEqual(status["server_memory"]["path"], "[private-path]")
        self.assertEqual(status["server_memory"]["path_expanded"], "[private-path]")
        self.assertEqual(status["graphs"][0]["root_path"], "/placeholder/repo-map")
        self.assertEqual(status["graphs"][0]["database"], "repomap_repo_map")
        self.assertEqual(private_status["root_path"], "[private-root]")
        self.assertEqual(private_status["root_path_expanded"], "[private-root]")
        self.assertEqual(private_status["database"], "[private-database]")
        self.assertEqual(private_status["exclude_paths"], ["[private-path]"])
        self.assertEqual(registry["config_path"], "[local-config]")
        self.assertEqual(private_registry["root_path_display"], "[private-root]")
        self.assertEqual(private_registry["root_path_expanded"], "[private-root]")
        self.assertEqual(private_registry["database"], "[private-database]")
        self.assertEqual(private_registry["exclude_paths"], ["[private-path]"])

        serialized = json.dumps((status, registry), sort_keys=True)
        tables = "\n".join(
            (
                format_ops_config_status_table(config),
                format_ops_graph_registry_table(config),
            )
        )
        for private_value in (
            config.config_path,
            config.server_memory.path,
            config.server_memory.path_expanded,
            config.graphs[1].root_path,
            config.graphs[1].root_path_expanded,
            "repomap_codex_vc",
            "mcp/secrets.toml",
        ):
            self.assertNotIn(private_value, serialized)
            self.assertNotIn(private_value, tables)

    def test_config_home_status_redacts_home_but_preserves_file_names(self):
        home = self.write_config_home(PUBLIC_CONFIG)
        config = load_ops_config_home(home)

        status = ops_config_status_to_jsonable(config)
        registry = ops_graph_registry_status_to_jsonable(config)
        table = format_ops_config_status_table(config)

        self.assertEqual(status["config_path"], "[local-config]")
        self.assertEqual(status["config_home"], "[local-config]")
        self.assertEqual(status["config_files"], ["00-project.rp.toml"])
        self.assertEqual(registry["config_path"], "[local-config]")
        self.assertEqual(registry["config_home"], "[local-config]")
        self.assertNotIn(str(home), json.dumps((status, registry), sort_keys=True))
        self.assertNotIn(str(home), table)

    def test_graph_storage_status_redacts_private_database_and_internal_id(self):
        config = load_ops_config(self.write_config(PUBLIC_CONFIG + PRIVATE_GRAPH))
        storage_status = {
            "repo-map": OpsGraphStorageStatus(
                db_checked=True,
                repository_name="repo-map",
                database="repomap_repo_map",
                schema_available=True,
                repository_exists=True,
                repository_id=41,
                raw_observations=7,
                canonical_nodes=5,
                canonical_edges=3,
            ),
            "codex-vc": OpsGraphStorageStatus(
                db_checked=True,
                repository_name="codex-vc",
                database="repomap_codex_vc",
                schema_available=True,
                repository_exists=True,
                repository_id=42,
                raw_observations=11,
                canonical_nodes=9,
                canonical_edges=4,
            ),
        }

        registry = ops_graph_registry_status_to_jsonable(
            config,
            graph_storage_status=storage_status,
        )
        table = format_ops_graph_registry_table(
            config,
            graph_storage_status=storage_status,
        )
        public_status = registry["graphs"][0]["storage_status"]
        private_status = registry["graphs"][1]["storage_status"]

        self.assertEqual(public_status["database"], "repomap_repo_map")
        self.assertEqual(private_status["database"], "[private-database]")
        self.assertNotIn("repository_id", public_status)
        self.assertNotIn("repository_id", private_status)
        self.assertEqual(private_status["canonical_nodes"], 9)
        self.assertNotIn("repomap_codex_vc", json.dumps(registry, sort_keys=True))
        self.assertNotIn("repomap_codex_vc", table)


if __name__ == "__main__":
    unittest.main()
