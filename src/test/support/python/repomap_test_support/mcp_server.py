"""Server test support and assertion contracts for RepoMap MCP server tests."""

from __future__ import annotations

import json
import unittest

from repomap_test_support.mcp_server_requests import (
    McpServerRequestSupport,
    McpServerRequests,
    NixSummaryRecord,
)


class McpServerTestSupport(McpServerRequestSupport, unittest.TestCase):
    EXPECTED_SAFETY_MARKERS = frozenset(
        {
            "read_only",
            "no_refresh",
            "no_discovery",
            "no_source_tree_reads",
            "no_source_mutation",
            "no_destructive_db_actions",
            "no_server_memory_read",
            "no_source_acquisition",
            "no_remote_exposure",
        }
    )

    def assert_read_only_payload(self, payload):
        self.assertTrue(payload["read_only"])
        self.assertEqual(
            self.EXPECTED_SAFETY_MARKERS,
            self.EXPECTED_SAFETY_MARKERS.intersection(payload["safety"].keys()),
        )
        for key in self.EXPECTED_SAFETY_MARKERS:
            self.assertTrue(payload["safety"][key], key)

    def assert_public_graph_payload(
        self,
        graph,
        *,
        graph_id: str = "repo-map",
    ):
        self.assertEqual(graph["graph_id"], graph_id)
        self.assertFalse(graph["private"])
        self.assertEqual(graph["privacy"], "public-dev")
        self.assertEqual(graph["root_path_display"], "[graph-root]")
        self.assertEqual(graph["root_path_expanded"], "[graph-root]")

    def assert_private_graph_payload(
        self,
        graph,
        *,
        graph_id: str = "private-visible",
    ):
        self.assertEqual(graph["graph_id"], graph_id)
        self.assertTrue(graph["private"])
        self.assertEqual(graph["privacy"], "private-ops")
        self.assertEqual(graph["root_path_display"], "[private-root]")
        self.assertEqual(graph["root_path_expanded"], "[private-root]")

    def assert_no_synthetic_private_root(self, payload, *extra_tokens: str):
        serialized = json.dumps(payload, sort_keys=True)
        for token in (
            "~/private-visible",
            "synthetic-private-root",
            *extra_tokens,
        ):
            self.assertNotIn(token, serialized)

    def assert_projects_payload_fields(self, payload):
        self.assertEqual(
            set(payload),
            {
                "default_project",
                "allow_project_overrides",
                "projects",
                "graph_registry_available",
                "graph_count",
                "graphs",
                "message",
            },
        )

    def assert_raw_payload_policy(self, payload, *, include_raw: bool):
        self.assertEqual(
            payload["raw_payload_policy"],
            {
                "include_raw": include_raw,
                "payload_included": include_raw,
                "metadata_included": True,
                "metadata_semantics": (
                    "include_raw controls the full raw payload field only; "
                    "metadata remains included"
                ),
            },
        )

    def assert_observation_search_payload_contract(
        self,
        payload,
        *,
        query: str,
        limit: int,
        offset: int,
        total: int,
        has_more: bool,
        include_raw: bool,
        kind: str | None = None,
        path: str | None = None,
    ):
        self.assertLessEqual(
            {
                "target",
                "query",
                "kind",
                "path",
                "limit",
                "offset",
                "result_count",
                "total",
                "has_more",
                "read_only",
                "safety",
                "graph",
                "results",
                "raw_payload_policy",
            },
            set(payload),
        )
        self.assert_read_only_payload(payload)
        self.assertEqual(payload["target"], "observations")
        self.assertEqual(payload["query"], query)
        self.assertEqual(payload["kind"], kind)
        self.assertEqual(payload["path"], path)
        self.assertEqual(payload["limit"], limit)
        self.assertEqual(payload["offset"], offset)
        self.assertEqual(payload["result_count"], len(payload["results"]))
        self.assertEqual(payload["total"], total)
        self.assertEqual(payload["has_more"], has_more)
        self.assertLessEqual(payload["result_count"], limit)
        self.assert_raw_payload_policy(payload, include_raw=include_raw)

    def assert_tool_schema_omits_unsafe_arguments(self, schema):
        self.assertNotIn("psql_command", schema["properties"])


__all__ = [
    "McpServerRequestSupport",
    "McpServerRequests",
    "McpServerTestSupport",
    "NixSummaryRecord",
]
