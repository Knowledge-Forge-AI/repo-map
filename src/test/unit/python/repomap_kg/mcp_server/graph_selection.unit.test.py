"""RESOLVE1: neutral logical graph selection routes named reads to bound stores.

A configured graph is selected as a ``GraphSelection`` carrying no PostgreSQL
database, endpoint, credential, client command or credential-bearing config.
Injected fake bindings (unit-only, not a user-selectable backend) prove that all
23 database-reading tools reach their named store operation after the config
parse without deriving a database, building psql arguments, constructing the
PostgreSQL context, selecting a psql executable, resolving read authority,
reading a secret or entering a JSON driver. The config parse itself remains
PostgreSQL-coupled and runs before the tripwires are armed.
"""

from __future__ import annotations

import ast
import dataclasses
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

from repomap_kg.server.canonical_read_store import (
    CanonicalEdgeExplanationQuery,
    CanonicalEdgeQuery,
    CanonicalNeighborhoodQuery,
    CanonicalNodeQuery,
)
from repomap_kg.server.graph_selection import GraphSelection, McpOpsError, select_graph
from repomap_kg.server.investigation_read_store import (
    ConfiguredNeighborhoodQuery,
    GraphRefreshStatusQuery,
    GraphSearchQuery,
    GraphSearchResult,
    LanguageSummaryFamily,
    LanguageSummaryQuery,
    ProjectSummaryQuery,
)
from repomap_kg.server.source_read_store import (
    IngestedSourcesQuery,
    SourceFeedItemExplanationQuery,
    SourceFeedItemsQuery,
    SourceReferencesQuery,
    SourceRunsQuery,
    SourceSummaryQuery,
)
from repomap_kg.storage import (
    CanonicalEdgeExplanationRecord,
    CanonicalEdgeRecord,
    CanonicalNeighborhoodRecord,
    CanonicalNodeRecord,
    CanonicalStorageSummaryRecord,
    SourceSummaryRecord,
    identity_metadata_hash,
)
from repomap_test_support.host_read_store_config import (
    INVALID_PSQL_COMMAND,
    PG_BINDING_TRIPWIRES,
    fail_if_reached,
    patched_guards,
    setup_owned_config,
)
from repomap_test_support.mcp_server import McpServerTestSupport

A, B = "python.module:a", "python.module:b"
ITEM_KEY = "feed.item:feed.channel%3Afeed.document%253Afile%25253Arss.xml%3Aself:item-1"
NODE = CanonicalNodeRecord(
    canonical_key=A, graph_key_version=1, kind="python.module", display_name="a", confidence="extracted",
    conflict=False, metadata={}, first_seen_run_id=1, last_seen_run_id=1,
)
EDGE = CanonicalEdgeRecord(
    source_key=A, edge_kind="imports", target_key=B, graph_key_version=1, identity_metadata={},
    identity_metadata_hash=identity_metadata_hash({}), metadata={}, confidence="extracted", conflict=False,
    first_seen_run_id=1, last_seen_run_id=1,
)
SUMMARY = CanonicalStorageSummaryRecord(
    root_path="/tmp/fixture", repository_name="fixture", latest_run_id=1, runs=1, files=1,
    raw_observations=1, canonical_nodes=1, canonical_edges=1, canonical_evidence=1,
)
SOURCE_SUMMARY = SourceSummaryRecord(
    source_id="feed", source_type="feed.rss", display_name="Feed", policy_status="allowed",
    configured_url_summary="https://example.invalid/feed.xml", latest_source_run_id="run-1",
    latest_artifact_id="a1", latest_artifact_path=".repomap/a1.xml", latest_acquired_at="2026-06-30T12:00:00Z",
    feed_documents=1, feed_channels=1, feed_items=1, feed_authors=1, feed_categories=1, link_references=1,
    enclosure_references=0, parse_errors=0, known_limitations=(),
)
FORBIDDEN_SELECTION_ATTRIBUTES = (
    "database", "psql_args", "psql_command", "config", "password", "host", "port", "user", "postgres",
)


