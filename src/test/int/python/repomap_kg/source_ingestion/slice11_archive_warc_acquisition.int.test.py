"""Integration tests for Slice 11 archive and WARC acquisition (Group S11-B).

Covers:
- S11-B01: Supported JSON payload route and provenance composition
- S11-B02: Supported CSS payload route and provenance composition
- S11-B03: Safe header redaction through persisted/canonical metadata
- S11-B04: URI credential/query redaction through provenance
- S11-B05: Duplicate record identity disambiguation
- S11-B06: Multi-record ordinal/provenance composition
- S11-B07: Resource record direct payload materialization
- S11-B08: Conversion/continuation deferred outcome provenance
- S11-B09: Additional source-qualified canonical evidence/reference alternative
- S11-B10: Supported payload-route fallback/deferred provenance alternative
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
from repomap_test_support.source_ingestion_integration import (
    copy_warc_fixture_root,
    fixed_clock,
)
from repomap_test_support.test_scratch import select_scratch_root


class Slice11ArchiveWarcAcquisitionIntegrationTests(unittest.TestCase):
    """Slice 11 Group S11-B integration tests for WARC and archive acquisition."""

    def _write_warc_config(
        self,
        target_dir: Path,
        *,
        source_id: str = "test-warc",
        artifact_path: str = "warc_artifacts/test.warc",
        max_artifact_bytes: int = 1048576,
        max_file_count: int = 10,
        max_warc_records: int = 100,
        max_record_bytes: int = 1048576,
        max_total_payload_bytes: int = 1048576,
        policy_status: str = "allowed",
        source_type: str = "saved_page.archive",
    ) -> Path:
        toml_content = f"""[source]
id = "{source_id}"
type = "{source_type}"
display_name = "Test WARC Source"

[policy]
status = "{policy_status}"
max_artifact_bytes = {max_artifact_bytes}
max_file_count = {max_file_count}
max_warc_records = {max_warc_records}
max_record_bytes = {max_record_bytes}
max_total_payload_bytes = {max_total_payload_bytes}
retention_policy = "materialize-safe-payloads"
requires_manual_review = false

