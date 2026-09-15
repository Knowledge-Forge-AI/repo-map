import json
from typing import TypedDict
import unittest

from repomap_test_support.canonical_contract import (
    DISCOVERY_FIXTURE_ROOT,
    odf_package as _odf_package,
)

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.extractors.documents.office import (
    extract_document_file_observations,
    extract_odf_file_observations,
)
from repomap_kg.observations import RawObservation


class _OdfOptions(TypedDict, total=False):
    max_file_count: int
    max_package_bytes: int
    max_part_bytes: int
    max_total_uncompressed_bytes: int


class CanonicalDocumentsOdfIntegrationTests(unittest.TestCase):
    def test_docs1_text_table_latex_extraction_and_canonicalization_contract(self):
        observations = (
            *extract_document_file_observations(
                "docs/notes.txt",
                """# Paths
Read /Users/example/private.txt
Read ../../outside.txt
Read ${DOCS_ROOT}/dynamic.txt
Read https://example.com/docs.
""",
            ),
            *extract_document_file_observations("empty.csv", "\n"),
            *extract_document_file_observations(
                "numbers.csv",
                "1,2.5\n3,4.5\n",
            ),
            *extract_document_file_observations(
                "secrets.csv",
                "account_number,amount\nacct-docs1-secret,5\n",
            ),
            *extract_document_file_observations(
                "data.tsv",
                "name\tactive\tstarted\nalpha\ttrue\t2026-01-02\n",
            ),
            *extract_document_file_observations(
                "header-only.csv",
                "name,amount\n",
            ),
            *extract_document_file_observations(
                "duplicate-header.csv",
                "name,name\nalpha,beta\n",
            ),
            *extract_document_file_observations(
                "empty-mix.csv",
                "name,amount\nalpha,\nbeta,2\n",
            ),
            *extract_document_file_observations(
                "typed.csv",
                "url,date,answer\nhttps://example.com,2026-01-01,yes\n",
            ),
            *extract_document_file_observations(
                "bad.csv",
                "name,amount\nalpha,1\nbeta,2,extra\n",
            ),
            *extract_document_file_observations(
                "paper.tex",
                r"""\section{Intro} % \input{ignored}
\href{https://example.com/href}
\input{chapter}
\includegraphics{figures/diagram.png}
\bibliography{references}
""",
                repository_paths=frozenset(
                    {
                        "paper.tex",
                        "chapter.tex",
                        "figures/diagram.png",
                        "references.bib",
                    }
                ),
            ),
            *extract_document_file_observations(
                "links.tex",
                r"""\url{ftp://example.com/archive}
\href{mailto:dev@example.com}
""",
            ),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertEqual(extract_document_file_observations("ignored.docx", "x"), ())
        self.assertTrue(result.ok)
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("acct-docs1-secret", serialized)
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn("document.file:file%3Adocs%2Fnotes.txt", node_keys)
        self.assertIn("document.table:file%3Aempty.csv:%2Ftable", node_keys)
        self.assertIn(
            "document.column:file%3Anumbers.csv:%2Ftable%2Fcolumns%2Fcolumn-1",
            node_keys,
        )
        self.assertIn(
            "document.latex_command:file%3Apaper.tex:%2Fcommands%2Fhref%3A1",
            node_keys,
        )
        edges = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        self.assertIn(
            (
                "document.section:file%3Adocs%2Fnotes.txt:%2Fsections%2Fpaths",
                "references",
                "external:file:absolute-document-reference",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.section:file%3Adocs%2Fnotes.txt:%2Fsections%2Fpaths",
                "references",
                "unknown:file:repo-escaping-document-reference",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.section:file%3Adocs%2Fnotes.txt:%2Fsections%2Fpaths",
                "references",
                "dynamic:file:dynamic-document-reference",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.latex_command:file%3Apaper.tex:%2Fcommands%2Finput%3A2",
                "references",
                "file:chapter.tex",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.latex_command:file%3Apaper.tex:%2Fcommands%2Fhref%3A1",
                "references",
                "external.url:https%3A%2F%2Fexample.com%2Fhref",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.latex_command:file%3Alinks.tex:%2Fcommands%2Furl%3A1",
                "references",
                "unknown:document.reference:unsupported-scheme",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.latex_command:file%3Alinks.tex:%2Fcommands%2Fhref%3A2",
                "references",
                "external.url:mailto%3Adev%40example.com",
            ),
            edges,
        )
        self.assertEqual(
            [observation.kind for observation in observations].count(
                "document.parse_error"
            ),
            1,
        )

    def test_docs1_canonicalization_diagnostic_contracts(self):
        missing_target = canonicalize_observations(
            [
                RawObservation(
                    kind="document.reference",
                    source_id="notes.txt#missing-target",
                    path="notes.txt",
                    confidence="heuristic",
                    extractor="repo-documents",
                    extractor_version="0.1.0",
                    metadata={"source_key": "document.file:file%3Anotes.txt"},
                )
            ]
        )
        malformed_target = canonicalize_observations(
            [
                RawObservation(
                    kind="document.reference",
                    source_id="notes.txt#malformed-target",
                    path="notes.txt",
                    confidence="heuristic",
                    extractor="repo-documents",
                    extractor_version="0.1.0",
                    target="not a canonical key",
                    metadata={"source_key": "document.file:file%3Anotes.txt"},
                )
            ]
        )
        bad_source = canonicalize_observations(
            [
                RawObservation(
                    kind="document.reference",
                    source_id="notes.txt#bad-source",
                    path="notes.txt",
                    confidence="heuristic",
                    extractor="repo-documents",
                    extractor_version="0.1.0",
                    target="file:target.txt",
                    metadata={"source_key": "config.document:file%3Anotes.txt"},
                )
            ]
        )
        bad_table_parent = canonicalize_observations(
            [
                RawObservation(
                    kind="document.table_column",
                    source_id="data.csv#bad-table-key",
                    path="data.csv",
                    confidence="extracted",
                    extractor="repo-documents",
                    extractor_version="0.1.0",
                    target="document.column:file%3Adata.csv:%2Ftable%2Fcolumns%2Fname",
                    metadata={
                        "pointer": "/table/columns/name",
                        "table_key": "file:data.csv",
                    },
                )
            ]
        )

        self.assertTrue(missing_target.ok)
        self.assertEqual(
            missing_target.graph.edges[0].target_key,
            "unknown:document.reference:missing-target",
        )
        self.assertEqual(
            missing_target.diagnostics[0].category,
            "missing_required_metadata",
        )
        self.assertTrue(malformed_target.ok)
        self.assertEqual(
            malformed_target.graph.edges[0].target_key,
            "unknown:document.reference:malformed-target",
        )
        self.assertFalse(bad_source.ok)
        self.assertEqual(bad_source.diagnostics[0].category, "invalid_canonical_key")
        self.assertFalse(bad_table_parent.ok)
        self.assertEqual(
            bad_table_parent.diagnostics[0].message,
            "document.table_column table_key must be document.table",
        )

    def test_docs2_odf_extraction_and_canonicalization_contract(self):
        fixture = DISCOVERY_FIXTURE_ROOT / "docs_odf_basic"
        observations = (
            *extract_odf_file_observations(
                "notes.odt",
                (fixture / "notes.odt").read_bytes(),
            ),
            *extract_odf_file_observations(
                "spreadsheet.ods",
                (fixture / "spreadsheet.ods").read_bytes(),
            ),
            *extract_odf_file_observations(
                "template.ott",
                (fixture / "template.ott").read_bytes(),
            ),
            *extract_odf_file_observations(
                "sheet-template.ots",
                (fixture / "sheet-template.ots").read_bytes(),
            ),
            *extract_odf_file_observations(
                "malformed.odt",
                (fixture / "malformed.odt").read_bytes(),
            ),
            *extract_odf_file_observations(
                "dangerous.odt",
                (fixture / "dangerous.odt").read_bytes(),
            ),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("docs2-sensitive-secret", serialized)
        self.assertNotIn("docs2-cell-secret", serialized)
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn("document.file:file%3Anotes.odt", node_keys)
        self.assertIn(
            "document.section:file%3Anotes.odt:%2Fsections%2Foverview",
            node_keys,
        )
        self.assertIn(
            "document.table:file%3Anotes.odt:%2Ftables%2Ftasks",
            node_keys,
        )
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
                "external.url:https%3A%2F%2Fexample.com%2Fdocs2",
            ),
            edges,
        )
        self.assertEqual(
            [observation.kind for observation in observations].count(
                "document.parse_error"
            ),
            2,
        )

    def test_docs2_odf_package_safety_contracts(self):
        safe_content = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<office:document-content '
            b'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            b'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            b"<office:body><office:text><text:p>Fixture</text:p></office:text>"
            b"</office:body></office:document-content>"
        )

        self.assertEqual(extract_odf_file_observations("ignored.docx", b"not-odf"), ())

        cases: tuple[tuple[str, bytes, _OdfOptions, str], ...] = (
            ("missing-content.odt", _odf_package({"meta.xml": safe_content}), {}, "missing-content-xml"),
            ("traversal.odt", _odf_package({"content.xml": safe_content, "../outside.xml": b"x"}), {}, "zip-path-traversal"),
            ("absolute.odt", _odf_package({"content.xml": safe_content, "/absolute.xml": b"x"}), {}, "zip-path-traversal"),
            (
                "dangerous.odt",
                _odf_package(
                    {
                        "content.xml": (
                            b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
                            b"<office:document-content />"
                        )
                    }
                ),
                {},
                "dangerous-xml",
            ),
            (
                "file-count.odt",
                _odf_package({"content.xml": safe_content, "styles.xml": b"<styles />"}),
                {"max_file_count": 1},
                "zip-file-count-limit",
            ),
            ("package-size.odt", _odf_package({"content.xml": safe_content}), {"max_package_bytes": 8}, "zip-package-size-limit"),
            ("part-size.odt", _odf_package({"content.xml": safe_content}), {"max_part_bytes": 8}, "zip-part-size-limit"),
            ("total-size.odt", _odf_package({"content.xml": safe_content}), {"max_total_uncompressed_bytes": 8}, "zip-uncompressed-limit"),
        )

        for path, package_bytes, options, error_kind in cases:
            with self.subTest(path=path):
                observations = extract_odf_file_observations(
                    path,
                    package_bytes,
                    **options,
                )

                self.assertEqual(len(observations), 1)
                self.assertEqual(observations[0].kind, "document.parse_error")
                self.assertEqual(observations[0].metadata["error_kind"], error_kind)
                result = canonicalize_observations(observations)
                self.assertTrue(result.ok)
                self.assertEqual(result.to_dict()["summary"]["nodes"], 0)
