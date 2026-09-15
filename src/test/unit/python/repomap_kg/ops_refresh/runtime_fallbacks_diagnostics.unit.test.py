import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.ops_refresh import (
    OpsRefreshUnitTestCase,
)

from repomap_kg.ops.refresh import (
    run_storage_readback_with_ops_psql,
)
from repomap_kg.storage import StorageSchemaError


class OpsRefreshRuntimeDiagnosticsUnitTests(OpsRefreshUnitTestCase):
    def test_live_ops3_missing_database_diagnostic_does_not_blame_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            home = Path(tmpdir) / "home"
            config = self.config_home_for_roots(home, root)

            class ContainerStatus:
                exists = True
                owned = True
                status = "running"
                diagnostic = None

            calls = []
            private_path = str(Path.home() / "private-live-ops3")

            def fake_query(psql_args, **kwargs):
                calls.append((list(psql_args), dict(kwargs)))
                if kwargs["psql_command"] == "psql":
                    raise StorageSchemaError(
                        'could not translate host name "postgres" to address'
                    )
                raise StorageSchemaError(
                    "psql failed: FATAL: database "
                    '"repomap_live_ops3" does not exist '
                    f"while reading {private_path} via docker exec psql"
                )

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
                with self.assertRaises(StorageSchemaError) as caught:
                    run_storage_readback_with_ops_psql(
                        config,
                        "repomap_live_ops3",
                        fake_query,
                        psql_command=None,
                        root_path=str(root),
                    )

        message = str(caught.exception)
        self.assertIn("graph database is missing or not initialized", message)
        self.assertNotIn("no running RepoMap-owned Postgres container", message)
        self.assertNotIn("Postgres container", message)
        self.assertNotIn(private_path, message)
        self.assertNotIn("docker exec", message)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]["psql_command"], "psql")
        self.assertEqual(calls[1][1]["psql_command"], "docker")

    def test_live_ops3_runtime_unavailable_diagnostic_remains_distinct(self):
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

            def fake_query(psql_args, **kwargs):
                raise StorageSchemaError(
                    'could not translate host name "postgres" to address'
                )

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
                with self.assertRaises(StorageSchemaError) as caught:
                    run_storage_readback_with_ops_psql(
                        config,
                        "repomap_repo_map",
                        fake_query,
                        psql_command=None,
                        root_path=str(root),
                    )

        message = str(caught.exception)
        self.assertIn("no running RepoMap-owned Postgres container", message)
        self.assertIn("Start the local runtime", message)
        self.assertNotIn("graph database is missing or not initialized", message)
