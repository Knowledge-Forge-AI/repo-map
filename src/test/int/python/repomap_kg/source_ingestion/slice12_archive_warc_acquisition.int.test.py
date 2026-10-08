"""Integration tests for Slice 12 archive and WARC acquisition (Group S12-B).

Covers:
- S12-B01: WARC header line alternatives
- S12-B02: HTTP boundary parsing alternative
- S12-B03: HTTP payload route fallback
- S12-B04: WARC filename extension fallback
- S12-B05: Header-value shape through provenance
- S12-B06: WARC target URI alternate form
- S12-B07: WARC target identity fallback
- S12-B08: WARC definition-source fallback
- S12-B09: WARC definition-target fallback
- S12-B10: WARC reference target/source composition
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from repomap_kg.ops.ingestion.source import (
    build_warc_manifest,
    load_warc_source_config,
    warc_observations_from_manifest,
)
from repomap_kg.storage.canonical_rows import prepare_canonical_load
from repomap_test_support.source_ingestion_integration import fixed_clock
from repomap_test_support.test_scratch import select_scratch_root


class Slice12ArchiveWarcAcquisitionIntegrationTests(unittest.TestCase):
    """Slice 12 Group S12-B integration tests for WARC ingestion and canonical evidence."""

    def _write_config(self, directory: Path, path: str = "test.warc") -> Path:
        cfg = directory / f"src_{Path(path).stem}.toml"
        cfg.write_text(
            f"""[source]
id = "{Path(path).stem}"
type = "saved_page.archive"
display_name = "Test WARC"

[policy]
status = "allowed"
max_artifact_bytes = 1048576
max_file_count = 10
max_warc_records = 100
max_record_bytes = 1048576
max_total_payload_bytes = 1048576
retention_policy = "materialize-safe-payloads"
requires_manual_review = false

