import json
import zipfile
from io import BytesIO
from pathlib import Path

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.observations.raw import RawObservation

ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink"'
)

CANONICAL_FIXTURE_ROOT = Path(__file__).parents[3] / "fixtures" / "canonicalization"

def raw_fixture_records(name):
    fixture_path = CANONICAL_FIXTURE_ROOT / name / "raw_observations.jsonl"
    return [
        json.loads(line)
        for line in fixture_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

def expected_graph_fixture(name):
    fixture_path = CANONICAL_FIXTURE_ROOT / name / "expected_canonical_graph.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))

def canonicalize_fixture_payload(name):
    observations = [
        RawObservation.from_dict(record) for record in raw_fixture_records(name)
    ]
    return canonicalize_observations(observations).to_dict()

def odf_package(parts):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, content in parts.items():
            package.writestr(name, content.encode("utf-8"))
    return buffer.getvalue()

def odf_spreadsheet_content():
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {ODF_NS}>
  <office:body>
    <office:spreadsheet>
      <table:table table:name="Budget">
        <table:table-row>
          <table:table-cell><text:p>item</text:p></table:table-cell>
          <table:table-cell><text:p>amount</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>hosting</text:p></table:table-cell>
          <table:table-cell office:value-type="float" office:value="12.5"><text:p>12.5</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>
"""

def odf_text_content():
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {ODF_NS}>
  <office:body>
    <office:text>
      <text:h text:outline-level="1">Overview</text:h>
      <text:p><text:a xlink:href="https://example.com/odf">link</text:a></text:p>
    </office:text>
  </office:body>
</office:document-content>
"""
