import json
import tempfile
import unittest
from pathlib import Path

from repomap_test_support.source_ingestion_integration import (
    copy_warc_fixture_root,
    fixed_clock,
    int_warc_record,
    warc_source_fixture,
    write_warc_source_config,
)
from repomap_kg.ops.ingestion.source import (
    SourcePolicyError,
    build_warc_manifest,
    import_warc_source,
    load_warc_source_config,
    warc_observations_from_manifest,
)


class WarcSourceIngestionIntegrationTests(unittest.TestCase):
    def test_warc_source_fixture_policy_manifest_and_observations(self):
        allowed = load_warc_source_config(warc_source_fixture("allowed-warc.toml"))

        self.assertEqual(allowed.source_id, "example-warc-archive")
        self.assertEqual(allowed.source_type, "saved_page.archive")
        self.assertEqual(allowed.max_warc_records, 100)
        for filename in ("blocked-policy.toml", "manual-review.toml"):
            with self.subTest(filename=filename):
                with self.assertRaises(SourcePolicyError):
                    load_warc_source_config(warc_source_fixture(filename))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = copy_warc_fixture_root(Path(tmpdir))
            config = load_warc_source_config(root / "warc_sources" / "allowed-warc.toml")
            record_limited = load_warc_source_config(
                root / "warc_sources" / "record-limit.toml"
            )
            byte_limited = load_warc_source_config(
                root / "warc_sources" / "byte-limit.toml"
            )
            malformed = load_warc_source_config(
                root / "warc_sources" / "malformed-warc.toml"
            )

            manifest = build_warc_manifest(config, root_path=root, clock=fixed_clock)
            observations = warc_observations_from_manifest(
                config,
                manifest,
                root_path=root,
            )
            record_limit_manifest = build_warc_manifest(
                record_limited,
                root_path=root,
                clock=fixed_clock,
            )
            byte_limit_manifest = build_warc_manifest(
                byte_limited,
                root_path=root,
                clock=fixed_clock,
            )
            malformed_manifest = build_warc_manifest(
                malformed,
                root_path=root,
                clock=fixed_clock,
            )

        kinds = {observation.kind for observation in observations}
        payload = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        self.assertEqual(manifest.record_count, 8)
        self.assertEqual(manifest.routed_payload_count, 4)
        self.assertEqual(manifest.skipped_record_count, 1)
        self.assertIn("warc.document", kinds)
        self.assertIn("warc.record", kinds)
        self.assertIn("warc.payload", kinds)
        self.assertIn("warc.reference", kinds)
        self.assertIn("html.document", kinds)
        self.assertIn("css.document", kinds)
        self.assertIn("config.document", kinds)
        self.assertIn("js.file", kinds)
        self.assertIn("js.module", kinds)
        self.assertIn("js.function", kinds)
        self.assertIn("js.reference", kinds)
        self.assertIn('"source_id": "example-warc-archive"', payload)
        self.assertIn('"warc_record_key"', payload)
        self.assertIn('"warc_payload_path"', payload)
        self.assertIn('"artifact_extractor_route": "javascript"', payload)
        self.assertIn(
            "file:.repomap/source-artifacts/example-warc-archive/"
            "20260630T120000Z/warc-payloads/record-0005/payload.js.map",
            payload,
        )
        self.assertIn('"not_fetched": true', payload)
        self.assertNotIn("fixture-secret", payload)
        self.assertTrue(
            any("max_warc_records" in error for error in record_limit_manifest.errors)
        )
        self.assertTrue(
            any("max_record_bytes" in error for error in byte_limit_manifest.errors)
        )
        self.assertTrue(malformed_manifest.errors)

    def test_warc_import_is_acquisition_only_without_network(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = copy_warc_fixture_root(Path(tmpdir))
            summary = import_warc_source(
                root / "warc_sources" / "allowed-warc.toml",
                root_path=root,
                clock=fixed_clock,
            )

        self.assertEqual(summary.source_id, "example-warc-archive")
        self.assertEqual(summary.record_count, 8)
        self.assertEqual(summary.routed_payloads, 4)
        self.assertEqual(summary.publication.publication_state, "not_published")
        self.assertGreater(len(summary.raw_observations), 10)
        self.assertIn("js.file", {item.kind for item in summary.raw_observations})
        payload = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn('"source_id": "example-warc-archive"', payload)
        self.assertIn('"artifact_extractor_route": "javascript"', payload)
        self.assertIn('"not_fetched": true', payload)
        self.assertNotIn("fixture-secret", payload)

    def test_warc_policy_parser_and_target_error_paths_are_local_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = copy_warc_fixture_root(Path(tmpdir))
            write_warc_source_config(
                root / "warc_sources" / "network-field.toml",
                extra="\n[acquisition]\nurl = \"https://example.invalid/archive.warc\"\n",
            )
            write_warc_source_config(
                root / "warc_sources" / "missing-file.toml",
                artifact_path="warc_artifacts/missing.warc",
            )
            (root / "warc_artifacts" / "example.warc.gz").write_text(
                "not used",
                encoding="utf-8",
            )
            write_warc_source_config(
                root / "warc_sources" / "gz.toml",
                artifact_path="warc_artifacts/example.warc.gz",
            )
            write_warc_source_config(
                root / "warc_sources" / "too-large.toml",
                max_artifact_bytes=1,
            )
            write_warc_source_config(
                root / "warc_sources" / "repo-escape.toml",
                artifact_path="../outside.warc",
            )
            target_warc = root / "warc_artifacts" / "target-branches.warc"
            target_warc.write_bytes(
                b"".join(
                    (
                        int_warc_record(
                            "resource",
                            "urn:uuid:javascript",
                            "javascript:alert(1)",
                            b"<html></html>",
                            content_type="text/html",
                        ),
                        int_warc_record(
                            "resource",
                            "urn:uuid:absolute",
                            "/Library/example.css",
                            b".absolute {}\n",
                            content_type="text/css",
                        ),
                        int_warc_record(
                            "resource",
                            "urn:uuid:local",
                            "assets/local.css",
                            b".local {}\n",
                            content_type="text/css",
                        ),
                        int_warc_record(
                            "resource",
                            "urn:uuid:unknown",
                            "../escape.css",
                            b".escape {}\n",
                            content_type="text/css",
                        ),
                    )
                )
            )
            write_warc_source_config(
                root / "warc_sources" / "target-branches.toml",
                artifact_path="warc_artifacts/target-branches.warc",
            )
            invalid_length = root / "warc_artifacts" / "invalid-length.warc"
            invalid_length.write_text(
                "\n".join(
                    [
                        "WARC/1.1",
                        "WARC-Type: resource",
                        "WARC-Record-ID: <urn:uuid:invalid>",
                        "WARC-Date: 2026-06-30T12:00:00Z",
                        "Content-Type: text/css",
                        "Content-Length: nope",
                        "",
                        ".bad {}",
                    ]
                ),
                encoding="utf-8",
            )
            write_warc_source_config(
                root / "warc_sources" / "invalid-length.toml",
                artifact_path="warc_artifacts/invalid-length.warc",
            )
            missing_length = root / "warc_artifacts" / "missing-length.warc"
            missing_length.write_text(
                "WARC/1.1\nWARC-Type: resource\n\nbody",
                encoding="utf-8",
            )
            write_warc_source_config(
                root / "warc_sources" / "missing-length.toml",
                artifact_path="warc_artifacts/missing-length.warc",
            )
            negative_length = root / "warc_artifacts" / "negative-length.warc"
            negative_length.write_text(
                "\n".join(
                    [
                        "WARC/1.1",
                        "WARC-Type: resource",
                        "Content-Length: -1",
                        "",
                        "body",
                    ]
                ),
                encoding="utf-8",
            )
            write_warc_source_config(
                root / "warc_sources" / "negative-length.toml",
                artifact_path="warc_artifacts/negative-length.warc",
            )
            bad_version = root / "warc_artifacts" / "bad-version.warc"
            bad_version.write_text(
                "WARC/0.9\nWARC-Type: resource\nContent-Length: 0\n\n",
                encoding="utf-8",
            )
            write_warc_source_config(
                root / "warc_sources" / "bad-version.toml",
                artifact_path="warc_artifacts/bad-version.warc",
            )
            unterminated = root / "warc_artifacts" / "unterminated.warc"
            unterminated.write_text("WARC/1.1\nWARC-Type: resource", encoding="utf-8")
            write_warc_source_config(
                root / "warc_sources" / "unterminated.toml",
                artifact_path="warc_artifacts/unterminated.warc",
            )
            fallback_warc = root / "warc_artifacts" / "fallback-identity.warc"
            fallback_warc.write_bytes(
                b"".join(
                    (
                        int_warc_record(
                            "resource",
                            None,
                            "https://example.invalid/fallback.css",
                            b".fallback {}\n",
                            content_type="text/css",
                        ),
                        int_warc_record(
                            "resource",
                            None,
                            None,
                            b".ordinal {}\n",
                            content_type="text/css",
                            include_date=False,
                        ),
                        int_warc_record(
                            "resource",
                            "urn:uuid:redacted-header",
                            "https://example.invalid/header.css",
                            b".header {}\n",
                            content_type="text/css",
                            extra_headers={"API-Key": "fixture-secret"},
                        ),
                    )
                )
            )
            write_warc_source_config(
                root / "warc_sources" / "fallback-identity.toml",
                artifact_path="warc_artifacts/fallback-identity.warc",
            )

            with self.assertRaisesRegex(SourcePolicyError, "network acquisition"):
                load_warc_source_config(root / "warc_sources" / "network-field.toml")
            for filename, message in (
                ("missing-file.toml", "existing WARC file"),
                ("gz.toml", "local .warc files only"),
                ("too-large.toml", "max_artifact_bytes"),
                ("repo-escape.toml", "inside root_path"),
            ):
                with self.subTest(filename=filename):
                    with self.assertRaisesRegex(SourcePolicyError, message):
                        build_warc_manifest(
                            load_warc_source_config(root / "warc_sources" / filename),
                            root_path=root,
                            clock=fixed_clock,
                        )

            target_manifest = build_warc_manifest(
                load_warc_source_config(root / "warc_sources" / "target-branches.toml"),
                root_path=root,
                clock=fixed_clock,
            )
            invalid_manifest = build_warc_manifest(
                load_warc_source_config(root / "warc_sources" / "invalid-length.toml"),
                root_path=root,
                clock=fixed_clock,
            )
            malformed_manifest = build_warc_manifest(
                load_warc_source_config(root / "warc_sources" / "malformed-warc.toml"),
                root_path=root,
                clock=fixed_clock,
            )
            error_manifests = {
                filename: build_warc_manifest(
                    load_warc_source_config(root / "warc_sources" / filename),
                    root_path=root,
                    clock=fixed_clock,
                )
                for filename in (
                    "missing-length.toml",
                    "negative-length.toml",
                    "bad-version.toml",
                    "unterminated.toml",
                )
            }
            fallback_manifest = build_warc_manifest(
                load_warc_source_config(root / "warc_sources" / "fallback-identity.toml"),
                root_path=root,
                clock=fixed_clock,
            )
            invalid_observations = warc_observations_from_manifest(
                load_warc_source_config(root / "warc_sources" / "invalid-length.toml"),
                invalid_manifest,
                root_path=root,
            )

        target_keys = {record.target_key for record in target_manifest.records}
        self.assertTrue(any(key and key.startswith("dynamic:") for key in target_keys))
        self.assertTrue(
            any(key == "external:file:absolute-warc-reference" for key in target_keys)
        )
        self.assertTrue(any(key == "file:assets/local.css" for key in target_keys))
        self.assertTrue(any(key and key.startswith("unknown:") for key in target_keys))
        self.assertTrue(
            any("invalid Content-Length" in error for error in invalid_manifest.errors)
        )
        self.assertTrue(
            any("truncated payload" in error for error in malformed_manifest.errors)
        )
        self.assertTrue(
            any(observation.kind == "warc.parse_error" for observation in invalid_observations)
        )
        self.assertTrue(
            any(
                "missing Content-Length" in error
                for error in error_manifests["missing-length.toml"].errors
            )
        )
        self.assertTrue(
            any(
                "negative Content-Length" in error
                for error in error_manifests["negative-length.toml"].errors
            )
        )
        self.assertTrue(
            any(
                "unsupported WARC version" in error
                for error in error_manifests["bad-version.toml"].errors
            )
        )
        self.assertTrue(
            any(
                "missing header terminator" in error
                for error in error_manifests["unterminated.toml"].errors
            )
        )
        self.assertEqual(
            [record.identity_source for record in fallback_manifest.records[:2]],
            ["warc-date-target-uri-type", "record-ordinal"],
        )
        self.assertIn("<redacted>", json.dumps(fallback_manifest.to_jsonable()))
