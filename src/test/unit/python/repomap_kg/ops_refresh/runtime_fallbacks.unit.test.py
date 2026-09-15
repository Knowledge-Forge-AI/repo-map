import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.ops_refresh import (
    OpsRefreshUnitTestCase,
)

from repomap_kg.runtime.local import LocalRuntimeIdentity
from repomap_kg.ops.refresh import (
    query_graph_summary,
    query_refresh_status,
    run_storage_readback_with_ops_psql,
)
from repomap_kg.storage import StorageSchemaError


class OpsRefreshRuntimeFallbackUnitTests(OpsRefreshUnitTestCase):
    def test_query_refresh_status_uses_normal_psql_when_no_container_fallback_needed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_for_roots(root)

            with patch(
                "repomap_kg.ops.refresh.execute_ops_json_readback"
            ) as execute_readback:
                execute_readback.side_effect = [
                    {"connected": True, "schema_available": True},
                    {"graphs": []},
                ]
                query_refresh_status(config, graph_ids=["repo-map"])

        self.assertEqual(execute_readback.call_count, 2)
        self.assertIsNone(execute_readback.call_args_list[0].kwargs["psql_command"])

    def test_query_refresh_status_does_not_inspect_container_when_host_psql_works(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_home_for_roots(Path(tmpdir) / "home", root)

            with (
                patch(
                    "repomap_kg.ops.refresh.execute_ops_json_readback"
                ) as execute_readback,
                patch(
                    "repomap_kg.ops.readback._container_psql_execution",
                    side_effect=AssertionError("container fallback should be lazy"),
                ),
            ):
                execute_readback.side_effect = [
                    {"connected": True, "schema_available": True},
                    {"graphs": []},
                ]
                query_refresh_status(config, graph_ids=["repo-map"])

        self.assertEqual(execute_readback.call_count, 2)

    def test_query_refresh_status_explicit_psql_command_override_wins(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            config = self.config_home_for_roots(Path(tmpdir) / "home", root)

            with (
                patch(
                    "repomap_kg.ops.refresh.execute_ops_json_readback"
                ) as execute_readback,
                patch(
                    "repomap_kg.ops.readback._container_psql_execution",
                    side_effect=AssertionError("container fallback should not inspect"),
                ),
            ):
                execute_readback.side_effect = [
                    {"connected": True, "schema_available": True},
                    {"graphs": []},
                ]
                query_refresh_status(
                    config,
                    graph_ids=["repo-map"],
                    psql_command="/bin/psql",
                )

        self.assertEqual(
            execute_readback.call_args_list[0].kwargs["psql_command"],
            "/bin/psql",
        )

    def test_query_refresh_status_falls_back_to_owned_runtime_container(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            home = Path(tmpdir) / "home"
            config = self.config_home_for_roots(home, root)
            identity = LocalRuntimeIdentity.from_home(home)

            class ContainerStatus:
                exists = True
                owned = True
                status = "running"
                diagnostic = None

            docker_results = [
                {"connected": True, "schema_available": True},
                {"graphs": [{"graph_id": "repo-map", "repository_exists": True, "latest_run_id": 41, "raw_observations": 5, "canonical_nodes": 4, "canonical_edges": 3}]},
            ]

            def fake_readback(sql, **kwargs):
                if kwargs["psql_command"] == "psql":
                    raise StorageSchemaError(
                        'could not translate host name "postgres" to address'
                    )
                self.assertEqual(
                    list(kwargs["psql_args"][:4]),
                    ["exec", "-i", identity.postgres_container, "psql"],
                )
                return docker_results.pop(0)

            with (
                patch(
                    "repomap_kg.ops.readback.execute_json_readback_with_driver",
                    side_effect=fake_readback,
                ) as execute_readback,
                patch(
                    "repomap_kg.ops.readback.selected_json_readback_driver",
                    return_value="psql",
                ),
                patch(
                    "repomap_kg.ops.readback.shutil.which",
                    return_value="/usr/bin/docker",
                ),
                patch(
                    "repomap_kg.runtime.local.inspect_container",
                    return_value=ContainerStatus(),
                ),
            ):
                statuses = query_refresh_status(config, graph_ids=["repo-map"])

        self.assertEqual(statuses["repo-map"].latest_run_id, 41)
        self.assertEqual(statuses["repo-map"].raw_observations, 5)
        self.assertEqual(execute_readback.call_count, 4)

    def test_query_refresh_status_rejects_unowned_runtime_container(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            home = Path(tmpdir) / "home"
            config = self.config_home_for_roots(home, root)

            class ContainerStatus:
                exists = True
                owned = False
                status = "running"
                diagnostic = None

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
                patch(
                    "repomap_kg.ops.readback.shutil.which",
                    return_value="/usr/bin/docker",
                ),
                patch(
                    "repomap_kg.runtime.local.inspect_container",
                    return_value=ContainerStatus(),
                ),
            ):
                statuses = query_refresh_status(config, graph_ids=["repo-map"])

        self.assertEqual(execute_readback.call_count, 1)
        self.assertIn(
            "RepoMap-owned Postgres container",
            statuses["repo-map"].error or "",
        )

    def test_query_graph_summary_falls_back_to_owned_runtime_container(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            home = Path(tmpdir) / "home"
            config = self.config_home_for_roots(home, root)
            identity = LocalRuntimeIdentity.from_home(home)

            class ContainerStatus:
                exists = True
                owned = True
                status = "running"
                diagnostic = None

            docker_results = [
                {"connected": True, "schema_available": True},
                {
                    "repository_exists": True,
                    "latest_run_id": 8,
                    "files": 9,
                    "raw_observations": 10,
                    "canonical_nodes": 11,
                    "canonical_edges": 12,
                },
            ]

            def fake_readback(sql, **kwargs):
                if kwargs["psql_command"] == "psql":
                    raise StorageSchemaError(
                        'could not translate host name "postgres" to address'
                    )
                self.assertEqual(
                    list(kwargs["psql_args"][:4]),
                    ["exec", "-i", identity.postgres_container, "psql"],
                )
                return docker_results.pop(0)

            with (
                patch(
                    "repomap_kg.ops.readback.execute_json_readback_with_driver",
                    side_effect=fake_readback,
                ) as execute_readback,
                patch(
                    "repomap_kg.ops.readback.selected_json_readback_driver",
                    return_value="psql",
                ),
                patch(
                    "repomap_kg.ops.readback.shutil.which",
                    return_value="/usr/bin/docker",
                    create=True,
                ),
                patch(
                    "repomap_kg.runtime.local.inspect_container",
                    return_value=ContainerStatus(),
                    create=True,
                ),
            ):
                summary = query_graph_summary(config, "repo-map")

        self.assertEqual(summary.result, "success")
        self.assertEqual(summary.files, 9)
        self.assertEqual(summary.raw_observations, 10)
        self.assertEqual(execute_readback.call_count, 4)

    def test_storage_readback_falls_back_to_owned_runtime_container(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            home = Path(tmpdir) / "home"
            config = self.config_home_for_roots(home, root)
            identity = LocalRuntimeIdentity.from_home(home)

            class ContainerStatus:
                exists = True
                owned = True
                status = "running"
                diagnostic = None

            calls = []

            def fake_query(psql_args, **kwargs):
                calls.append((list(psql_args), dict(kwargs)))
                if kwargs["psql_command"] == "psql":
                    raise StorageSchemaError(
                        'could not translate host name "postgres" to address'
                    )
                self.assertEqual(kwargs["psql_command"], "docker")
                self.assertEqual(
                    list(psql_args[:4]),
                    ["exec", "-i", identity.postgres_container, "psql"],
                )
                return {"reachable": True}

            with (
                patch(
                    "repomap_kg.ops.readback.shutil.which",
                    return_value="/usr/bin/docker",
                    create=True,
                ),
                patch(
                    "repomap_kg.runtime.local.inspect_container",
                    return_value=ContainerStatus(),
                    create=True,
                ),
            ):
                result = run_storage_readback_with_ops_psql(
                    config,
                    "repomap_repo_map",
                    fake_query,
                    psql_command=None,
                    root_path=str(root),
                )

        self.assertEqual(result, {"reachable": True})
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]["psql_command"], "psql")
        self.assertEqual(calls[1][1]["psql_command"], "docker")
