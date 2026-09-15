import json
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.mcp_server import McpServerTestSupport


class McpServerObservationPolicyUnitTests(McpServerTestSupport):
    def test_mcp_harden5_observation_raw_payload_policy_contract(self):
        from repomap_kg.server.mcp import repomap_search_observations

        config_path = self.write_visible_ops_config()
        safe_metadata = {"safe_label": "safe-value", "command": "echo 1"}
        payload_false = {
            "results": [
                {"ordinal": 1, "kind": "command.reference", "path": "synthetic/config.txt", "source_id": "synthetic/config.txt#command:1", "metadata": safe_metadata},
                {"ordinal": 2, "kind": "command.reference", "path": "synthetic/config.txt", "source_id": "synthetic/config.txt#command:2", "metadata": {"safe_label": "bounded-away"}},
            ],
            "total": 5, "has_more": False,
        }
        payload_true = {
            "results": [{
                "ordinal": 1, "kind": "command.reference", "path": "synthetic/config.txt", "source_id": "synthetic/config.txt#command:1",
                "metadata": safe_metadata, "payload": {"kind": "command.reference", "metadata": safe_metadata},
            }],
            "total": 1, "has_more": False,
        }
        cases = [
            ("include_raw_false", False, 1, 0, payload_false, 5, True),
            ("include_raw_true", True, 2, 0, payload_true, 1, False),
        ]
        with self.patch_ops_config(config_path):
            for label, include_raw, limit, offset, query_payload, expected_total, expected_has_more in cases:
                with self.subTest(policy=label):
                    with patch("repomap_kg.server.ops.query_mcp_search", return_value=query_payload) as query:
                        payload = repomap_search_observations(
                            graph_id="repo-map", query="command", kind="command.reference",
                            path="synthetic/config.txt", limit=limit, offset=offset, include_raw=include_raw,
                        )
                    self.assert_observation_search_payload_contract(
                        payload, query="command", kind="command.reference", path="synthetic/config.txt",
                        limit=limit, offset=offset, total=expected_total, has_more=expected_has_more, include_raw=include_raw,
                    )
                    self.assert_public_graph_payload(payload["graph"])
                    self.assertEqual(query.call_args.kwargs["target"], "observations")
                    self.assertEqual(query.call_args.kwargs["query"], "command")
                    self.assertEqual(query.call_args.kwargs["kind"], "command.reference")
                    self.assertEqual(query.call_args.kwargs["path"], "synthetic/config.txt")
                    self.assertEqual(query.call_args.kwargs["limit"], limit)
                    self.assertEqual(query.call_args.kwargs["offset"], offset)
                    self.assertEqual(query.call_args.kwargs["include_raw"], include_raw)
                    self.assertEqual(payload["results"][0]["metadata"], safe_metadata)
                    if include_raw:
                        self.assertIn("payload", payload["results"][0])
                        self.assertEqual(payload["results"][0]["payload"]["metadata"], safe_metadata)
                    else:
                        self.assertNotIn("payload", payload["results"][0])
                        self.assertFalse(payload["raw_payload_policy"]["payload_included"])
                        self.assertTrue(payload["raw_payload_policy"]["metadata_included"])

    def test_mcp_harden5_observation_include_raw_schema_contract(self):
        from repomap_kg.server.mcp import tool_input_schema

        schema = tool_input_schema("repomap_search_observations")
        include_raw_schema = schema["properties"]["include_raw"]
        self.assertEqual(include_raw_schema["type"], "boolean")
        self.assertEqual(
            include_raw_schema["description"],
            "Include the full raw payload field. Observation metadata is still returned when this is false.",
        )
        self.assertNotIn("include_raw", schema.get("required", []))

    def test_mcp_harden5_observation_search_redacts_secret_metadata_but_retains_safe_metadata(self):
        from repomap_kg.server.mcp import repomap_search_observations

        config_path = self.write_visible_ops_config()
        secret_token, credentialed_url = "mcp-harden5-secret-value", "https://user:password@example.invalid/private.git"
        safe_label, safe_url = "mcp-harden5-safe-metadata", "https://example.invalid/public.git"
        observation_payload = {
            "results": [{
                "ordinal": 1, "kind": "command.reference", "path": "synthetic/config.txt",
                "source_id": "synthetic/config.txt#command:1",
                "metadata": {"token": secret_token, "repository_url": credentialed_url, "safe_label": safe_label, "safe_url": safe_url, "raw": "synthetic public observation text"},
            }],
            "total": 1, "has_more": False,
        }
        with self.patch_ops_config(config_path):
            with patch("repomap_kg.server.ops.query_mcp_search", return_value=observation_payload) as query:
                payload = repomap_search_observations(graph_id="repo-map", query="command", include_raw=False)

        self.assert_observation_search_payload_contract(payload, query="command", limit=20, offset=0, total=1, has_more=False, include_raw=False)
        self.assert_public_graph_payload(payload["graph"])
        self.assertFalse(query.call_args.kwargs["include_raw"])
        metadata = payload["results"][0]["metadata"]
        self.assertEqual(metadata["safe_label"], safe_label)
        self.assertEqual(metadata["safe_url"], safe_url)
        self.assertEqual(metadata["raw"], "synthetic public observation text")
        serialized = json.dumps(payload, sort_keys=True)
        for hidden in (secret_token, credentialed_url, "user:password"):
            self.assertNotIn(hidden, serialized)
        self.assertIn("[REDACTED]", serialized)

    def test_mcp_harden5_observation_search_bounded_payload_contract(self):
        from repomap_kg.server.mcp import repomap_search_observations

        config_path = self.write_visible_ops_config()
        observation_payload = {
            "results": [
                {"ordinal": 1, "kind": "command.reference", "path": "synthetic/config.txt", "source_id": "synthetic/config.txt#command:1", "metadata": {"safe_label": "first"}},
                {"ordinal": 2, "kind": "command.reference", "path": "synthetic/config.txt", "source_id": "synthetic/config.txt#command:2", "metadata": {"safe_label": "second"}},
                {"ordinal": 3, "kind": "command.reference", "path": "synthetic/config.txt", "source_id": "synthetic/config.txt#command:3", "metadata": {"safe_label": "third"}},
            ],
            "total": 9, "has_more": False,
        }
        with self.patch_ops_config(config_path):
            with patch("repomap_kg.server.ops.query_mcp_search", return_value=observation_payload) as query:
                payload = repomap_search_observations(
                    graph_id="repo-map", query="command", kind="command.reference",
                    path="synthetic/config.txt", limit=2, offset=4, include_raw=False,
                )

        self.assert_observation_search_payload_contract(payload, query="command", kind="command.reference", path="synthetic/config.txt", limit=2, offset=4, total=9, has_more=True, include_raw=False)
        self.assert_public_graph_payload(payload["graph"])
        self.assertEqual([r["source_id"] for r in payload["results"]], ["synthetic/config.txt#command:1", "synthetic/config.txt#command:2"])
        self.assertEqual(query.call_args.kwargs["target"], "observations")
        self.assertEqual(query.call_args.kwargs["query"], "command")
        self.assertEqual(query.call_args.kwargs["limit"], 2)
        self.assertEqual(query.call_args.kwargs["offset"], 4)
        self.assertFalse(query.call_args.kwargs["include_raw"])

    def test_live_ops8_private_observation_search_redacts_config_path_value_summary(self):
        from repomap_kg.server.mcp import repomap_search_observations

        synthetic_user = "synthetic-live-user"
        private_root = f"/Users/{synthetic_user}/private-visible"
        private_value = f"{private_root}/profiles/{synthetic_user}/config.toml"
        config_path = self.write_live_ops8_private_ops_config(private_root)
        observation_payload = {
            "results": [{
                "ordinal": 1, "kind": "config.path", "path": "flake.nix", "source_id": "flake.nix#config-path:1",
                "metadata": {"pointer": "/profiles", "value_summary": private_value, "safe_label": "kept", "token": "synthetic-token"},
            }],
            "total": 1, "has_more": False,
        }
        with self.patch_ops_config(config_path):
            with patch("repomap_kg.server.ops.query_mcp_search", return_value=observation_payload) as query:
                payload = repomap_search_observations(graph_id="private-visible", query="config.path", kind="config.path", include_raw=False)

        self.assert_observation_search_payload_contract(payload, query="config.path", kind="config.path", limit=20, offset=0, total=1, has_more=False, include_raw=False)
        self.assert_private_graph_payload(payload["graph"])
        self.assertFalse(query.call_args.kwargs["include_raw"])
        self.assertNotIn("payload", payload["results"][0])
        metadata = payload["results"][0]["metadata"]
        self.assertEqual(metadata["pointer"], "/profiles")
        self.assertEqual(metadata["safe_label"], "kept")
        self.assertEqual(metadata["value_summary"], "[private-path]")
        serialized = json.dumps(payload, sort_keys=True)
        for token in (
            private_root, private_value, synthetic_user, str(Path.home()),
            Path.home().name, str(config_path), "docker exec", "pg_dump",
            "pg_restore", "POSTGRES_PASSWORD", "PGPASSWORD", "synthetic-token", "synthetic-secret",
        ):
            self.assertNotIn(token, serialized)

    def test_live_ops8_private_observation_include_raw_does_not_bypass_redaction(self):
        from repomap_kg.server.mcp import repomap_search_observations

        synthetic_user = "synthetic-live-user"
        private_root = f"/Users/{synthetic_user}/private-visible"
        private_value = f"{private_root}/profiles/{synthetic_user}/config.toml"
        config_path = self.write_live_ops8_private_ops_config(private_root)
        raw_payload = {
            "kind": "config.path", "path": "flake.nix",
            "metadata": {"pointer": "/profiles", "value_summary": private_value, "nested": {"path": private_value}},
            "target": private_value,
        }
        observation_payload = {
            "results": [{
                "ordinal": 1, "kind": "config.path", "path": "flake.nix", "source_id": "flake.nix#config-path:1",
                "metadata": {"pointer": "/profiles", "value_summary": private_value, "safe_label": "kept", "token": "synthetic-token"},
                "payload": raw_payload,
            }],
            "total": 1, "has_more": False,
        }
        with self.patch_ops_config(config_path):
            with patch("repomap_kg.server.ops.query_mcp_search", return_value=observation_payload) as query:
                payload = repomap_search_observations(graph_id="private-visible", query="config.path", kind="config.path", include_raw=True)

        self.assert_observation_search_payload_contract(payload, query="config.path", kind="config.path", limit=20, offset=0, total=1, has_more=False, include_raw=True)
        self.assert_private_graph_payload(payload["graph"])
        self.assertTrue(query.call_args.kwargs["include_raw"])
        self.assertIn("payload", payload["results"][0])
        result = payload["results"][0]
        self.assertEqual(result["metadata"]["pointer"], "/profiles")
        self.assertEqual(result["metadata"]["safe_label"], "kept")
        self.assertEqual(result["metadata"]["value_summary"], "[private-path]")
        raw_result = result["payload"]
        self.assertEqual(raw_result["kind"], "config.path")
        self.assertEqual(raw_result["path"], "flake.nix")
        self.assertEqual(raw_result["metadata"]["pointer"], "/profiles")
        self.assertEqual(raw_result["metadata"]["value_summary"], "[private-path]")
        self.assertEqual(raw_result["metadata"]["nested"]["path"], "[private-path]")
        self.assertEqual(raw_result["target"], "[private-path]")
        serialized = json.dumps(payload, sort_keys=True)
        for token in (
            private_root, private_value, synthetic_user, str(Path.home()),
            Path.home().name, str(config_path), "docker exec", "pg_dump",
            "pg_restore", "POSTGRES_PASSWORD", "PGPASSWORD", "synthetic-token", "synthetic-secret",
        ):
            self.assertNotIn(token, serialized)

    def test_live_ops8_public_observation_search_preserves_safe_metadata(self):
        from repomap_kg.server.mcp import repomap_search_observations

        config_path = self.write_visible_ops_config()
        safe_value = "/opt/repo-map/public-config.toml"
        observation_payload = {
            "results": [{
                "ordinal": 1, "kind": "config.path", "path": "pyproject.toml", "source_id": "pyproject.toml#config-path:1",
                "metadata": {"pointer": "/tool", "value_summary": safe_value, "safe_label": "kept"},
                "payload": {"kind": "config.path", "metadata": {"pointer": "/tool", "value_summary": safe_value}},
            }],
            "total": 1, "has_more": False,
        }
        with self.patch_ops_config(config_path):
            with patch("repomap_kg.server.ops.query_mcp_search", return_value=observation_payload):
                payload = repomap_search_observations(graph_id="repo-map", query="config.path", kind="config.path", include_raw=True)

        self.assert_public_graph_payload(payload["graph"])
        self.assertEqual(payload["results"][0]["metadata"]["value_summary"], safe_value)
        self.assertEqual(payload["results"][0]["payload"]["metadata"]["value_summary"], safe_value)

    def test_live_ops8_config_path_metadata_redaction_keeps_payload_bounded(self):
        from repomap_kg.server.mcp import repomap_search_observations

        synthetic_user = "synthetic-live-user"
        private_root = f"/Users/{synthetic_user}/private-visible"
        private_value = f"{private_root}/profiles/{synthetic_user}/config.toml"
        config_path = self.write_live_ops8_private_ops_config(private_root)
        observation_payload = {
            "results": [
                {"ordinal": 1, "kind": "config.path", "path": "flake.nix", "source_id": "flake.nix#config-path:1", "metadata": {"value_summary": private_value}},
                {"ordinal": 2, "kind": "config.path", "path": "flake.nix", "source_id": "flake.nix#config-path:2", "metadata": {"value_summary": private_value}},
            ],
            "total": 9, "has_more": False,
        }
        with self.patch_ops_config(config_path):
            with patch("repomap_kg.server.ops.query_mcp_search", return_value=observation_payload) as query:
                payload = repomap_search_observations(graph_id="private-visible", query="config.path", kind="config.path", limit=1, offset=3, include_raw=False)

        self.assert_observation_search_payload_contract(payload, query="config.path", kind="config.path", limit=1, offset=3, total=9, has_more=True, include_raw=False)
        self.assertEqual(payload["result_count"], 1)
        self.assertEqual(len(payload["results"]), 1)
        self.assert_read_only_payload(payload)
        self.assertEqual(query.call_args.kwargs["limit"], 1)
        self.assertEqual(query.call_args.kwargs["offset"], 3)
        self.assertEqual(payload["results"][0]["metadata"]["value_summary"], "[private-path]")
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn(private_value, serialized)
        self.assertNotIn(synthetic_user, serialized)
