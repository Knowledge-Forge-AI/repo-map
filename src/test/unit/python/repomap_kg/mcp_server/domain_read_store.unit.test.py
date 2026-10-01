"""READSTORE3: twelve remaining database-reading MCP tools use named read stores.

The five language/framework summaries read through
``InvestigationReadStore.language_summary``; the six ingested-source/feed tools
read through ``SourceReadStore``; legacy ``repomap_status`` reads through
``CanonicalReadStore.canonical_storage_summary``. Fake stores are unit-only.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import patch

from repomap_kg.server.canonical_read_store import PostgresCanonicalReadStore
from repomap_kg.server.investigation_read_store import (
    InvestigationStorageQueries,
    LanguageSummaryFamily,
    LanguageSummaryQueries,
    LanguageSummaryQuery,
    PostgresInvestigationReadStore,
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
    CanonicalStorageSummaryRecord,
    IngestedSourceRecord,
    SourceFeedItemRecord,
    SourceReferenceRecord,
    SourceRunRecord,
    SourceSummaryRecord,
)
from repomap_test_support.host_read_store_config import fail_if_reached, failing_store_binding
from repomap_test_support.mcp_server import McpServerTestSupport

ITEM_KEY = "feed.item:feed.channel%3Afeed.document%253Afile%25253Arss.xml%3Aself:item-1"
FAMILIES: tuple[LanguageSummaryFamily, ...] = ("python", "terraform", "openapi", "js_framework", "nix")
SUMMARY_OWNERS = {family: f"query_{family}_summary" for family in FAMILIES}
SUMMARY = CanonicalStorageSummaryRecord(
    root_path="/tmp/fixture", repository_name="fixture", latest_run_id=7, runs=2, files=3,
    raw_observations=5, canonical_nodes=11, canonical_edges=13, canonical_evidence=17,
)
INGESTED = (IngestedSourceRecord(
    source_id="example-feed", source_type="feed.rss", display_name="Example", policy_status="allowed",
    latest_source_run_id="run-1", latest_artifact_id="a1", latest_artifact_path=".repomap/a1.xml",
    latest_acquired_at="2026-06-30T12:00:00Z", feed_observation_count=8, canonical_feed_item_count=2,
),)
SOURCE_SUMMARY = SourceSummaryRecord(
    source_id="example-feed", source_type="feed.rss", display_name="Example", policy_status="allowed",
    configured_url_summary="https://example.invalid/feed.xml", latest_source_run_id="run-1",
    latest_artifact_id="a1", latest_artifact_path=".repomap/a1.xml", latest_acquired_at="2026-06-30T12:00:00Z",
    feed_documents=1, feed_channels=1, feed_items=2, feed_authors=1, feed_categories=2, link_references=2,
    enclosure_references=1, parse_errors=0, known_limitations=("inferred",),
)
RUNS = (SourceRunRecord(
    source_run_id="run-1", acquired_at="2026-06-30T12:00:00Z", artifact_id="a1",
    artifact_path=".repomap/a1.xml", artifact_byte_length=10, artifact_sha256="0" * 64, http_status=200,
    content_type="application/rss+xml", observation_count=8, status_summary="ok",
),)
ITEMS = (SourceFeedItemRecord(
    item_key=ITEM_KEY, title="One", published_at=None, updated_at=None, identity_source="guid",
    identity_strength="strong", duplicate_identity=False, link_targets=("https://example.invalid/1",),
    authors=(), categories=(), source_run_id="run-1", artifact_id="a1", artifact_path=".repomap/a1.xml",
),)
EXPLANATION = {"item": {"item_key": ITEM_KEY}, "references": []}
REFERENCES = (SourceReferenceRecord(
    source_item_key=ITEM_KEY, relation="links_to", target_key="external.url:https%3A//example.invalid/1",
    target_display="https://example.invalid/1", not_fetched=True, media_type=None, source_run_id="run-1",
    artifact_id="a1", artifact_path=".repomap/a1.xml",
),)
SOURCE_RESULTS: dict[str, Any] = {
    "ingested_sources": INGESTED, "source_summary": SOURCE_SUMMARY, "source_runs": RUNS,
    "source_feed_items": ITEMS, "source_feed_item_explanation": EXPLANATION, "source_references": REFERENCES,
}
SOURCE_OWNERS = {
    "ingested_sources": "query_ingested_source_records", "source_summary": "query_source_summary",
    "source_runs": "query_source_run_records", "source_feed_items": "query_source_feed_item_records",
    "source_feed_item_explanation": "query_source_feed_item_explanation",
    "source_references": "query_source_reference_records",
}


class _Summary:
    """Serializable stand-in for one maintained language summary record."""

    def __init__(self, family: str) -> None:
        self.family = family

    def to_dict(self) -> dict[str, Any]:
        return {"root_path": "/tmp/fixture", "repository_name": "fixture", "family": self.family, "count": 3}


SUMMARY_RECORDS = {family: _Summary(family) for family in FAMILIES}


def source_calls(project_args: dict[str, Any]) -> tuple[tuple[str, dict[str, Any], str, Any], ...]:
    return (
        ("repomap_ingested_sources", {**project_args, "source_type": "feed.rss", "policy_status": "allowed",
                                      "limit": 3}, "ingested_sources", IngestedSourcesQuery("feed.rss", "allowed", 3)),
        ("repomap_source_summary", {**project_args, "source_id": "example-feed"}, "source_summary",
         SourceSummaryQuery("example-feed")),
        ("repomap_source_runs", {**project_args, "source_id": "example-feed"}, "source_runs",
         SourceRunsQuery("example-feed", 25)),
        ("repomap_source_feed_items", {**project_args, "source_id": "example-feed", "source_run_id": "run-1",
                                       "limit": 1}, "source_feed_items", SourceFeedItemsQuery("example-feed", "run-1", 1)),
        ("repomap_explain_source_feed_item", {**project_args, "item_key": ITEM_KEY, "source_id": "example-feed"},
         "source_feed_item_explanation", SourceFeedItemExplanationQuery(ITEM_KEY, "example-feed")),
        ("repomap_source_references", {**project_args, "source_id": "example-feed", "target_kind": "external.url"},
         "source_references", SourceReferencesQuery("example-feed", None, "external.url", 50)),
    )


class FakeSourceReadStore:
    def __init__(self) -> None:
        self.queries: list[tuple[str, Any]] = []

    def _record(self, operation: str, query: Any) -> Any:
        self.queries.append((operation, query))
        return SOURCE_RESULTS[operation]

    def ingested_sources(self, query: IngestedSourcesQuery) -> Any:
        return self._record("ingested_sources", query)

    def source_summary(self, query: SourceSummaryQuery) -> Any:
        return self._record("source_summary", query)

    def source_runs(self, query: SourceRunsQuery) -> Any:
        return self._record("source_runs", query)

    def source_feed_items(self, query: SourceFeedItemsQuery) -> Any:
        return self._record("source_feed_items", query)

    def source_feed_item_explanation(self, query: SourceFeedItemExplanationQuery) -> Any:
        return self._record("source_feed_item_explanation", query)

    def source_references(self, query: SourceReferencesQuery) -> Any:
        return self._record("source_references", query)


class FakeInvestigationReadStore:
    def __init__(self) -> None:
        self.queries: list[LanguageSummaryQuery] = []

    def language_summary(self, query: LanguageSummaryQuery) -> Any:
        self.queries.append(query)
        return SUMMARY_RECORDS[query.family]


class FakeCanonicalReadStore:
    def __init__(self) -> None:
        self.calls = 0

    def canonical_storage_summary(self) -> CanonicalStorageSummaryRecord:
        self.calls += 1
        return SUMMARY


class FakeInvestigationBinding:
    """Investigation binding double; the label feeds only the redacted display."""

    def __init__(self, store: Any) -> None:
        self.store = store
        self.storage_label = lambda _selection: "fake-storage"

    def investigation_store(self) -> Any:
        return self.store


class DomainReadStoreDispatchTests(McpServerTestSupport):
    def _handle(self, name: str, args: dict[str, Any]) -> Any:
        from repomap_kg.server.mcp import handle_tool_call

        return handle_tool_call(name, dict(args))["structuredContent"]

    def _adapter_owners(self):
        patches: list[Any] = [patch(f"repomap_kg.server.ops.{owner}", lambda *_a, _f=family, **_k: SUMMARY_RECORDS[_f])
                   for family, owner in SUMMARY_OWNERS.items()]
        patches += [patch(f"repomap_kg.server.mcp.{owner}", lambda *_a, _o=operation, **_k: SOURCE_RESULTS[_o])
                    for operation, owner in SOURCE_OWNERS.items()]
        patches.append(patch("repomap_kg.server.mcp.query_canonical_storage_summary", lambda *_a, **_k: SUMMARY))
        return patches

    def test_twelve_configured_tools_dispatch_through_named_stores_with_unchanged_results(self) -> None:
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        investigation, source, canonical = FakeInvestigationReadStore(), FakeSourceReadStore(), FakeCanonicalReadStore()
        connections: list[Any] = []

        def source_factory(connection: Any) -> FakeSourceReadStore:
            connections.append(connection)
            return source

        def canonical_factory(connection: Any) -> FakeCanonicalReadStore:
            connections.append(connection)
            return canonical

        summary_calls = [(f"repomap_{family}_summary", {"graph_id": "repo-map"}) for family in FAMILIES]
        sources = source_calls({"project": "repo-map"})
        status = ("repomap_status", {"project": "repo-map"})
        calls = [*summary_calls, *((name, args) for name, args, _op, _query in sources), status]
        guards = ("repomap_kg.ops.refresh.run_storage_readback_with_ops_psql",
                  "repomap_kg.ops.refresh._container_psql_execution")
        with env, patch("repomap_kg.server.ops.investigation_stores",
                        lambda _config: FakeInvestigationBinding(investigation)), \
                patch("repomap_kg.server.mcp.source_read_store", source_factory), \
                patch("repomap_kg.server.mcp.canonical_read_store", canonical_factory):
            seam_results = [self._handle(name, args) for name, args in calls]
        with env:
            for guard in guards:
                patch(guard, fail_if_reached).start()
            for owner in self._adapter_owners():
                owner.start()
            try:
                adapter_results = [self._handle(name, args) for name, args in calls]
            finally:
                patch.stopall()

        self.assertEqual(investigation.queries,
                         [LanguageSummaryQuery(graph_id="repo-map", family=family) for family in FAMILIES])
        self.assertEqual(source.queries, [(operation, query) for _n, _a, operation, query in sources])
        self.assertEqual(canonical.calls, 1)
        self.assertEqual(seam_results, adapter_results)
        for connection in connections:
            self.assertEqual(connection.selection.graph_id, "repo-map")
        for index, family in enumerate(FAMILIES):
            self.assertEqual(seam_results[index]["summary_kind"], family)
            self.assertEqual(seam_results[index]["summary"]["family"], family)
            self.assertEqual(seam_results[index]["summary"]["root_path"], "[graph-root]")
        self.assertEqual(seam_results[5][0]["source_id"], "example-feed")
        self.assertEqual(seam_results[9], EXPLANATION)
        self.assertEqual(seam_results[11]["counts"]["canonical_nodes"], 11)
        self.assertEqual((seam_results[11]["root_path"], seam_results[11]["project"]), ("[graph-root]", "repo-map"))

    def test_legacy_default_project_override_and_explicit_forms_are_preserved(self) -> None:
        legacy = self.write_mcp_config({
            "default_project": "legacy", "allow_project_overrides": True,
            "projects": {"legacy": {"root_path": "/workspace/legacy", "pg_database": "legacy_db",
                                    "pg_host": "db.internal", "pg_port": "6543", "pg_user": "reader"}},
        })
        forms: tuple[tuple[dict[str, Any], dict[str, Any], str | None], ...] = (
            ({}, {"root_path": "/workspace/legacy", "pg_database": "legacy_db", "pg_host": "db.internal",
                  "pg_port": "6543", "pg_user": "reader"}, "legacy"),
            ({"project": "legacy", "pg_database": "override_db"}, {"pg_database": "override_db"}, "legacy"),
            ({"root_path": "/workspace/explicit", "pg_database": "explicit_db", "pg_host": "127.0.0.1",
              "pg_port": 5544, "pg_user": "explicit"},
             {"root_path": "/workspace/explicit", "pg_database": "explicit_db", "pg_port": "5544"}, None),
        )
        for project_args, expected_connection, expected_project in forms:
            source, canonical = FakeSourceReadStore(), FakeCanonicalReadStore()
            connections: list[Any] = []

            def source_factory(connection: Any, _store: FakeSourceReadStore = source) -> FakeSourceReadStore:
                connections.append(connection)
                return _store

            def canonical_factory(connection: Any, _store: FakeCanonicalReadStore = canonical) -> Any:
                connections.append(connection)
                return _store

            calls = source_calls(project_args)
            with self.subTest(form=sorted(project_args)), \
                    patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(legacy)}, clear=True), \
                    patch("repomap_kg.server.mcp.source_read_store", source_factory), \
                    patch("repomap_kg.server.mcp.canonical_read_store", canonical_factory), \
                    patch("repomap_kg.server.mcp.graph_stores", fail_if_reached), \
                    patch("repomap_kg.server.canonical_read_store.readback_postgres_authority", fail_if_reached):
                for name, args, _operation, _query in calls:
                    self._handle(name, args)
                status = self._handle("repomap_status", project_args)
            self.assertEqual(source.queries, [(operation, query) for _n, _a, operation, query in calls])
            self.assertEqual(status.get("project"), expected_project)
            self.assertEqual(len(connections), 7)
            for connection in connections:
                self.assertIsNone(connection.selection)
                for field, value in expected_connection.items():
                    self.assertEqual(getattr(connection, field), value, field)

    def test_legacy_connection_adapter_call_is_the_incumbent_ambient_call(self) -> None:
        from repomap_kg.server.mcp import source_read_store
        from repomap_kg.server.mcp_core import StorageConnection

        connection = StorageConnection(
            root_path="/workspace/legacy", pg_database="legacy_db", root_path_display="[project-root]",
            pg_host="db.internal", pg_port="6543", pg_user="reader", psql_command="/opt/bin/psql",
        )
        calls: list[tuple[tuple, dict]] = []

        def owner(*args: Any, **kwargs: Any) -> Any:
            calls.append((args, kwargs))
            return RUNS

        with patch("repomap_kg.server.mcp.query_source_run_records", owner), \
                patch("repomap_kg.server.canonical_read_store.readback_postgres_authority", fail_if_reached):
            source_read_store(connection).source_runs(SourceRunsQuery("example-feed", 4))
        kwargs = {"psql_command": "/opt/bin/psql", "root_path": "/workspace/legacy", "source_id": "example-feed"}
        self.assertEqual(calls, [((["-h", "db.internal", "-p", "6543", "-U", "reader", "-d", "legacy_db"],),
                                  {**kwargs, "limit": 4})])

    def test_invalid_arguments_and_graphs_refuse_before_store_access(self) -> None:
        from repomap_kg.server.mcp import RepoMapMcpError

        feed = {"project": "repo-map", "source_id": "example-feed"}
        cases: tuple[tuple[str, dict[str, Any], str], ...] = (
            ("repomap_source_summary", {**feed, "source_id": "   "}, "source_id is required"),
            ("repomap_source_runs", {**feed, "source_id": "https://example.invalid/feed"},
             "source_id must not be a URL"),
            ("repomap_source_runs", {**feed, "source_id": "has space"}, "source_id must not contain whitespace"),
            ("repomap_source_feed_items", {**feed, "limit": 0}, "limit must be between 1 and 500"),
            ("repomap_source_feed_items", {**feed, "source_run_id": "  "}, "source_run_id is required"),
            ("repomap_source_references", {**feed, "target_kind": "https://x.invalid"},
             "target_kind must not be a URL"),
            ("repomap_ingested_sources", {"project": "repo-map", "source_type": "   "}, "source_type is required"),
            ("repomap_ingested_sources", {"project": "repo-map", "limit": 501}, "limit must be between 1 and 500"),
            ("repomap_explain_source_feed_item", {"project": "repo-map", "item_key": "python.module:a"},
             "item_key must use the feed.item namespace"),
            ("repomap_source_summary", {**feed, "project": "missing"},
             "unknown legacy MCP project or graph-registry graph_id: missing"),
            ("repomap_source_summary", {**feed, "project": "hidden"}, "graph 'hidden' is not MCP-visible"),
            ("repomap_source_runs", {**feed, "project": "disabled"}, "graph 'disabled' is not enabled"),
            ("repomap_status", {"project": "hidden"}, "graph 'hidden' is not MCP-visible"),
            ("repomap_status", {"project": "missing"},
             "unknown legacy MCP project or graph-registry graph_id: missing"),
            ("repomap_python_summary", {"graph_id": "missing"}, "unknown graph_id: missing"),
            ("repomap_nix_summary", {"graph_id": "hidden"}, "graph 'hidden' is not MCP-visible"),
            ("repomap_openapi_summary", {"graph_id": "disabled"}, "graph 'disabled' is not enabled"),
            ("repomap_terraform_summary", {"graph_id": "repo-map", "sql": "SELECT 1"},
             "unexpected argument(s): sql"),
        )
        env = self.patch_mcp_and_ops_config(self.write_empty_mcp_config(), self.write_visible_ops_config())
        owners: dict[str, Any] = {**{owner: fail_if_reached for owner in SUMMARY_OWNERS.values()},
                                  "investigation_stores": failing_store_binding}
        mcp_owners: dict[str, Any] = {"graph_stores": failing_store_binding,
                                      **{owner: fail_if_reached for owner in SOURCE_OWNERS.values()}}
        with env, patch.multiple("repomap_kg.server.ops", **owners), \
                patch.multiple("repomap_kg.server.mcp", **mcp_owners):
            for name, args, expected in cases:
                with self.subTest(name=name, args=args), self.assertRaises(RepoMapMcpError) as raised:
                    self._handle(name, args)
                self.assertEqual(str(raised.exception), expected)

    def test_unknown_summary_kind_refuses_before_store_and_adapter_is_closed(self) -> None:
        from repomap_kg.ops.config import load_ops_config
        from repomap_kg.server._ops_records import McpOpsError
        from repomap_kg.server.ops import summary_payload

        config_path = self.write_visible_ops_config()
        # The no-IO binding exists (psql-env refusal keeps its position); no store or read is reached.
        with self.patch_ops_config(config_path), \
                patch("repomap_kg.server.ops.investigation_stores", failing_store_binding), \
                self.assertRaises(KeyError):
            summary_payload("repo-map", summary_kind="ruby")
        store = PostgresInvestigationReadStore(load_ops_config(config_path), None, InvestigationStorageQueries(
            refresh_status=fail_if_reached, search=fail_if_reached, storage_summary=fail_if_reached,
            neighborhood=fail_if_reached, language_summaries=LanguageSummaryQueries(*(fail_if_reached,) * 5),
        ))
        unsupported: Any = "ruby"
        with self.assertRaisesRegex(McpOpsError, "unsupported summary family: ruby"):
            store.language_summary(LanguageSummaryQuery(graph_id="repo-map", family=unsupported))

    def test_no_server_module_references_the_retired_or_fallback_readers(self) -> None:
        # RESOLVE1 removed the dormant MCP readers; the explicit CLI
        # host_then_container route stays with ops.refresh and is unreachable
        # from every server module (exact names and the mode literal).
        import repomap_kg.server as server

        retired = {"query_storage", "query_configured_storage", "run_storage_readback_with_ops_psql",
                   "_container_psql_execution"}
        modules = sorted(Path(next(iter(server.__path__))).glob("*.py"))
        self.assertGreater(len(modules), 20)
        for module in modules:
            nodes = list(ast.walk(ast.parse(module.read_text(encoding="utf-8"))))
            names = {node.id for node in nodes if isinstance(node, ast.Name)}
            names |= {node.attr for node in nodes if isinstance(node, ast.Attribute)}
            names |= {node.name for node in nodes if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
            names |= {alias.name for node in nodes if isinstance(node, (ast.Import, ast.ImportFrom))
                      for alias in node.names}
            literals = {node.value for node in nodes if isinstance(node, ast.Constant) and isinstance(node.value, str)}
            with self.subTest(module=module.name):
                self.assertEqual(names & retired, set())
                self.assertNotIn("host_then_container", literals)

    def test_canonical_store_status_operation_uses_the_bound_summary_owner(self) -> None:
        from repomap_kg.server.mcp import canonical_read_store
        from repomap_kg.server.mcp_core import StorageConnection

        connection = StorageConnection(root_path="/workspace/x", pg_database="x_db", root_path_display="[explicit-root]")
        with patch("repomap_kg.server.mcp.query_canonical_storage_summary",
                   lambda *args, **kwargs: (args, kwargs)) as _owner:
            store = canonical_read_store(connection)
            assert isinstance(store, PostgresCanonicalReadStore)
            result: Any = store.canonical_storage_summary()
        self.assertEqual(result, ((["-d", "x_db"],), {"psql_command": "psql", "root_path": "/workspace/x"}))
        self.assertIs(_owner, store.queries.storage_summary)
