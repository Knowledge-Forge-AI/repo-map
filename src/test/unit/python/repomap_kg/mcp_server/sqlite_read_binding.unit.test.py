"""SQLite Local MCP routing: selection first, SQLite reads, bounded refusals.

A SQLite Local home routes all 23 database-reading tools to real read-only
SQLite queries with every PostgreSQL binding tripwire armed, including the six
source/feed tools over a real offline feed publication (LOCAL5); logical
selection refusals and argument validation keep the PostgreSQL texts and
precede any open; legacy ``repomap_status`` keeps its legacy and explicit
PostgreSQL routes; and PostgreSQL homes still bind PostgreSQL stores.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import repomap_kg.server.mcp as mcp
import repomap_kg.runtime.plan as runtime_plan
import repomap_kg.server.ops as server_ops
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from repomap_kg.server._ops_records import McpOpsError, graph_context, load_mcp_ops_config
from repomap_kg.server.mcp_core import RepoMapMcpError
from repomap_kg.server.graph_selection import select_graph
from repomap_kg.server.postgres_read_binding import PostgresGraphStores, PostgresInvestigationStores
from repomap_kg.server.source_read_store import PostgresSourceReadStore
from repomap_kg.server.sqlite_read_binding import (
    SUPPORTED_TOOLS,
    SqliteGraphStores,
    SqliteInvestigationStores,
    SqliteSourceReadStore,
)
from repomap_kg.storage import CanonicalStorageSummaryRecord
from repomap_kg.storage.sqlite_local.connection import initialize_graph_database
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_test_support.host_read_store_config import (
    PG_BINDING_TRIPWIRES,
    fail_if_reached,
    patched_guards,
    setup_owned_config,
)
from repomap_test_support.sqlite_local_feed_corpus import (
    RSS,
    acquire_feed_runs,
    feed_bundle,
    generation_observations,
)
from repomap_test_support.sqlite_local_fixtures import (
    generation_bundle,
    graph_toml,
    local_binding,
    publication_for,
    write_sqlite_home,
)
from repomap_test_support.sqlite_local_read_corpus import CorpusRow, read_corpus_bundle

# The tripwires patch ``resolve_ops_config`` by module attribute, and selection
# lazily imports ``runtime.plan``, which binds that name at import time. Importing
# it here, before any tripwire, keeps a first import under an armed tripwire from
# freezing the double into the module for later owners in the same process (an
# entry-state interaction); ``home`` asserts the real function is still bound.
REAL_RESOLVE_OPS_CONFIG = runtime_plan.resolve_ops_config

GRAPH = "portable-fixture"
CORPUS = "read-corpus"
FEEDS = "feeds"
PG_STATUS = "repomap_kg.server.mcp.query_canonical_storage_summary"
ITEM_KEY = "feed.item:feed.channel%3Afeed.document%253Afile%25253Arss.xml%3Aself:item-1"
READ_TRANSACTION = "repomap_kg.server.sqlite_read_binding.read_transaction"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    graphs = (
        graph_toml(GRAPH, tmp_path / "src")
        + graph_toml("hidden", tmp_path / "src", visible=False)
        + graph_toml("disabled", tmp_path / "src", enabled=False)
        + graph_toml("absent", tmp_path / "src")
        + graph_toml(CORPUS, tmp_path / "src")
        + graph_toml("private", tmp_path / "src", privacy="private-ops")
        + graph_toml(FEEDS, tmp_path / "src")
    )
    home = write_sqlite_home(tmp_path / "home", graphs)
    registry = tmp_path / "registry.json"
    registry.write_text('{"projects": {}}\n', encoding="utf-8")
    for name in ("REPOMAP_OPS_CONFIG", "REPOMAP_READ_STATUS_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.setenv("REPOMAP_MCP_CONFIG", str(registry))
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    assert runtime_plan.resolve_ops_config is REAL_RESOLVE_OPS_CONFIG
    config.graph_store_root.mkdir(parents=True, mode=0o700)
    # The configured root is a private path marker; one observation carries it.
    leaked: tuple[CorpusRow, ...] = (("custom.note", "notes/where.md", {"where": str(tmp_path / "src")}, {}),)
    feed_runs = acquire_feed_runs(tmp_path / "feed-root")
    for graph_id, bundle in ((GRAPH, generation_bundle(1)), (CORPUS, read_corpus_bundle(CORPUS)),
                             ("private", read_corpus_bundle("private", extra_rows=leaked)),
                             (FEEDS, feed_bundle(FEEDS, 1, generation_observations(feed_runs, 2)))):
        path = config.graph_store_root / f"{graph_id}.sqlite3"
        initialize_graph_database(path, local_binding(graph_id), applied_at="2026-09-29T00:00:00Z")
        publish_generation(path, publication_for(bundle, graph_id), bundle.families, expected_generation=0)
    return home


def _call(name: str, arguments: dict[str, Any]) -> Any:
    return mcp.handle_tool_call(name, arguments)["structuredContent"]


def _refusal(name: str, arguments: dict[str, Any]) -> str:
    with pytest.raises(RepoMapMcpError) as caught:
        mcp.handle_tool_call(name, arguments)
    return str(caught.value)


SOURCE_ARGUMENTS: dict[str, dict[str, Any]] = {
    "repomap_ingested_sources": {"project": FEEDS},
    "repomap_source_summary": {"project": FEEDS, "source_id": RSS},
    "repomap_source_runs": {"project": FEEDS, "source_id": RSS},
    "repomap_source_feed_items": {"project": FEEDS, "source_id": RSS},
    "repomap_explain_source_feed_item": {"project": FEEDS, "item_key": ITEM_KEY},
    "repomap_source_references": {"project": FEEDS, "source_id": RSS},
}
SUMMARIES = ("python", "terraform", "openapi", "js_framework", "nix")


def test_matrix_covers_every_graph_reading_tool() -> None:
    assert len(SUPPORTED_TOOLS) == len(set(SUPPORTED_TOOLS)) == 23
    assert set(SOURCE_ARGUMENTS) <= set(SUPPORTED_TOOLS)
    catalog = {tool["name"] for tool in mcp.tool_definitions()}
    configuration = {"repomap_list_graphs", "repomap_projects"}
    server_memory = {"repomap_server_memory_summary", "repomap_server_memory_search"}
    assert len(catalog) == 27
    assert catalog == set(SUPPORTED_TOOLS) | configuration | server_memory
    assert not set(SUPPORTED_TOOLS) & (configuration | server_memory)


def test_source_tools_validate_before_any_database_open(home: Path) -> None:
    cases = (
        ("repomap_source_summary", {"project": FEEDS, "source_id": "has space"},
         "source_id must not contain whitespace"),
        ("repomap_source_runs", {"project": FEEDS, "source_id": "https://example.invalid/x"},
         "source_id must not be a URL"),
        ("repomap_source_runs", {"project": FEEDS, "source_id": RSS, "limit": 0},
         "limit must be between 1 and 500"),
        ("repomap_ingested_sources", {"project": FEEDS, "policy_status": "https://x.invalid/"},
         "policy_status must not be a URL"),
        ("repomap_source_feed_items", {"project": FEEDS, "source_id": RSS, "source_run_id": "file://x"},
         "source_run_id must not be a URL"),
        ("repomap_source_references", {"project": FEEDS, "source_id": RSS, "target_kind": "http://x"},
         "target_kind must not be a URL"),
        ("repomap_explain_source_feed_item", {"project": FEEDS, "item_key": "file:x.xml"},
         "item_key must use the feed.item namespace"),
        ("repomap_explain_source_feed_item", {"project": FEEDS, "item_key": ITEM_KEY, "source_id": "a b"},
         "source_id must not contain whitespace"),
        ("repomap_source_summary", {"project": "hidden", "source_id": RSS}, "graph 'hidden' is not MCP-visible"),
        ("repomap_source_references", {"project": "disabled", "source_id": RSS}, "graph 'disabled' is not enabled"),
    )
    with patched_guards(PG_BINDING_TRIPWIRES), patch(READ_TRANSACTION, fail_if_reached):
        for name, arguments, text in cases:
            assert _refusal(name, arguments) == text, (name, arguments)


def test_source_tools_read_a_feed_publication_with_every_postgres_tripwire_armed(home: Path) -> None:
    with patched_guards(PG_BINDING_TRIPWIRES):
        inventory = _call("repomap_ingested_sources", {"project": FEEDS})
        summary = _call("repomap_source_summary", SOURCE_ARGUMENTS["repomap_source_summary"])
        runs = _call("repomap_source_runs", SOURCE_ARGUMENTS["repomap_source_runs"])
        items = _call("repomap_source_feed_items", SOURCE_ARGUMENTS["repomap_source_feed_items"])
        references = _call("repomap_source_references", {"project": FEEDS, "source_id": RSS,
                                                         "target_kind": "feed.author"})
        explained = _call("repomap_explain_source_feed_item", {
            "project": FEEDS, "item_key": items[0]["item_key"], "source_id": RSS})
        corpus = _call("repomap_ingested_sources", {"project": CORPUS})
    assert [row["source_id"] for row in inventory] == [
        "example-atom-feed", RSS, "example-secret-bearing-feed"]
    assert summary["parse_errors"] == 1 and summary["feed_items"] == 5, summary
    assert [row["status_summary"] for row in runs] == ["parse_errors", "ok"]
    assert len(items) == 5 and len(references) == 1
    assert explained["item"]["kind"] == "feed.item" and explained["evidence"], explained
    assert corpus == []  # a published graph without feeds reads as empty


def test_selection_refusals_keep_public_texts_before_any_open(home: Path) -> None:
    cases = (
        ("repomap_canonical_nodes", {"project": "nope"},
         "unknown legacy MCP project or graph-registry graph_id: nope"),
        ("repomap_canonical_nodes", {"project": "hidden"}, "graph 'hidden' is not MCP-visible"),
        ("repomap_canonical_edges", {"project": "disabled"}, "graph 'disabled' is not enabled"),
        ("repomap_status", {"project": "hidden"}, "graph 'hidden' is not MCP-visible"),
        ("repomap_search_nodes", {"graph_id": "nope", "query": "x"}, "unknown graph_id: nope"),
        ("repomap_graph_status", {"graph_id": "hidden"}, "graph 'hidden' is not MCP-visible"),
        ("repomap_refresh_status", {"graph_id": "hidden"}, "graph 'hidden' is not MCP-visible"),
        ("repomap_project_summary", {"graph_id": "disabled"}, "graph 'disabled' is not enabled"),
        ("repomap_search_observations", {"graph_id": "hidden", "query": "x"},
         "graph 'hidden' is not MCP-visible"),
        ("repomap_neighborhood", {"graph_id": "disabled", "node": "x"}, "graph 'disabled' is not enabled"),
        ("repomap_nix_summary", {"graph_id": "hidden"}, "graph 'hidden' is not MCP-visible"),
        ("repomap_status", {"project": GRAPH, "pg_database": "other"},
         "graph-registry project routing cannot be combined with explicit connection overrides"),
    )
    with patched_guards(PG_BINDING_TRIPWIRES), patch(READ_TRANSACTION, fail_if_reached):
        for name, arguments, text in cases:
            assert _refusal(name, arguments) == text, (name, arguments)


def test_new_tools_validate_before_any_database_open(home: Path) -> None:
    long_query = "x" * 201
    cases = (
        ("repomap_neighborhood", {"graph_id": GRAPH, "node": "x", "depth": 2},
         "neighborhood depth is capped at 1 in MCP-OPS4"),
        ("repomap_neighborhood", {"graph_id": GRAPH, "node": "x", "direction": "sideways"},
         "neighborhood direction must be one of both, in, out"),
        ("repomap_search_observations", {"graph_id": GRAPH, "query": "   "}, "query is required"),
        ("repomap_search_observations", {"graph_id": GRAPH, "query": long_query},
         "query must be at most 200 characters"),
        ("repomap_search_observations", {"graph_id": GRAPH, "query": "x", "limit": 0},
         "limit must be a positive integer"),
        ("repomap_search_observations", {"graph_id": GRAPH, "query": "x", "offset": -1},
         "offset must be a non-negative integer"),
    )
    with patched_guards(PG_BINDING_TRIPWIRES), patch(READ_TRANSACTION, fail_if_reached):
        for name, arguments, text in cases:
            assert _refusal(name, arguments) == text, (name, arguments)


def test_canonical_and_investigation_tools_read_sqlite_with_every_postgres_tripwire_armed(home: Path) -> None:
    edge = mcp.handle_tool_call("repomap_canonical_edges", {"project": GRAPH, "limit": 1})
    first = edge["structuredContent"]["items"][0]
    with patched_guards(PG_BINDING_TRIPWIRES), patch(PG_STATUS, fail_if_reached):
        nodes = _call("repomap_canonical_nodes", {"project": GRAPH, "limit": 2})
        assert len(nodes["items"]) == 2 and nodes["page"]["truncated"] is True
        assert _call("repomap_canonical_nodes", {"project": GRAPH, "result_schema_version": 0})
        assert _call("repomap_canonical_edges", {"project": GRAPH})["items"]
        explained = _call("repomap_explain_canonical_edge", {
            "project": GRAPH, "source_key": first["source_key"], "kind": first["edge_kind"],
            "target_key": first["target_key"], "identity_metadata": first["identity_metadata"],
        })
        assert explained["result"]["edge"]["source_key"] == first["source_key"]
        assert explained["result"]["evidence"]
        around = _call("repomap_canonical_neighborhood", {"project": GRAPH, "node": first["source_key"]})
        assert around["result"]["center"]["canonical_key"] == first["source_key"]
        status = _call("repomap_graph_status", {"graph_id": GRAPH})
        assert status["storage"]["publication"]["execution_route"] == "portable-worker-v1"
        assert status["graph"]["database_source"] == "sqlite-graph-file"
        everything = _call("repomap_refresh_status", {})
        rows = {row["graph_id"]: row for row in everything["graphs"]}
        assert rows[GRAPH]["repository_exists"] is True
        assert rows["absent"]["error"] == "graph-database-not-initialized"
        assert rows["absent"]["repository_exists"] is False and rows["absent"]["db_checked"] is True
        summary = _call("repomap_project_summary", {"graph_id": GRAPH})
        assert summary["summary"]["counts"]["runs"] == 1
        assert _call("repomap_search_nodes", {"graph_id": GRAPH, "query": "init"})["results"]
        files = _call("repomap_search_files", {"graph_id": GRAPH, "query": "py"})
        assert [row["path"] for row in files["results"]] == ["pkg/init.py"]
        listed = _call("repomap_list_graphs", {})
        assert {graph["database_source"] for graph in listed["graphs"]} == {"sqlite-graph-file"}
        projects = _call("repomap_projects", {})
        assert projects["graph_registry_available"] is True and projects["graph_count"] == 5

        legacy = _call("repomap_status", {"project": GRAPH})
        assert legacy["project"] == GRAPH and legacy["counts"]["runs"] == 1
        assert legacy["counts"]["canonical_nodes"] == summary["summary"]["counts"]["canonical_nodes"]
        assert legacy["root_path"] == "[graph-root]" and legacy["storage_model"] == "canonical"
        observed = _call("repomap_search_observations", {"graph_id": CORPUS, "query": "tfvars", "limit": 2})
        assert observed["result_count"] == 2 and observed["has_more"] is True
        assert all("payload" not in row for row in observed["results"])
        assert observed["raw_payload_policy"]["payload_included"] is False
        center = _call("repomap_neighborhood", {"graph_id": GRAPH, "node": first["source_key"]})
        assert center["result"]["center"]["canonical_key"] == first["source_key"]
        assert center["result"]["edges"] and center["depth"] == 1
        missing = _call("repomap_neighborhood", {"graph_id": GRAPH, "node": "python.module:absent"})
        assert missing["result"] == {"center": None, "nodes": [], "edges": []}
        headline = {"python": "python_observations", "terraform": "terraform_observations",
                    "openapi": "openapi_observations", "js_framework": "framework_observations",
                    "nix": "nix_observations"}
        for family in SUMMARIES:
            payload = _call(f"repomap_{family}_summary", {"graph_id": CORPUS})
            assert payload["summary_kind"] == family and payload["summary"][headline[family]] > 0, family


def test_observation_raw_payload_consent_and_private_redaction(home: Path) -> None:
    with patched_guards(PG_BINDING_TRIPWIRES):
        plain = _call("repomap_search_observations", {"graph_id": CORPUS, "query": "custom.note"})
        raw = _call("repomap_search_observations",
                    {"graph_id": CORPUS, "query": "custom.note", "include_raw": True})
        hidden = _call("repomap_search_observations",
                       {"graph_id": "private", "query": "custom.note", "include_raw": True})
    assert [row["kind"] for row in plain["results"]] == ["custom.note"]
    assert "payload" not in plain["results"][0] and plain["results"][0]["metadata"]["b"] == 150
    assert raw["results"][0]["payload"]["metadata"] == plain["results"][0]["metadata"]
    assert raw["raw_payload_policy"] == {**plain["raw_payload_policy"], "include_raw": True,
                                         "payload_included": True}
    assert hidden["graph"]["private"] is True and hidden["result_count"] == 2
    where = next(row for row in hidden["results"] if row["path"] == "notes/where.md")
    assert where["metadata"]["where"] == "[private-path]"
    assert where["payload"]["metadata"]["where"] == "[private-path]"


def test_legacy_status_routing_precedence(home: Path, tmp_path: Path) -> None:
    record = CanonicalStorageSummaryRecord(
        root_path="/legacy", repository_name="legacy", latest_run_id=7, runs=7, files=0,
        raw_observations=0, canonical_nodes=0, canonical_edges=0, canonical_evidence=0,
    )
    registry = tmp_path / "legacy-registry.json"
    registry.write_text(
        '{"default_project": "' + GRAPH + '", "projects": {"' + GRAPH
        + '": {"root_path": "/legacy", "pg_database": "legacy_db"}}}\n',
        encoding="utf-8",
    )
    with patch(READ_TRANSACTION, fail_if_reached), patch(PG_STATUS, return_value=record) as query, \
            patch.dict("os.environ", {"REPOMAP_MCP_CONFIG": str(registry)}):
        assert _call("repomap_status", {"project": GRAPH})["counts"]["runs"] == 7  # legacy entry wins
        assert _call("repomap_status", {})["project"] == GRAPH  # legacy default_project
        explicit = _call("repomap_status", {"root_path": "/explicit", "pg_database": "explicit_db"})
    assert "project" not in explicit and explicit["counts"]["runs"] == 7
    assert [call.args[0][-1] for call in query.call_args_list] == ["legacy_db", "legacy_db", "explicit_db"]


def test_content_tools_refuse_unpublished_graphs_and_legacy_status_reports_zeros(home: Path) -> None:
    config = load_mcp_ops_config()
    assert isinstance(config, LocalSqliteConfig)
    path = config.graph_store_root / "absent.sqlite3"
    initialize_graph_database(path, local_binding("absent"), applied_at="2026-09-29T00:00:00Z")
    for name, arguments in (
        ("repomap_search_observations", {"graph_id": "absent", "query": "x"}),
        ("repomap_neighborhood", {"graph_id": "absent", "node": "x"}),
        *((f"repomap_{family}_summary", {"graph_id": "absent"}) for family in SUMMARIES),
        *((name, {**arguments, "project": "absent"}) for name, arguments in SOURCE_ARGUMENTS.items()),
    ):
        assert _refusal(name, arguments) == "graph-publication-absent", name
    zeros = _call("repomap_status", {"project": "absent"})
    assert zeros["repository_name"] is None and set(zeros["counts"].values()) == {0}


def test_uninitialized_graph_refuses_content_tools_without_creating_a_file(home: Path) -> None:
    store_root = home / "state" / "sqlite-local" / "graphs"
    assert _refusal("repomap_canonical_nodes", {"project": "absent"}) == "graph-database-not-initialized"
    assert _refusal("repomap_project_summary", {"graph_id": "absent"}) == "graph-database-not-initialized"
    assert _refusal("repomap_status", {"project": "absent"}) == "graph-database-not-initialized"
    assert _refusal("repomap_nix_summary", {"graph_id": "absent"}) == "graph-database-not-initialized"
    assert not (store_root / "absent.sqlite3").exists()


def test_bindings_follow_the_declared_backend(home: Path, tmp_path: Path) -> None:
    local = load_mcp_ops_config()
    assert isinstance(local, LocalSqliteConfig)
    assert isinstance(mcp.graph_stores(local), SqliteGraphStores)
    assert isinstance(mcp.source_read_store(mcp.storage_connection(project=FEEDS)), SqliteSourceReadStore)
    assert isinstance(server_ops.investigation_stores(local), SqliteInvestigationStores)
    with pytest.raises(McpOpsError):
        graph_context(GRAPH)
    pg_home = tmp_path / "pg"
    pg_home.mkdir()
    (pg_home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    postgres = load_mcp_ops_config(pg_home)
    assert not isinstance(postgres, LocalSqliteConfig)
    assert isinstance(mcp.graph_stores(postgres), PostgresGraphStores)
    pg_stores = mcp.graph_stores(postgres)
    assert isinstance(pg_stores.source_store(select_graph(postgres, postgres.graphs[0].id)), PostgresSourceReadStore)
    assert isinstance(server_ops.investigation_stores(postgres), PostgresInvestigationStores)
    payload = server_ops.graph_payload(postgres.graphs[0], database="repomap_host_one")
    assert payload["database_source"] == "graph"