class _Summary:
    def to_dict(self) -> dict[str, Any]:
        return {"root_path": "/tmp/fixture", "count": 1}


RESULTS: dict[str, Any] = {
    "refresh_statuses": {}, "search": GraphSearchResult(rows=(), total=None, has_more=False),
    "project_summary": SUMMARY, "configured_neighborhood": CanonicalNeighborhoodRecord(NODE, (), ()),
    "language_summary": _Summary(), "canonical_nodes": (NODE,), "canonical_edges": (EDGE,),
    "canonical_edge_explanation": CanonicalEdgeExplanationRecord(edge=EDGE, evidence=()),
    "canonical_neighborhood": CanonicalNeighborhoodRecord(NODE, (), ()),
    "canonical_storage_summary": SUMMARY, "ingested_sources": (), "source_summary": SOURCE_SUMMARY,
    "source_runs": (), "source_feed_items": (), "source_feed_item_explanation": {"item": {"item_key": ITEM_KEY}},
    "source_references": (),
}
G = "repo-map"
SEARCH = {"graph_id": G, "query": "a"}
LANGUAGE_FAMILIES: tuple[LanguageSummaryFamily, ...] = ("python", "terraform", "openapi", "js_framework", "nix")
# (tool, arguments, expected (family, operation, graph id, query record)).
TOOLS: tuple[tuple[str, dict[str, Any], tuple[str, str, str, Any]], ...] = (
    ("repomap_graph_status", {"graph_id": G},
     ("investigation", "refresh_statuses", G, GraphRefreshStatusQuery((G,)))),
    ("repomap_refresh_status", {"graph_id": "private-visible"},
     ("investigation", "refresh_statuses", "private-visible", GraphRefreshStatusQuery(("private-visible",)))),
    ("repomap_refresh_status", {},
     ("investigation", "refresh_statuses", "*", GraphRefreshStatusQuery((G, "private-visible")))),
    ("repomap_search_nodes", SEARCH,
     ("investigation", "search", G, GraphSearchQuery(G, "nodes", "a", None, None, 20, 0, False))),
    ("repomap_search_files", SEARCH,
     ("investigation", "search", G, GraphSearchQuery(G, "files", "a", None, None, 20, 0, False))),
    ("repomap_search_observations", {**SEARCH, "include_raw": True},
     ("investigation", "search", G, GraphSearchQuery(G, "observations", "a", None, None, 20, 0, True))),
    ("repomap_project_summary", {"graph_id": G}, ("investigation", "project_summary", G, ProjectSummaryQuery(G))),
    ("repomap_neighborhood", {"graph_id": G, "node": A},
     ("investigation", "configured_neighborhood", G, ConfiguredNeighborhoodQuery(G, A, "both", 1, 1))),
    *(
        (f"repomap_{family}_summary", {"graph_id": G},
         ("investigation", "language_summary", G, LanguageSummaryQuery(G, family)))
        for family in LANGUAGE_FAMILIES
    ),
    ("repomap_status", {"project": G}, ("canonical", "canonical_storage_summary", G, None)),
    ("repomap_canonical_nodes", {"project": G},
     ("canonical", "canonical_nodes", G, CanonicalNodeQuery(None, None, None, 1, 51, 0))),
    ("repomap_canonical_edges", {"project": G},
     ("canonical", "canonical_edges", G, CanonicalEdgeQuery(None, None, None, 1, 51, 0))),
    ("repomap_explain_canonical_edge", {"project": G, "source_key": A, "kind": "imports", "target_key": B},
     ("canonical", "canonical_edge_explanation", G,
      CanonicalEdgeExplanationQuery(A, "imports", B, identity_metadata_hash({}), 1, 51, 0))),
    ("repomap_canonical_neighborhood", {"project": G, "node": A},
     ("canonical", "canonical_neighborhood", G, CanonicalNeighborhoodQuery(A, "both", 1, 1, 51, 0, 51, 0))),
    ("repomap_ingested_sources", {"project": G},
     ("source", "ingested_sources", G, IngestedSourcesQuery(None, None, 50))),
    ("repomap_source_summary", {"project": G, "source_id": "feed"},
     ("source", "source_summary", G, SourceSummaryQuery("feed"))),
    ("repomap_source_runs", {"project": G, "source_id": "feed"},
     ("source", "source_runs", G, SourceRunsQuery("feed", 25))),
    ("repomap_source_feed_items", {"project": G, "source_id": "feed"},
     ("source", "source_feed_items", G, SourceFeedItemsQuery("feed", None, 50))),
    ("repomap_explain_source_feed_item", {"project": G, "item_key": ITEM_KEY},
     ("source", "source_feed_item_explanation", G, SourceFeedItemExplanationQuery(ITEM_KEY, None))),
    ("repomap_source_references", {"project": G, "source_id": "feed"},
     ("source", "source_references", G, SourceReferencesQuery("feed", None, None, 50))),
)


