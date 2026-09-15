import json
import tempfile
import unittest
from pathlib import Path

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
)



class StorageMigrationsOpsStatusIntegrationTests(unittest.TestCase):
    def test_apply_migrations_creates_core_graph_tables(self):
        require_postgres_binaries()

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            tables = postgres.psql_scalar(
                """
SELECT string_agg(table_name, ',' ORDER BY table_name)
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'repositories',
    'runs',
    'files',
    'nodes',
    'edges',
    'evidence',
    'raw_observations',
    'canonical_nodes',
    'canonical_edges',
    'canonical_evidence',
    'canonical_node_evidence',
    'canonical_edge_evidence'
  );
"""
            )
            inserted_path = postgres.psql_scalar(
                """
INSERT INTO repositories(name, root_path)
VALUES ('fixture', '/tmp/fixture')
RETURNING id
\\gset
INSERT INTO runs(repository_id, status)
VALUES (:id, 'complete')
RETURNING id
\\gset run_
INSERT INTO files(
  repository_id,
  path,
  language,
  role,
  content_hash,
  executable,
  generated
)
VALUES (:id, 'bin/tool', 'shell', 'entrypoint', repeat('0', 64), true, false)
RETURNING id
\\gset file_
INSERT INTO canonical_nodes(
  repository_id,
  graph_key_version,
  canonical_key,
  kind,
  display_name,
  confidence,
  first_seen_run_id,
  last_seen_run_id
)
VALUES (
  :id,
  1,
  'file:bin/tool',
  'file',
  'bin/tool',
  'manual',
  :run_id,
  :run_id
);
SELECT path FROM files WHERE role = 'entrypoint';
"""
            )

        self.assertEqual(
            tables,
            "canonical_edge_evidence,canonical_edges,canonical_evidence,"
            "canonical_node_evidence,canonical_nodes,files,raw_observations,"
            "repositories,runs",
        )
        self.assertEqual(inserted_path, "bin/tool")

    def test_ops_config_check_cli_probes_postgres_status_read_only(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            graph_root = Path(tmpdir) / "repo-map"
            graph_root.mkdir()
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                before_count = postgres.psql_scalar("SELECT count(*) FROM repositories;")
                config_text = f"""\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "{graph_root}"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
"""
                config_path.write_text(
                    config_text,
                    encoding="utf-8",
                )

                exit_code, stdout, stderr = run_repo_map_in_process(
                    "ops",
                    "config-check",
                    "--config",
                    str(config_path),
                    "--check-db",
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
                after_count = postgres.psql_scalar("SELECT count(*) FROM repositories;")

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["postgres_status"]["db_checked"])
        self.assertTrue(payload["postgres_status"]["connected"])
        self.assertTrue(payload["postgres_status"]["schema_available"])
        self.assertTrue(payload["postgres_status"]["required_tables"]["repositories"])
        self.assertEqual(before_count, "0")
        self.assertEqual(after_count, before_count)
        self.assertTrue(payload["safety"]["no_destructive_operations"])
        self.assertNotIn("DROP", stdout.upper())
        self.assertEqual(stderr, "")

    def test_ops_graphs_cli_checks_storage_status_read_only(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            graph_root = Path(tmpdir) / "repo-map"
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                postgres.psql_scalar(
                    f"""
INSERT INTO repositories(name, root_path)
VALUES ('repo-map', '{graph_root}')
"""
                )
                before_count = postgres.psql_scalar("SELECT count(*) FROM repositories;")
                config_text = f"""\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "{graph_root}"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
"""
                config_path.write_text(
                    config_text,
                    encoding="utf-8",
                )

                exit_code, stdout, stderr = run_repo_map_in_process(
                    "ops",
                    "graphs",
                    "--config",
                    str(config_path),
                    "--check-db",
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
                after_count = postgres.psql_scalar("SELECT count(*) FROM repositories;")

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["db_checked"])
        status = payload["graphs"][0]["storage_status"]
        self.assertTrue(status["db_checked"])
        self.assertTrue(status["schema_available"])
        self.assertTrue(status["repository_exists"])
        self.assertNotIn("repository_id", status)
        self.assertEqual(status["raw_observations"], 0)
        self.assertEqual(status["canonical_nodes"], 0)
        self.assertEqual(status["canonical_edges"], 0)
        self.assertEqual(before_count, "1")
        self.assertEqual(after_count, before_count)
        self.assertFalse(payload["security"]["destructive_db_actions"])
        self.assertNotIn("DROP", stdout.upper())
        self.assertEqual(stderr, "")

    def test_ops_refresh_graph_cli_loads_graph_and_reports_status(self):
        require_postgres_binaries()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "repomap.local.toml"
            graph_root = Path(tmpdir) / "repo-map"
            graph_root.mkdir()
            (graph_root / "README.md").write_text("# Fixture\n", encoding="utf-8")
            before_files = sorted(path.name for path in graph_root.iterdir())
            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                config_text = f"""\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"
password_env = "REPOMAP_PG_PASSWORD"

[[graphs]]
id = "repo-map"
name = "RepoMap"
root_path = "{graph_root}"
repository_name = "repo-map"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
"""
                config_path.write_text(
                    config_text,
                    encoding="utf-8",
                )

                exit_code, stdout, stderr = run_repo_map_in_process(
                    "ops",
                    "refresh-graph",
                    "--config",
                    str(config_path),
                    "--graph",
                    "repo-map",
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
                status_exit_code, status_stdout, status_stderr = run_repo_map_in_process(
                    "ops",
                    "refresh-status",
                    "--config",
                    str(config_path),
                    "--graph",
                    "repo-map",
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
                table_status_exit_code, table_status_stdout, table_status_stderr = (
                    run_repo_map_in_process(
                        "ops",
                        "refresh-status",
                        "--config",
                        str(config_path),
                        "--psql-command",
                        postgres.psql_command,
                    )
                )
                repository_count = postgres.psql_scalar(
                    "SELECT count(*) FROM repositories;"
                )
                raw_count = postgres.psql_scalar(
                    "SELECT count(*) FROM raw_observations;"
                )
                finished_at_stored = postgres.psql_scalar(
                    """
SELECT (finished_at IS NOT NULL)::text
FROM runs
WHERE id = (SELECT max(id) FROM runs);
"""
                )
            after_files = sorted(path.name for path in graph_root.iterdir())

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["result"], "success")
        self.assertEqual(payload["refreshed_graph_count"], 1)
        self.assertEqual(payload["graphs"][0]["graph_id"], "repo-map")
        self.assertGreater(payload["graphs"][0]["observations"], 0)
        self.assertIsNotNone(payload["graphs"][0]["finished_at"])
        self.assertFalse(payload["safety"]["destructive_db_actions"])
        self.assertEqual(status_exit_code, 0, status_stderr)
        status_payload = json.loads(status_stdout)
        self.assertTrue(status_payload["db_checked"])
        self.assertEqual(
            status_payload["graphs"][0]["latest_run_id"],
            payload["graphs"][0]["run_id"],
        )
        self.assertEqual(status_payload["graphs"][0]["latest_run_status"], "complete")
        self.assertIsNotNone(status_payload["graphs"][0]["latest_run_finished_at"])
        self.assertGreater(status_payload["graphs"][0]["raw_observations"], 0)
        self.assertEqual(table_status_exit_code, 0, table_status_stderr)
        self.assertIn("RepoMap ops refresh status", table_status_stdout)
        self.assertIn(
            "repo-map | repo-map | repomap_test | public-dev | complete",
            table_status_stdout,
        )
        self.assertEqual(repository_count, "1")
        self.assertGreater(int(raw_count), 0)
        self.assertEqual(finished_at_stored, "true")
        self.assertEqual(before_files, after_files)
        self.assertEqual(stderr, "")
        self.assertEqual(status_stderr, "")
        self.assertEqual(table_status_stderr, "")
