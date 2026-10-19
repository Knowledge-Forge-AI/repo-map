"""Guarded SQLite Local boundary contracts for navigation, similarity, and neighborhood."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from repomap_test_support.navigation_search_fixtures import BETA_DOC, BINDING, GRAPH, navigation_home
from repomap_test_support.sqlite_local_harness import LocalHarness, initialize, refusal, structured, tool


def test_sqlite_embedding_profiles_and_similar_nodes_disabled_refusals(tmp_path: Path) -> None:
    home, database = navigation_home(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    similar_args = {
        "graph_id": GRAPH,
        "canonical_key": BETA_DOC,
        "rebuild_id": "rb-seed",
        "profile_identity": "sha256:" + "a" * 64,
        "dimensions": 128,
    }
    requests = [
        initialize(),
        tool(2, "repomap_embedding_profiles", {"graph_id": GRAPH, "selected": False}),
        tool(3, "repomap_embedding_profiles", {"graph_id": GRAPH, "selected": True}),
        tool(4, "repomap_similar_nodes", {**similar_args, "selected": False}),
        tool(5, "repomap_similar_nodes", {**similar_args, "selected": True}),
        tool(6, "repomap_navigation_search", {"graph_id": GRAPH, "query": "beacon"}),
    ]
    responses = harness.mcp(home, requests)
    assert responses == harness.mcp(home, requests)

    p_disabled = structured(responses, 2)
    assert p_disabled["status"] == "capability_unavailable" and p_disabled["reason"] == "disabled"
    assert p_disabled["server"] == "repomap-kg" and p_disabled["read_only"] is True

    p_unsupported = structured(responses, 3)
    assert p_unsupported["status"] == "capability_unavailable" and p_unsupported["reason"] == "sqlite_unsupported"

    s_disabled = structured(responses, 4)
    assert s_disabled["status"] == "capability_unavailable" and s_disabled["reason"] == "disabled"
    assert s_disabled["server"] == "repomap-kg" and s_disabled["read_only"] is True

    s_unsupported = structured(responses, 5)
    assert s_unsupported["status"] == "capability_unavailable" and s_unsupported["reason"] == "sqlite_unsupported"

    valid = structured(responses, 6)
    assert valid["status"] == "ok" and valid["results"]
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_navigation_search_scope_prefix_exclusion_and_conflicting_identities(tmp_path: Path) -> None:
    home, database = navigation_home(tmp_path)
    with sqlite3.connect(database) as connection:
        # Link a second distinct direct evidence destination to BETA_DOC to induce conflicting direct identities.
        alpha_ev = connection.execute(
            "SELECT id FROM canonical_evidence WHERE path = 'root/docs/alpha.md' "
            "AND raw_kind = 'markdown.document' LIMIT 1"
        ).fetchone()[0]
        beta_node_id = connection.execute(
            "SELECT id FROM canonical_nodes WHERE canonical_key = ?", (BETA_DOC,)
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO canonical_node_evidence(canonical_node_id, canonical_evidence_id, link_kind) "
            "VALUES (?, ?, 'observed')",
            (beta_node_id, alpha_ev),
        )
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)

    # Scoped navigation excluding paths outside prefix:
    prefix_args = {
        "graph_id": GRAPH,
        "query": "beacon",
        "scope": "docs",
        "grouping": "source_document",
        "source_binding_id": BINDING,
        "source_path_prefix": "docs/adr",
    }
    # The page title is Deployment Operations; its section alone matches beacon.
    unscoped_args = {
        "graph_id": GRAPH,
        "query": "deployment",
        "scope": "docs",
        "grouping": "source_document",
    }
    requests = [
        initialize(),
        tool(2, "repomap_navigation_search", prefix_args),
        tool(3, "repomap_navigation_search", unscoped_args),
        tool(4, "repomap_search_nodes", {"graph_id": GRAPH, "query": "beacon", "limit": 1}),
    ]
    responses = harness.mcp(home, requests)
    assert responses == harness.mcp(home, requests)

    scoped = structured(responses, 2)
    assert scoped["status"] == "ok" and scoped["results"]
    for group in scoped["results"]:
        assert group["destination"] is not None
        assert group["destination"]["source_relative_path"].startswith("docs/adr")

    unscoped = structured(responses, 3)
    assert unscoped["status"] == "ok"
    reasons = {group["unresolved_reason"] for group in unscoped["results"] if group["unresolved_reason"]}
    assert "conflicting_direct_identities" in reasons

    assert any(group["destination"] is None and group["basis"] == "singleton"
               and any(member["canonical_key"] == BETA_DOC for member in group["members"])
               for group in unscoped["results"])

    nodes = structured(responses, 4)
    assert nodes["target"] == "nodes" and nodes["results"]
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_bounded_neighborhood_validation_and_refusals(tmp_path: Path) -> None:
    home, database = navigation_home(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    base_args = {"graph_id": GRAPH, "node": BETA_DOC}

    invalid_options: list[tuple[dict[str, Any], str]] = [
        ({"node_limit": 0}, "node_limit must be an integer between 1 and 100"),
        ({"node_limit": 101}, "node_limit must be an integer between 1 and 100"),
        ({"node_limit": "invalid"}, "node_limit must be an integer between 1 and 100"),
        ({"edge_limit": -1}, "edge_limit must be an integer between 1 and 100"),
        ({"edge_limit": 200}, "edge_limit must be an integer between 1 and 100"),
        ({"edge_limit": "invalid"}, "edge_limit must be an integer between 1 and 100"),
        ({"direction": "sideways"}, "neighborhood direction must be one of both, in, out"),
        ({"depth": 2}, "neighborhood depth is capped at 1 in MCP-OPS4"),
    ]
    requests = [
        initialize(),
        *(tool(mid, "repomap_neighborhood", {**base_args, **opts})
          for mid, (opts, _) in enumerate(invalid_options, 2)),
        tool(20, "repomap_neighborhood", {**base_args, "node_limit": 5, "edge_limit": 5}),
    ]
    responses = harness.mcp(home, requests)
    for mid, (_, expected_msg) in enumerate(invalid_options, 2):
        assert expected_msg in refusal(responses, mid)

    valid = structured(responses, 20)
    assert valid["result"]["center"]["canonical_key"] == BETA_DOC
    assert "bounds" in valid["result"]
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_navigation_search_validation_contract_boundaries(tmp_path: Path) -> None:
    home, database = navigation_home(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    base_args = {"graph_id": GRAPH, "query": "beacon"}

    invalid_queries: list[tuple[dict[str, Any], str]] = [
        ({"query": "x" * 201}, "query must be at most 200 characters"),
        ({"scope": "unsupported"}, "scope must be all, code, or docs"),
        ({"grouping": "by_author"}, "grouping must be none or source_document"),
        ({"limit": 51}, "limit must be between 1 and 50"),
        ({"limit": 0}, "limit must be between 1 and 50"),
        ({"member_limit": 21}, "member_limit must be between 1 and 20"),
        ({"member_limit": 0}, "member_limit must be between 1 and 20"),
        ({"offset": 10001}, "offset must be between 0 and 10000"),
        ({"offset": -5}, "offset must be between 0 and 10000"),
        ({"source_path_prefix": "/abs/docs"}, "source_path_prefix requires source_binding_id"),
        ({"source_binding_id": BINDING, "source_path_prefix": "/abs/docs"}, "source-relative"),
        ({"source_binding_id": BINDING, "source_path_prefix": "~home"}, "source-relative"),
        ({"source_binding_id": BINDING, "source_path_prefix": "docs:anchor"}, "source-relative"),
        ({"source_binding_id": BINDING, "source_path_prefix": "docs/../escape"}, "source-relative"),
        ({"source_binding_id": "bad\x01id"}, "source_binding_id must be a nonempty bounded string"),
    ]
    requests = [
        initialize(),
        *(tool(mid, "repomap_navigation_search", {**base_args, **opts})
          for mid, (opts, _) in enumerate(invalid_queries, 2)),
        tool(50, "repomap_navigation_search", base_args),
    ]
    responses = harness.mcp(home, requests)
    for mid, (_, expected_msg) in enumerate(invalid_queries, 2):
        assert expected_msg in refusal(responses, mid)

    valid = structured(responses, 50)
    assert valid["status"] == "ok" and valid["results"]
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""
