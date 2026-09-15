import tempfile
import unittest
from pathlib import Path

from repomap_test_support.github_api_ingestion import GitHubApiIngestionTestSupport

from repomap_kg.ops.ingestion import github_api as github


class GitHubApiIngestionHelperBranchUnitTests(unittest.TestCase):
    def test_github_payload_validation_helpers_cover_safe_error_branches(self):
        self.assertEqual(github.count_response_items([1, 2]), 2)
        self.assertEqual(github.count_response_items({"workflow_runs": [1, 2, 3]}), 3)
        self.assertEqual(github.count_response_items({"workflow_runs": "not-list"}), 1)
        self.assertEqual(github.count_response_items("scalar"), 1)
        self.assertEqual(github.parse_json_response(b'{"ok": true}', "repo"), {"ok": True})
        for body in (b"\xff", b"{not-json"):
            with self.subTest(body=body):
                with self.assertRaises(github.GitHubApiPolicyError):
                    github.parse_json_response(body, "repo")

        self.assertEqual(github.literal_type(None), "null")
        self.assertEqual(github.literal_type(True), "bool")
        self.assertEqual(github.literal_type(7), "number")
        self.assertEqual(github.literal_type("value"), "string")
        self.assertEqual(github.literal_type(["value"]), "array")
        self.assertEqual(github.literal_type({"value": 1}), "object")
        self.assertEqual(github.literal_type(object()), "object")

        self.assertEqual(
            github.redact_github_value("body text", key="body")["body_length"],
            9,
        )
        self.assertFalse(github.redact_github_value(None, key="body")["body_present"])
        self.assertEqual(
            github.redact_github_value("secret", key="api-token")["redaction_reason"],
            "secret_key",
        )
        self.assertEqual(
            github.redact_github_value(
                "https://example.invalid/path?token=secret",
            )["redaction_reason"],
            "sensitive_url",
        )
        self.assertEqual(
            github.redact_github_value(
                {"items": [{"token": "secret"}, {"safe": "value"}]},
            )["items"][0]["token"]["redaction_reason"],
            "secret_key",
        )

        self.assertEqual(github.required_table({"source": {"id": "x"}}, "source"), {"id": "x"})
        with self.assertRaises(github.GitHubApiPolicyError):
            github.required_table({"source": []}, "source")

        endpoints = github.required_endpoint_list({"endpoints": [{"name": "repo"}]})
        self.assertEqual(endpoints[0]["name"], "repo")
        bad_endpoints_payloads: tuple[dict[str, list[str] | str], ...] = (
            {"endpoints": []}, {"endpoints": "bad"}, {"endpoints": ["bad"]},
        )
        for ep_payload in bad_endpoints_payloads:
            with self.subTest(payload=ep_payload):
                with self.assertRaises(github.GitHubApiPolicyError):
                    github.required_endpoint_list(ep_payload)

        self.assertEqual(github.required_string({"name": " repo "}, "name"), " repo ")
        for str_payload in ({}, {"name": ""}, {"name": 7}):
            with self.subTest(payload=str_payload):
                with self.assertRaises(github.GitHubApiPolicyError):
                    github.required_string(str_payload, "name")
        self.assertIsNone(github.optional_string({}, "name"))
        self.assertEqual(github.optional_string({"name": " repo "}, "name"), " repo ")
        with self.assertRaises(github.GitHubApiPolicyError):
            github.optional_string({"name": 7}, "name")

        self.assertEqual(github.required_positive_int({"limit": 1}, "limit"), 1)
        for int_payload in ({}, {"limit": True}, {"limit": 0}):
            with self.subTest(payload=int_payload):
                with self.assertRaises(github.GitHubApiPolicyError):
                    github.required_positive_int(int_payload, "limit")
        self.assertEqual(github.optional_positive_int({}, "limit", default=3), 3)
        with self.assertRaises(github.GitHubApiPolicyError):
            github.optional_positive_int({"limit": False}, "limit", default=3)
        self.assertEqual(github.required_nonnegative_int({"limit": 0}, "limit"), 0)
        with self.assertRaises(github.GitHubApiPolicyError):
            github.required_nonnegative_int({"limit": -1}, "limit")
        self.assertTrue(github.required_bool({"flag": True}, "flag"))
        with self.assertRaises(github.GitHubApiPolicyError):
            github.required_bool({}, "flag")
        with self.assertRaises(github.GitHubApiPolicyError):
            github.required_bool({"flag": "true"}, "flag")
        self.assertFalse(github.optional_bool({}, "flag", default=False))
        with self.assertRaises(github.GitHubApiPolicyError):
            github.optional_bool({"flag": "false"}, "flag", default=False)
        self.assertEqual(github.string_tuple(["a", "b"]), ("a", "b"))
        for value in ("bad", ["a", 2]):
            with self.subTest(value=value):
                with self.assertRaises(github.GitHubApiPolicyError):
                    github.string_tuple(value)

    def test_github_transport_dispatch_helpers_cover_safe_error_branches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_case = GitHubApiIngestionTestSupport()
            fixture_path = fixture_case.write_github_fixture(Path(tmpdir))
            config = github.load_github_api_source_config(fixture_path)
            endpoint = github.endpoint_by_name(config, "repository")
            request = github.build_github_api_plan_from_config(fixture_path).requests[0]

        self.assertEqual(endpoint.name, "repository")
        with self.assertRaises(github.GitHubApiPolicyError):
            github.endpoint_by_name(config, "missing")
        self.assertIsInstance(github.github_transport_for_config(config), github.FixtureGitHubApiTransport)
        public_config = config.__class__(
            **{**config.__dict__, "acquisition_transport": "github_public_rest"}
        )
        self.assertIsInstance(
            github.github_transport_for_config(public_config),
            github.PublicGitHubRestTransport,
        )
        bad_config = config.__class__(**{**config.__dict__, "acquisition_transport": "bad"})
        with self.assertRaises(github.GitHubApiPolicyError):
            github.github_transport_for_config(bad_config)

        ok_response = github.GitHubTransportResponse(
            status_code=200,
            body=b"{}",
            response_type="application/json",
        )
        github.validate_transport_response(config, request, ok_response)
        error_cases = (
            github.GitHubTransportResponse(
                status_code=302,
                body=b"{}",
                response_type="application/json",
            ),
            github.GitHubTransportResponse(
                status_code=200,
                body=b"{}",
                response_type="application/json",
                rate_limit={"x-ratelimit-remaining": "0"},
            ),
            github.GitHubTransportResponse(
                status_code=500,
                body=b"{}",
                response_type="application/json",
            ),
            github.GitHubTransportResponse(
                status_code=200,
                body=b"{}",
                response_type="text/plain",
            ),
            github.GitHubTransportResponse(
                status_code=200,
                body=b"x" * (config.max_bytes_per_run + 1),
                response_type="application/json",
            ),
        )
        for response in error_cases:
            with self.subTest(status=response.status_code, response_type=response.response_type):
                with self.assertRaises(github.GitHubApiPolicyError):
                    github.validate_transport_response(config, request, response)