[artifact]
path = "{path}"
kind = "warc"
profile = "warc-local-archive"
""",
            encoding="utf-8",
        )
        return cfg

    def _build_warc(
        self,
        *,
        target_uri: str = "http://example.com/data",
        content_type: str = "application/json",
        body: bytes = b"{}",
        extra_headers: str = "",
        warc_headers: str = "",
        raw_http: bytes | None = None,
    ) -> bytes:
        if raw_http is None:
            raw_http = (
                b"HTTP/1.1 200 OK\r\n"
                + f"Content-Type: {content_type}\r\n".encode()
                + extra_headers.encode()
                + f"Content-Length: {len(body)}\r\n\r\n".encode()
                + body
            )
        return (
            b"WARC/1.0\r\n"
            b"WARC-Type: response\r\n"
            b"WARC-Record-ID: <urn:uuid:11111111-2222-3333-4444-555555555555>\r\n"
            b"WARC-Date: 2026-09-12T12:00:00Z\r\n"
            + warc_headers.encode()
            + f"WARC-Target-URI: {target_uri}\r\n".encode()
            + b"Content-Type: application/http; msgtype=response\r\n"
            + f"Content-Length: {len(raw_http)}\r\n\r\n".encode()
            + raw_http
            + b"\r\n\r\n"
        )

    def test_s12_b01_warc_header_line_alternatives(self) -> None:
        """Parses headers with leading and trailing whitespace into clean safe headers."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            (root / "b01.warc").write_bytes(
                self._build_warc(warc_headers="ETag   :   \"custom-etag\"   \r\n")
            )
            cfg = self._write_config(root, "b01.warc")
            scfg = load_warc_source_config(cfg)
            m = build_warc_manifest(scfg, root_path=root, clock=fixed_clock)
            self.assertEqual(len(m.records), 1)
            self.assertEqual(m.records[0].safe_headers.get("etag"), "\"custom-etag\"")
            obs = warc_observations_from_manifest(scfg, m, root_path=root)
            load = prepare_canonical_load(obs)
            self.assertTrue(load.result.ok)
            self.assertTrue(any(n.kind == "warc.document" for n in load.canonical_rows.nodes))
            self.assertTrue(len(load.canonical_rows.evidence) >= 1)

    def test_s12_b02_http_boundary_parsing_alternative(self) -> None:
        """Handles HTTP payload with newline delimiter and captures structured observations."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            raw = b"HTTP/1.1 200 OK\nContent-Type: application/json\nContent-Length: 2\n\n{}"
            (root / "b02.warc").write_bytes(self._build_warc(raw_http=raw))
            cfg = self._write_config(root, "b02.warc")
            scfg = load_warc_source_config(cfg)
            m = build_warc_manifest(scfg, root_path=root, clock=fixed_clock)
            self.assertEqual(len(m.records), 1)
            self.assertEqual(m.records[0].extractor_route, "json")
            obs = warc_observations_from_manifest(scfg, m, root_path=root)
            load = prepare_canonical_load(obs)
            self.assertTrue(load.result.ok)
            self.assertTrue(any(n.kind == "warc.document" for n in load.canonical_rows.nodes))
            self.assertTrue(len(load.canonical_rows.evidence) >= 1)

    def test_s12_b03_http_payload_route_fallback(self) -> None:
        """Unsupported MIME type routes to fallback with explicit skip reason."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            (root / "b03.warc").write_bytes(
                self._build_warc(content_type="application/pdf", body=b"%PDF-1.4")
            )
            cfg = self._write_config(root, "b03.warc")
            scfg = load_warc_source_config(cfg)
            m = build_warc_manifest(scfg, root_path=root, clock=fixed_clock)
            self.assertEqual(len(m.records), 1)
            self.assertIsNone(m.records[0].extractor_route)
            self.assertEqual(m.records[0].skip_reason, "metadata-only")
            obs = warc_observations_from_manifest(scfg, m, root_path=root)
            load = prepare_canonical_load(obs)
            self.assertTrue(load.result.ok)
            self.assertTrue(any(n.kind == "warc.document" for n in load.canonical_rows.nodes))

    def test_s12_b04_warc_filename_extension_fallback(self) -> None:
        """XML payload content routes to xml extractor and materializes .xml file."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            (root / "b04.warc").write_bytes(
                self._build_warc(content_type="application/xml", body=b"<feed/>")
            )
            cfg = self._write_config(root, "b04.warc")
            scfg = load_warc_source_config(cfg)
            m = build_warc_manifest(scfg, root_path=root, clock=fixed_clock)
            self.assertEqual(len(m.records), 1)
            self.assertEqual(m.records[0].extractor_route, "xml")
            self.assertTrue(str(m.records[0].materialized_path).endswith(".xml"))
            obs = warc_observations_from_manifest(scfg, m, root_path=root)
            load = prepare_canonical_load(obs)
            self.assertTrue(load.result.ok)
            self.assertTrue(any(n.kind == "warc.document" for n in load.canonical_rows.nodes))

    def test_s12_b05_header_value_shape_through_provenance(self) -> None:
        """Redacts credentials while retaining standard HTTP headers through provenance."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            hdrs = "Authorization: Bearer secret-tok\r\nETag: \"public-etag\"\r\n"
            (root / "b05.warc").write_bytes(self._build_warc(warc_headers=hdrs))
            cfg = self._write_config(root, "b05.warc")
            scfg = load_warc_source_config(cfg)
            m = build_warc_manifest(scfg, root_path=root, clock=fixed_clock)
            safe = m.records[0].safe_headers
            self.assertEqual(safe.get("authorization"), "<redacted>")
            self.assertEqual(safe.get("etag"), "\"public-etag\"")
            obs = warc_observations_from_manifest(scfg, m, root_path=root)
            load = prepare_canonical_load(obs)
            self.assertTrue(load.result.ok)
            self.assertTrue(any(n.kind == "warc.document" for n in load.canonical_rows.nodes))

            # Prove complete absence of secret canary in all downstream rows and observations
            combined_downstream = json.dumps(
                [n.metadata_json for n in load.canonical_rows.nodes]
                + [e.metadata_json for e in load.canonical_rows.evidence]
                + [o.metadata for o in obs]
            )
            self.assertNotIn("secret-tok", combined_downstream)
            self.assertIn("public-etag", combined_downstream)

    def test_s12_b06_warc_target_uri_alternate_form(self) -> None:
        """Sanitizes target URI credentials while preserving port and non-secret query."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            uri = "https://user:pass@example.com:8443/feed?token=sec1&q=search"
            (root / "b06.warc").write_bytes(self._build_warc(target_uri=uri))
            cfg = self._write_config(root, "b06.warc")
            scfg = load_warc_source_config(cfg)
            m = build_warc_manifest(scfg, root_path=root, clock=fixed_clock)
            rec = m.records[0]
            self.assertTrue(rec.target_uri_redacted)
            self.assertIn("example.com:8443", str(rec.target_uri_summary))
            self.assertNotIn("pass", str(rec.target_uri_summary))
            obs = warc_observations_from_manifest(scfg, m, root_path=root)
            load = prepare_canonical_load(obs)
            self.assertTrue(load.result.ok)
            self.assertTrue(any(n.kind == "warc.document" for n in load.canonical_rows.nodes))

            # Downstream credential sanitization and port preservation
            combined_downstream = json.dumps(
                [n.metadata_json for n in load.canonical_rows.nodes]
                + [e.metadata_json for e in load.canonical_rows.evidence]
                + [o.metadata for o in obs]
            )
            self.assertNotIn("pass", combined_downstream)
            self.assertNotIn("sec1", combined_downstream)
            self.assertIn("8443", combined_downstream)
            self.assertIn("example.com:8443", combined_downstream)

    def test_s12_b07_warc_target_identity_fallback(self) -> None:
        """Classifies non-HTTP URN target URI into unsupported-scheme target key."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            (root / "b07.warc").write_bytes(self._build_warc(target_uri="urn:uuid:custom-target-001"))
            cfg = self._write_config(root, "b07.warc")
            scfg = load_warc_source_config(cfg)
            m = build_warc_manifest(scfg, root_path=root, clock=fixed_clock)
            self.assertEqual(m.records[0].target_key, "unknown:warc.target-uri:unsupported-scheme")
            obs = warc_observations_from_manifest(scfg, m, root_path=root)
            load = prepare_canonical_load(obs)
            self.assertTrue(load.result.ok)
            # Downstream verification: node exists for the unsupported-scheme target key
            target_nodes = [
                n for n in load.canonical_rows.nodes
                if n.canonical_key == "unknown:warc.target-uri:unsupported-scheme"
            ]
            self.assertEqual(len(target_nodes), 1)
            self.assertEqual(target_nodes[0].display_name, "unsupported-scheme")

    def test_s12_b08_warc_definition_source_fallback(self) -> None:
        """Derives document definition source key from observation path and canonicalizes."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            (root / "b08.warc").write_bytes(self._build_warc(target_uri="http://example.com/page1"))
            cfg = self._write_config(root, "b08.warc")
            scfg = load_warc_source_config(cfg)
            m = build_warc_manifest(scfg, root_path=root, clock=fixed_clock)
            obs = warc_observations_from_manifest(scfg, m, root_path=root)
            doc_obs = [o for o in obs if o.kind == "warc.document"]
            self.assertEqual(len(doc_obs), 1)
            load = prepare_canonical_load(obs)
            self.assertTrue(load.result.ok)
            doc_nodes = [n for n in load.canonical_rows.nodes if n.kind == "warc.document"]
            self.assertEqual(len(doc_nodes), 1)
            self.assertEqual(doc_nodes[0].display_name, "file%3Ab08.warc")
            self.assertTrue(len(load.canonical_rows.evidence) >= 1)

    def test_s12_b09_warc_definition_target_fallback(self) -> None:
        """Fallback target key links WARC document to canonical representation."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            (root / "b09.warc").write_bytes(self._build_warc(target_uri="http://example.com/page2"))
            cfg = self._write_config(root, "b09.warc")
            scfg = load_warc_source_config(cfg)
            m = build_warc_manifest(scfg, root_path=root, clock=fixed_clock)
            obs = warc_observations_from_manifest(scfg, m, root_path=root)
            load = prepare_canonical_load(obs)
            self.assertTrue(load.result.ok)
            node_keys = {n.canonical_key for n in load.canonical_rows.nodes}
            self.assertTrue(any("warc.document" in k for k in node_keys))
            define_edges = [e for e in load.canonical_rows.edges if e.edge_kind == "defines"]
            self.assertTrue(len(define_edges) >= 1)

    def test_s12_b10_warc_reference_target_source_composition(self) -> None:
        """Composes WARC reference observations with evidence records and edges."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmp:
            root = Path(tmp)
            (root / "b10.warc").write_bytes(self._build_warc(target_uri="http://example.com/page3"))
            cfg = self._write_config(root, "b10.warc")
            scfg = load_warc_source_config(cfg)
            m = build_warc_manifest(scfg, root_path=root, clock=fixed_clock)
            obs = warc_observations_from_manifest(scfg, m, root_path=root)
            load = prepare_canonical_load(obs)
            self.assertTrue(load.result.ok)
            self.assertTrue(len(load.canonical_rows.evidence) >= 1)
            ref_edges = [e for e in load.canonical_rows.edges if e.edge_kind == "references"]
            self.assertTrue(len(ref_edges) >= 1)


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
