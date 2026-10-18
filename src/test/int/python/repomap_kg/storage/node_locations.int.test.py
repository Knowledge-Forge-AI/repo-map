"""Guarded source-blind stdio owner; canonical execution requires container authority."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from repomap_test_support.node_location_fixtures import (
    DOC, GRAPH, SYMBOL, locator_home, publish_locator_generation,
)
from repomap_test_support.sqlite_local_harness import LocalHarness, initialize, refusal, structured, tool


def test_node_locations_over_guarded_sqlite_stdio(tmp_path: Path) -> None:
    home, database = locator_home(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    args = {"graph_id": GRAPH, "canonical_key": SYMBOL}
    requests = [initialize(1),
                tool(2, "repomap_node_locations", args),
                tool(3, "repomap_node_locations", {**args, "limit": 1}),
                tool(4, "repomap_node_locations", {**args, "canonical_key": DOC}),
                tool(5, "repomap_node_locations", {**args, "graph_id": "sibling"}),
                tool(6, "repomap_node_locations", {**args, "graph_id": "hidden"}),
                tool(7, "repomap_search_nodes", {"graph_id": GRAPH, "query": "sample.service"})]
    first = harness.mcp(home, requests)
    second = harness.mcp(home, requests)
    assert first == second
    result = structured(first, 2)
    assert result["status"] == "located" and len(result["locations"]) == 2
    assert result["ambiguity"] == "multiple_stored_locations"
    assert structured(first, 3)["has_more"] is True
    document = structured(first, 4)
    assert document["metadata_location"]["path"] == "docs/guide.md"
    assert document["metadata_location"]["path_namespace"] == "source_relative"
    assert document["locations"][0]["path_namespace"] == "graph_source_relative"
    assert document["ambiguity"] == "single_stored_location"
    assert structured(first, 5)["reason"] == "node_not_found"
    assert "not MCP-visible" in refusal(first, 6)
    assert structured(first, 7)["results"][0]["metadata"] == {}
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert str(tmp_path) not in json.dumps(first)
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_node_locations_keep_refresh_history_separate_over_stdio(tmp_path: Path) -> None:
    home, database = locator_home(tmp_path)
    for generation in range(2, 13):
        publish_locator_generation(database, generation, start_line=40, alternatives=False)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    requests = [initialize(1), tool(2, "repomap_node_locations", {
        "graph_id": GRAPH, "canonical_key": SYMBOL, "limit": 2,
    })]
    response = harness.mcp(home, requests)
    assert response == harness.mcp(home, requests)
    result = structured(response, 2)
    assert result["location_scope"] == "accepted_run" and result["location_run_id"] == 12
    assert result["ambiguity"] == "single_stored_location" and result["has_more"] is False
    assert [(row["start_line"], row["end_line"]) for row in result["locations"]] == [(40, 50)]
    assert [row["run_id"] for row in result["historical_locations"]] == [11, 10]
    assert result["historical_has_more"] is True
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert not (tmp_path / "never-created-source").exists()
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_direct_source_view_filters_before_guarded_stdio_windows(tmp_path: Path) -> None:
    home, database = locator_home(tmp_path, reference_count=5)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    args = {"graph_id": GRAPH, "canonical_key": DOC, "limit": 1}
    requests = [initialize(1),
                tool(2, "repomap_node_locations", args),
                tool(3, "repomap_node_locations", {**args, "evidence_role": "direct"}),
                tool(4, "repomap_node_locations", {**args, "evidence_role": "reference"}),
                tool(5, "repomap_node_locations", {**args, "evidence_role": "unknown"})]
    response = harness.mcp(home, requests)
    assert response == harness.mcp(home, requests)
    assert structured(response, 2)["locations"][0]["link_kind"] == "inferred_from_edge"
    direct = structured(response, 3)
    assert direct["locations"][0]["path"] == "root/docs/guide.md"
    assert direct["locations"][0]["evidence_role"] == "direct" and direct["has_more"] is False
    assert direct["locations"][0]["start_line"] is None
    assert structured(response, 4)["has_more"] is True
    assert structured(response, 5)["locations"] == []
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    publish_locator_generation(database, 2, reference_count=5, definitions=False)
    after_publication = hashlib.sha256(database.read_bytes()).hexdigest()
    historical = structured(harness.mcp(home, [initialize(1), requests[2]]), 3)
    assert historical["location_scope"] == "accepted_run" and historical["locations"] == []
    assert historical["status"] == "unavailable" and historical["reason"] == "historical_locations_only"
    assert historical["historical_locations"][0]["publication_relation"] == "historical_run"
    assert hashlib.sha256(database.read_bytes()).hexdigest() == after_publication
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE canonical_nodes SET metadata_json = ? WHERE canonical_key = ?",
                           (json.dumps({"doc_path": "docs/guide.md"}), DOC))
    after_metadata = hashlib.sha256(database.read_bytes()).hexdigest()
    partial = structured(harness.mcp(home, [initialize(1), requests[2]]), 3)
    assert partial["status"] == "metadata_only" and partial["ambiguity"] == "metadata_only"
    assert partial["locations"] == [] and partial["metadata_location"]["evidence_role"] == "unknown"
    assert hashlib.sha256(database.read_bytes()).hexdigest() == after_metadata
    assert not (tmp_path / "never-created-source").exists()
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_compact_source_locations_over_guarded_sqlite_stdio(tmp_path: Path) -> None:
    home, database = locator_home(tmp_path, reference_count=5)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    args = {"graph_id": GRAPH, "canonical_key": DOC, "evidence_role": "direct", "limit": 1}
    requests = [initialize(1), tool(2, "repomap_node_locations", args),
                tool(3, "repomap_node_locations", {**args, "detail": "full"}),
                tool(4, "repomap_node_locations", {**args, "detail": "compact"}),
                tool(5, "repomap_node_locations", {**args, "detail": "invalid"})]
    responses = harness.mcp(home, requests)
    full, compact = structured(responses, 2), structured(responses, 4)
    assert structured(responses, 3) == full
    assert compact["detail"] == "compact" and compact["schema_version"] == 1
    assert compact["locations"][0]["path"] == full["locations"][0]["path"] == "root/docs/guide.md"
    assert compact["locations"][0]["start_line"] is compact["locations"][0]["end_line"] is None
    assert compact["bindings"][0]["binding_alias"] == "root"
    assert compact["locations"][0]["source_relative_path"] == "docs/guide.md"
    assert compact["has_more"] == full["has_more"] is False
    assert compact["accepted_publication"] == full["accepted_publication"]
    assert "detail must be full or compact" in refusal(responses, 5)
    assert responses[4]["result"]["structuredContent"] == json.loads(responses[4]["result"]["content"][0]["text"])
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert not (tmp_path / "never-created-source").exists()
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""
