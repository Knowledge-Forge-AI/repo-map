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
    query_refresh_status,
    refresh_status_to_jsonable,
)
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
)

from repomap_test_support.storage_integration import (
    canonicalization_fixture,
)


class StorageMcpRefreshStatusIntegrationTests(unittest.TestCase):
    def test_live_harden2_storage_refresh_status_smoke_combines_finished_at_and_raw_counts(
        self,
    ):
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
                ops_config_path = Path(ops_config_tmpdir) / "live-harden2.local.toml"
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
root_path = "/tmp/live-harden2-fixture"
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

                def load_fixture() -> tuple[int, str, str]:
                    return run_repo_map_in_process(
                        "storage",
                        "load-files",
                        str(raw_jsonl),
                        "--repository-name",
                        "fixture",
                        "--root-path",
                        "/tmp/live-harden2-fixture",
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

                first_exit_code, _first_stdout, first_stderr = load_fixture()
                self.assertEqual(first_exit_code, 0, first_stderr)
                first_summary = query_graph_summary(
                    config,
                    "repo-map",
                    psql_command=postgres.psql_command,
                )
                first_finished_at_stored = postgres.psql_scalar(
                    """
SELECT (status = 'complete' AND finished_at IS NOT NULL)::text
FROM runs
WHERE id = (SELECT max(id) FROM runs);
"""
                )

                second_exit_code, _second_stdout, second_stderr = load_fixture()
                self.assertEqual(second_exit_code, 0, second_stderr)
                second_summary = query_graph_summary(
                    config,
                    "repo-map",
                    psql_command=postgres.psql_command,
                )
                cli_refresh_status = refresh_status_to_jsonable(
                    config,
                    query_refresh_status(
                        config,
                        graph_ids=["repo-map"],
                        psql_command=postgres.psql_command,
                    ),
                    graph_ids=["repo-map"],
                )["graphs"][0]
                second_finished_at_stored = postgres.psql_scalar(
                    """
SELECT (status = 'complete' AND finished_at IS NOT NULL)::text
FROM runs
WHERE id = (SELECT max(id) FROM runs);
"""
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
        self.assertEqual(first_finished_at_stored, "true")
        self.assertEqual(second_finished_at_stored, "true")
        self.assertNotEqual(
            first_payload["latest_run_id"],
            second_payload["latest_run_id"],
        )
        self.assertEqual(first_payload["latest_run_status"], "complete")
        self.assertEqual(second_payload["latest_run_status"], "complete")
        self.assertIsNotNone(first_payload["latest_run_finished_at"])
        self.assertIsNotNone(second_payload["latest_run_finished_at"])
        self.assertEqual(
            first_payload["latest_run_consistency"],
            {"complete_without_finished_at": False},
        )
        self.assertEqual(
            second_payload["latest_run_consistency"],
            {"complete_without_finished_at": False},
        )
        self.assertEqual(
            cli_refresh_status["latest_run_consistency"],
            {"complete_without_finished_at": False},
        )
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
        self.assertGreater(first_payload["canonical_nodes"], 0)
        self.assertGreater(first_payload["canonical_edges"], 0)
        self.assertEqual(
            second_payload["canonical_nodes"],
            first_payload["canonical_nodes"],
        )
        self.assertEqual(
            second_payload["canonical_edges"],
            first_payload["canonical_edges"],
        )

        self.assertEqual(graph_status["graph"]["graph_id"], "repo-map")
        self.assertEqual(refresh_status["graphs"][0]["graph_id"], "repo-map")
        for status_payload in (
            graph_status["storage"],
            refresh_status["graphs"][0],
        ):
            self.assertEqual(status_payload["latest_run_status"], "complete")
            self.assertIsNotNone(status_payload["latest_run_finished_at"])
            self.assertEqual(
                status_payload["latest_run_consistency"],
                {"complete_without_finished_at": False},
            )
            self.assertIn("raw_observations_total", status_payload)
            self.assertIn("latest_run_raw_observations", status_payload)
            self.assertEqual(
                status_payload["raw_observations"],
                expected_latest_raw * 2,
            )
            self.assertEqual(
                status_payload["raw_observations_total"],
                expected_latest_raw * 2,
            )
            self.assertEqual(
                status_payload["latest_run_raw_observations"],
                expected_latest_raw,
            )
            self.assertEqual(
                status_payload["canonical_nodes"],
                first_payload["canonical_nodes"],
            )
            self.assertEqual(
                status_payload["canonical_edges"],
                first_payload["canonical_edges"],
            )
