import json
import tempfile
from pathlib import Path

from repomap_test_support.source_ingestion import (
    SourceIngestionUnitTestCase,
    warc_record,
)

from repomap_kg.ops.ingestion.source import (
    SourcePolicyError,
    build_warc_manifest,
    import_warc_source,
    load_warc_source_config,
    warc_observations_from_manifest,
)


class WarcSourceIngestionUnitTests(SourceIngestionUnitTestCase):
    def test_warc_config_policy_rejects_blocked_url_fields_and_missing_limits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            (root / "warc_artifacts").mkdir()
            (root / "warc_artifacts" / "example.warc").write_bytes(b"WARC/1.1\r\n")
            allowed = self.write_warc_config(root / "allowed.toml")
            blocked = self.write_warc_config(
                root / "blocked.toml",
                policy_status="blocked_terms_risk",
            )
            acquisition = self.write_warc_config(
                root / "acquisition.toml",
                extra="\n[acquisition]\nurl = \"https://example.invalid/archive.warc\"\n",
            )
            missing_records = self.write_warc_config(
                root / "missing-records.toml",
                max_warc_records=None,
            )
            wrong_kind = self.write_warc_config(
                root / "wrong-kind.toml",
                artifact_kind="directory",
            )

            config = load_warc_source_config(allowed)

            self.assertEqual(config.source_id, "example-warc-archive")
            self.assertEqual(config.source_type, "saved_page.archive")
            self.assertEqual(config.artifact_kind, "warc")
            self.assertEqual(config.max_warc_records, 100)
            with self.assertRaisesRegex(SourcePolicyError, "policy status"):
                load_warc_source_config(blocked)
            with self.assertRaisesRegex(SourcePolicyError, "network acquisition"):
                load_warc_source_config(acquisition)
            with self.assertRaisesRegex(SourcePolicyError, "max_warc_records"):
                load_warc_source_config(missing_records)
            with self.assertRaisesRegex(SourcePolicyError, "artifact.kind"):
                load_warc_source_config(wrong_kind)

    def test_warc_manifest_parses_records_redacts_and_materializes_payloads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            self.write_warc_fixture(root)
            config = load_warc_source_config(self.write_warc_config(root / "warc.toml"))

            manifest = build_warc_manifest(config, root_path=root, clock=self.fixed_clock)
            materialized = [
                record.materialized_path
                for record in manifest.records
                if record.materialized_path is not None
            ]
            materialized_exists = [
                (root / relative_path).is_file()
                for relative_path in materialized
            ]

        payload = json.dumps(manifest.to_jsonable(), sort_keys=True)
        self.assertEqual(manifest.record_count, 8)
        self.assertEqual(manifest.parsed_record_count, 8)
        self.assertEqual(manifest.routed_payload_count, 4)
        self.assertEqual(manifest.skipped_record_count, 1)
        self.assertIn('"warc_version": "WARC/1.1"', payload)
        self.assertIn('"identity_source": "warc_record_id"', payload)
        self.assertIn('"duplicate_identity": true', payload)
        self.assertIn('"extractor_route": "html"', payload)
        self.assertIn('"extractor_route": "css"', payload)
        self.assertIn('"extractor_route": "json"', payload)
        self.assertIn('"extractor_route": "javascript"', payload)
        self.assertIn('"skip_reason": "metadata-only"', payload)
        self.assertIn("<redacted>", payload)
        self.assertNotIn("fixture-secret", payload)
        self.assertEqual(
            materialized,
            [
                ".repomap/source-artifacts/example-warc-archive/20260630T120000Z/warc-payloads/record-0002/payload.html",
                ".repomap/source-artifacts/example-warc-archive/20260630T120000Z/warc-payloads/record-0003/payload.css",
                ".repomap/source-artifacts/example-warc-archive/20260630T120000Z/warc-payloads/record-0004/payload.json",
                ".repomap/source-artifacts/example-warc-archive/20260630T120000Z/warc-payloads/record-0005/payload.js",
            ],
        )
        self.assertTrue(all(materialized_exists))

    def test_warc_observations_route_payload_extractors_and_attach_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            self.write_warc_fixture(root)
            config = load_warc_source_config(
                self.write_warc_config(root / "warc.toml", secret=True)
            )
            manifest = build_warc_manifest(config, root_path=root, clock=self.fixed_clock)
            observations = warc_observations_from_manifest(
                config,
                manifest,
                root_path=root,
            )

        kinds = {observation.kind for observation in observations}
        self.assertIn("warc.document", kinds)
        self.assertIn("warc.record", kinds)
        self.assertIn("warc.header", kinds)
        self.assertIn("warc.payload", kinds)
        self.assertIn("warc.reference", kinds)
        self.assertIn("html.document", kinds)
        self.assertIn("css.document", kinds)
        self.assertIn("config.document", kinds)
        self.assertIn("js.file", kinds)
        self.assertIn("js.module", kinds)
        self.assertIn("js.function", kinds)
        self.assertIn("js.reference", kinds)
        self.assertNotIn("javascript.execution", kinds)
        document = next(
            observation
            for observation in observations
            if observation.kind == "warc.document"
        )
        self.assertEqual(document.target, "warc.document:file%3Awarc_artifacts%2Fexample.warc")
        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        self.assertIn('"source_id": "example-warc-archive"', payload)
        self.assertIn('"warc_record_ordinal": 2', payload)
        self.assertIn('"warc_record_ordinal": 5', payload)
        self.assertIn('"warc_record_key"', payload)
        self.assertIn('"warc_payload_path"', payload)
        self.assertIn('"artifact_extractor_route": "javascript"', payload)
        self.assertIn("file:.repomap/source-artifacts/example-warc-archive/20260630T120000Z/warc-payloads/record-0005/payload.js.map", payload)
        self.assertIn('"not_fetched": true', payload)
        self.assertIn("credentials.token", payload)
        self.assertNotIn("fixture-secret", payload)
        self.assertNotIn("Set-Cookie: session", payload)
        self.assertNotIn("Authorization: Bearer", payload)

    def test_warc_record_and_byte_limits_emit_parse_errors_without_payload_routing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            self.write_warc_fixture(root)
            limited = load_warc_source_config(
                self.write_warc_config(root / "limited.toml", max_warc_records=2)
            )
            too_small = load_warc_source_config(
                self.write_warc_config(root / "small.toml", max_record_bytes=32)
            )

            limited_manifest = build_warc_manifest(
                limited,
                root_path=root,
                clock=self.fixed_clock,
            )
            small_manifest = build_warc_manifest(
                too_small,
                root_path=root,
                clock=self.fixed_clock,
            )
            observations = warc_observations_from_manifest(
                limited,
                limited_manifest,
                root_path=root,
            )

        self.assertTrue(any("max_warc_records" in error for error in limited_manifest.errors))
        self.assertTrue(any("max_record_bytes" in error for error in small_manifest.errors))
        self.assertIn("warc.parse_error", {observation.kind for observation in observations})

    def test_warc_manifest_reports_malformed_record_shapes_safely(self):
        cases = {
            "missing_header_terminator": (
                b"not a warc",
                "missing header terminator",
            ),
            "unsupported_version": (
                b"WARC/0.9\r\nContent-Length: 0\r\n\r\n",
                "unsupported WARC version",
            ),
            "missing_content_length": (
                b"WARC/1.1\r\nWARC-Type: response\r\n\r\n",
                "missing Content-Length",
            ),
            "invalid_content_length": (
                b"WARC/1.1\r\nContent-Length: nope\r\n\r\n",
                "invalid Content-Length",
            ),
            "negative_content_length": (
                b"WARC/1.1\r\nContent-Length: -1\r\n\r\n",
                "negative Content-Length",
            ),
            "truncated_payload": (
                b"WARC/1.1\r\nContent-Length: 10\r\n\r\nx",
                "truncated payload",
            ),
        }

        for name, (content, expected_error) in cases.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir) / "repo"
                    artifact_dir = root / "warc_artifacts"
                    artifact_dir.mkdir(parents=True)
                    (artifact_dir / "example.warc").write_bytes(content)
                    config = load_warc_source_config(
                        self.write_warc_config(root / "warc.toml")
                    )

                    manifest = build_warc_manifest(
                        config,
                        root_path=root,
                        clock=self.fixed_clock,
                    )

                self.assertTrue(
                    any(expected_error in error for error in manifest.errors),
                    manifest.errors,
                )
                self.assertEqual(manifest.routed_payload_count, 0)

    def test_warc_manifest_records_skip_reasons_for_unrouted_payload_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            artifact_dir = root / "warc_artifacts"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "example.warc").write_bytes(
                b"".join(
                    [
                        warc_record(
                            "resource",
                            "urn:uuid:empty-html",
                            "https://example.invalid/empty.html",
                            b"",
                            content_type="text/html",
                        ),
                        warc_record(
                            "continuation",
                            "urn:uuid:continuation",
                            "https://example.invalid/continuation",
                            b"continued bytes",
                            content_type="text/html",
                        ),
                        warc_record(
                            "weird-record",
                            "urn:uuid:weird",
                            "https://example.invalid/weird",
                            b"weird bytes",
                            content_type="text/html",
                        ),
                        warc_record(
                            "resource",
                            "urn:uuid:unknown-content",
                            "https://example.invalid/blob.bin",
                            b"binary-ish bytes",
                            content_type="application/octet-stream",
                        ),
                        warc_record(
                            "resource",
                            "urn:uuid:too-large",
                            "https://example.invalid/too-large.html",
                            b"<html>too large</html>",
                            content_type="text/html",
                        ),
                    ]
                )
            )
            config = load_warc_source_config(
                self.write_warc_config(
                    root / "warc.toml",
                    max_total_payload_bytes=8,
                )
            )

            manifest = build_warc_manifest(
                config,
                root_path=root,
                clock=self.fixed_clock,
            )

        skip_reasons = {record.skip_reason for record in manifest.records}
        self.assertIn("empty-payload", skip_reasons)
        self.assertIn("continuation-deferred", skip_reasons)
        self.assertIn("unsupported-record-type", skip_reasons)
        self.assertIn("metadata-only", skip_reasons)
        self.assertIn("max_total_payload_bytes", skip_reasons)
        self.assertEqual(manifest.routed_payload_count, 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            artifact_dir = root / "warc_artifacts"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "example.warc").write_bytes(
                b"".join(
                    [
                        warc_record(
                            "resource",
                            "urn:uuid:xml",
                            "https://example.invalid/feed.xml",
                            b"<feed />",
                            content_type="application/xml",
                        ),
                        warc_record(
                            "resource",
                            "urn:uuid:first",
                            "https://example.invalid/first.html",
                            b"<html>first</html>",
                            content_type="text/html",
                        ),
                        warc_record(
                            "resource",
                            "urn:uuid:second",
                            "https://example.invalid/second.css",
                            b".second { color: blue; }",
                            content_type="text/css",
                        ),
                    ]
                )
            )
            config = load_warc_source_config(
                self.write_warc_config(
                    root / "warc-max-files.toml",
                    max_file_count=2,
                )
            )

            manifest = build_warc_manifest(
                config,
                root_path=root,
                clock=self.fixed_clock,
            )

        self.assertEqual(manifest.routed_payload_count, 2)
        self.assertIn("max_file_count", {record.skip_reason for record in manifest.records})

    def test_import_warc_source_loads_observations_and_reports_record_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            self.write_warc_fixture(root)
            config_path = self.write_warc_config(root / "warc.toml")

            summary = import_warc_source(
                config_path,
                root_path=root,
                clock=self.fixed_clock,
            )

        self.assertEqual(summary.source_id, "example-warc-archive")
        self.assertEqual(summary.record_count, 8)
        self.assertEqual(summary.routed_payloads, 4)
        self.assertGreater(summary.observations, 10)
        self.assertIn("warc.record", {item.kind for item in summary.raw_observations})
        self.assertEqual(
            summary.to_jsonable()["publication"]["publication_state"],
            "not_published",
        )
        self.assertEqual(summary.to_jsonable()["routed_payloads"], 4)
