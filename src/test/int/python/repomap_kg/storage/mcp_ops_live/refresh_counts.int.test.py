import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.refresh import (
    graph_summary_to_jsonable,
    query_graph_summary,
)
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
)

from repomap_test_support.storage_integration import (
    canonicalization_fixture,
)


class StorageMcpRefreshCountIntegrationTests(unittest.TestCase):
    def test_live_ops4_repeated_refresh_count_semantics_are_explicit(self):
        require_postgres_binaries()
        raw_jsonl = canonicalization_fixture(
            "python_package",
            "raw_observations.jsonl",
        )
        expected_latest_raw = sum(
            1 for line in raw_jsonl.read_text(encoding="utf-8").splitlines() if line
        )
        from repomap_kg.server.mcp import repomap_graph_status, repomap_refresh_status

        with temporary_postgres() as postgres:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            with tempfile.TemporaryDirectory() as ops_config_tmpdir:
                ops_config_path = Path(ops_config_tmpdir) / "live-ops4.local.toml"
                ops_config_path.write_text(
                    f"""
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
root_path = "/tmp/live-ops4-fixture"
repository_name = "fixture"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                    encoding="utf-8",
                )
                config = load_ops_config(ops_config_path)

                first_exit_code, _first_stdout, first_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        str(raw_jsonl),
                        "--repository-name",
                        "fixture",
                        "--root-path",
                        "/tmp/live-ops4-fixture",
                        "--pg-host",
                        str(postgres.socket_dir),
                        "--pg-port",
                        str(postgres.port),
                        "--pg-user",
                        postgres.user,
                        "--pg-database",
                        postgres.database,
                        "--psql-command",
                        postgres.psql_command,
                        "--json",
                    )
                )
                self.assertEqual(first_exit_code, 0, first_stderr)
                first_summary = query_graph_summary(
                    config,
                    "repo-map",
                    psql_command=postgres.psql_command,
                )

                second_exit_code, _second_stdout, second_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        str(raw_jsonl),
                        "--repository-name",
                        "fixture",
                        "--root-path",
                        "/tmp/live-ops4-fixture",
                        "--pg-host",
                        str(postgres.socket_dir),
                        "--pg-port",
                        str(postgres.port),
                        "--pg-user",
                        postgres.user,
                        "--pg-database",
                        postgres.database,
                        "--psql-command",
                        postgres.psql_command,
                        "--json",
                    )
                )
                self.assertEqual(second_exit_code, 0, second_stderr)
                second_summary = query_graph_summary(
                    config,
                    "repo-map",
                    psql_command=postgres.psql_command,
                )

                with patch.dict(
                    "os.environ",
                    {
                        "REPOMAP_OPS_CONFIG": str(ops_config_path),
                        "REPOMAP_PSQL_COMMAND": postgres.psql_command,
                    },
                    clear=False,
                ):
                    graph_status = repomap_graph_status(graph_id="repo-map")
                    refresh_status = repomap_refresh_status(graph_id="repo-map")

        first_payload = graph_summary_to_jsonable(config, first_summary)["graph"]
        second_payload = graph_summary_to_jsonable(config, second_summary)["graph"]
        self.assertEqual(first_payload["raw_observations"], expected_latest_raw)
        self.assertEqual(first_payload["raw_observations_total"], expected_latest_raw)
        self.assertEqual(
            first_payload["latest_run_raw_observations"],
            expected_latest_raw,
        )
        self.assertEqual(second_payload["raw_observations"], expected_latest_raw * 2)
        self.assertEqual(
            second_payload["raw_observations_total"],
            expected_latest_raw * 2,
        )
        self.assertEqual(
            second_payload["latest_run_raw_observations"],
            expected_latest_raw,
        )
        self.assertEqual(
            second_payload["latest_run_observation_kind_counts"],
            first_payload["observation_kind_counts"],
        )
        self.assertEqual(
            second_payload["canonical_nodes"],
            first_payload["canonical_nodes"],
        )
        self.assertEqual(
            second_payload["canonical_edges"],
            first_payload["canonical_edges"],
        )
        self.assertEqual(
            graph_status["storage"]["raw_observations_total"],
            expected_latest_raw * 2,
        )
        self.assertEqual(
            graph_status["storage"]["latest_run_raw_observations"],
            expected_latest_raw,
        )
        self.assertEqual(
            refresh_status["graphs"][0]["raw_observations_total"],
            expected_latest_raw * 2,
        )
        self.assertEqual(
            refresh_status["graphs"][0]["latest_run_raw_observations"],
            expected_latest_raw,
        )
