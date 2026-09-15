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


class StorageHtmlReadbackIntegrationTests(unittest.TestCase):
    def test_storage_loads_static_html_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("html_static_basic")

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
                        "html-static-fixture",
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
                    "html.document"
                )
                element_exit, element_stdout, element_stderr = canonical_nodes(
                    "html.element"
                )
                anchor_exit, anchor_stdout, anchor_stderr = canonical_nodes(
                    "html.anchor"
                )

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
                external_explain_exit, external_explain_stdout, external_explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain%2Fa%5B2%5D",
                        "--kind",
                        "references",
                        "--target-key",
                        "external.url:https%3A%2F%2Fexample.com%2Fdocs",
                        "--json",
                    )
                )
                asset_explain_exit, asset_explain_stdout, asset_explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "html.element:file%3Aindex.html:%2Fhtml%2Fhead%2Flink",
                        "--kind",
                        "references",
                        "--target-key",
                        "file:assets/site.css",
                        "--json",
                    )
                )
                form_explain_exit, form_explain_stdout, form_explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain%2Fform",
                        "--kind",
                        "references",
                        "--target-key",
                        "file:submit/login",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("html1-sensitive-password", discover_stdout)
        self.assertNotIn("html1-js-should-not-leak", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "file",
                "html.document",
                "html.element",
                "html.heading",
                "html.link",
                "html.asset",
                "html.form",
                "html.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertIn("html.document:file%3Aindex.html", document_keys)
        self.assertIn("html.document:file%3Abroken.html", document_keys)

        self.assertEqual(element_exit, 0, element_stderr)
        element_keys = {record["canonical_key"] for record in json.loads(element_stdout)}
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain%2Fa%5B2%5D",
            element_keys,
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fsection%2Fp%5B2%5D",
            element_keys,
        )

        self.assertEqual(anchor_exit, 0, anchor_stderr)
        anchor_keys = {record["canonical_key"] for record in json.loads(anchor_stdout)}
        self.assertIn("html.anchor:file%3Aindex.html:welcome", anchor_keys)

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn("html.document:file%3Aindex.html", define_targets)
        self.assertIn("html.anchor:file%3Aindex.html:welcome", define_targets)

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        reference_targets = {record["target_key"] for record in reference_edges}
        self.assertIn("html.anchor:file%3Aindex.html:welcome", reference_targets)
        self.assertIn("file:assets/site.css", reference_targets)
        self.assertIn("file:assets/app.js", reference_targets)
        self.assertIn("file:images/logo.png", reference_targets)
        self.assertIn("file:submit/login", reference_targets)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            reference_targets,
        )
        self.assertIn("external.url:mailto%3Adev%40example.com", reference_targets)
        self.assertIn("dynamic:url:javascript-url", reference_targets)

        self.assertEqual(external_explain_exit, 0, external_explain_stderr)
        external_explanation = json.loads(external_explain_stdout)["result"]
        self.assertEqual(external_explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            external_explanation["evidence"][0]["raw_observation"]["kind"],
            "html.link",
        )

        self.assertEqual(asset_explain_exit, 0, asset_explain_stderr)
        asset_explanation = json.loads(asset_explain_stdout)["result"]
        self.assertEqual(asset_explanation["edge"]["target_key"], "file:assets/site.css")
        self.assertEqual(
            asset_explanation["evidence"][0]["raw_observation"]["kind"],
            "html.asset",
        )

        self.assertEqual(form_explain_exit, 0, form_explain_stderr)
        form_explanation = json.loads(form_explain_stdout)["result"]
        self.assertEqual(form_explanation["edge"]["target_key"], "file:submit/login")
        self.assertEqual(
            form_explanation["evidence"][0]["raw_observation"]["kind"],
            "html.form",
        )
        self.assertNotIn("html1-sensitive-password", form_explain_stdout)