class _FakeStore:
    """Record (family, operation, graph id, query) and return fixed records."""

    def __init__(self, family: str, calls: list[tuple[str, str, str, Any]], graph_id: str) -> None:
        self._family, self._calls, self._graph_id = family, calls, graph_id

    def __getattr__(self, operation: str) -> Any:
        if operation not in RESULTS:
            raise AttributeError(operation)

        def read(query: Any = None) -> Any:
            graph_id = getattr(query, "graph_id", self._graph_id)
            if isinstance(query, GraphRefreshStatusQuery):
                graph_id = query.graph_ids[0] if len(query.graph_ids) == 1 else "*"
            self._calls.append((self._family, operation, graph_id, query))
            return RESULTS[operation]
        return read


class _FakeBinding:
    """Unit-only binding over fake stores; it never sees backend details."""

    def __init__(self, calls: list[tuple[str, str, str, Any]], selections: list[GraphSelection]) -> None:
        self._calls, self._selections = calls, selections

    def storage_label(self, selection: GraphSelection) -> str:
        return f"fake:{selection.graph_id}"

    def investigation_store(self) -> _FakeStore:
        return _FakeStore("investigation", self._calls, "")

    def canonical_store(self, selection: GraphSelection) -> _FakeStore:
        self._selections.append(selection)
        return _FakeStore("canonical", self._calls, selection.graph_id)

    def source_store(self, selection: GraphSelection) -> _FakeStore:
        self._selections.append(selection)
        return _FakeStore("source", self._calls, selection.graph_id)


