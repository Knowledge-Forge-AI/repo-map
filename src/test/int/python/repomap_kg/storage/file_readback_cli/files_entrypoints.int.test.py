import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.observations import RawObservation
from repomap_test_support.storage_publication import load_file_observations
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
)
from repomap_kg.storage.readback_driver import (
    PG_CONNECTOR_ENV,
    READBACK_DRIVER_ENV,
)



class StorageFilesEntrypointsCliIntegrationTests(unittest.TestCase):
    def test_ops_graph_files_cli_reads_canonicalized_file_rows(self):
        require_postgres_binaries()
        observations = [
            RawObservation(
                kind="file",
                source_id="generated/report.json",
                path="generated/report.json",
                confidence="extracted",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "json",
                    "role": "generated",
                    "content_hash": "a" * 64,
                    "generated": True,
                    "executable": False,
                },
            ),
            RawObservation(
                kind="file",
                source_id="bin/tool",
                path="bin/tool",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "c" * 64,
                    "generated": False,
                    "executable": True,
                },
            ),
            RawObservation(
                kind="file",
                source_id="src/main/python/app.py",
                path="src/main/python/app.py",
                confidence="manual",
                extractor="fixture-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "python",
                    "role": "source",
                    "content_hash": "b" * 64,
                    "generated": False,
                    "executable": False,
                },
            ),
        ]

        with temporary_postgres() as postgres, tempfile.TemporaryDirectory() as tmpdir:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            load_file_observations(
                postgres.psql_args,
                observations,
                repository_name="fixture",
                root_path="/tmp/fixture",
                psql_command=postgres.psql_command,
            )
            home = Path(tmpdir)
            (home / "repomap.rpl.toml").write_text(
                f'''schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"
password_env = "PUBLIC_SAFE_PASSWORD"
[[graphs]]
id = "fixture"
name = "Fixture"
root_path = "/tmp/fixture"
repository_name = "fixture"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
[server_memory]
enabled = false
path = "./public-server-memory"
mode = "read_only"
''',
                encoding="utf-8",
            )
            exit_code, stdout, stderr = run_repo_map_in_process(
                "ops",
                "graph-files",
                "--repo-map-home",
                str(home),
                "--graph",
                "fixture",
                "--role",
                "source",
                "--language",
                "python",
                "--generated",
                "exclude",
                "--psql-command",
                postgres.psql_command,
                "--json",
            )
            entrypoints_exit, entrypoints_stdout, entrypoints_stderr = (
                run_repo_map_in_process(
                    "ops",
                    "graph-files",
                    "--repo-map-home",
                    str(home),
                    "--graph",
                    "fixture",
                    "--role",
                    "entrypoint",
                    "--observation-state",
                    "observed",
                    "--psql-command",
                    postgres.psql_command,
                    "--json",
                )
            )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["graph"]["id"], "fixture")
        self.assertEqual(payload["pagination"]["returned"], 1)
        self.assertEqual(payload["files"][0]["path"], "src/main/python/app.py")
        self.assertEqual(payload["files"][0]["languages"], ["python"])
        self.assertEqual(payload["files"][0]["roles"], ["source"])
        self.assertEqual(payload["files"][0]["confidence"], "manual")
        self.assertNotIn("content_hash", stdout)
        self.assertEqual(entrypoints_exit, 0, entrypoints_stderr)
        entrypoints_payload = json.loads(entrypoints_stdout)
        self.assertEqual(entrypoints_payload["command"], "graph-files")
        self.assertEqual(entrypoints_payload["pagination"]["returned"], 1)
        self.assertEqual(entrypoints_payload["files"][0]["path"], "bin/tool")
        self.assertEqual(entrypoints_payload["files"][0]["roles"], ["entrypoint"])
        self.assertEqual(
            entrypoints_payload["files"][0]["observation_state"],
            "observed",
        )
        self.assertNotIn("content_hash", entrypoints_stdout)

    def test_ops_graph_files_cli_bounds_psql_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            failing_psql = home / "psql"
            failing_psql.write_text(
                "#!/bin/sh\n"
                "echo connection refused at /private/synthetic/socket >&2\n"
                "exit 2\n"
            )
            failing_psql.chmod(0o755)
            (home / "repomap.rpl.toml").write_text(
                '''schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[postgres]
host = "/public/socket"
port = 5432
database = "repomap_test"
user = "repo_map_test"
password_env = "PUBLIC_SAFE_PASSWORD"
[[graphs]]
id = "fixture"
name = "Fixture"
root_path = "/public/fixture"
repository_name = "fixture"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
[server_memory]
enabled = false
path = "./public-server-memory"
mode = "read_only"
''',
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    PG_CONNECTOR_ENV: "psql",
                    READBACK_DRIVER_ENV: "psql",
                },
            ):
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "ops",
                    "graph-files",
                    "--repo-map-home",
                    str(home),
                    "--graph",
                    "fixture",
                    "--psql-command",
                    str(failing_psql),
                    "--json",
                )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("graph 'fixture' file readback failed", stderr)
        self.assertNotIn("connection refused", stderr)
        self.assertNotIn(str(failing_psql), stderr)
    def test_storage_load_files_cli_uses_staged_connection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            raw_jsonl.write_text("")
            bad_json_psql = Path(tmpdir) / "psql"
            bad_json_psql.write_text(
                "#!/bin/sh\n"
                "echo '{bad json}'\n"
                "exit 0\n"
            )
            bad_json_psql.chmod(0o755)

            exit_code, stdout, stderr = run_repo_map_in_process(
                "storage",
                "load-files",
                str(raw_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
                "--psql-command",
                str(bad_json_psql),
                "--json",
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("staged PostgreSQL connection failed", stderr)
        self.assertNotIn("load summary", stderr)
        self.assertNotIn(str(bad_json_psql), stderr)
