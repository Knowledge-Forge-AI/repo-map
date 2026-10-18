"""Unit tests for the repomap_similar_nodes MCP tool and dispatch surface."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from repomap_kg.ops.config_local import LocalSqliteConfig
from repomap_kg.server._mcp_dispatch import TOOL_FUNCTIONS
from repomap_kg.server._mcp_similar import (
    SimilarNodesQuery,
    similar_nodes_payload,
)
from repomap_kg.server.mcp import (
    handle_jsonrpc_message,
    handle_tool_call,
    repomap_similar_nodes as facade_similar_nodes,
    similar_nodes_payload as facade_similar_nodes_payload,
)
from repomap_kg.server.sqlite_read_binding import SqliteInvestigationStores
from repomap_kg.storage.semantic_candidates import CandidateResult
from repomap_test_support.mcp_server import McpServerTestSupport


class SimilarNodesUnitTest(McpServerTestSupport):
    """Test suite for repomap_similar_nodes tool reachability and validation."""

    def _call_rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            message["params"] = params
        response = handle_jsonrpc_message(message)
        self.assertIsNotNone(response)
        assert response is not None
        return response

    def _call_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._call_rpc("tools/call", {"name": "repomap_similar_nodes", "arguments": arguments})

    def _valid_args(self, **overrides: Any) -> dict[str, Any]:
        args: dict[str, Any] = {
            "graph_id": "repo-map",
            "canonical_key": "symbol:main",
            "rebuild_id": "rebuild-20261008-01",
            "profile_identity": "sha256:" + "0" * 64,
            "dimensions": 128,
        }
        args.update(overrides)
        return args

    def test_tools_list_advertises_repomap_similar_nodes_contract(self) -> None:
        response = self._call_rpc("tools/list")
        tools = response["result"]["tools"]
        tool = next((t for t in tools if t["name"] == "repomap_similar_nodes"), None)
        self.assertIsNotNone(tool)
        assert tool is not None
        schema = tool["inputSchema"]
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["additionalProperties"], False)
        self.assertEqual(
            schema["required"],
            ["graph_id", "canonical_key", "rebuild_id", "profile_identity", "dimensions"],
        )
        self.assertNotIn("vector", schema["properties"])
        self.assertIn("selected", schema["properties"])
        self.assertIn("limit", schema["properties"])
        self.assertIn("evidence_limit", schema["properties"])
        self.assertIn("source_binding_id", schema["properties"])
        self.assertIn("kind", schema["properties"])
        self.assertIn("path", schema["properties"])

    def test_similar_nodes_baseline_disabled_outcome(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            response = self._call_tool(self._valid_args())
        self.assertNotIn("error", response)
        result = response["result"]
        self.assertFalse(result.get("isError", False))
        payload = result["structuredContent"]
        self.assert_read_only_payload(payload)
        self.assert_public_graph_payload(payload["graph"])
        self.assertEqual(payload["capability"], "pgvector-candidates-v1")
        self.assertEqual(payload["status"], "capability_unavailable")
        self.assertEqual(payload["reason"], "disabled")
        self.assertEqual(payload["candidates"], [])

    def test_similar_nodes_sqlite_unsupported_outcome(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())

        def sqlite_factory(config: Any) -> SqliteInvestigationStores:
            local = LocalSqliteConfig(
                config.config_path,
                config.config_home,
                config.config_files,
                config.schema_version,
                config.service,
                config.graphs,
                config.server_memory,
                config.sources,
            )
            return SqliteInvestigationStores(local)

        with env, patch("repomap_kg.server.ops.investigation_stores", sqlite_factory):
            disabled_resp = self._call_tool(self._valid_args(selected=False))
            unsupported_resp = self._call_tool(self._valid_args(selected=True))

        disabled_payload = disabled_resp["result"]["structuredContent"]
        self.assertEqual(disabled_payload["status"], "capability_unavailable")
        self.assertEqual(disabled_payload["reason"], "disabled")
        self.assertEqual(disabled_payload["graph"]["database_source"], "sqlite-graph-file")

        unsupported_payload = unsupported_resp["result"]["structuredContent"]
        self.assertEqual(unsupported_payload["status"], "capability_unavailable")
        self.assertEqual(unsupported_payload["reason"], "sqlite_unsupported")
        self.assertEqual(unsupported_payload["graph"]["database_source"], "sqlite-graph-file")

    def test_similar_nodes_hidden_graph_refusal(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            response = self._call_tool(self._valid_args(graph_id="hidden"))
        result = response["result"]
        self.assertTrue(result.get("isError", False))
        self.assertIn("graph 'hidden' is not MCP-visible", result["content"][0]["text"])

    def test_similar_nodes_disabled_graph_refusal(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            response = self._call_tool(self._valid_args(graph_id="disabled"))
        result = response["result"]
        self.assertTrue(result.get("isError", False))
        self.assertIn("graph 'disabled' is not enabled", result["content"][0]["text"])

    def test_similar_nodes_unknown_graph_refusal(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            response = self._call_tool(self._valid_args(graph_id="unknown-graph-id"))
        result = response["result"]
        self.assertTrue(result.get("isError", False))
        self.assertIn("unknown graph_id: unknown-graph-id", result["content"][0]["text"])

    def test_similar_nodes_private_graph_outcome(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            response = self._call_tool(self._valid_args(graph_id="private-visible", selected=True))
        self.assertNotIn("error", response)
        result = response["result"]
        payload = result["structuredContent"]
        self.assert_private_graph_payload(payload["graph"])
        self.assertEqual(payload["status"], "capability_unavailable")
        self.assertEqual(payload["reason"], "private_graph_unsupported")

    def test_similar_nodes_rejects_booleans_as_ints(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            resp_dim = self._call_tool(self._valid_args(dimensions=True))
            self.assertTrue(resp_dim["result"]["isError"])
            self.assertIn(
                "embedding dimensions must be between 1 and 2000",
                resp_dim["result"]["content"][0]["text"],
            )

            resp_lim = self._call_tool(self._valid_args(limit=True))
            self.assertTrue(resp_lim["result"]["isError"])
            self.assertIn(
                "candidate limit must be between 1 and 100",
                resp_lim["result"]["content"][0]["text"],
            )

            resp_ev = self._call_tool(self._valid_args(evidence_limit=False))
            self.assertTrue(resp_ev["result"]["isError"])
            self.assertIn(
                "evidence limit must be between 1 and 20",
                resp_ev["result"]["content"][0]["text"],
            )

            resp_sel = self._call_tool(self._valid_args(selected=1))
            self.assertTrue(resp_sel["result"]["isError"])
            self.assertIn(
                "candidate selection must be explicit boolean",
                resp_sel["result"]["content"][0]["text"],
            )

    def test_similar_nodes_rejects_out_of_bound_ranges(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            resp_dim_zero = self._call_tool(self._valid_args(dimensions=0))
            self.assertTrue(resp_dim_zero["result"]["isError"])
            resp_dim_large = self._call_tool(self._valid_args(dimensions=2500))
            self.assertTrue(resp_dim_large["result"]["isError"])

            resp_lim_zero = self._call_tool(self._valid_args(limit=0))
            self.assertTrue(resp_lim_zero["result"]["isError"])
            resp_lim_large = self._call_tool(self._valid_args(limit=150))
            self.assertTrue(resp_lim_large["result"]["isError"])

            resp_ev_zero = self._call_tool(self._valid_args(evidence_limit=0))
            self.assertTrue(resp_ev_zero["result"]["isError"])
            resp_ev_large = self._call_tool(self._valid_args(evidence_limit=25))
            self.assertTrue(resp_ev_large["result"]["isError"])

    def test_similar_nodes_rejects_unsafe_identities_and_keys(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            resp_rebuild = self._call_tool(self._valid_args(rebuild_id="../etc/passwd"))
            self.assertTrue(resp_rebuild["result"]["isError"])
            self.assertIn("invalid enrichment identity", resp_rebuild["result"]["content"][0]["text"])

            resp_space = self._call_tool(self._valid_args(rebuild_id="bad id"))
            self.assertTrue(resp_space["result"]["isError"])
            self.assertIn("invalid enrichment identity", resp_space["result"]["content"][0]["text"])

            resp_profile = self._call_tool(self._valid_args(profile_identity="invalid-profile"))
            self.assertTrue(resp_profile["result"]["isError"])
            self.assertIn("invalid embedding profile identity", resp_profile["result"]["content"][0]["text"])

            resp_key_empty = self._call_tool(self._valid_args(canonical_key=""))
            self.assertTrue(resp_key_empty["result"]["isError"])
            self.assertIn("invalid similar-node identity or filter", resp_key_empty["result"]["content"][0]["text"])

            resp_key_null = self._call_tool(self._valid_args(canonical_key="bad\x00key"))
            self.assertTrue(resp_key_null["result"]["isError"])
            self.assertIn("invalid similar-node identity or filter", resp_key_null["result"]["content"][0]["text"])

            resp_filter = self._call_tool(self._valid_args(kind="bad\x00kind"))
            self.assertTrue(resp_filter["result"]["isError"])
            self.assertIn("invalid similar-node identity or filter", resp_filter["result"]["content"][0]["text"])

    def test_similar_nodes_rejects_vector_and_unexpected_args(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            resp = self._call_tool(self._valid_args(vector=[0.1, 0.2, 0.3]))
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("unexpected argument(s): vector", resp["result"]["content"][0]["text"])

    def test_similar_nodes_rejects_missing_required_args(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            args = self._valid_args()
            del args["dimensions"]
            resp = self._call_tool(args)
        self.assertTrue(resp["result"]["isError"])
        self.assertIn("missing required argument(s): dimensions", resp["result"]["content"][0]["text"])

    def test_similar_nodes_dispatches_to_investigation_store_when_implemented(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        received_queries: list[SimilarNodesQuery] = []

        class FakeStore:
            def similar_nodes(self, graph_id: str, query: SimilarNodesQuery) -> CandidateResult:
                received_queries.append(query)
                return CandidateResult(
                    status="candidate_discovery",
                    reason=None,
                    candidates=({"canonical_key": "symbol:helper", "score": 0.92},),
                    provenance={"run_id": 42},
                )

        class FakeBinding:
            def storage_label(self, selection: Any) -> str:
                return "fake-storage"

            def investigation_store(self) -> FakeStore:
                return FakeStore()

        with env, patch("repomap_kg.server.ops.investigation_stores", lambda cfg: FakeBinding()):
            response = self._call_tool(
                self._valid_args(
                    selected=True,
                    limit=10,
                    evidence_limit=3,
                    kind="function",
                    path="src/main.py",
                    source_binding_id="src-1",
                )
            )

        self.assertNotIn("error", response)
        result = response["result"]
        self.assertFalse(result.get("isError", False))
        payload = result["structuredContent"]
        self.assertEqual(payload["status"], "candidate_discovery")
        self.assertIsNone(payload["reason"])
        self.assertEqual(len(payload["candidates"]), 1)
        self.assertEqual(payload["candidates"][0]["canonical_key"], "symbol:helper")
        self.assertEqual(payload["provenance"], {"run_id": 42})
        self.assertEqual(len(received_queries), 1)
        q = received_queries[0]
        self.assertEqual(q.canonical_key, "symbol:main")
        self.assertEqual(q.rebuild_id, "rebuild-20261008-01")
        self.assertEqual(q.profile_identity, "sha256:" + "0" * 64)
        self.assertEqual(q.dimensions, 128)
        self.assertTrue(q.selected)
        self.assertEqual(q.limit, 10)
        self.assertEqual(q.evidence_limit, 3)
        self.assertEqual(q.kind, "function")
        self.assertEqual(q.path, "src/main.py")
        self.assertEqual(q.source_binding_id, "src-1")

    def test_facade_and_direct_tool_call_reachability(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env:
            direct = handle_tool_call("repomap_similar_nodes", self._valid_args())
            self.assertEqual(direct["structuredContent"]["status"], "capability_unavailable")

            facade = facade_similar_nodes(**self._valid_args())
            self.assertEqual(facade["status"], "capability_unavailable")

            payload = similar_nodes_payload(**self._valid_args())
            self.assertEqual(payload["status"], "capability_unavailable")

            facade_payload = facade_similar_nodes_payload(**self._valid_args())
            self.assertEqual(facade_payload["status"], "capability_unavailable")

        self.assertEqual(TOOL_FUNCTIONS["repomap_similar_nodes"], "repomap_similar_nodes")
