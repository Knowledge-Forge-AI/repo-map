from repomap_test_support.policy_helper_branches import write_api_fixture
import json
import tempfile
import unittest
from pathlib import Path

from repomap_kg.ops.ingestion.api import (
    ApiPolicyError,
    FixtureApiTransport,
    acquire_api_source,
    build_api_plan_from_config,
    load_api_source_config,
)


class ApiIngestionUnitTests(unittest.TestCase):
    def test_api_config_requires_policy_consent_credential_limits_and_get_endpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            valid = self.write_api_fixture(root)
            blocked = self.write_api_fixture(root, policy_status="blocked")
            missing_consent = self.write_api_fixture(root, include_consent=False)
            invalid_credential = self.write_api_fixture(
                root,
                credentials_ref="plain-token-name",
            )
            mutation = self.write_api_fixture(root, method="POST")
            provider_class = self.write_api_fixture(
                root,
                api_source_class="api.email_provider",
            )

            config = load_api_source_config(valid)
            with self.assertRaisesRegex(ApiPolicyError, "policy status"):
                load_api_source_config(blocked)
            with self.assertRaisesRegex(ApiPolicyError, "consent"):
                load_api_source_config(missing_consent)
            with self.assertRaisesRegex(ApiPolicyError, "credentials_ref"):
                load_api_source_config(invalid_credential)
            with self.assertRaisesRegex(ApiPolicyError, "GET"):
                load_api_source_config(mutation)
            with self.assertRaisesRegex(ApiPolicyError, "api_source_class"):
                load_api_source_config(provider_class)

        self.assertEqual(config.source_id, "fixture-readonly-api")
        self.assertEqual(config.source_type, "api.rest")
        self.assertEqual(config.api_source_class, "api.custom_documented_api")
        self.assertEqual(config.credentials_ref, "local_secret_ref:fixture-api-token")
        self.assertEqual(config.endpoints[0].name, "items")
        self.assertEqual(config.endpoints[0].downstream_route, "config")

    def test_api_plan_is_deterministic_and_does_not_call_transport(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_api_fixture(Path(tmpdir))

            first = build_api_plan_from_config(config_path)
            second = build_api_plan_from_config(config_path)

        self.assertEqual(first.api_run_id, second.api_run_id)
        self.assertEqual(first.api_manifest_id, second.api_manifest_id)
        self.assertEqual(first.request_count, 1)
        self.assertEqual(first.requests[0].endpoint_name, "items")
        self.assertEqual(first.requests[0].method, "GET")
        self.assertEqual(first.requests[0].path, "/v1/items")
        payload = json.dumps(first.to_jsonable(), sort_keys=True)
        self.assertIn('"no_network": true', payload)
        self.assertIn('"no_mutation": true', payload)
        self.assertNotIn("fixture-api-token", payload)
        self.assertNotIn(str(config_path.parent), payload)

    def test_api_acquire_uses_fixture_transport_writes_artifacts_and_routes_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self.write_api_fixture(root)
            summary = acquire_api_source(
                config_path,
                root_path=root,
                transport=FixtureApiTransport(),
            )
            manifest_path = summary.output_path / "manifest.json"
            redacted_path = summary.output_path / "redacted-responses.jsonl"
            artifact_path = summary.output_path / "artifacts" / "items.json"
            manifest_exists = manifest_path.is_file()
            redacted_exists = redacted_path.is_file()
            artifact_exists = artifact_path.is_file()

        self.assertEqual(summary.source_id, "fixture-readonly-api")
        self.assertEqual(summary.requests, 1)
        self.assertEqual(summary.responses, 1)
        self.assertGreater(summary.observations, 0)
        self.assertEqual(summary.publication.publication_state, "not_published")
        self.assertTrue(manifest_exists)
        self.assertTrue(redacted_exists)
        self.assertTrue(artifact_exists)
        observation_payload = json.dumps(
            [observation.to_dict() for observation in summary.raw_observations],
            sort_keys=True,
        )
        self.assertIn('"api_run_id"', observation_payload)
        self.assertIn('"endpoint_name": "items"', observation_payload)
        self.assertIn('"api_retention_policy": "local_user_controlled"', observation_payload)
        self.assertIn("config.document", observation_payload)
        self.assertNotIn("fixture-secret-value", observation_payload)
        self.assertNotIn("fixture-api-token", observation_payload)
        summary_payload = json.dumps(summary.to_jsonable(), sort_keys=True)
        self.assertIn('"no_network": true', summary_payload)
        self.assertIn('"no_mutation": true', summary_payload)
        self.assertNotIn(str(root), summary_payload)
        self.assertNotIn("fixture-secret-value", summary_payload)

    def test_api_acquire_enforces_response_limits_before_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = self.write_api_fixture(root, max_bytes_per_run=10)

            with self.assertRaisesRegex(ApiPolicyError, "max_bytes_per_run"):
                acquire_api_source(
                    config_path,
                    root_path=root,
                    transport=FixtureApiTransport(),
                )

        self.assertFalse((root / ".repomap" / "api-runs").exists())

    write_api_fixture = staticmethod(write_api_fixture)