class GraphSelectionRecordTests(McpServerTestSupport):
    def _config(self, body: str | None = None) -> Any:
        from repomap_kg.ops.config import load_ops_config

        return load_ops_config(self.write_ops_config(body or self.visible_ops_config()))

    def test_selection_record_carries_no_postgres_or_credential_data(self) -> None:
        self.assertEqual([field.name for field in dataclasses.fields(GraphSelection)], ["graph", "config_locations"])
        selection = select_graph(self._config(), G)
        for name in FORBIDDEN_SELECTION_ATTRIBUTES:
            self.assertFalse(hasattr(selection, name), name)
        self.assertTrue(all(isinstance(value, str) for value in selection.config_locations))
        self.assertEqual((selection.graph_id, selection.private, selection.root_path, selection.repository_identity),
                         (G, False, "/tmp/fixture", "repo1:repo-map"))
        # Selection after the parse is pure: no database derivation, psql
        # arguments, PostgreSQL context, authority or secret lookup.
        config = self._config()
        with patched_guards(PG_BINDING_TRIPWIRES):
            selected = select_graph(config, "private-visible")
            self.assertTrue(selected.private)
            self.assertTrue(selected.path_markers)

    def test_selection_matches_the_postgres_context_identity_root_and_markers(self) -> None:
        from repomap_kg.server._ops_records import graph_context
        from repomap_kg.server._ops_sanitization import readback_path_markers

        for body, graph_ids in ((self.visible_ops_config(), (G, "private-visible")),
                                (setup_owned_config(), ("host-one", "host-multi"))):
            path = self.write_ops_config(body)
            with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(path)}, clear=True):
                from repomap_kg.server.ops import load_mcp_ops_config

                config = load_mcp_ops_config()
                for graph_id in graph_ids:
                    context, selection = graph_context(graph_id), select_graph(config, graph_id)
                    with self.subTest(graph_id=graph_id):
                        self.assertEqual(selection.root_path, context.root_path)
                        self.assertEqual(selection.repository_identity, context.repository_identity)
                        self.assertEqual(selection.path_markers, readback_path_markers(context))
                        self.assertEqual(selection.graph, context.graph)
        self.assertEqual(select_graph(self._config(setup_owned_config()), "host-multi").root_path, "graph:host-multi")

    def test_selection_refusals_keep_the_public_texts(self) -> None:
        config = self._config()
        for graph_id, expected in (("", "graph_id is required"), ("missing", "unknown graph_id: missing"),
                                   ("disabled", "graph 'disabled' is not enabled"),
                                   ("hidden", "graph 'hidden' is not MCP-visible")):
            with self.subTest(graph_id=graph_id), self.assertRaises(McpOpsError) as raised:
                select_graph(config, graph_id)
            self.assertEqual(str(raised.exception), expected)

    def test_selection_module_static_imports_stay_backend_neutral(self) -> None:
        import sys

        import repomap_kg.server.graph_selection as module

        repo = next(parent for parent in Path(__file__).resolve().parents if (parent / "src/main/python").is_dir())
        sys.path.insert(0, str(repo))
        try:
            from src.test.unit.python.repomap_kg.architecture.import_graph_support import _import_graph
        finally:
            sys.path.remove(str(repo))
        graph, _ = _import_graph()
        closure: set[str] = set()
        pending = [module.__name__]
        while pending:
            for dependency in graph[pending.pop()]:
                if dependency not in closure:
                    closure.add(dependency)
                    pending.append(dependency)
        forbidden = ("repomap_kg.server", "repomap_kg.runtime", "repomap_kg.storage", "repomap_kg.ops.readback",
                     "repomap_kg.ops.config_status", "repomap_kg.ops.config_loading", "repomap_kg.ops.refresh",
                     "repomap_kg.coordinator")
        self.assertEqual({name for name in closure if name.startswith(forbidden)}, set())
        tree = ast.parse(Path(module.__file__ or "").read_text(encoding="utf-8"))
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse({name for name in imported if name and name.startswith(("psycopg", "subprocess", "shutil"))})


