import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.extractors.documents.office import (
    extract_document_file_observations,
    extract_odf_file_observations,
)
from repomap_kg.observations.raw import RawObservation
from repomap_test_support.canonicalization import (
    odf_package,
    odf_spreadsheet_content,
    odf_text_content,
)


class CanonicalizationDocumentFamilyUnitTests(unittest.TestCase):
    def test_document_text_and_table_observations_define_document_nodes(self):
        observations = (
            *extract_document_file_observations(
                "notes.txt",
                "# Overview\nSee docs/guide.txt\n",
                repository_paths=frozenset({"notes.txt", "docs/guide.txt"}),
            ),
            *extract_document_file_observations(
                "data.csv",
                "name,amount\nalpha,42\n",
            ),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn("document.file:file%3Anotes.txt", node_keys)
        self.assertIn(
            "document.section:file%3Anotes.txt:%2Fsections%2Foverview",
            node_keys,
        )
        self.assertIn("document.table:file%3Adata.csv:%2Ftable", node_keys)
        self.assertIn(
            "document.column:file%3Adata.csv:%2Ftable%2Fcolumns%2Famount",
            node_keys,
        )
        edges = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        self.assertIn(
            ("file:notes.txt", "defines", "document.file:file%3Anotes.txt"),
            edges,
        )
        self.assertIn(
            (
                "document.file:file%3Anotes.txt",
                "defines",
                "document.section:file%3Anotes.txt:%2Fsections%2Foverview",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.table:file%3Adata.csv:%2Ftable",
                "defines",
                "document.column:file%3Adata.csv:%2Ftable%2Fcolumns%2Famount",
            ),
            edges,
        )

    def test_document_references_create_reference_edges(self):
        observations = extract_document_file_observations(
            "paper.tex",
            r"""\section{Intro}
\input{chapter}
\url{https://example.com/paper}
""",
            repository_paths=frozenset({"paper.tex", "chapter.tex"}),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        edges = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        self.assertIn(
            (
                "document.latex_command:file%3Apaper.tex:%2Fcommands%2Finput%3A1",
                "references",
                "file:chapter.tex",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.latex_command:file%3Apaper.tex:%2Fcommands%2Furl%3A2",
                "references",
                "external.url:https%3A%2F%2Fexample.com%2Fpaper",
            ),
            edges,
        )

    def test_odf_observations_define_document_sheet_columns_and_references(self):
        observations = (
            *extract_odf_file_observations(
                "notes.odt",
                odf_package({"content.xml": odf_text_content()}),
            ),
            *extract_odf_file_observations(
                "spreadsheet.ods",
                odf_package({"content.xml": odf_spreadsheet_content()}),
            ),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn("document.file:file%3Anotes.odt", node_keys)
        self.assertIn(
            "document.section:file%3Anotes.odt:%2Fsections%2Foverview",
            node_keys,
        )
        self.assertIn("document.file:file%3Aspreadsheet.ods", node_keys)
        self.assertIn(
            "document.sheet:file%3Aspreadsheet.ods:%2Fsheets%2Fbudget",
            node_keys,
        )
        self.assertIn(
            "document.column:file%3Aspreadsheet.ods:"
            "%2Fsheets%2Fbudget%2Fcolumns%2Famount",
            node_keys,
        )
        edges = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        self.assertIn(
            (
                "document.file:file%3Aspreadsheet.ods",
                "defines",
                "document.sheet:file%3Aspreadsheet.ods:%2Fsheets%2Fbudget",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.sheet:file%3Aspreadsheet.ods:%2Fsheets%2Fbudget",
                "defines",
                "document.column:file%3Aspreadsheet.ods:"
                "%2Fsheets%2Fbudget%2Fcolumns%2Famount",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.section:file%3Anotes.odt:%2Fsections%2Foverview",
                "references",
                "external.url:https%3A%2F%2Fexample.com%2Fodf",
            ),
            edges,
        )

    def test_document_identity_fields_fail_closed(self):
        cases: tuple[tuple[str, dict[str, str], str], ...] = (
            ("document.text_section", {}, "requires pointer"),
            ("document.table_document", {}, "requires pointer"),
            ("document.odf_sheet", {}, "requires pointer"),
            ("document.table_column", {}, "requires pointer"),
            ("document.latex_command", {}, "requires pointer"),
            (
                "document.table_column",
                {"pointer": "/columns/name", "table_key": "file:data.csv"},
                "table_key must be document.table",
            ),
            (
                "document.odf_column",
                {"pointer": "/sheets/main/columns/name", "parent_key": "file:data.ods"},
                "parent_key must be document.table or document.sheet",
            ),
            (
                "document.text_document",
                {"document_key": "file:notes.txt"},
                "document_key must be document.file",
            ),
        )

        for index, (kind, metadata, expected_message) in enumerate(cases):
            with self.subTest(kind=kind, metadata=metadata):
                observation = RawObservation(
                    kind=kind,
                    source_id=f"document-boundary-{index}",
                    path="notes.txt",
                    confidence="heuristic",
                    extractor="repo-document",
                    extractor_version="0.1.0",
                    metadata=metadata,
                )

                payload = canonicalize_observations([observation]).to_dict()

                self.assertEqual(payload["summary"]["errors"], 1)
                self.assertEqual(payload["summary"]["nodes"], 0)
                self.assertIn(expected_message, payload["diagnostics"][0]["message"])

    def test_document_references_preserve_closed_source_namespaces(self):
        source_keys = (
            "document.file:file%3Anotes.txt",
            "document.section:file%3Anotes.txt:%2Foverview",
            "document.table:file%3Anotes.txt:%2Ftable",
            "document.sheet:file%3Anotes.txt:%2Fsheet",
            "document.column:file%3Anotes.txt:%2Fcolumn",
            "document.latex_command:file%3Anotes.txt:%2Fcommand",
        )
        observations = [
            RawObservation(
                kind="document.reference",
                source_id=f"document-reference-{index}",
                path="notes.txt",
                target="file:guide.txt",
                confidence="heuristic",
                extractor="repo-document",
                extractor_version="0.1.0",
                metadata={
                    "source_key": source_key,
                    "reference_kind": "relative-file",
                    "redacted": False,
                    "not_fetched": True,
                },
            )
            for index, source_key in enumerate(source_keys)
        ]
        observations.extend(
            (
                RawObservation(
                    kind="document.reference",
                    source_id="document-reference-missing",
                    path="notes.txt",
                    confidence="heuristic",
                    extractor="repo-document",
                    extractor_version="0.1.0",
                    metadata={},
                ),
                RawObservation(
                    kind="document.reference",
                    source_id="document-reference-malformed",
                    path="notes.txt",
                    target="not a canonical key",
                    confidence="heuristic",
                    extractor="repo-document",
                    extractor_version="0.1.0",
                    metadata={},
                ),
            )
        )

        payload = canonicalize_observations(observations).to_dict()
        reference_edges = {
            (edge["source_key"], edge["target_key"])
            for edge in payload["edges"]
            if edge["kind"] == "references"
        }

        self.assertTrue(payload["ok"])
        self.assertTrue(
            all((source_key, "file:guide.txt") in reference_edges for source_key in source_keys)
        )
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(
            {diagnostic["placeholder_key"] for diagnostic in payload["diagnostics"]},
            {
                "unknown:document.reference:missing-target",
                "unknown:document.reference:malformed-target",
            },
        )
        edge = next(
            edge
            for edge in payload["edges"]
            if edge["source_key"] == source_keys[0]
            and edge["target_key"] == "file:guide.txt"
        )
        self.assertEqual(edge["metadata"]["redacted_observed"], False)
        self.assertEqual(edge["metadata"]["not_fetched"], True)

    def test_document_parse_error_is_evidence_only(self):
        observations = extract_document_file_observations(
            "bad.csv",
            "name,amount\nalpha,1\nbeta,2,extra\n",
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 1)
