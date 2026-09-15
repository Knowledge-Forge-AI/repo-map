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


class StoragePlistReadbackIntegrationTests(unittest.TestCase):
    def test_storage_loads_plist_config_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("xml_plist_chrome_policy_basic")

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
                        "plist-config-fixture",
                        *storage_args,
                        "--json",
                    )
                )

                def canonical_nodes(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "nodes",
                        *storage_args,
                        "--kind",
                        kind,
                        "--limit",
                        "200",
                        "--legacy-json-array",
                        "--json",
                    )

                document_exit, document_stdout, document_stderr = canonical_nodes(
                    "config.document"
                )
                path_exit, path_stdout, path_stderr = canonical_nodes("config.path")

                def canonical_edges(kind):
                    return run_repo_map_in_process(
                        "storage",
                        "edges",
                        *storage_args,
                        "--kind",
                        kind,
                        "--limit",
                        "200",
                        "--legacy-json-array",
                        "--json",
                    )

                defines_exit, defines_stdout, defines_stderr = canonical_edges(
                    "defines"
                )
                references_exit, references_stdout, references_stderr = (
                    canonical_edges("references")
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3Achrome-policy.plist:%2FPolicyPath",
                        "--kind",
                        "references",
                        "--target-key",
                        "file:managed/policy.json",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("xml1-fixture-redacted-secret", discover_stdout)
        self.assertNotIn("file:///etc/passwd", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "file",
                "config.document",
                "config.path",
                "config.reference",
                "config.parse_error",
            }.issubset(discovered_kinds)
        )
        self.assertIn("xml.document", discovered_kinds)
        self.assertTrue(
            any(
                record["kind"] == "config.document"
                and record["path"] == "chrome-policy.plist"
                for record in discovered
            )
        )
        self.assertTrue(
            any(
                record["kind"] == "xml.document"
                and record["path"] == "generic.xml"
                for record in discovered
            )
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertIn(
            "config.document:file%3Achrome-policy.plist",
            document_keys,
        )

        self.assertEqual(path_exit, 0, path_stderr)
        path_keys = {record["canonical_key"] for record in json.loads(path_stdout)}
        self.assertIn(
            "config.path:file%3Achrome-policy.plist:%2FPolicyPath",
            path_keys,
        )
        self.assertIn(
            "config.path:file%3Achrome-policy.plist:%2FManagedBookmarks%2FDocs%2Furl",
            path_keys,
        )
        self.assertIn(
            "config.path:file%3Achrome-policy.plist:%2Fapi_key",
            path_keys,
        )
        self.assertTrue(all(":0" not in key for key in path_keys))

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn(
            "config.document:file%3Achrome-policy.plist",
            define_targets,
        )
        self.assertIn(
            "config.path:file%3Achrome-policy.plist:%2FManagedBookmarks%2FDocs%2Furl",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        reference_targets = {record["target_key"] for record in reference_edges}
        self.assertIn("file:managed/policy.json", reference_targets)
        self.assertIn("env:CHROME_POLICY_HOME", reference_targets)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fhome",
            reference_targets,
        )
        self.assertIn(
            "unknown:file:repo-escaping-config-reference",
            reference_targets,
        )
        self.assertIn(
            "external:file:absolute-config-reference",
            reference_targets,
        )
        self.assertIn(
            "dynamic:file:config-reference-expanded-from-variable",
            reference_targets,
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)["result"]
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(explanation["edge"]["target_key"], "file:managed/policy.json")
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "config.reference",
        )
        self.assertNotIn("xml1-fixture-redacted-secret", explain_stdout)
