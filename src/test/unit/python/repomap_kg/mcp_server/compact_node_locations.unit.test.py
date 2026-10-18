"""Compact contract through real publication, sanitization and public MCP dispatch."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from repomap_kg.server import mcp
from repomap_kg.server.mcp_core import RepoMapMcpError
from repomap_kg.storage.sqlite_local import node_location_queries
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_test_support.host_read_store_config import NO_FALLBACK_GUARDS, patched_guards, setup_owned_config
from repomap_test_support.node_location_fixtures import DOC, GRAPH, SYMBOL, locator_home, publish_locator_generation
from repomap_test_support.sqlite_local_fixtures import generation_bundle, publication_for


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home, database = locator_home(tmp_path, reference_count=5)
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    return database


def call(key: str = DOC, **options: Any) -> dict[str, Any]:
    return mcp.handle_tool_call("repomap_node_locations", {
        "graph_id": GRAPH, "canonical_key": key, **options,
    })["structuredContent"]


def edit(database: Path, sql: str, params: tuple = ()) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(sql, params)


def compare(key: str = DOC, **options: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    full = call(key, **options)
    assert full == call(key, detail="full", **options)
    compact = call(key, detail="compact", **options)
    assert compact == call(key, detail="compact", **options)
    assert compact["detail"] == "compact" and compact["schema_version"] == 1
    assert compact["graph"] == {name: full["graph"][name] for name in ("graph_id", "repository_name")}
    assert compact["evidence_role"] == full.get("evidence_role", "all")
    for name in full.keys() - {"graph", "safety", "locations", "historical_locations"}:
        assert compact[name] == full[name]
    assert "safety" not in compact
    for window in ("locations", "historical_locations"):
        assert len(compact[window]) == len(full[window])
        for row, original in zip(compact[window], full[window], strict=True):
            for name in original.keys() - {"source", "publication", "raw_observation", "path_namespace", "evidence_key"}:
                assert row[name] == original[name]
            assert "evidence_key" not in row
            assert original["path_namespace"] == compact["path_namespace"]
            source = dict(compact["bindings"][row["binding"]])
            if "source_relative_path" in row:
                source["source_relative_path"] = row["source_relative_path"]
            assert source == original["source"]
            assert compact["publications"][row["publication"]] == original["publication"]
            assert row["raw_observation"] == {
                name: original["raw_observation"][name] for name in ("status", "ordinal", "kind")
            }
            assert original["raw_observation"]["run_id"] == row["run_id"]
    return full, compact


@pytest.mark.parametrize("key", [DOC, SYMBOL])
@pytest.mark.parametrize("role", ["all", "direct", "reference", "unknown"])
@pytest.mark.parametrize("limit", [1, 2])
def test_compact_matches_full_navigation_facts(store: Path, tmp_path: Path, key: str, role: str, limit: int) -> None:
    before = hashlib.sha256(store.read_bytes()).hexdigest()
    full, compact = compare(key, evidence_role=role, limit=limit)
    if role == "direct" and key == DOC:
        row = compact["locations"][0]
        assert row["path"] == "root/docs/guide.md" and row["start_line"] is row["end_line"] is None
        assert row["range_status"] == "missing_or_invalid" and compact["has_more"] is False
    if role == "direct" and key == SYMBOL:
        assert compact["locations"][0]["start_line"] == 5
        assert compact["has_more"] is (limit == 1)
    serialize = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert len(serialize(compact)) < len(serialize(full))
    assert hashlib.sha256(store.read_bytes()).hexdigest() == before
    assert not (tmp_path / "never-created-source").exists()


def test_compact_preserves_default_search_and_uses_one_bound_read(store: Path) -> None:
    search = mcp.repomap_search_nodes(graph_id=GRAPH, query="root", limit=2)
    full = call()
    with patch.object(node_location_queries, "read_transaction", wraps=node_location_queries.read_transaction) as read:
        compact = call(detail="compact")
    assert read.call_count == 1
    assert "evidence_role" not in full and compact["evidence_role"] == "all"
    assert call() == full and call(detail="full") == full
    assert mcp.repomap_search_nodes(graph_id=GRAPH, query="root", limit=2) == search


def test_conflicting_direct_ranges_and_bindings_are_not_merged(store: Path) -> None:
    edit(store, "UPDATE canonical_evidence SET path = 'root/src/service.py' WHERE raw_kind = 'python.function'")
    # Persisted conflicting binding facts must stay distinct, even for equal paths.
    edit(store, "UPDATE canonical_evidence SET metadata_json = ? WHERE path = ? AND start_line = 20",
         (json.dumps({"binding_id": "bind1:other", "binding_revision": 8,
                      "source_relative_path": "src/service.py"}), "root/src/service.py"))
    _, one = compare(SYMBOL, evidence_role="direct", limit=1)
    _, both = compare(SYMBOL, evidence_role="direct", limit=2)
    assert one["has_more"] is True and one["ambiguity"] == "truncated"
    assert both["ambiguity"] == "multiple_stored_locations" and both["has_more"] is False
    assert [(row["start_line"], row["end_line"]) for row in both["locations"]] == [(5, 15), (20, 23)]
    assert both["locations"][0]["binding"] != both["locations"][1]["binding"]
    assert len(both["publications"]) == 1


def test_historical_only_and_historical_primary_remain_historical(store: Path) -> None:
    publish_locator_generation(store, 2, reference_count=5, definitions=False)
    _, compact = compare(evidence_role="direct", limit=1)
    assert compact["locations"] == [] and compact["reason"] == "historical_locations_only"
    assert compact["status"] == "unavailable" and compact["location_scope"] == "accepted_run"
    assert compact["historical_locations"][0]["publication_relation"] == "historical_run"
    bundle = generation_bundle(2)
    publish_generation(store, publication_for(bundle, GRAPH), bundle.families, expected_generation=2)
    _, historical = compare(SYMBOL, evidence_role="all", limit=2)
    assert historical["location_scope"] == "historical_run"
    assert all(row["publication_relation"] == "historical_run" for row in historical["locations"])


def test_truncated_history_keeps_its_own_bounds_and_null_ranges(store: Path) -> None:
    for generation in range(2, 6):
        publish_locator_generation(store, generation, alternatives=False, start_line=40)
    _, compact = compare(SYMBOL, evidence_role="direct", limit=2)
    assert [row["run_id"] for row in compact["historical_locations"]] == [4, 3]
    assert compact["historical_has_more"] is True and compact["has_more"] is False
    assert compact["ambiguity"] == "single_stored_location"
    assert len(compact["publications"]) == 3


def test_withheld_historical_paths_preserve_gaps_without_advertising_a_lead(store: Path) -> None:
    publish_locator_generation(store, 2, reference_count=5, definitions=False)
    edit(store, "UPDATE canonical_evidence SET path = '/private/withheld/history.md'")
    _, compact = compare(evidence_role="direct", limit=1)
    assert compact["historical_locations"][0]["path"] is None
    assert compact["historical_locations"][0]["path_status"] == "missing_or_withheld"
    assert compact["reason"] == "no_usable_location"
    assert "/private/withheld" not in json.dumps(compact)


@pytest.mark.parametrize("fault", ["raw", "binding", "path", "range", "metadata", "evidence"])
def test_missing_withheld_and_unbound_facts_remain_explicit(store: Path, fault: str) -> None:
    if fault == "raw":
        edit(store, "DELETE FROM raw_observations")
    elif fault == "binding":
        edit(store, "UPDATE canonical_evidence SET metadata_json = '{}'")
    elif fault == "path":
        edit(store, "UPDATE canonical_evidence SET path = '/private/withheld/example.md'")
    elif fault == "range":
        edit(store, "UPDATE canonical_evidence SET start_line = 9, end_line = 2")
    else:
        edit(store, "DELETE FROM canonical_node_evidence")
        if fault == "metadata":
            edit(store, "UPDATE canonical_nodes SET metadata_json = ? WHERE canonical_key = ?",
                 (json.dumps({"doc_path": "docs/guide.md"}), DOC))
    _, result = compare(evidence_role="direct", limit=1)
    if fault == "raw":
        assert result["locations"][0]["raw_observation"]["status"] == "unavailable"
    elif fault == "binding":
        assert result["bindings"] == [{}] and "source_relative_path" not in result["locations"][0]
    elif fault == "path":
        assert result["locations"][0]["path"] is None
        assert result["locations"][0]["path_status"] == "missing_or_withheld"
        assert "/private/withheld" not in json.dumps(result)
    elif fault == "range":
        assert result["locations"][0]["start_line"] is result["locations"][0]["end_line"] is None
    elif fault == "metadata":
        assert result["status"] == result["ambiguity"] == "metadata_only"
        assert result["metadata_location"]["binding_status"] == "unavailable"
        assert result["metadata_location"]["evidence_role"] == "unknown"
    else:
        assert result["status"] == "unavailable" and result["locations"] == []


def test_withheld_source_relative_path_does_not_reappear_in_binding_table(store: Path) -> None:
    edit(store, "UPDATE canonical_evidence SET metadata_json = ?",
         (json.dumps({"binding_id": "bind1:test", "source_relative_path": "/private/hidden"}),))
    _, result = compare(evidence_role="direct")
    assert result["locations"][0]["source_relative_path"] is None
    assert "/private/hidden" not in json.dumps(result)


def test_unavailable_graphs_and_boundaries_match_full(store: Path) -> None:
    for graph in ("sibling", "unpublished"):
        compare(graph_id=graph)
    with pytest.raises(RepoMapMcpError, match="not MCP-visible"):
        call(graph_id="hidden", detail="compact")
    edit(store, "UPDATE graph_binding SET repository_identity = 'repo1:foreign'")
    with pytest.raises(RepoMapMcpError, match="graph-database-graph-mismatch"):
        call(detail="compact")


def test_postgresql_unsupported_stays_an_ordinary_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "postgres-home"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    with patched_guards(NO_FALLBACK_GUARDS):
        _, result = compare(graph_id="host-one", evidence_role="direct")
    assert result["reason"] == "backend_unsupported" and result["locations"] == []


@pytest.mark.parametrize("detail", ["small", "", None, True, [], {}])
def test_invalid_detail_refuses_before_configuration_or_storage(detail: Any) -> None:
    with patch("repomap_kg.server._mcp_locations.configured_graph", side_effect=AssertionError("I/O")):
        with pytest.raises(RepoMapMcpError, match="detail must be full or compact"):
            call(detail=detail)
        response = mcp.handle_jsonrpc_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "repomap_node_locations", "arguments": {
                "graph_id": GRAPH, "canonical_key": DOC, "detail": detail}}})
        assert response is not None
        assert response["result"]["isError"] is True


def test_public_schema_and_jsonrpc_serialization(store: Path) -> None:
    definition = next(row for row in mcp.tool_definitions() if row["name"] == "repomap_node_locations")
    assert definition["inputSchema"]["properties"]["detail"] == {
        "type": "string", "enum": ["full", "compact"], "default": "full",
    }
    response = mcp.handle_jsonrpc_message({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "repomap_node_locations", "arguments": {
            "graph_id": GRAPH, "canonical_key": DOC, "detail": "compact", "evidence_role": "direct"}}})
    assert response is not None
    result = response["result"]
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    assert result["structuredContent"]["locations"][0]["path"] == "root/docs/guide.md"
