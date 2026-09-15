import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.cli_in_process import run_repo_map_in_process

from repomap_kg.runtime.local import LocalRuntimeIdentity
from repomap_kg.observations import RawObservation
from repomap_kg.storage import (
    StorageSchemaError,
)



class StorageOpsRuntimeFallbackIntegrationTests(unittest.TestCase):
    def test_ops_readback_cli_falls_back_to_owned_runtime_container_with_loopback_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            graph_root = Path(tmpdir) / "repo-map"
            home.mkdir()
            graph_root.mkdir()
            identity = LocalRuntimeIdentity.from_home(home)
            (home / "repomap.rpl.toml").write_text(
                f"""\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[runtime]
container_runtime = "docker"
server_host_port = 55880

[runtime.postgres]
direct_host_port_enabled = false
host_port = 55432
bind_host = "127.0.0.1"

[postgres]
host = "127.0.0.1"
port = 5432
database = "repomap"
user = "admin"
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
database = "repomap_repo_map"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )

            class ContainerStatus:
                exists = True
                owned = True
                status = "running"
                diagnostic = None

            docker_results = [
                '{"connected": true, "schema_available": true}\n',
                (
                    '{"graphs": [{"graph_id": "repo-map", '
                    '"repository_exists": true, "latest_run_id": 1, '
                    '"latest_run_status": "complete", "raw_observations": 7, '
                    '"canonical_nodes": 5, "canonical_edges": 3}]}\n'
                ),
                '{"connected": true, "schema_available": true}\n',
                json.dumps(
                    {
                        "repository_exists": True,
                        "latest_run_id": 1,
                        "latest_run_status": "complete",
                        "files": 2,
                        "raw_observations": 7,
                        "canonical_nodes": 5,
                        "canonical_edges": 3,
                        "language_counts": {"python": 1},
                        "observation_kind_counts": {"file": 2},
                        "canonical_node_kind_counts": {"file": 2},
                        "canonical_edge_kind_counts": {"defines": 1},
                    }
                ),
            ]

            def fake_json_readback(sql, **kwargs):
                if kwargs["psql_command"] == "psql":
                    raise StorageSchemaError(
                        'could not translate host name "postgres" to address'
                    )
                self.assertEqual(
                    list(kwargs["psql_args"][:4]),
                    ["exec", "-i", identity.postgres_container, "psql"],
                )
                return json.loads(docker_results.pop(0))

            with (
                patch(
                    "repomap_kg.ops.refresh.run_psql",
                    side_effect=AssertionError("legacy JSON transport used"),
                ) as run_psql_mock,
                patch(
                    "repomap_kg.ops.readback.execute_json_readback_with_driver",
                    side_effect=fake_json_readback,
                ),
                patch(
                    "repomap_kg.ops.readback.selected_json_readback_driver",
                    return_value="psql",
                ),
                patch("repomap_kg.ops.readback.shutil.which", return_value="/bin/docker"),
                patch(
                    "repomap_kg.runtime.local.inspect_container",
                    return_value=ContainerStatus(),
                ) as inspect_container,
            ):
                status_exit_code, status_stdout, status_stderr = (
                    run_repo_map_in_process(
                        "ops",
                        "refresh-status",
                        "--repo-map-home",
                        str(home),
                        "--graph",
                        "repo-map",
                        "--json",
                    )
                )
                summary_exit_code, summary_stdout, summary_stderr = (
                    run_repo_map_in_process(
                        "ops",
                        "graph-summary",
                        "--repo-map-home",
                        str(home),
                        "--graph",
                        "repo-map",
                        "--json",
                    )
                )

        self.assertEqual(status_exit_code, 0, status_stderr)
        status_payload = json.loads(status_stdout)
        self.assertEqual(status_payload["graphs"][0]["raw_observations"], 7)
        self.assertEqual(summary_exit_code, 0, summary_stderr)
        summary_payload = json.loads(summary_stdout)
        self.assertEqual(summary_payload["graph"]["files"], 2)
        self.assertFalse(summary_payload["safety"]["storage_written"])
        self.assertEqual(inspect_container.call_count, 4)
        run_psql_mock.assert_not_called()
        self.assertEqual(docker_results, [])

    def test_ops_refresh_graph_cli_does_not_fall_back_to_owned_runtime_container(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            graph_root = Path(tmpdir) / "repo-map"
            home.mkdir()
            graph_root.mkdir()
            (home / "repomap.rpl.toml").write_text(
                f"""\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[runtime]
container_runtime = "docker"
server_host_port = 55880

[runtime.postgres]
direct_host_port_enabled = false
host_port = 55432
bind_host = "127.0.0.1"

[postgres]
host = "postgres"
port = 5432
database = "repomap"
user = "admin"
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
database = "repomap_repo_map"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )
            observations = [
                RawObservation(
                    kind="file",
                    source_id="README.md",
                    path="README.md",
                    confidence="extracted",
                    extractor="repo-discovery",
                    extractor_version="0.1.0",
                    metadata={"language": "markdown", "role": "documentation"},
                )
            ]

            class ContainerStatus:
                exists = True
                owned = True
                status = "running"
                diagnostic = None

            with (
                patch(
                    "repomap_kg.ops.refresh.discover_observations",
                    return_value=observations,
                ),
                patch(
                    "repomap_kg.ops.portable_refresh.execute_portable_refresh",
                    side_effect=StorageSchemaError(
                        'could not translate host name "postgres" to address'
                    ),
                ) as staged_refresh_mock,
                patch(
                    "repomap_kg.cli.maintenance_activity_for_home",
                    return_value=nullcontext(),
                ),
                patch("repomap_kg.ops.readback.shutil.which", return_value="/bin/docker"),
                patch(
                    "repomap_kg.runtime.local.inspect_container",
                    return_value=ContainerStatus(),
                ) as inspect_container,
            ):
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "ops",
                    "refresh-graph",
                    "--repo-map-home",
                    str(home),
                    "--graph",
                    "repo-map",
                    "--json",
                )

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(staged_refresh_mock.call_count, 1)
        self.assertEqual(inspect_container.call_count, 0)

    def test_ops_readback_cli_reports_internal_host_without_owned_container(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "repo-map-home"
            graph_root = Path(tmpdir) / "repo-map"
            home.mkdir()
            graph_root.mkdir()
            (home / "repomap.rpl.toml").write_text(
                f"""\
schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[runtime]
container_runtime = "docker"
server_host_port = 55880

[runtime.postgres]
direct_host_port_enabled = false
host_port = 55432
bind_host = "127.0.0.1"

[postgres]
host = "postgres"
port = 5432
database = "repomap"
user = "admin"
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
database = "repomap_repo_map"

[server_memory]
enabled = false
path = "~/.codex/codex-vc/mcp/server-memory"
mode = "read_only"
""",
                encoding="utf-8",
            )

            class ContainerStatus:
                exists = False
                owned = False
                status = "missing"
                diagnostic = "not found"

            with (
                patch(
                    "repomap_kg.ops.readback.execute_json_readback_with_driver",
                    side_effect=StorageSchemaError(
                        'could not translate host name "postgres" to address'
                    ),
                ) as execute_readback,
                patch(
                    "repomap_kg.ops.readback.selected_json_readback_driver",
                    return_value="psql",
                ),
                patch("repomap_kg.ops.readback.shutil.which", return_value="/bin/docker"),
                patch(
                    "repomap_kg.runtime.local.inspect_container",
                    return_value=ContainerStatus(),
                ) as inspect_container,
            ):
                exit_code, stdout, stderr = run_repo_map_in_process(
                    "ops",
                    "refresh-status",
                    "--repo-map-home",
                    str(home),
                    "--graph",
                    "repo-map",
                    "--json",
                )

        self.assertEqual(exit_code, 0, stderr)
        payload = json.loads(stdout)
        error = payload["graphs"][0]["error"]
        self.assertIn("Direct DB host-port exposure is disabled", error)
        self.assertIn("RepoMap-owned Postgres container", error)
        self.assertEqual(execute_readback.call_count, 1)
        self.assertEqual(inspect_container.call_count, 1)
