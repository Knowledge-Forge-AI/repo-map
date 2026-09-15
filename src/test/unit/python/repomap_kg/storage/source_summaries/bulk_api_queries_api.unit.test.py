import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from repomap_kg.storage import (
    StorageSchemaError,
    build_api_summary_query_sql,
    query_api_summary,
)

class StorageSourceApiQueryUnitTests(unittest.TestCase):
    def test_query_api_summary_combines_manifests_and_api_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run_dir = root / ".repomap" / "api-runs" / "source-one" / "run-one"
            run_dir.mkdir(parents=True)
            (run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "api_run_id": "run-one",
                        "source_id": "source-one",
                        "source_type": "api.rest",
                        "api_source_class": "api.custom_documented_api",
                        "provider_name": "Fixture Provider",
                        "provider_product": "Fixture API",
                        "policy_status": "allowed_with_limits",
                        "requests": [
                            {
                                "endpoint_name": "items",
                                "method": "GET",
                                "path": "/v1/items",
                                "response_type": "application/json",
                                "downstream_route": "config",
                            }
                        ],
                        "responses": [
                            {
                                "endpoint_name": "items",
                                "method": "GET",
                                "path_template": "/v1/items",
                                "response_type": "application/json",
                                "response_byte_count": 512,
                                "redacted": True,
                                "downstream_route": "config",
                                "artifact_path": "artifacts/items.json",
                            }
                        ],
                        "no_network": True,
                        "no_mutation": True,
                        "no_credentials_resolved": True,
                        "no_scheduler": True,
                    }
                ),
                encoding="utf-8",
            )
            storage_payload = {
                "repository_name": "fixture",
                "observations_with_api_provenance": 7,
                "config_documents_from_api": 1,
            }

            with patch("repomap_kg.storage.summaries.execute_json_readback", return_value=storage_payload) as adapter:
                summary = query_api_summary(
                    ["-d", "postgres"],
                    root_path=str(root),
                    psql_command="/bin/psql",
                )

        self.assertEqual(summary.root_path_summary, ".")
        self.assertEqual(summary.repository_name, "fixture")
        self.assertEqual(summary.api_runs, 1)
        self.assertEqual(summary.sources, 1)
        self.assertEqual(summary.source_ids, ("source-one",))
        self.assertEqual(summary.source_types["api.rest"], 1)
        self.assertEqual(summary.api_source_classes["api.custom_documented_api"], 1)
        self.assertEqual(summary.provider_names["Fixture Provider"], 1)
        self.assertEqual(summary.provider_products["Fixture API"], 1)
        self.assertEqual(summary.policy_statuses["allowed_with_limits"], 1)
        self.assertEqual(summary.requests, 1)
        self.assertEqual(summary.responses, 1)
        self.assertEqual(summary.endpoints, 1)
        self.assertEqual(summary.endpoint_names, ("items",))
        self.assertEqual(summary.methods["GET"], 1)
        self.assertEqual(summary.downstream_routes["config"], 1)
        self.assertEqual(summary.response_types["application/json"], 1)
        self.assertEqual(summary.response_byte_count, 512)
        self.assertEqual(summary.redacted_responses, 1)
        self.assertEqual(summary.routed_artifacts, 1)
        self.assertEqual(summary.observations_with_api_provenance, 7)
        self.assertEqual(summary.config_documents_from_api, 1)
        self.assertTrue(summary.no_network)
        self.assertTrue(summary.no_mutation)
        self.assertTrue(summary.no_credentials_resolved)
        self.assertTrue(summary.no_scheduler)
        self.assertTrue(summary.no_provider_specific_behavior)
        self.assertEqual(adapter.call_args.args[0], build_api_summary_query_sql(str(root)))

    def test_query_api_summary_handles_false_safety_flags_and_bad_manifests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            good_run = root / ".repomap" / "api-runs" / "source-two" / "run-two"
            non_dict_run = root / ".repomap" / "api-runs" / "source-three" / "run-three"
            malformed_run = root / ".repomap" / "api-runs" / "source-four" / "run-four"
            good_run.mkdir(parents=True)
            non_dict_run.mkdir(parents=True)
            malformed_run.mkdir(parents=True)
            (good_run / "manifest.json").write_text(
                json.dumps(
                    {
                        "api_run_id": "run-two",
                        "source_id": "source-two",
                        "source_type": "api.rest",
                        "api_source_class": "api.custom_documented_api",
                        "provider_name": "Fixture Provider",
                        "provider_product": "Fixture API",
                        "policy_status": "allowed_with_limits",
                        "requests": [
                            {
                                "endpoint_name": "items",
                                "method": "GET",
                                "downstream_route": "graph",
                                "response_type": "application/json",
                            },
                            {
                                "endpoint_name": None,
                                "method": None,
                                "downstream_route": None,
                                "response_type": None,
                            },
                        ],
                        "responses": [
                            {
                                "endpoint_name": "items",
                                "response_byte_count": 128,
                                "redacted": False,
                                "artifact_path": None,
                            },
                            {
                                "endpoint_name": None,
                                "response_byte_count": 256,
                                "redacted": True,
                                "artifact_path": "artifacts/item.json",
                            },
                        ],
                        "no_network": False,
                        "no_mutation": False,
                        "no_credentials_resolved": False,
                        "no_scheduler": False,
                    }
                ),
                encoding="utf-8",
            )
            (non_dict_run / "manifest.json").write_text("[]\n", encoding="utf-8")
            (malformed_run / "manifest.json").write_text("{not-json", encoding="utf-8")
            storage_payload = {
                "repository_name": "fixture",
                "observations_with_api_provenance": 4,
                "config_documents_from_api": 2,
            }

            with patch("repomap_kg.storage.summaries.execute_json_readback", return_value=storage_payload):
                summary = query_api_summary(["-d", "postgres"], root_path=str(root))

        self.assertEqual(summary.api_runs, 1)
        self.assertEqual(summary.sources, 1)
        self.assertEqual(summary.requests, 2)
        self.assertEqual(summary.responses, 2)
        self.assertEqual(summary.endpoints, 1)
        self.assertEqual(summary.endpoint_names, ("items",))
        self.assertEqual(summary.methods["GET"], 1)
        self.assertEqual(summary.downstream_routes["graph"], 1)
        self.assertEqual(summary.response_types["application/json"], 1)
        self.assertEqual(summary.response_byte_count, 384)
        self.assertEqual(summary.redacted_responses, 1)
        self.assertEqual(summary.routed_artifacts, 1)
        self.assertEqual(summary.diagnostic_counts["manifest_parse_error"], 2)
        self.assertFalse(summary.no_network)
        self.assertFalse(summary.no_mutation)
        self.assertFalse(summary.no_credentials_resolved)
        self.assertFalse(summary.no_scheduler)

    def test_query_api_summary_empty_repo_returns_zero_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_payload = {
                "repository_name": None,
                "observations_with_api_provenance": 0,
                "config_documents_from_api": 0,
            }

            with patch("repomap_kg.storage.summaries.execute_json_readback", return_value=storage_payload):
                summary = query_api_summary(["-d", "postgres"], root_path=tmpdir)

        self.assertEqual(summary.api_runs, 0)
        self.assertEqual(summary.sources, 0)
        self.assertEqual(summary.requests, 0)
        self.assertEqual(summary.responses, 0)
        self.assertEqual(summary.observations_with_api_provenance, 0)
        self.assertEqual(summary.config_documents_from_api, 0)
        self.assertTrue(summary.no_network)
        self.assertTrue(summary.no_mutation)

    def test_query_api_summary_rejects_escaped_manifest_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with tempfile.TemporaryDirectory() as escaped_tmpdir:
                root = Path(tmpdir)
                escaped_root = Path(escaped_tmpdir) / "api-runs"
                escaped_root.mkdir()
                (root / ".repomap").mkdir()
                (root / ".repomap" / "api-runs").symlink_to(
                    escaped_root,
                    target_is_directory=True,
                )
                storage_payload = {
                    "repository_name": None,
                    "observations_with_api_provenance": 0,
                    "config_documents_from_api": 0,
                }

                with patch("repomap_kg.storage.summaries.execute_json_readback", return_value=storage_payload):
                    summary = query_api_summary(["-d", "postgres"], root_path=tmpdir)

        self.assertEqual(summary.api_runs, 0)
        self.assertEqual(summary.sources, 0)
        self.assertEqual(summary.diagnostic_counts["manifest_parse_error"], 1)
        self.assertTrue(summary.no_network)

    def test_query_api_summary_rejects_malformed_storage_json(self):
        storage_payload = {"repository_name": "fixture"}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("repomap_kg.storage.summaries.execute_json_readback", return_value=storage_payload):
                with self.assertRaisesRegex(StorageSchemaError, "api summary"):
                    query_api_summary(["-d", "postgres"], root_path=tmpdir)
