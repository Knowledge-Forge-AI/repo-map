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


class StorageDocumentReadbackIntegrationTests(unittest.TestCase):
    def test_storage_loads_docs1_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("docs_text_table_basic")

        discover_exit_code, discover_stdout, discover_stderr = run_repo_map_in_process(
            "discover", str(fixture_root), "--jsonl",
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
                load_exit_code, _load_stdout, load_stderr = run_repo_map_in_process(
                    "storage", "load-files", jsonl_file.name,
                    "--repository-name", "docs1-fixture",
                    *storage_args, "--json",
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
                    "document.file"
                )
                section_exit, section_stdout, section_stderr = canonical_nodes(
                    "document.section"
                )
                table_exit, table_stdout, table_stderr = canonical_nodes(
                    "document.table"
                )
                column_exit, column_stdout, column_stderr = canonical_nodes(
                    "document.column"
                )
                command_exit, command_stdout, command_stderr = canonical_nodes(
                    "document.latex_command"
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
                        "document.latex_command:file%3Apaper.tex:%2Fcommands%2Finput%3A2",
                        "--kind",
                        "references",
                        "--target-key",
                        "file:chapter.tex",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("docs1-sensitive-secret", discover_stdout)
        self.assertNotIn("acct-docs1-redacted", discover_stdout)
        discovered_kinds = {
            json.loads(line)["kind"]
            for line in discover_stdout.splitlines()
            if line.strip()
        }
        self.assertTrue(
            {
                "document.text_document",
                "document.text_section",
                "document.table_document",
                "document.table_column",
                "document.latex_document",
                "document.latex_section",
                "document.latex_command",
                "document.reference",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {record["canonical_key"] for record in json.loads(document_stdout)}
        self.assertIn("document.file:file%3Anotes.txt", document_keys)
        self.assertIn("document.file:file%3Adata.csv", document_keys)
        self.assertIn("document.file:file%3Apaper.tex", document_keys)

        self.assertEqual(section_exit, 0, section_stderr)
        section_keys = {record["canonical_key"] for record in json.loads(section_stdout)}
        self.assertIn(
            "document.section:file%3Anotes.txt:%2Fsections%2Foverview",
            section_keys,
        )
        self.assertIn(
            "document.section:file%3Apaper.tex:%2Fsections%2F1-intro",
            section_keys,
        )

        self.assertEqual(table_exit, 0, table_stderr)
        table_keys = {record["canonical_key"] for record in json.loads(table_stdout)}
        self.assertIn("document.table:file%3Adata.csv:%2Ftable", table_keys)

        self.assertEqual(column_exit, 0, column_stderr)
        column_payload = json.loads(column_stdout)
        column_keys = {record["canonical_key"] for record in column_payload}
        self.assertIn(
            "document.column:file%3Adata.csv:%2Ftable%2Fcolumns%2Famount",
            column_keys,
        )
        self.assertTrue(
            any(record["metadata"].get("redacted") for record in column_payload)
        )

        self.assertEqual(command_exit, 0, command_stderr)
        command_keys = {record["canonical_key"] for record in json.loads(command_stdout)}
        self.assertIn(
            "document.latex_command:file%3Apaper.tex:%2Fcommands%2Finput%3A2",
            command_keys,
        )

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {record["target_key"] for record in json.loads(defines_stdout)}
        self.assertIn("document.file:file%3Anotes.txt", define_targets)
        self.assertIn("document.table:file%3Adata.csv:%2Ftable", define_targets)
        self.assertIn(
            "document.column:file%3Adata.csv:%2Ftable%2Fcolumns%2Famount",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_targets = {
            record["target_key"]
            for record in json.loads(references_stdout)
        }
        self.assertIn("file:chapter.tex", reference_targets)
        self.assertIn("file:figures/diagram.png", reference_targets)
        self.assertIn("file:references.bib", reference_targets)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fpaper",
            reference_targets,
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)["result"]
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "document.reference",
        )
        self.assertNotIn("docs1-sensitive-secret", explain_stdout)
        self.assertNotIn("acct-docs1-redacted", explain_stdout)

    def test_storage_loads_docs2_odf_discovery_into_canonical_readback(self):
        require_postgres_binaries()
        fixture_root = discovery_fixture("docs_odf_basic")

        discover_exit_code, discover_stdout, discover_stderr = run_repo_map_in_process(
            "discover", str(fixture_root), "--jsonl",
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
                load_exit_code, _load_stdout, load_stderr = run_repo_map_in_process(
                    "storage", "load-files", jsonl_file.name,
                    "--repository-name", "docs2-fixture",
                    *storage_args, "--json",
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
                    "document.file"
                )
                section_exit, section_stdout, section_stderr = canonical_nodes(
                    "document.section"
                )
                table_exit, table_stdout, table_stderr = canonical_nodes(
                    "document.table"
                )
                sheet_exit, sheet_stdout, sheet_stderr = canonical_nodes(
                    "document.sheet"
                )
                column_exit, column_stdout, column_stderr = canonical_nodes(
                    "document.column"
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
                        "document.section:file%3Anotes.odt:%2Fsections%2Foverview",
                        "--kind",
                        "references",
                        "--target-key",
                        "external.url:https%3A%2F%2Fexample.com%2Fdocs2",
                        "--json",
                    )
                )

        self.assertEqual(discover_exit_code, 0, discover_stderr)
        self.assertNotIn("docs2-sensitive-secret", discover_stdout)
        self.assertNotIn("docs2-cell-secret", discover_stdout)
        discovered_kinds = {
            json.loads(line)["kind"]
            for line in discover_stdout.splitlines()
            if line.strip()
        }
        self.assertTrue(
            {
                "document.odf_document",
                "document.odf_text",
                "document.odf_table",
                "document.odf_sheet",
                "document.odf_column",
                "document.reference",
                "document.parse_error",
            }.issubset(discovered_kinds)
        )

        self.assertEqual(load_exit_code, 0, load_stderr)
        self.assertEqual(document_exit, 0, document_stderr)
        document_keys = {record["canonical_key"] for record in json.loads(document_stdout)}
        self.assertIn("document.file:file%3Anotes.odt", document_keys)
        self.assertIn("document.file:file%3Aspreadsheet.ods", document_keys)

        self.assertEqual(section_exit, 0, section_stderr)
        section_keys = {record["canonical_key"] for record in json.loads(section_stdout)}
        self.assertIn(
            "document.section:file%3Anotes.odt:%2Fsections%2Foverview",
            section_keys,
        )

        self.assertEqual(table_exit, 0, table_stderr)
        table_keys = {record["canonical_key"] for record in json.loads(table_stdout)}
        self.assertIn("document.table:file%3Anotes.odt:%2Ftables%2Ftasks", table_keys)

        self.assertEqual(sheet_exit, 0, sheet_stderr)
        sheet_keys = {record["canonical_key"] for record in json.loads(sheet_stdout)}
        self.assertIn(
            "document.sheet:file%3Aspreadsheet.ods:%2Fsheets%2Fbudget",
            sheet_keys,
        )

        self.assertEqual(column_exit, 0, column_stderr)
        column_payload = json.loads(column_stdout)
        column_keys = {record["canonical_key"] for record in column_payload}
        self.assertIn(
            "document.column:file%3Aspreadsheet.ods:"
            "%2Fsheets%2Fbudget%2Fcolumns%2Famount",
            column_keys,
        )
        self.assertTrue(
            any(record["metadata"].get("redacted") for record in column_payload)
        )

        self.assertEqual(defines_exit, 0, defines_stderr)
        define_targets = {record["target_key"] for record in json.loads(defines_stdout)}
        self.assertIn("document.file:file%3Anotes.odt", define_targets)
        self.assertIn(
            "document.sheet:file%3Aspreadsheet.ods:%2Fsheets%2Fbudget",
            define_targets,
        )

        self.assertEqual(references_exit, 0, references_stderr)
        reference_targets = {
            record["target_key"]
            for record in json.loads(references_stdout)
        }
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs2",
            reference_targets,
        )
        self.assertIn(
            "unknown:document.reference:odf-internal-package-part",
            reference_targets,
        )

        self.assertEqual(explain_exit, 0, explain_stderr)
        explanation = json.loads(explain_stdout)["result"]
        self.assertEqual(explanation["edge"]["edge_kind"], "references")
        self.assertEqual(
            explanation["evidence"][0]["raw_observation"]["kind"],
            "document.reference",
        )
        self.assertNotIn("docs2-sensitive-secret", explain_stdout)
        self.assertNotIn("docs2-cell-secret", explain_stdout)
