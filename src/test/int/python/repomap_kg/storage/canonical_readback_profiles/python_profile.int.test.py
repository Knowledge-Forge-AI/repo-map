import json
import tempfile
import unittest

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
)

from repomap_test_support.storage_integration import (
    discovery_fixture,
)


class StoragePythonProfileReadbackIntegrationTests(unittest.TestCase):
    def test_storage_loads_python_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("python_package")

        discover_exit_code, discover_stdout, discover_stderr = (
            run_repo_map_in_process(
                "discover",
                str(fixture_root),
                "--jsonl",
            )
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(discover_stdout)
            jsonl_file.flush()

            with temporary_postgres() as postgres:
                apply_migrations(
                    default_rdbms_root(),
                    postgres.psql_args,
                    psql_command=postgres.psql_command,
                )
                storage_args = (
                    "--root-path",
                    str(fixture_root),
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
                )
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "python-fixture",
                        *storage_args,
                        "--json",
                    )
                )
                nodes_exit_code, nodes_stdout, nodes_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "nodes",
                        *storage_args,
                        "--limit",
                        "200",
                        "--legacy-json-array",
                        "--json",
                    )
                )
                imports_exit_code, imports_stdout, imports_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "edges",
                        *storage_args,
                        "--kind",
                        "imports",
                        "--source-key",
                        "python.module:pkg.app",
                        "--limit",
                        "200",
                        "--legacy-json-array",
                        "--json",
                    )
                )
                public_imports_exit, public_imports_stdout, (
                    public_imports_stderr
                ) = run_repo_map_in_process(
                    "storage",
                    "edges",
                    *storage_args,
                    "--kind",
                    "imports",
                    "--source-key",
                    "python.module:pkg.app",
                    "--limit",
                    "200",
                    "--legacy-json-array",
                    "--json",
                )
                explain_exit_code, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "python.module:pkg.app",
                        "--kind",
                        "imports",
                        "--target-key",
                        "python.module:pkg.lib.helper",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered_kinds = {
            json.loads(line)["kind"]
            for line in discover_stdout.splitlines()
            if line.strip()
        }
        self.assertTrue(
            {
                "file",
                "python.module",
                "python.import",
                "python.class",
                "python.function",
                "python.method",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(nodes_exit_code, 0, nodes_stderr)
        node_keys = {
            record["canonical_key"]
            for record in json.loads(nodes_stdout)
        }
        self.assertTrue(
            {
                "file:src/main/python/pkg/app.py",
                "file:src/main/python/pkg/lib/helper.py",
                "python.module:pkg.app",
                "python.module:pkg.lib.helper",
                "python.class:pkg.app:Service",
                "python.function:pkg.app:build",
                "python.method:pkg.app:Service:run",
                "external:python.module:json",
                "unknown:python.module:missing-module",
            }.issubset(node_keys)
        )

        self.assertEqual(imports_exit_code, 0, imports_stderr)
        import_edges = json.loads(imports_stdout)
        self.assertEqual(
            [record["target_key"] for record in import_edges],
            [
                "external:python.module:json",
                "python.module:pkg.lib.helper",
                "unknown:python.module:missing-module",
            ],
        )
        self.assertTrue(
            all(
                record["source_key"] == "python.module:pkg.app"
                for record in import_edges
            )
        )
        self.assertEqual(public_imports_exit, 0, public_imports_stderr)
        self.assertEqual(json.loads(public_imports_stdout), import_edges)

        self.assertEqual(explain_exit_code, 0, explain_stderr)
        explanation = json.loads(explain_stdout)["result"]
        self.assertEqual(explanation["edge"]["source_key"], "python.module:pkg.app")
        self.assertEqual(explanation["edge"]["edge_kind"], "imports")
        self.assertEqual(
            explanation["edge"]["target_key"],
            "python.module:pkg.lib.helper",
        )
        self.assertEqual(len(explanation["evidence"]), 1)
        evidence = explanation["evidence"][0]
        self.assertEqual(evidence["raw_observation"]["kind"], "python.import")
        self.assertEqual(
            evidence["path"],
            "src/main/python/pkg/app.py",
        )
        self.assertEqual(evidence["start_line"], 1)
