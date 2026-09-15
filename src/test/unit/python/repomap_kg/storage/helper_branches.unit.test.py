import json
import tempfile
import unittest
from pathlib import Path
from typing import Callable, Mapping


from repomap_kg import storage


class StorageHelperBranchUnitTests(unittest.TestCase):
    def test_storage_payload_helpers_cover_safe_error_branches(self):
        payload = {
            "text": "value",
            "empty": "",
            "bool": True,
            "none": None,
            "items": ["a", "b"],
            "object": {"b": 2, "a": "1"},
            "bools": {"enabled": True, "visible": False},
            "count": "7",
        }

        self.assertEqual(storage.payload_text(payload, "text"), "value")
        self.assertEqual(storage.payload_string(payload, "empty"), "")
        self.assertTrue(storage.payload_bool(payload, "bool"))
        self.assertIsNone(storage.payload_optional_bool(payload, "none"))
        self.assertTrue(storage.payload_optional_bool(payload, "bool"))
        self.assertEqual(storage.payload_string_tuple(payload, "items", label="x"), ("a", "b"))
        self.assertEqual(storage.payload_json_object(payload, "object", label="x"), {"a": "1", "b": 2})
        self.assertEqual(storage.payload_count_map(payload, "object", label="x"), {"a": 1, "b": 2})
        self.assertEqual(
            storage.payload_required_count_map(payload, "object", ("a", "b"), label="x"),
            {"a": 1, "b": 2},
        )
        self.assertEqual(
            storage.payload_required_bool_map(payload, "bools", ("enabled", "visible"), label="x"),
            {"enabled": True, "visible": False},
        )
        self.assertEqual(storage.payload_int(payload, "count", label="x"), 7)
        self.assertIsNone(storage.payload_optional_int(payload, "none", label="x"))
        self.assertEqual(storage.payload_optional_int(payload, "count", label="x"), 7)
        self.assertIsNone(storage.payload_optional_text(payload, "none", label="x"))
        self.assertEqual(storage.payload_optional_text(payload, "text", label="x"), "value")

        malformed_payloads: tuple[
            tuple[Callable[..., object], object, tuple[object, ...], Mapping[str, object]],
            ...,
        ] = (
            (storage.payload_text, {"text": ""}, ("text",), {"label": "x"}),
            (storage.payload_text, {"text": 1}, ("text",), {"label": "x"}),
            (storage.payload_string, {}, ("text",), {"label": "x"}),
            (storage.payload_bool, {"flag": "true"}, ("flag",), {"label": "x"}),
            (storage.payload_optional_bool, {"flag": "true"}, ("flag",), {"label": "x"}),
            (storage.payload_string_tuple, {"items": "bad"}, ("items",), {"label": "x"}),
            (storage.payload_string_tuple, {"items": ["a", 2]}, ("items",), {"label": "x"}),
            (storage.payload_json_object, {"object": []}, ("object",), {"label": "x"}),
            (storage.payload_count_map, {"object": {"": 1}}, ("object",), {"label": "x"}),
            (storage.payload_count_map, {"object": {"a": "bad"}}, ("object",), {"label": "x"}),
            (
                storage.payload_required_count_map,
                {"object": {"a": 1}},
                ("object", ("a", "b")),
                {"label": "x"},
            ),
            (
                storage.payload_required_bool_map,
                {"bools": {"enabled": "true"}},
                ("bools", ("enabled",)),
                {"label": "x"},
            ),
            (storage.payload_int, {"count": object()}, ("count",), {"label": "x"}),
            (storage.payload_optional_int, {"count": object()}, ("count",), {"label": "x"}),
            (storage.payload_optional_text, {"text": ""}, ("text",), {"label": "x"}),
        )
        for func, bad_payload, args, kwargs in malformed_payloads:
            with self.subTest(helper=func.__name__, payload=bad_payload):
                with self.assertRaises(storage.StorageSchemaError):
                    func(bad_payload, *args, **kwargs)

        self.assertEqual(storage.metadata_text({"name": "repo"}, "name", "default"), "repo")
        self.assertEqual(storage.metadata_text({"name": ""}, "name", "default"), "default")
        self.assertEqual(storage.metadata_text({"name": 1}, "name", "default"), "default")
        self.assertTrue(storage.metadata_bool({"enabled": True}, "enabled"))
        self.assertFalse(storage.metadata_bool({"enabled": "true"}, "enabled"))
        self.assertEqual(storage.optional_text("value"), "value")
        self.assertIsNone(storage.optional_text(""))
        self.assertEqual(storage.canonical_file_path_prefix(""), "file:")
        self.assertEqual(storage.canonical_file_path_prefix("."), "file:")
        self.assertEqual(storage.canonical_file_path_prefix("src/main"), "file:src/main/")
        self.assertEqual(storage.sql_like_prefix_literal("a_%b\\c"), "'a\\_\\%b\\\\c%'")
        self.assertEqual(storage.last_output_line("\nNOTICE\n{\"ok\": true}\n"), '{"ok": true}')
        with self.assertRaisesRegex(
            storage.StorageSchemaError,
            "psql did not return a load summary",
        ):
            storage.last_output_line("\n\n")

    def test_storage_readback_payload_helpers_cover_neighborhood_branches(self):
        canonical_node_payload = {
            "canonical_key": "function:main",
            "graph_key_version": 1,
            "kind": "function",
            "display_name": "main",
            "confidence": "extracted",
            "conflict": False,
            "metadata": {},
            "first_seen_run_id": 1,
            "last_seen_run_id": 1,
        }
        canonical_edge_payload = {
            "source_key": "function:main",
            "edge_kind": "calls",
            "target_key": "function:helper",
            "graph_key_version": 1,
            "identity_metadata": {},
            "identity_metadata_hash": "abc",
            "metadata": {},
            "confidence": "extracted",
            "conflict": False,
            "first_seen_run_id": 1,
            "last_seen_run_id": 1,
        }
        evidence_payload = {
            "evidence_key": "evidence:1",
            "link_kind": "supports",
            "raw_observation": {
                "run_id": 1,
                "ordinal": 1,
                "payload_hash": "abc",
                "kind": "python.function",
                "source_id": "src/app.py:function",
            },
            "path": "src/app.py",
            "start_line": 1,
            "end_line": 3,
            "extractor": "pytest",
            "extractor_version": "1",
            "confidence": "extracted",
            "metadata": {},
        }

        canonical = storage.canonical_neighborhood_from_storage_payload(
            {
                "center": canonical_node_payload,
                "nodes": [canonical_node_payload],
                "edges": [canonical_edge_payload],
            }
        )
        assert canonical.center is not None
        self.assertEqual(canonical.center.display_name, "main")
        self.assertEqual(canonical.edges[0].target_key, "function:helper")
        self.assertIsNone(
            storage.canonical_neighborhood_from_storage_payload(
                {"center": None, "nodes": [], "edges": []}
            ).center
        )

        explanation = storage.canonical_edge_explanation_from_storage_payload(
            {"edge": canonical_edge_payload, "evidence": [evidence_payload]}
        )
        assert explanation.edge is not None
        self.assertEqual(explanation.edge.source_key, "function:main")
        self.assertEqual(explanation.evidence[0].raw_observation["kind"], "python.function")
        self.assertIsNone(
            storage.canonical_edge_explanation_from_storage_payload(
                {"edge": None, "evidence": []}
            ).edge
        )

        malformed_payloads: tuple[tuple[Callable[..., object], object], ...] = (
            (storage.canonical_neighborhood_from_storage_payload, []),
            (storage.canonical_neighborhood_from_storage_payload, {"center": "bad", "nodes": [], "edges": []}),
            (storage.canonical_neighborhood_from_storage_payload, {"center": None, "nodes": {}, "edges": []}),
            (storage.canonical_neighborhood_from_storage_payload, {"center": None, "nodes": [], "edges": {}}),
            (storage.canonical_edge_explanation_from_storage_payload, []),
            (storage.canonical_edge_explanation_from_storage_payload, {"edge": "bad", "evidence": []}),
            (storage.canonical_edge_explanation_from_storage_payload, {"edge": None, "evidence": {}}),
            (storage.canonical_edge_evidence_record_from_storage_payload, {"raw_observation": []}),
        )
        for func, bad_payload in malformed_payloads:
            with self.subTest(helper=func.__name__, payload=bad_payload):
                with self.assertRaises(storage.StorageSchemaError):
                    func(bad_payload)

    def test_storage_manifest_summary_helpers_cover_count_and_diagnostic_branches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bulk_manifest = root / ".repomap" / "bulk-runs" / "source" / "run" / "manifest.json"
            bulk_manifest.parent.mkdir(parents=True)
            bulk_manifest.write_text(
                json.dumps(
                    {
                        "source_id": "bulk-source",
                        "bulk_run_id": "bulk-run",
                        "corpus_kind": "mixed_corpus",
                        "policy_status": "allowed",
                        "file_count_included": "3",
                        "file_count_skipped": 2,
                        "total_bytes_included": 123,
                        "extractor_counts": {"markdown": "2", "python": 1},
                        "diagnostic_counts": {"warn": 1},
                        "redaction_counts": {"secret": 1},
                        "skipped_files": [
                            {"reason": "archive_deferred"},
                            {"reason": "warc_deferred"},
                            {"reason": ""},
                        ],
                        "limit_hit": True,
                        "limit_reason": (
                            "max_files_exceeded, max_total_bytes_exceeded, "
                            "max_file_bytes_exceeded, max_depth_exceeded"
                        ),
                    }
                ),
                encoding="utf-8",
            )
            bad_bulk_manifest = root / ".repomap" / "bulk-runs" / "source" / "bad" / "manifest.json"
            bad_bulk_manifest.parent.mkdir(parents=True)
            bad_bulk_manifest.write_text("[not an object]", encoding="utf-8")

            bulk_summary = storage.bulk_manifest_summary_payload(root)
            self.assertEqual(bulk_summary["bulk_runs"], 1)
            self.assertEqual(bulk_summary["file_count_included"], 3)
            self.assertEqual(bulk_summary["file_count_skipped"], 2)
            self.assertEqual(bulk_summary["extractor_counts"], {"markdown": 2, "python": 1})
            self.assertEqual(bulk_summary["archive_deferred"], 1)
            self.assertEqual(bulk_summary["warc_deferred"], 1)
            self.assertEqual(bulk_summary["limit_hit_count"], 1)
            self.assertEqual(bulk_summary["max_files_hit_count"], 1)
            self.assertEqual(bulk_summary["max_total_bytes_hit_count"], 1)
            self.assertEqual(bulk_summary["max_file_bytes_hit_count"], 1)
            self.assertEqual(bulk_summary["max_depth_hit_count"], 1)
            self.assertEqual(bulk_summary["diagnostic_counts"]["manifest_parse_error"], 1)

            api_manifest = root / ".repomap" / "api-runs" / "source" / "run" / "manifest.json"
            api_manifest.parent.mkdir(parents=True)
            api_manifest.write_text(
                json.dumps(
                    {
                        "source_id": "api-source",
                        "api_run_id": "api-run",
                        "source_type": "github.api",
                        "api_source_class": "github",
                        "provider_name": "github",
                        "provider_product": "repos",
                        "policy_status": "allowed",
                        "no_network": False,
                        "no_mutation": False,
                        "no_credentials_resolved": False,
                        "no_scheduler": False,
                        "requests": [
                            {
                                "endpoint_name": "repo",
                                "method": "GET",
                                "downstream_route": "json",
                                "response_type": "application/json",
                            }
                        ],
                        "responses": [
                            {
                                "endpoint_name": "repo",
                                "response_byte_count": "12",
                                "redacted": True,
                                "artifact_path": "responses/repo.json",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            bad_api_manifest = root / ".repomap" / "api-runs" / "source" / "bad" / "manifest.json"
            bad_api_manifest.parent.mkdir(parents=True)
            bad_api_manifest.write_text("not-json", encoding="utf-8")

            api_summary = storage.api_manifest_summary_payload(root)
            self.assertEqual(api_summary["api_runs"], 1)
            self.assertEqual(api_summary["sources"], 1)
            self.assertEqual(api_summary["source_types"], {"github.api": 1})
            self.assertEqual(api_summary["api_source_classes"], {"github": 1})
            self.assertEqual(api_summary["provider_names"], {"github": 1})
            self.assertEqual(api_summary["requests"], 1)
            self.assertEqual(api_summary["responses"], 1)
            self.assertEqual(api_summary["endpoint_names"], ["repo"])
            self.assertEqual(api_summary["methods"], {"GET": 1})
            self.assertEqual(api_summary["downstream_routes"], {"json": 1})
            self.assertEqual(api_summary["response_types"], {"application/json": 1})
            self.assertEqual(api_summary["response_byte_count"], 12)
            self.assertEqual(api_summary["redacted_responses"], 1)
            self.assertEqual(api_summary["routed_artifacts"], 1)
            self.assertFalse(api_summary["no_network"])
            self.assertFalse(api_summary["no_mutation"])
            self.assertFalse(api_summary["no_credentials_resolved"])
            self.assertFalse(api_summary["no_scheduler"])
            self.assertEqual(api_summary["diagnostic_counts"]["manifest_parse_error"], 1)
