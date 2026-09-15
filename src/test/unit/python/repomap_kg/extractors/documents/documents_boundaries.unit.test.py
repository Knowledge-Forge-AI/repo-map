import unittest
import zipfile
from io import BytesIO
from unittest.mock import patch

from repomap_kg.extractors.documents.office import extract_odf_file_observations
from repomap_kg.observations.raw import RawObservation


def by_kind(observations: tuple[RawObservation, ...]) -> dict[str, list[RawObservation]]:
    kinds = dict.fromkeys(observation.kind for observation in observations)
    return {kind: [item for item in observations if item.kind == kind] for kind in kinds}


ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"'
)


def odf_package(parts, *, compression=zipfile.ZIP_DEFLATED):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as package:
        for name, content in parts.items():
            data = content if isinstance(content, bytes) else content.encode("utf-8")
            package.writestr(name, data)
    return buffer.getvalue()


def odt_content(*, secret_text="password docs2-secret-value"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {ODF_NS}>
  <office:body>
    <office:text>
      <text:h text:outline-level="1">Overview</text:h>
      <text:p>See <text:a xlink:href="https://example.com/docs">docs</text:a>.</text:p>
      <text:p>{secret_text}</text:p>
      <table:table table:name="Tasks">
        <table:table-row>
          <table:table-cell><text:p>Status</text:p></table:table-cell>
          <table:table-cell><text:p>Owner</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>open</text:p></table:table-cell>
          <table:table-cell><text:p>team</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:text>
  </office:body>
</office:document-content>
"""


def ods_content(*, secret_cell="docs2-cell-secret"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {ODF_NS}>
  <office:body>
    <office:spreadsheet>
      <table:table table:name="Budget">
        <table:table-row>
          <table:table-cell><text:p>item</text:p></table:table-cell>
          <table:table-cell><text:p>amount</text:p></table:table-cell>
          <table:table-cell><text:p>api_key</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>hosting</text:p></table:table-cell>
          <table:table-cell office:value-type="float" office:value="12.5"><text:p>12.5</text:p></table:table-cell>
          <table:table-cell><text:p>{secret_cell}</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>total</text:p></table:table-cell>
          <table:table-cell table:formula="of:=SUM([.B2:.B2])"><text:p>12.5</text:p></table:table-cell>
          <table:table-cell/>
        </table:table-row>
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>
"""


def manifest_xml():
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest {ODF_NS}>
  <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="Pictures/local-image.png" manifest:media-type="image/png"/>
</manifest:manifest>
"""


def meta_xml(title="Fixture ODF"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta {ODF_NS}>
  <office:meta>
    <dc:title>{title}</dc:title>
    <meta:keyword>example</meta:keyword>
  </office:meta>
</office:document-meta>
"""


def styles_xml():
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles {ODF_NS}>
  <office:styles>
    <style:style style:name="Heading_20_1"/>
  </office:styles>
</office:document-styles>
"""


class DocumentsExtractorBoundariesUnitTests(unittest.TestCase):
    def test_odt_extracts_headings_tables_and_references_without_body_leakage(self):
        with patch("subprocess.run") as run:
            observations = extract_odf_file_observations(
                "notes.odt",
                odf_package(
                    {
                        "content.xml": odt_content(),
                        "meta.xml": meta_xml(),
                        "styles.xml": styles_xml(),
                        "META-INF/manifest.xml": manifest_xml(),
                    }
                ),
            )

        run.assert_not_called()
        grouped = by_kind(observations)
        document = grouped["document.odf_document"][0]
        self.assertEqual(document.metadata["format"], "odt")
        self.assertFalse(document.metadata["template"])
        self.assertEqual(document.metadata["paragraph_count"], 2)
        self.assertEqual(document.metadata["heading_count"], 1)
        self.assertEqual(document.metadata["table_count"], 1)
        self.assertEqual(grouped["document.odf_text"][0].metadata["heading_summary"], "Overview")
        self.assertEqual(grouped["document.odf_table"][0].metadata["display_name"], "Tasks")
        targets = {observation.target for observation in grouped["document.reference"]}
        self.assertIn("external.url:https%3A%2F%2Fexample.com%2Fdocs", targets)
        self.assertIn("unknown:document.reference:odf-internal-package-part", targets)
        serialized = "\n".join(observation.to_json_line() for observation in observations)
        self.assertNotIn("docs2-secret-value", serialized)

    def test_ods_extracts_sheets_columns_and_does_not_evaluate_formulas(self):
        observations = extract_odf_file_observations(
            "spreadsheet.ods",
            odf_package(
                {
                    "content.xml": ods_content(),
                    "meta.xml": meta_xml("Budget"),
                    "META-INF/manifest.xml": manifest_xml(),
                }
            ),
        )
        grouped = by_kind(observations)

        document = grouped["document.odf_document"][0]
        self.assertEqual(document.metadata["format"], "ods")
        self.assertFalse(document.metadata["template"])
        self.assertEqual(document.metadata["sheet_count"], 1)
        self.assertEqual(document.metadata["formula_count"], 1)
        self.assertFalse(document.metadata["formulas_evaluated"])
        sheet = grouped["document.odf_sheet"][0]
        self.assertEqual(sheet.metadata["display_name"], "Budget")
        self.assertEqual(sheet.metadata["row_count"], 2)
        self.assertEqual(sheet.metadata["column_count"], 3)
        columns = grouped["document.odf_column"]
        self.assertEqual(columns[0].metadata["column_name_summary"], "item")
        self.assertEqual(columns[1].metadata["type_summary"], "decimal")
        redacted = next(column for column in columns if column.metadata["redacted"])
        self.assertEqual(redacted.metadata["column_name_summary"], "[redacted]")
        serialized = "\n".join(observation.to_json_line() for observation in observations)
        self.assertNotIn("docs2-cell-secret", serialized)

    def test_ott_and_ots_are_template_variants(self):
        ott = by_kind(
            extract_odf_file_observations(
                "template.ott",
                odf_package({"content.xml": odt_content(), "META-INF/manifest.xml": manifest_xml()}),
            )
        )["document.odf_document"][0]
        ots = by_kind(
            extract_odf_file_observations(
                "sheet-template.ots",
                odf_package({"content.xml": ods_content(), "META-INF/manifest.xml": manifest_xml()}),
            )
        )["document.odf_document"][0]

        self.assertEqual(ott.metadata["format"], "ott")
        self.assertTrue(ott.metadata["template"])
        self.assertEqual(ots.metadata["format"], "ots")
        self.assertTrue(ots.metadata["template"])

    def test_odf_package_safety_rejects_traversal_dangerous_xml_and_limits(self):
        traversal = extract_odf_file_observations(
            "bad.odt",
            odf_package({"../content.xml": odt_content()}),
        )
        doctype = extract_odf_file_observations(
            "dangerous.odt",
            odf_package({"content.xml": "<!DOCTYPE x [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><x/>"}),
        )
        limited = extract_odf_file_observations(
            "large.odt",
            odf_package({"content.xml": odt_content()}),
            max_total_uncompressed_bytes=10,
        )
        malformed = extract_odf_file_observations("broken.odt", b"not-a-zip")

        self.assertEqual(traversal[0].metadata["error_kind"], "zip-path-traversal")
        self.assertEqual(doctype[0].metadata["error_kind"], "dangerous-xml")
        self.assertEqual(limited[0].metadata["error_kind"], "zip-uncompressed-limit")
        self.assertEqual(malformed[0].metadata["error_kind"], "malformed-zip")

    def test_odf_unsupported_native_formats_are_not_docs2_observations(self):
        package = odf_package({"content.xml": odt_content()})

        self.assertEqual(extract_odf_file_observations("ignored.docx", package), ())
        self.assertEqual(extract_odf_file_observations("ignored.xlsx", package), ())


if __name__ == "__main__":
    unittest.main()