[artifact]
path = "{artifact_path}"
kind = "warc"
profile = "warc-local-archive"
"""
        cfg_path = target_dir / f"{source_id}.toml"
        cfg_path.write_text(toml_content, encoding="utf-8")
        return cfg_path

    def _build_warc_record(
        self,
        *,
        record_id: str = "11111111-1111-1111-1111-111111111111",
        target_uri: str = "http://example.com/api/data.json",
        warc_type: str = "response",
        content_type: str = "application/json",
        body: bytes = b'{"status": "ok"}',
    ) -> bytes:
        if warc_type == "response":
            http_msg = (
                b"HTTP/1.1 200 OK\r\n"
                + f"Content-Type: {content_type}\r\n".encode()
                + f"Content-Length: {len(body)}\r\n\r\n".encode()
                + body
            )
            return (
                b"WARC/1.0\r\n"
                b"WARC-Type: response\r\n"
                + f"WARC-Record-ID: <urn:uuid:{record_id}>\r\n".encode()
                + b"WARC-Date: 2026-09-12T12:00:00Z\r\n"
                + f"WARC-Target-URI: {target_uri}\r\n".encode()
                + b"Content-Type: application/http; msgtype=response\r\n"
                + f"Content-Length: {len(http_msg)}\r\n\r\n".encode()
                + http_msg
                + b"\r\n\r\n"
            )
        return (
            b"WARC/1.0\r\n"
            + f"WARC-Type: {warc_type}\r\n".encode()
            + f"WARC-Record-ID: <urn:uuid:{record_id}>\r\n".encode()
            + b"WARC-Date: 2026-09-12T12:00:00Z\r\n"
            + f"WARC-Target-URI: {target_uri}\r\n".encode()
            + f"Content-Type: {content_type}\r\n".encode()
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
            + b"\r\n\r\n"
        )

    def test_s11_b01_supported_json_payload_route_and_provenance(self) -> None:
        """WARC application/json payload is routed to json extractor and materialized."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            art_dir = root / "warc_artifacts"
            art_dir.mkdir()
            warc_p = art_dir / "json_route.warc"
            warc_p.write_bytes(self._build_warc_record(content_type="application/json"))

            cfg_p = self._write_warc_config(root, artifact_path="warc_artifacts/json_route.warc")
            cfg = load_warc_source_config(cfg_p)
            manifest = build_warc_manifest(cfg, root_path=root, clock=fixed_clock)
            self.assertEqual(len(manifest.records), 1)
            rec = manifest.records[0]
            self.assertEqual(rec.extractor_route, "json")
            self.assertTrue(rec.materialized_path is not None and rec.materialized_path.endswith(".json"))

    def test_s11_b02_supported_css_payload_route_and_provenance(self) -> None:
        """WARC text/css payload routes to css and materializes .css payload."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            art_dir = root / "warc_artifacts"
            art_dir.mkdir()
            warc_p = art_dir / "style_route.warc"
            warc_p.write_bytes(self._build_warc_record(content_type="text/css", body=b"body { margin: 0; }"))

            cfg_p = self._write_warc_config(root, artifact_path="warc_artifacts/style_route.warc")
            cfg = load_warc_source_config(cfg_p)
            manifest = build_warc_manifest(cfg, root_path=root, clock=fixed_clock)
            self.assertEqual(len(manifest.records), 1)
            rec = manifest.records[0]
            self.assertEqual(rec.extractor_route, "css")
            self.assertTrue(rec.materialized_path is not None and rec.materialized_path.endswith(".css"))

    def test_s11_b03_safe_header_redaction_through_persisted_metadata(self) -> None:
        """Sensitive headers (authorization, cookie) are redacted from WARC header observations."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            art_dir = root / "warc_artifacts"
            art_dir.mkdir()
            warc_p = art_dir / "headers.warc"
            body = b'{"status": "ok"}'
            http_msg = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Authorization: Bearer secret-token-xyz\r\n"
                b"Cookie: session=secret-cookie-val\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode()
                + body
            )
            rec = (
                b"WARC/1.0\r\n"
                b"WARC-Type: response\r\n"
                b"WARC-Record-ID: <urn:uuid:33333333-3333-3333-3333-333333333333>\r\n"
                b"WARC-Date: 2026-09-12T12:00:00Z\r\n"
                b"WARC-Target-URI: http://example.com/api/secure\r\n"
                b"Content-Type: application/http; msgtype=response\r\n"
                + f"Content-Length: {len(http_msg)}\r\n\r\n".encode()
                + http_msg
                + b"\r\n\r\n"
            )
            warc_p.write_bytes(rec)
            cfg_p = self._write_warc_config(root, artifact_path="warc_artifacts/headers.warc")
            cfg = load_warc_source_config(cfg_p)
            manifest = build_warc_manifest(cfg, root_path=root, clock=fixed_clock)
            self.assertEqual(len(manifest.records), 1)
            obs = warc_observations_from_manifest(cfg, manifest, root_path=root)
            self.assertTrue(len(obs) >= 1)
            for o in obs:
                hdrs = o.metadata.get("headers", {})
                if hdrs:
                    self.assertEqual(hdrs.get("authorization"), "<redacted>")
                    self.assertEqual(hdrs.get("cookie"), "<redacted>")
                    self.assertNotIn("secret-token-xyz", json.dumps(o.metadata))
                    self.assertNotIn("secret-cookie-val", json.dumps(o.metadata))
            load = prepare_canonical_load(obs)
            self.assertTrue(load.result.ok)

    def test_s11_b04_uri_credential_and_query_redaction_through_provenance(self) -> None:
        """Target URIs with passwords or sensitive queries are redacted in observations."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            art_dir = root / "warc_artifacts"
            art_dir.mkdir()
            warc_p = art_dir / "sensitive_uri.warc"
            sensitive_uri = "https://user:mypassword@example.com/search?token=secret99&q=test"
            warc_p.write_bytes(self._build_warc_record(target_uri=sensitive_uri))
            cfg_p = self._write_warc_config(root, artifact_path="warc_artifacts/sensitive_uri.warc")
            cfg = load_warc_source_config(cfg_p)
            manifest = build_warc_manifest(cfg, root_path=root, clock=fixed_clock)
            self.assertEqual(len(manifest.records), 1)
            obs = warc_observations_from_manifest(cfg, manifest, root_path=root)
            self.assertTrue(len(obs) >= 1)
            obs_json = json.dumps([o.metadata for o in obs])
            self.assertNotIn("mypassword", obs_json)
            self.assertNotIn("secret99", obs_json)
            self.assertIn("<redacted>", obs_json)
            load = prepare_canonical_load(obs)
            self.assertTrue(load.result.ok)

    def test_s11_b05_duplicate_record_identity_disambiguation(self) -> None:
        """WARC records with colliding IDs are disambiguated with distinct ordinals."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            art_dir = root / "warc_artifacts"
            art_dir.mkdir()
            warc_p = art_dir / "dup.warc"
            rec1 = self._build_warc_record(record_id="same-uuid", body=b'{"id": 1}')
            rec2 = self._build_warc_record(record_id="same-uuid", body=b'{"id": 2}')
            warc_p.write_bytes(rec1 + rec2)

            cfg_p = self._write_warc_config(root, artifact_path="warc_artifacts/dup.warc")
            cfg = load_warc_source_config(cfg_p)
            manifest = build_warc_manifest(cfg, root_path=root, clock=fixed_clock)
            self.assertEqual(len(manifest.records), 2)
            ordinals = [r.ordinal for r in manifest.records]
            self.assertEqual(ordinals, [1, 2])
            keys = [r.record_key for r in manifest.records]
            self.assertEqual(len(set(keys)), 2)

    def test_s11_b06_multi_record_ordinal_provenance_composition(self) -> None:
        """Sequential WARC records maintain strict ordinal sequencing and metadata links."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            art_dir = root / "warc_artifacts"
            art_dir.mkdir()
            warc_p = art_dir / "multi.warc"
            records = b"".join(
                self._build_warc_record(record_id=f"rec-{i:02d}", body=f'{{"n": {i}}}'.encode())
                for i in range(1, 4)
            )
            warc_p.write_bytes(records)

            cfg_p = self._write_warc_config(root, artifact_path="warc_artifacts/multi.warc")
            cfg = load_warc_source_config(cfg_p)
            manifest = build_warc_manifest(cfg, root_path=root, clock=fixed_clock)
            self.assertEqual(manifest.record_count, 3)
            self.assertEqual([r.ordinal for r in manifest.records], [1, 2, 3])

    def test_s11_b07_resource_record_direct_payload_materialization(self) -> None:
        """WARC resource records materialize non-HTTP payloads directly."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            art_dir = root / "warc_artifacts"
            art_dir.mkdir()
            warc_p = art_dir / "resource.warc"
            res_rec = self._build_warc_record(
                warc_type="resource",
                target_uri="file:///styles/main.css",
                content_type="text/css",
                body=b"h1 { font-size: 24px; }",
            )
            warc_p.write_bytes(res_rec)

            cfg_p = self._write_warc_config(root, artifact_path="warc_artifacts/resource.warc")
            cfg = load_warc_source_config(cfg_p)
            manifest = build_warc_manifest(cfg, root_path=root, clock=fixed_clock)
            self.assertEqual(len(manifest.records), 1)
            rec = manifest.records[0]
            self.assertEqual(rec.record_type, "resource")
            self.assertEqual(rec.extractor_route, "css")

    def test_s11_b08_conversion_continuation_deferred_outcome_provenance(self) -> None:
        """WARC continuation or unsupported record types record explicit skip reasons."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            art_dir = root / "warc_artifacts"
            art_dir.mkdir()
            warc_p = art_dir / "binary.warc"
            rec = self._build_warc_record(
                warc_type="continuation",
                content_type="application/octet-stream",
                body=b"\x00\x01\x02\x03",
            )
            warc_p.write_bytes(rec)

            cfg_p = self._write_warc_config(root, artifact_path="warc_artifacts/binary.warc")
            cfg = load_warc_source_config(cfg_p)
            manifest = build_warc_manifest(cfg, root_path=root, clock=fixed_clock)
            self.assertEqual(len(manifest.records), 1)
            self.assertIsNone(manifest.records[0].extractor_route)
            self.assertEqual(manifest.records[0].skip_reason, "continuation-deferred")

    def test_s11_b09_additional_source_qualified_canonical_evidence_alternative(self) -> None:
        """WARC observations canonicalize into source-qualified nodes with evidence links."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = copy_warc_fixture_root(Path(tmpdir))
            config = load_warc_source_config(root / "warc_sources" / "allowed-warc.toml")
            manifest = build_warc_manifest(config, root_path=root, clock=fixed_clock)
            obs = warc_observations_from_manifest(config, manifest, root_path=root)
            load = prepare_canonical_load(obs)
            self.assertTrue(load.result.ok)
            self.assertTrue(len(load.canonical_rows.evidence) >= 1)
            evidence_kinds = {e.extractor for e in load.canonical_rows.evidence}
            self.assertIn("source-ingestion", evidence_kinds)

    def test_s11_b10_supported_payload_route_fallback_deferred_provenance(self) -> None:
        """Oversized payload records retain metadata provenance while skipping materialization."""
        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            root = Path(tmpdir)
            art_dir = root / "warc_artifacts"
            art_dir.mkdir()
            warc_p = art_dir / "oversized_rec.warc"
            rec = self._build_warc_record(content_type="application/json", body=b"x" * 200)
            warc_p.write_bytes(rec)

            cfg_p = self._write_warc_config(
                root,
                artifact_path="warc_artifacts/oversized_rec.warc",
                max_total_payload_bytes=50,
            )
            cfg = load_warc_source_config(cfg_p)
            manifest = build_warc_manifest(cfg, root_path=root, clock=fixed_clock)
            self.assertEqual(len(manifest.records), 1)
            self.assertEqual(manifest.records[0].skip_reason, "max_total_payload_bytes")
            self.assertIsNone(manifest.records[0].materialized_path)
            self.assertEqual(len(manifest.errors), 0)


if __name__ == "__main__":
    import sys
    sys.exit(
        "Direct execution unsupported; use tools/run_tests.py for container sandbox admission."
    )
