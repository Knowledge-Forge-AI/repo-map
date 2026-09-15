import json
from unittest.mock import patch

from repomap_kg.storage import (
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    JSFrameworkSummaryRecord,
    OpenAPISummaryRecord,
    PythonSummaryRecord,
    TerraformSummaryRecord,
)

from repomap_test_support.mcp_server import McpServerTestSupport


def _make_record(cls, **kwargs):
    rec = cls.__new__(cls)
    rec.__dict__.update(kwargs)
    return rec


class McpServerPrivatePayloadRedactionDomainsUnitTests(McpServerTestSupport):
    def test_mcp_harden3_private_graph_payloads_never_serialize_private_roots(
        self,
    ):
        from repomap_kg.server.mcp import (
            repomap_graph_status,
            repomap_list_graphs,
            repomap_neighborhood,
            repomap_projects,
            repomap_search_files,
        )
        from repomap_kg.ops.refresh import OpsRefreshGraphStatus

        mcp_config_path = self.write_empty_mcp_config()
        ops_config_path = self.write_visible_ops_config()
        private_status = OpsRefreshGraphStatus(
            graph_id="private-visible",
            repository_name="private-visible",
            privacy="private-ops",
            enabled=True,
            mcp_visible=True,
            refresh_policy="manual",
            root_path_display="[private-root]",
            root_path_expanded="[private-root]",
            repository_exists=True,
            latest_run_id=88,
            latest_run_status="complete",
            latest_run_started_at="2026-07-01T00:00:00Z",
            latest_run_finished_at="2026-07-01T00:01:00Z",
            raw_observations=3,
            canonical_nodes=2,
            canonical_edges=1,
        )
        neighborhood = CanonicalNeighborhoodRecord(
            center=CanonicalNodeRecord(
                canonical_key="python.module:private.visible",
                graph_key_version=1,
                kind="python.module",
                display_name="private.visible",
                confidence="extracted",
                conflict=False,
                metadata={},
                first_seen_run_id=1,
                last_seen_run_id=2,
            ),
            nodes=(),
            edges=(),
        )
        cases = [
            ("list_graphs", None, None, repomap_list_graphs, lambda p: p["graphs"][1], True),
            ("projects_hint", None, None, repomap_projects, lambda p: {g["graph_id"]: g for g in p["graphs"]}["private-visible"], False),
            ("graph_status", "repomap_kg.server.ops.query_refresh_status", {"private-visible": private_status},
             lambda: repomap_graph_status(graph_id="private-visible"), lambda p: p["graph"], True),
            ("neighborhood", "repomap_kg.server.ops.query_canonical_neighborhood", neighborhood,
             lambda: repomap_neighborhood(graph_id="private-visible", node="python.module:private.visible"), lambda p: p["graph"], True),
            ("search_files", "repomap_kg.server.ops.query_mcp_search", {"results": [{"path": "src/private_visible.py", "metadata": {"origin": "synthetic-fixture"}}], "total": 1},
             lambda: repomap_search_files(graph_id="private-visible", query="private"), lambda p: p["graph"], True),
        ]

        with self.patch_mcp_and_ops_config(mcp_config_path, ops_config_path):
            for label, patch_target, patch_val, call_fn, get_graph, read_only in cases:
                with self.subTest(tool=label):
                    if patch_target is None:
                        payload = call_fn()
                    else:
                        with patch(patch_target, return_value=patch_val):
                            payload = call_fn()
                    if read_only:
                        self.assert_read_only_payload(payload)
                    self.assert_private_graph_payload(get_graph(payload))
                    self.assert_no_synthetic_private_root(payload)

    def test_mcp_harden3_private_summary_roots_are_redacted_across_domains(
        self,
    ):
        from repomap_kg.server.mcp import (
            repomap_js_framework_summary,
            repomap_openapi_summary,
            repomap_python_summary,
            repomap_terraform_summary,
        )

        config_path = self.write_visible_ops_config()
        secret_token = "mcp-harden3-secret-value"
        credentialed_url = "https://user:password@example.invalid/private.git"
        nested_sensitive_metadata = {
            "root_path": "synthetic-private-root",
            "root_path_display": "synthetic-private-root",
            "root_path_expanded": "synthetic-private-root",
            "api_key": secret_token,
            "repository_url": credentialed_url,
        }
        cases = [
            ("python", "repomap_kg.server.ops.query_python_summary", _make_record(
                PythonSummaryRecord, root_path="synthetic-private-root", repository_name="private-visible", python_observations=3,
                package_files={"pyproject": 1}, packaging={}, tests={}, frameworks={}, references={}, redactions={},
                diagnostics=nested_sensitive_metadata, generic_python={}, generic_config={"source": nested_sensitive_metadata},
                dogfooding={}, safety={"no_execution": True},
            ), lambda: repomap_python_summary(graph_id="private-visible")),
            ("terraform", "repomap_kg.server.ops.query_terraform_summary", _make_record(
                TerraformSummaryRecord, root_path="synthetic-private-root", repository_name="private-visible", terraform_observations=4,
                terraform_files=2, file_families={}, terraform={}, references={}, tfvars={"sensitive": nested_sensitive_metadata},
                redactions={}, diagnostics=nested_sensitive_metadata, generic_config={}, safety={"no_execution": True},
            ), lambda: repomap_terraform_summary(graph_id="private-visible")),
            ("openapi", "repomap_kg.server.ops.query_openapi_summary", _make_record(
                OpenAPISummaryRecord, root_path="synthetic-private-root", repository_name="private-visible", openapi_observations=5,
                openapi_documents=1, spec_families={"openapi3": 1}, openapi={}, methods={}, references={"source": nested_sensitive_metadata},
                redactions={}, diagnostics={}, generic_config={}, safety={"no_fetch": True},
            ), lambda: repomap_openapi_summary(graph_id="private-visible")),
            ("js_framework", "repomap_kg.server.ops.query_js_framework_summary", _make_record(
                JSFrameworkSummaryRecord, root_path="synthetic-private-root", repository_name="private-visible", framework_observations=6,
                framework_profiles={"node": 1}, node=nested_sensitive_metadata, express={}, nest={}, next={}, jest={}, jquery={},
                generic_js={}, diagnostics={}, safety={"no_execution": True},
            ), lambda: repomap_js_framework_summary(graph_id="private-visible")),
        ]

        with self.patch_ops_config(config_path):
            for label, patch_target, patch_val, call_fn in cases:
                with self.subTest(summary=label):
                    with patch(patch_target, return_value=patch_val):
                        payload = call_fn()
                    self.assert_read_only_payload(payload)
                    self.assert_private_graph_payload(payload["graph"])
                    self.assertEqual(payload["summary"]["root_path"], "[private-root]")
                    self.assert_no_synthetic_private_root(payload, secret_token, credentialed_url)

    def test_mcp_harden3_search_payloads_redact_secret_like_metadata(self):
        from repomap_kg.server.mcp import (
            repomap_search_files,
            repomap_search_nodes,
            repomap_search_observations,
        )

        config_path = self.write_visible_ops_config()
        secret_token = "mcp-harden3-secret-value"
        credentialed_url = "https://user:password@example.invalid/private.git"
        nodes_payload = {
            "results": [{"canonical_key": "python.module:private.visible", "kind": "python.module", "display_name": "private.visible",
                         "metadata": {"api_key": secret_token, "repository_url": credentialed_url}}],
            "total": 1,
        }
        obs_payload = {
            "results": [{"ordinal": 1, "kind": "command.reference", "path": "synthetic/private.txt",
                         "source_id": "synthetic/private.txt#command:1",
                         "metadata": {"token": secret_token, "repository_url": credentialed_url, "raw": "synthetic public command text"}}],
            "total": 1,
        }
        files_payload = {
            "results": [{"path": "src/private_visible.py", "language": "python",
                         "metadata": {"password": secret_token, "repository_url": credentialed_url}}],
            "total": 1,
        }
        cases = [
            ("nodes", lambda: repomap_search_nodes(graph_id="private-visible", query="private"), nodes_payload, None),
            ("observations", lambda: repomap_search_observations(graph_id="private-visible", query="command", include_raw=False), obs_payload, False),
            ("files", lambda: repomap_search_files(graph_id="private-visible", query="private"), files_payload, None),
        ]

        with self.patch_ops_config(config_path):
            for target_name, call_fn, ret_payload, include_raw in cases:
                with self.subTest(target=target_name):
                    with patch("repomap_kg.server.ops.query_mcp_search", return_value=ret_payload) as query:
                        payload = call_fn()
                    self.assert_read_only_payload(payload)
                    self.assert_private_graph_payload(payload["graph"])
                    self.assertEqual(payload["target"], target_name)
                    self.assertEqual(payload["result_count"], 1)
                    self.assert_no_synthetic_private_root(payload, secret_token, credentialed_url)
                    self.assertIn("[REDACTED]", json.dumps(payload, sort_keys=True))
                    if include_raw is not None:
                        self.assert_raw_payload_policy(payload, include_raw=bool(include_raw))
                        self.assertFalse(query.call_args.kwargs["include_raw"])
