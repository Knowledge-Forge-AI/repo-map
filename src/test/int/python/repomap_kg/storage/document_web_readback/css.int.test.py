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


class StorageCssReadbackIntegrationTests(unittest.TestCase):
    def test_storage_loads_static_css_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("css_static_basic")

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
                        "css-static-fixture",
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
                    "css.document"
                )
                rule_exit, rule_stdout, rule_stderr = canonical_nodes("css.rule")
                selector_exit, selector_stdout, selector_stderr = canonical_nodes(
                    "css.selector"
                )
                custom_exit, custom_stdout, custom_stderr = canonical_nodes(
                    "css.custom_property"
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
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        (
                            "css.rule:"
                            "file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:"
                            "%2Frule%3A2"
                        ),
                        "--kind",
                        "references",
                        "--target-key",
                        "file:tools/test/assets/panel.svg",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("fixture-secret-token", discover_stdout)
        self.assertNotIn("PHNlY3JldD4=", discover_stdout)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "file",
                "css.document",
                "css.rule",
                "css.selector",
                "css.declaration",
                "css.custom_property",
                "css.reference",
                "css.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertIn(
            "css.document:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css",
            document_keys,
        )

        self.assertEqual(rule_exit, 0, rule_stderr)
        rule_keys = {record["canonical_key"] for record in json.loads(rule_stdout)}
        self.assertIn(
            "css.rule:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:%2Frule%3A2",
            rule_keys,
        )

        self.assertEqual(selector_exit, 0, selector_stderr)
        selector_keys = {
            record["canonical_key"]
            for record in json.loads(selector_stdout)
        }
        self.assertIn(
            (
                "css.selector:"
                "file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:"
                "%2Frule%3A3%2Fselector%3A9"
            ),
            selector_keys,
        )

        self.assertEqual(custom_exit, 0, custom_stderr)
        custom_keys = {
            record["canonical_key"]
            for record in json.loads(custom_stdout)
        }
        self.assertIn(
            "css.custom_property:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:--surface",
            custom_keys,
        )
        self.assertIn(
            "css.custom_property:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:--api-token",
            custom_keys,
        )

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn(
            "css.document:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css",
            define_targets,
        )
        self.assertIn(
            "css.custom_property:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:--surface",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_targets = {
            record["target_key"]
            for record in json.loads(references_stdout)
        }
        self.assertIn("file:tools/test/report/static/reset.css", reference_targets)
        self.assertIn("file:tools/test/assets/panel.svg", reference_targets)
        self.assertIn("unknown:file:repo-escaping-css-reference", reference_targets)
        self.assertIn("dynamic:file:css-url-dynamic", reference_targets)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fassets%2Freport.png",
            reference_targets,
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)["result"]
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            explanation["edge"]["target_key"],
            "file:tools/test/assets/panel.svg",
        )
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "css.reference",
        )
        self.assertNotIn("fixture-secret-token", explain_stdout)
        self.assertNotIn("PHNlY3JldD4=", explain_stdout)

    def test_storage_loads_css_html_selector_matches_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("css_html_matching_basic")

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
                        "css-html-matching-fixture",
                        *storage_args,
                        "--json",
                    )
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

                styles_exit, styles_stdout, styles_stderr = canonical_edges("styles")
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        (
                            "css.selector:"
                            "file%3Astatic%2Freport.css:"
                            "%2Frule%3A1%2Fselector%3A1"
                        ),
                        "--kind",
                        "styles",
                        "--target-key",
                        (
                            "html.element:"
                            "file%3Aindex.html:"
                            "%2Fhtml%2Fbody%2Fheader%2Fspan"
                        ),
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        self.assertIn(
            "css.selector_match",
            {record["kind"] for record in discovered},
        )
        self.assertFalse(
            any(
                record["kind"] == "css.selector_match"
                and record["metadata"]["css_file"] == "static/unlinked.css"
                for record in discovered
            )
        )
        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(styles_exit, 0, styles_stderr)
        style_edges = json.loads(styles_stdout)
        style_pairs = {
            (record["source_key"], record["target_key"])
            for record in style_edges
        }
        self.assertIn(
            (
                (
                    "css.selector:"
                    "file%3Astatic%2Freport.css:"
                    "%2Frule%3A1%2Fselector%3A1"
                ),
                (
                    "html.element:"
                    "file%3Aindex.html:"
                    "%2Fhtml%2Fbody%2Fheader%2Fspan"
                ),
            ),
            style_pairs,
        )
        self.assertTrue(
            all(record["metadata"]["not_runtime_style_observed"] for record in style_edges)
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)["result"]
        self.assertEqual(explanation["edge"]["edge_kind"], "styles")
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "css.selector_match",
        )
        self.assertTrue(explanation["edge"]["metadata"]["not_runtime_style_observed"])
