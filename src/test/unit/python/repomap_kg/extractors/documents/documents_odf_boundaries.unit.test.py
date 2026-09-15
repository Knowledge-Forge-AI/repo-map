import io
import unittest
import zipfile

from repomap_kg.extractors.documents.office_odf import extract_odf_file_observations

class DocumentsOdfBoundariesUnitTests(unittest.TestCase):
    def _create_odf_zip(self, mimetype: str, meta_xml: str, content_xml: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", mimetype)
            zf.writestr("meta.xml", meta_xml)
            zf.writestr("content.xml", content_xml)
            manifest = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">
  <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
</manifest:manifest>"""
            zf.writestr("META-INF/manifest.xml", manifest)
        return buffer.getvalue()

    def test_odf_document_text_extraction(self):
        meta_xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                      xmlns:dc="http://purl.org/dc/elements/1.1/"
                      xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0">
  <office:meta>
    <dc:title>Sample Document</dc:title>
    <dc:creator>Alice Developer</dc:creator>
  </office:meta>
</office:document-meta>"""
        content_xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
                         xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:text>
      <text:h text:outline-level="1">Heading One</text:h>
      <text:p>This is paragraph text in ODF format.</text:p>
      <table:table table:name="Table1">
        <table:table-row>
          <table:table-cell><text:p>Cell 1</text:p></table:table-cell>
          <table:table-cell><text:p>Cell 2</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:text>
  </office:body>
</office:document-content>"""
        raw_bytes = self._create_odf_zip("application/vnd.oasis.opendocument.text", meta_xml, content_xml)
        obs = extract_odf_file_observations("docs/sample.odt", raw_bytes)
        self.assertTrue(len(obs) > 0)
        self.assertEqual(obs[0].kind, "document.odf_document")

    def test_odf_corrupted_archive_fallback(self):
        obs = extract_odf_file_observations("docs/corrupt.odt", b"not-a-valid-zip-file")
        self.assertEqual(obs[0].kind, "document.parse_error")

if __name__ == "__main__":
    unittest.main()
