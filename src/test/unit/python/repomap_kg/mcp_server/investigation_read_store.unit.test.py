"""Named investigation read-store dispatch for seven MCP tools (READSTORE2)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import patch

from repomap_kg.graph.keys import GRAPH_KEY_VERSION
from repomap_kg.server.investigation_read_store import (
    ConfiguredNeighborhoodQuery,
    GraphRefreshStatusQuery,
    GraphSearchQuery,
    GraphSearchResult,
    InvestigationStorageQueries,
    LanguageSummaryQueries,
    PostgresInvestigationReadStore,
    ProjectSummaryQuery,
)
from repomap_kg.storage import (
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    CanonicalStorageSummaryRecord,
    identity_metadata_hash,
)
from repomap_test_support.host_read_store_config import fail_if_reached, failing_store_binding
from repomap_test_support.mcp_server import McpServerTestSupport

LANGUAGE_FAMILIES = ("python", "terraform", "openapi", "js_framework", "nix")

NODE = CanonicalNodeRecord(
    canonical_key="python.module:pkg.a", graph_key_version=1, kind="python.module",
    display_name="pkg.a", confidence="extracted", conflict=False, metadata={},
    first_seen_run_id=1, last_seen_run_id=2,
)
EDGE = CanonicalEdgeRecord(
    source_key="python.module:pkg.a", edge_kind="imports", target_key="python.module:pkg.b",
    graph_key_version=1, identity_metadata={}, identity_metadata_hash=identity_metadata_hash({}),
    metadata={}, confidence="extracted", conflict=False, first_seen_run_id=1, last_seen_run_id=2,
)
NEIGHBORHOOD = CanonicalNeighborhoodRecord(center=NODE, nodes=(NODE,), edges=(EDGE,))
SUMMARY = CanonicalStorageSummaryRecord(
    root_path="/tmp/fixture", repository_name="fixture", latest_run_id=22, runs=2, files=3,
    raw_observations=13, canonical_nodes=5, canonical_edges=7, canonical_evidence=11,
)
SEARCH_ROWS = (
    {"path": "src/a.py", "kind": "python.module", "payload": {"k": "v"}},
    {"path": "src/b.py", "kind": "python.module", "payload": {"k": "w"}},
)
TOOL_CALLS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("repomap_graph_status", {"graph_id": "repo-map"}),
    ("repomap_refresh_status", {"graph_id": "private-visible"}),
    ("repomap_refresh_status", {}),
    ("repomap_search_nodes", {"graph_id": "repo-map", "query": " 50%_off\\ ", "kind": "python.module", "limit": 1, "offset": 4}),
    ("repomap_search_files", {"graph_id": "repo-map", "query": "src", "path": "src/", "limit": 250}),
    ("repomap_search_observations", {"graph_id": "private-visible", "query": "add", "include_raw": True}),
    ("repomap_project_summary", {"graph_id": "private-visible"}),
    ("repomap_neighborhood", {"graph_id": "repo-map", "node": "python.module:pkg.a", "direction": "out"}),
)
EXPECTED_QUERIES = (
    GraphRefreshStatusQuery(("repo-map",)),
    GraphRefreshStatusQuery(("private-visible",)),
    GraphRefreshStatusQuery(("repo-map", "private-visible")),
    GraphSearchQuery("repo-map", "nodes", "50%_off\\", "python.module", None, 1, 4, False),
    GraphSearchQuery("repo-map", "files", "src", None, "src/", 100, 0, False),
    GraphSearchQuery("private-visible", "observations", "add", None, None, 20, 0, True),
    ProjectSummaryQuery("private-visible"),
    ConfiguredNeighborhoodQuery("repo-map", "python.module:pkg.a", "out", 1, GRAPH_KEY_VERSION),
)


def _statuses(support: McpServerTestSupport) -> dict[str, Any]:
    base = support.synthetic_refresh_status(latest_run_status="complete", latest_run_finished_at="2026-07-01T00:01:00Z")
    return {
        graph_id: replace(base, graph_id=graph_id, repository_name=graph_id)
        for graph_id in ("repo-map", "private-visible", "disabled", "hidden")
    }


class FakeInvestigationReadStore:
    def __init__(self, statuses: dict[str, Any]) -> None:
        self.statuses = statuses
        self.queries: list[object] = []

    def refresh_statuses(self, query: GraphRefreshStatusQuery):
        self.queries.append(query)
        return self.statuses

    def search(self, query: GraphSearchQuery):
        self.queries.append(query)
        return GraphSearchResult(rows=SEARCH_ROWS[: query.limit], total=None, has_more=len(SEARCH_ROWS) > query.limit)

    def project_summary(self, query: ProjectSummaryQuery):
        self.queries.append(query)
        return SUMMARY

    def configured_neighborhood(self, query: ConfiguredNeighborhoodQuery):
        self.queries.append(query)
        return NEIGHBORHOOD


class InvestigationReadStoreDispatchTests(McpServerTestSupport):
    def _call_all(self) -> list[dict]:
        from repomap_kg.server.mcp import handle_tool_call

        return [handle_tool_call(name, dict(args)) for name, args in TOOL_CALLS]

    def test_seven_tools_dispatch_through_named_store_with_unchanged_results(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        fake = FakeInvestigationReadStore(_statuses(self))
        factory_calls: list[Any] = []

        class Binding:
            def storage_label(self, selection):
                return f"label-{selection.graph_id}"

            def investigation_store(self):
                return fake

        def factory(config):
            factory_calls.append(config)
            return Binding()

        with env, patch("repomap_kg.server.ops.investigation_stores", factory):
            seam_results = self._call_all()

        def search_owner(config, *, limit, **_kwargs):
            rows = list(SEARCH_ROWS[: limit + 1])
            return {"results": rows[:limit], "has_more": len(rows) > limit}

        with env, patch.multiple(
            "repomap_kg.server.ops",
            query_refresh_status=lambda *a, **k: _statuses(self),
            query_mcp_search=search_owner,
            query_canonical_storage_summary=lambda *a, **k: SUMMARY,
            query_canonical_neighborhood=lambda *a, **k: NEIGHBORHOOD,
        ):
            adapter_results = self._call_all()

        self.assertEqual(tuple(fake.queries), EXPECTED_QUERIES)
        self.assertEqual(seam_results, adapter_results)
        self.assertEqual(len(factory_calls), len(TOOL_CALLS))
        for config in factory_calls:
            self.assertEqual([graph.id for graph in config.graphs][:2], ["repo-map", "private-visible"])
        omitted = seam_results[2]["structuredContent"]
        self.assertEqual([graph["graph_id"] for graph in omitted["graphs"]], ["repo-map", "private-visible"])
        self.assertNotIn("hidden", str(omitted))
        self.assertNotIn('"disabled"', str(omitted))
        nodes = seam_results[3]["structuredContent"]
        self.assertEqual((nodes["result_count"], nodes["total"], nodes["has_more"]), (1, 5, True))
        self.assertEqual(nodes["query"], "50%_off\\")
        self.assertEqual(seam_results[4]["structuredContent"]["limit"], 100)
        observations = seam_results[5]["structuredContent"]
        self.assertEqual(observations["raw_payload_policy"]["include_raw"], True)
        self.assertEqual(seam_results[6]["structuredContent"]["summary"]["root_path"], "[private-root]")
        self.assertEqual(seam_results[7]["structuredContent"]["result"]["center"]["canonical_key"], NODE.canonical_key)

    def test_invalid_arguments_and_graphs_refuse_before_store_access(self) -> None:
        from repomap_kg.server.mcp import RepoMapMcpError, handle_tool_call

        search = {"graph_id": "repo-map", "query": "x"}
        cases = (
            ("repomap_graph_status", {"graph_id": "missing"}, "unknown graph_id: missing"),
            ("repomap_graph_status", {"graph_id": "disabled"}, "graph 'disabled' is not enabled"),
            ("repomap_graph_status", {"graph_id": "hidden"}, "graph 'hidden' is not MCP-visible"),
            ("repomap_refresh_status", {"graph_id": "missing"}, "unknown graph_id: missing"),
            ("repomap_refresh_status", {"graph_id": "disabled"}, "graph 'disabled' is not enabled"),
            ("repomap_refresh_status", {"graph_id": "hidden"}, "graph 'hidden' is not MCP-visible"),
            ("repomap_search_nodes", {**search, "query": "   "}, "query is required"),
            ("repomap_search_nodes", {**search, "query": "x" * 201}, "query must be at most 200 characters"),
            ("repomap_search_files", {**search, "limit": 0}, "limit must be a positive integer"),
            ("repomap_search_observations", {**search, "offset": -1}, "offset must be a non-negative integer"),
            ("repomap_search_observations", {**search, "graph_id": "hidden"}, "graph 'hidden' is not MCP-visible"),
            ("repomap_search_files", {**search, "sql": "SELECT 1"}, "unexpected argument(s): sql"),
            ("repomap_project_summary", {"graph_id": "disabled"}, "graph 'disabled' is not enabled"),
            ("repomap_neighborhood", {"graph_id": "repo-map", "node": "python.module:a", "depth": 2},
             "neighborhood depth is capped at 1 in MCP-OPS4"),
            ("repomap_neighborhood", {"graph_id": "hidden", "node": "python.module:a"},
             "graph 'hidden' is not MCP-visible"),
        )
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        with env, patch.multiple(
            "repomap_kg.server.ops",
            investigation_stores=failing_store_binding,
            query_refresh_status=fail_if_reached,
            query_mcp_search=fail_if_reached,
            query_canonical_storage_summary=fail_if_reached,
            query_canonical_neighborhood=fail_if_reached,
            execute_ops_json_readback=fail_if_reached,
        ):
            for name, args, expected in cases:
                with self.subTest(name=name, args=args), self.assertRaises(RepoMapMcpError) as raised:
                    handle_tool_call(name, args)
                self.assertEqual(str(raised.exception), expected)


class PostgresInvestigationReadStoreScopeTests(McpServerTestSupport):
    def _store(self, calls: list[tuple[str, tuple, dict]], body: str | None = None) -> PostgresInvestigationReadStore:
        from repomap_kg.ops.config import load_ops_config

        def make(name, result):
            def query(*args, **kwargs):
                calls.append((name, args, kwargs))
                return result
            return query

        config = load_ops_config(self.write_ops_config(body or self.visible_ops_config()))
        return PostgresInvestigationReadStore(config, None, InvestigationStorageQueries(
            refresh_status=make("status", {}), search=make("search", {"results": []}),
            storage_summary=make("summary", SUMMARY), neighborhood=make("neighborhood", NEIGHBORHOOD),
            language_summaries=LanguageSummaryQueries(*(make(family, None) for family in LANGUAGE_FAMILIES)),
        ))

    def test_refresh_statuses_pass_exact_ids_never_none_and_host_only(self) -> None:
        calls: list[tuple[str, tuple, dict]] = []
        store = self._store(calls)
        store.refresh_statuses(GraphRefreshStatusQuery(()))
        store.refresh_statuses(GraphRefreshStatusQuery(("private-visible", "repo-map")))
        self.assertEqual([kwargs["graph_ids"] for _name, _args, kwargs in calls], [(), ("private-visible", "repo-map")])
        for _name, args, kwargs in calls:
            self.assertIs(args[0], store.config)
            self.assertIsNotNone(kwargs["graph_ids"])
            self.assertEqual((kwargs["readback_mode"], kwargs["psql_command"]), ("host_only", None))

    def test_adapter_refuses_unknown_disabled_and_hidden_graphs_defensively(self) -> None:
        from repomap_kg.server.ops import McpOpsError

        calls: list[tuple[str, tuple, dict]] = []
        store = self._store(calls)
        operations = (
            lambda graph_id: store.refresh_statuses(GraphRefreshStatusQuery(("repo-map", graph_id))),
            lambda graph_id: store.search(GraphSearchQuery(graph_id, "files", "x", None, None, 1, 0, False)),
            lambda graph_id: store.project_summary(ProjectSummaryQuery(graph_id)),
            lambda graph_id: store.configured_neighborhood(ConfiguredNeighborhoodQuery(graph_id, "a:b", "both", 1, 1)),
        )
        for operation in operations:
            for graph_id, expected in (("missing", "unknown graph_id: missing"),
                                       ("disabled", "graph 'disabled' is not enabled"),
                                       ("hidden", "graph 'hidden' is not MCP-visible")):
                with self.subTest(graph_id=graph_id), self.assertRaises(McpOpsError) as raised:
                    operation(graph_id)
                self.assertEqual(str(raised.exception), expected)
        self.assertEqual(calls, [])

    def test_readback_unsupported_graph_is_a_status_row_but_refuses_reads(self) -> None:
        from repomap_kg.server.ops import McpOpsError
        from repomap_test_support.host_read_store_config import setup_owned_config

        body = setup_owned_config().replace(
            "role = \"source\"\nenabled = true\n",
            "role = \"source\"\nenabled = true\n[[graphs.source_bindings]]\nschema_version = 1\n"
            "source_definition_id = \"src1:beta\"\nalias = \"beta\"\nrevision = 1\nkind = \"folder\"\n"
            "root_path = \"./beta\"\nrepository_name = \"beta\"\nlogical_root = \"beta\"\n"
            "privacy = \"public-dev\"\nevidence_retention = \"inherit\"\nextractor_profile = \"default\"\n"
            "resolution_policy = \"isolated\"\nrole = \"source\"\nenabled = false\n",
        )
        calls: list[tuple[str, tuple, dict]] = []
        store = self._store(calls, body)
        graph = next(graph for graph in store.config.graphs if graph.id == "host-multi")
        self.assertIsNotNone(graph.readback_unsupported_classification)
        store.refresh_statuses(GraphRefreshStatusQuery(("host-multi",)))
        self.assertEqual(calls[0][2]["graph_ids"], ("host-multi",))
        with self.assertRaises(McpOpsError) as raised:
            store.project_summary(ProjectSummaryQuery("host-multi"))
        self.assertEqual(str(raised.exception), graph.readback_unsupported_classification)
        self.assertEqual(len(calls), 1)