class NeutralSelectionFakeStoreRoutingTests(McpServerTestSupport):
    """All 23 database-reading tools, injected fake bindings, tripwires armed."""

    def _armed(self, config: Any, investigation: Any, graph: Any) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(self.write_empty_mcp_config()),
                                                      "REPOMAP_PSQL_COMMAND": INVALID_PSQL_COMMAND}, clear=True))
        stack.enter_context(patch("repomap_kg.server.ops.load_mcp_ops_config", lambda *_a: config))
        stack.enter_context(patch("repomap_kg.server.mcp_core.load_mcp_ops_config", lambda *_a: config))
        stack.enter_context(patch("repomap_kg.server.ops.investigation_stores", investigation))
        stack.enter_context(patch("repomap_kg.server.mcp.graph_stores", graph))
        stack.enter_context(patched_guards(PG_BINDING_TRIPWIRES))
        return stack

    def _parsed_config(self) -> Any:
        from repomap_kg.server.ops import load_mcp_ops_config

        with patch.dict("os.environ", {"REPOMAP_OPS_CONFIG": str(self.write_visible_ops_config())}, clear=True):
            return load_mcp_ops_config()

    def test_all_23_tools_route_to_their_named_store_operation_without_postgres_binding(self) -> None:
        from repomap_kg.server.mcp import handle_tool_call, tool_definitions

        config = self._parsed_config()
        calls: list[tuple[str, str, str, Any]] = []
        selections: list[GraphSelection] = []
        factory_configs: list[Any] = []

        def factory(received: Any) -> _FakeBinding:
            factory_configs.append(received)
            return _FakeBinding(calls, selections)

        payloads: list[Any] = []
        with self._armed(config, factory, factory):
            for name, args, _expected in TOOLS:
                with self.subTest(tool=name):
                    payloads.append(handle_tool_call(name, dict(args))["structuredContent"])

        database_tools = {name for name, _args, _expected in TOOLS}
        other_tools = {"repomap_list_graphs", "repomap_projects", "repomap_server_memory_summary",
                       "repomap_server_memory_search"}
        self.assertEqual(len(database_tools), 23)
        self.assertEqual(database_tools | other_tools, {tool["name"] for tool in tool_definitions()})
        self.assertEqual(calls, [expected for _name, _args, expected in TOOLS])
        self.assertEqual(len(factory_configs), len(TOOLS))
        self.assertTrue(all(received is config for received in factory_configs))
        self.assertTrue(all(isinstance(selection, GraphSelection) for selection in selections))
        self.assertEqual(payloads[0]["graph"]["database"], "[graph-database]")
        self.assertEqual(payloads[6]["summary"]["root_path"], "[graph-root]")
        self.assertEqual(payloads[13]["root_path"], "[graph-root]")

    def test_selection_refusals_precede_backend_binding(self) -> None:
        from repomap_kg.server.mcp import RepoMapMcpError, handle_tool_call

        config = self._parsed_config()
        cases: tuple[tuple[str, dict[str, Any], str], ...] = (
            ("repomap_graph_status", {"graph_id": "missing"}, "unknown graph_id: missing"),
            ("repomap_search_nodes", {"graph_id": "hidden", "query": "a"}, "graph 'hidden' is not MCP-visible"),
            ("repomap_python_summary", {"graph_id": "disabled"}, "graph 'disabled' is not enabled"),
            ("repomap_refresh_status", {"graph_id": "hidden"}, "graph 'hidden' is not MCP-visible"),
            ("repomap_status", {"project": "missing"}, "unknown legacy MCP project or graph-registry graph_id: missing"),
            ("repomap_canonical_nodes", {"project": "hidden"}, "graph 'hidden' is not MCP-visible"),
            ("repomap_source_runs", {"project": "disabled", "source_id": "feed"}, "graph 'disabled' is not enabled"),
            ("repomap_ingested_sources", {"project": G, "pg_database": "x"},
             "graph-registry project routing cannot be combined with explicit connection overrides"),
        )
        with self._armed(config, fail_if_reached, fail_if_reached):
            for name, args, expected in cases:
                with self.subTest(name=name, args=args), self.assertRaises(RepoMapMcpError) as raised:
                    handle_tool_call(name, dict(args))
                self.assertEqual(str(raised.exception), expected)

    def test_configuration_only_tools_never_bind_a_backend(self) -> None:
        from repomap_kg.server.mcp import handle_tool_call

        path = self.write_visible_ops_config()
        env = {"REPOMAP_MCP_CONFIG": str(self.write_empty_mcp_config()), "REPOMAP_OPS_CONFIG": str(path)}
        with patch.dict("os.environ", env, clear=True), \
                patch("repomap_kg.server.ops.investigation_stores", fail_if_reached), \
                patch("repomap_kg.server.mcp.graph_stores", fail_if_reached), \
                patched_guards(("repomap_kg.server.canonical_read_store.readback_postgres_authority",
                                "repomap_kg.ops.readback.readback_postgres_authority",
                                "repomap_kg.server._ops_records.psql_command_from_environment")):
            graphs = handle_tool_call("repomap_list_graphs", {})["structuredContent"]
            projects = handle_tool_call("repomap_projects", {})["structuredContent"]
        self.assertEqual([graph["graph_id"] for graph in graphs["graphs"]], [G, "private-visible"])
        self.assertEqual([graph["graph_id"] for graph in projects["graphs"]], [G, "private-visible"])
