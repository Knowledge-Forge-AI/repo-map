import json
import unittest
from unittest.mock import patch

from repomap_kg.extractors.documents.office import (
    extract_document_file_observations,
)
from repomap_kg.observations.raw import RawObservation


def by_kind(observations: tuple[RawObservation, ...]) -> dict[str, list[RawObservation]]:
    kinds = dict.fromkeys(observation.kind for observation in observations)
    return {kind: [item for item in observations if item.kind == kind] for kind in kinds}


class DocumentsExtractorUnitTests(unittest.TestCase):
    def test_txt_extracts_document_sections_and_conservative_references(self):
        observations = extract_document_file_observations(
            "notes.txt",
            """# Overview
See docs/guide.txt and https://example.com/reference.

## Local Data
Open data/report.csv.

Token: docs/secret.txt should stay quiet.
""",
            repository_paths=frozenset(
                {"notes.txt", "docs/guide.txt", "data/report.csv"}
            ),
        )
        grouped = by_kind(observations)

        self.assertEqual(grouped["document.text_document"][0].target, "document.file:file%3Anotes.txt")
        self.assertEqual(len(grouped["document.text_section"]), 2)
        targets = {observation.target for observation in grouped["document.reference"]}
        self.assertIn("file:docs/guide.txt", targets)
        self.assertIn("file:data/report.csv", targets)
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Freference",
            targets,
        )
        serialized = "\n".join(observation.to_json_line() for observation in observations)
        self.assertNotIn("docs/secret.txt", serialized)

    def test_csv_extracts_table_columns_type_summaries_and_redacts_secret_columns(self):
        observations = extract_document_file_observations(
            "data.csv",
            """name,amount,password
alpha,42,docs1-secret-value
beta,7,another-secret-value
""",
        )
        grouped = by_kind(observations)

        table = grouped["document.table_document"][0]
        self.assertEqual(table.metadata["format"], "csv")
        self.assertEqual(table.metadata["row_count"], 2)
        self.assertEqual(table.metadata["column_count"], 3)
        columns = {observation.metadata["column_name_summary"]: observation for observation in grouped["document.table_column"]}
        self.assertEqual(columns["amount"].metadata["type_summary"], "integer")
        redacted = next(
            observation
            for observation in grouped["document.table_column"]
            if observation.metadata["redacted"]
        )
        self.assertEqual(redacted.metadata["column_name_summary"], "[redacted]")
        serialized = "\n".join(observation.to_json_line() for observation in observations)
        self.assertNotIn("docs1-secret-value", serialized)
        self.assertNotIn("another-secret-value", serialized)

    def test_tsv_extracts_table_with_tab_delimiter(self):
        observations = extract_document_file_observations(
            "data.tsv",
            "name\tactive\nalpha\ttrue\nbeta\tfalse\n",
        )
        grouped = by_kind(observations)

        self.assertEqual(grouped["document.table_document"][0].metadata["format"], "tsv")
        self.assertEqual(grouped["document.table_document"][0].metadata["delimiter"], "\\t")
        active = next(
            observation
            for observation in grouped["document.table_column"]
            if observation.metadata["column_name_summary"] == "active"
        )
        self.assertEqual(active.metadata["type_summary"], "boolean")

    def test_csv_without_header_uses_structural_column_names(self):
        observations = extract_document_file_observations(
            "numbers.csv",
            "1,2.5\n3,4.5\n",
        )
        grouped = by_kind(observations)

        self.assertFalse(grouped["document.table_document"][0].metadata["header_present"])
        columns = grouped["document.table_column"]
        self.assertEqual(columns[0].metadata["column_name_summary"], "column-1")
        self.assertEqual(columns[0].metadata["type_summary"], "integer")
        self.assertEqual(columns[1].metadata["type_summary"], "decimal")

    def test_empty_csv_emits_empty_table_document(self):
        observations = extract_document_file_observations("empty.csv", "\n")

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].kind, "document.table_document")
        self.assertEqual(observations[0].metadata["row_count"], 0)
        self.assertEqual(observations[0].metadata["column_count"], 0)

    def test_ragged_csv_emits_parse_error_without_table_structure(self):
        observations = extract_document_file_observations(
            "bad.csv",
            "name,amount\nalpha,1\nbeta,2,extra\n",
        )

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].kind, "document.parse_error")
        self.assertEqual(observations[0].metadata["error_kind"], "ragged-row")

    def test_txt_reference_placeholders_for_absolute_repo_escape_and_dynamic_paths(self):
        observations = extract_document_file_observations(
            "docs/notes.txt",
            """# Paths
Read /Users/example/private.txt
Read ../../outside.txt
Read ${DOCS_ROOT}/dynamic.txt
Read http://[not-ipv6
""",
        )
        targets = {
            observation.target
            for observation in observations
            if observation.kind == "document.reference"
        }

        self.assertIn("external:file:absolute-document-reference", targets)
        self.assertIn("unknown:file:repo-escaping-document-reference", targets)
        self.assertIn("dynamic:file:dynamic-document-reference", targets)
        self.assertIn("unknown:external.url:malformed-document-reference", targets)

    def test_latex_extracts_sections_commands_and_static_references_without_compiling(self):
        with patch("subprocess.run") as run:
            observations = extract_document_file_observations(
                "paper.tex",
                r"""\section{Intro}
\label{sec:intro}
\input{chapter}
\includegraphics{figures/diagram.png}
\bibliography{references}
\url{https://example.com/paper}
""",
                repository_paths=frozenset(
                    {
                        "paper.tex",
                        "chapter.tex",
                        "figures/diagram.png",
                        "references.bib",
                    }
                ),
            )

        run.assert_not_called()
        grouped = by_kind(observations)
        self.assertEqual(grouped["document.latex_document"][0].metadata["compiled"], False)
        self.assertEqual(grouped["document.latex_section"][0].metadata["command"], "section")
        commands = {observation.metadata["command"] for observation in grouped["document.latex_command"]}
        self.assertIn("input", commands)
        self.assertIn("includegraphics", commands)
        self.assertIn("bibliography", commands)
        targets = {observation.target for observation in grouped["document.reference"]}
        self.assertIn("file:chapter.tex", targets)
        self.assertIn("file:figures/diagram.png", targets)
        self.assertIn("file:references.bib", targets)
        self.assertIn("external.url:https%3A%2F%2Fexample.com%2Fpaper", targets)

    def test_latex_strips_comments_and_extracts_href_url(self):
        observations = extract_document_file_observations(
            "paper.tex",
            r"""\section{Intro} % \input{ignored}
\href{https://example.com/href}
""",
        )
        grouped = by_kind(observations)

        commands = {observation.metadata["command"] for observation in grouped["document.latex_command"]}
        self.assertNotIn("input", commands)
        self.assertIn("href", commands)
        targets = {observation.target for observation in grouped["document.reference"]}
        self.assertIn("external.url:https%3A%2F%2Fexample.com%2Fhref", targets)

    def test_unsupported_native_formats_are_not_docs1_observations(self):
        self.assertEqual(extract_document_file_observations("ignored.pdf", "%PDF"), ())
        self.assertEqual(
            extract_document_file_observations("ignored.docx", "zip-bytes"),
            (),
        )

    def test_observations_json_does_not_include_secret_table_values(self):
        observations = extract_document_file_observations(
            "secrets.csv",
            "account_number,amount\nacct-very-secret,5\n",
        )

        payload = json.loads("[" + ",".join(item.to_json_line() for item in observations) + "]")
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("acct-very-secret", serialized)



if __name__ == "__main__":
    unittest.main()
