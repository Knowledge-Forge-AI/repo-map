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


def _storage_args(fixture_root, postgres):
    return (
        "--root-path", str(fixture_root),
        "--pg-host", str(postgres.socket_dir),
        "--pg-port", str(postgres.port),
        "--pg-user", postgres.user,
        "--pg-database", postgres.database,
        "--psql-command", postgres.psql_command,
    )


class StorageConfigDocumentDomainSummaryIntegrationTests(unittest.TestCase):
    def test_storage_loads_markdown_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("markdown_docs_basic")

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
                storage_args = _storage_args(fixture_root, postgres)
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "markdown-fixture",
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

                page_exit, page_stdout, page_stderr = canonical_nodes("doc.page")
                section_exit, section_stdout, section_stderr = canonical_nodes(
                    "doc.section"
                )
                adr_exit, adr_stdout, adr_stderr = canonical_nodes("doc.adr")
                skill_exit, skill_stdout, skill_stderr = canonical_nodes("doc.skill")

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
                links_exit, links_stdout, links_stderr = canonical_edges("links_to")
                public_links_exit, public_links_stdout, public_links_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "edges",
                        *storage_args,
                        "--kind",
                        "links_to",
                        "--json",
                    )
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "doc.section:file%3AREADME.md:docs-fixture",
                        "--kind",
                        "links_to",
                        "--target-key",
                        "doc.section:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md:decision",
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
                "markdown.document",
                "markdown.heading",
                "markdown.link",
                "markdown.frontmatter",
                "markdown.code_fence",
                "markdown.adr_metadata",
                "markdown.skill_metadata",
            }.issubset(discovered_kinds)
        )
        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(page_exit, 0, page_stderr)
        page_keys = {record["canonical_key"] for record in json.loads(page_stdout)}
        self.assertTrue(
            {
                "doc.page:file%3AREADME.md",
                "doc.page:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md",
                "doc.page:file%3Adocs%2Fskills%2Fexample%2FSKILL.md",
                "doc.page:file%3AAGENTS.md",
            }.issubset(page_keys)
        )
        self.assertEqual(section_exit, 0, section_stderr)
        self.assertIn(
            "doc.section:file%3AREADME.md:docs-fixture",
            {record["canonical_key"] for record in json.loads(section_stdout)},
        )
        self.assertEqual(adr_exit, 0, adr_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(adr_stdout)],
            ["doc.adr:0008"],
        )
        self.assertEqual(skill_exit, 0, skill_stderr)
        self.assertEqual(
            [record["canonical_key"] for record in json.loads(skill_stdout)],
            ["doc.skill:example"],
        )

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {record["target_key"] for record in json.loads(defines_stdout)}
        self.assertIn("doc.page:file%3AREADME.md", define_targets)
        self.assertIn("doc.adr:0008", define_targets)
        self.assertIn("doc.skill:example", define_targets)

        self.assertEqual(links_exit, 0, links_stderr)
        link_edges = json.loads(links_stdout)
        self.assertEqual(public_links_exit, 0, public_links_stderr)
        self.assertEqual(json.loads(public_links_stdout)["items"], link_edges)
        self.assertIn(
            (
                "doc.section:file%3AREADME.md:docs-fixture",
                "doc.section:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md:decision",
            ),
            {
                (record["source_key"], record["target_key"])
                for record in link_edges
            },
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {record["target_key"] for record in link_edges},
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)["result"]
        self.assertEqual(explanation["edge"]["edge_kind"], "links_to")
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "markdown.link",
        )
    def test_storage_loads_json_config_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("config_json_basic")

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
                storage_args = _storage_args(fixture_root, postgres)
                load_exit_code, _load_stdout, load_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "load-files",
                        jsonl_file.name,
                        "--repository-name",
                        "config-fixture",
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

                document_exit, document_stdout, document_stderr = (
                    canonical_nodes("config.document")
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
                public_refs_exit, public_refs_stdout, public_refs_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "edges",
                        *storage_args,
                        "--kind",
                        "references",
                        "--json",
                    )
                )
                explain_exit, explain_stdout, explain_stderr = (
                    run_repo_map_in_process(
                        "storage",
                        "explain-canonical-edge",
                        *storage_args,
                        "--source-key",
                        "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
                        "--kind",
                        "references",
                        "--target-key",
                        "tool:repomap-kg",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        discovered = [
            json.loads(line)
            for line in discover_stdout.splitlines()
            if line.strip()
        ]
        discovered_kinds = {record["kind"] for record in discovered}
        self.assertTrue(
            {
                "config.document",
                "config.path",
                "config.reference",
                "config.jsonl_record",
                "config.parse_error",
            }.issubset(discovered_kinds)
        )
        self.assertNotIn("fixture-secret-placeholder", discover_stdout)

        self.assertEqual(load_exit_code, 0, load_stderr)

        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {
            record["canonical_key"]
            for record in json.loads(document_stdout)
        }
        self.assertTrue(
            {
                "config.document:file%3Aevents.jsonl",
                "config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
                "config.document:file%3Asettings.jsonc",
            }.issubset(document_keys)
        )

        self.assertEqual(path_exit, 0, path_stderr)
        path_keys = {record["canonical_key"] for record in json.loads(path_stdout)}
        self.assertIn(
            "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
            path_keys,
        )
        self.assertIn(
            "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fapi_key",
            path_keys,
        )
        self.assertTrue(all(":0" not in key for key in path_keys))

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {
            record["target_key"]
            for record in json.loads(defines_stdout)
        }
        self.assertIn(
            "config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
            define_targets,
        )
        self.assertIn(
            "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_edges = json.loads(references_stdout)
        self.assertEqual(public_refs_exit, 0, public_refs_stderr)
        self.assertEqual(json.loads(public_refs_stdout)["items"], reference_edges)
        self.assertIn(
            (
                "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:%2Fmcp_servers%2Frepomap%2Fcommand",
                "tool:repomap-kg",
            ),
            {
                (record["source_key"], record["target_key"])
                for record in reference_edges
            },
        )
        self.assertIn(
            "env:REPOMAP_MCP_CONFIG",
            {record["target_key"] for record in reference_edges},
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {record["target_key"] for record in reference_edges},
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)["result"]
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(explanation["edge"]["target_key"], "tool:repomap-kg")
        self.assertEqual(len(explanation["evidence"]), 1)
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "config.reference",
        )
        self.assertNotIn("fixture-secret-placeholder", explain_stdout)
