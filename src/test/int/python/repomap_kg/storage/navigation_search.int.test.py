"""Container-guarded stdio ownership for optional scoped navigation search."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from common_lore_index.graph.keys import file_key
from repomap_test_support.navigation_search_fixtures import BETA_DOC, BINDING, GRAPH, navigation_home
from repomap_test_support.sqlite_local_harness import LocalHarness, initialize, refusal, structured, tool
from repomap_test_support.navigation_pushdown_fixtures import pushdown_home


def test_scoped_grouped_navigation_over_guarded_sqlite_stdio(tmp_path: Path) -> None:
    home, database = navigation_home(tmp_path)
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    args = {"graph_id": GRAPH, "query": "beacon", "scope": "docs", "grouping": "source_document", "limit": 1}
    requests = [initialize(), tool(2, "repomap_navigation_search", args),
                tool(3, "repomap_navigation_search", {**args, "offset": 1}),
                tool(4, "repomap_navigation_search", {**args, "scope": "code", "source_binding_id": BINDING,
                                                     "source_path_prefix": "src/pkg/"}),
                tool(5, "repomap_search_nodes", {"graph_id": GRAPH, "query": "beacon", "limit": 1})]
    response = harness.mcp(home, requests)
    assert response == harness.mcp(home, requests)
    first, second = structured(response, 2), structured(response, 3)
    assert first["schema"] == "repomap.navigation_search" and first["count_unit"] == "groups"
    assert first["has_more"] and first["results"][0]["destination"] != second["results"][0]["destination"]
    hint = first["results"][0]["members"][0]["source_hints"][0]
    assert hint["evidence_role"] == "direct" and "evidence_key" not in hint and "publication" not in hint
    assert set(hint["raw_observation"]) == {"status", "ordinal", "kind"}
    assert structured(response, 4)["results"][0]["members"][0]["kind"].startswith("python.")
    assert structured(response, 5)["target"] == "nodes"
    assert hashlib.sha256(database.read_bytes()).hexdigest() == digest
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_production_cap_scope_admission_over_guarded_stdio(tmp_path: Path) -> None:
    home, database = pushdown_home(tmp_path)
    # Synthetic many-binding vector isolates request-local decode accounting.
    with sqlite3.connect(database) as connection:
        vector = json.loads(connection.execute("SELECT snapshot_vector_json FROM runs WHERE id=2").fetchone()[0])
        vector += [[f"binding-generic-{i:04d}", 1, f"snapshot-generic-{i:04d}"] for i in range(512)]
        connection.execute("UPDATE runs SET snapshot_vector_json=? WHERE id=2", (json.dumps(vector),))
    harness = LocalHarness(tmp_path / "pushdown-harness", block_psycopg=True)
    args = {"graph_id": GRAPH, "query": "needle", "scope": "docs", "source_binding_id": BINDING,
            "source_path_prefix": "docs/zzz", "grouping": "source_document"}
    responses = harness.mcp(home, [initialize(), tool(2, "repomap_navigation_search", args),
                                   tool(3, "repomap_navigation_search", {**args, "source_path_prefix": "docs/missing"}),
                                   tool(4, "repomap_navigation_search", {**args, "source_path_prefix": "docs"})])
    target, empty, overflow = (structured(responses, i) for i in (2, 3, 4))
    assert target["status"] == "ok" and target["scan"]["nodes"] == 2
    assert target["scan"]["admission"]["vector_decodes"] == 1
    assert target["post_admission_scope_excluded_count"] == 0
    assert target["results"][0]["matched_member_count"] == 2
    assert empty["status"] == "ok" and empty["results"] == [] and not empty["has_more"]
    assert overflow["status"] == "incomplete" and overflow["reason"] == "node_scan_limit"
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_navigation_validation_refuses_without_mutating_publication(tmp_path: Path) -> None:
    home, database = navigation_home(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    invalid: list[tuple[dict[str, Any], str]] = [({"query": " "}, "query"), ({"scope": "tests"}, "scope"),
               ({"grouping": "title"}, "grouping"), ({"limit": True}, "limit"),
               ({"member_limit": 0}, "member_limit"), ({"offset": -1}, "offset"),
               ({"source_binding_id": ""}, "source_binding_id"),
               ({"source_path_prefix": "src"}, "requires source_binding_id"),
               ({"source_binding_id": BINDING, "source_path_prefix": "../src"}, "source-relative")]
    args = {"graph_id": GRAPH, "query": "beacon"}
    requests = [initialize(), *(tool(i, "repomap_navigation_search", {**args, **options})
                               for i, (options, _) in enumerate(invalid, 2)),
                tool(20, "repomap_navigation_search", args)]
    responses = harness.mcp(home, requests)
    for i, (_, message) in enumerate(invalid, 2):
        assert message in refusal(responses, i)
    assert structured(responses, 20)["results"]
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


@pytest.mark.parametrize("mutation", ["withheld_path", "unbound_source", "missing_evidence"])
def test_unresolved_navigation_cannot_authorize_source_scope(tmp_path: Path, mutation: str) -> None:
    home, database = navigation_home(tmp_path)
    with sqlite3.connect(database) as connection:
        if mutation == "withheld_path":
            connection.execute("UPDATE canonical_evidence SET path = '/withheld/guide.md'")
        elif mutation == "unbound_source":
            connection.execute("UPDATE canonical_evidence SET metadata_json = '{}'")
        else:
            connection.execute("DELETE FROM canonical_node_evidence")
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    args = {"graph_id": GRAPH, "query": "beacon", "scope": "docs", "grouping": "source_document"}
    requests = [initialize(), tool(2, "repomap_navigation_search", args),
                tool(3, "repomap_navigation_search", {**args, "source_binding_id": BINDING,
                                                     "source_path_prefix": "docs"})]
    responses = harness.mcp(home, requests)
    result, scoped = structured(responses, 2), structured(responses, 3)
    assert result["results"] and result["status"] == "ok"
    reason = "no_direct_evidence" if mutation == "missing_evidence" else "missing_withheld_or_unbound_identity"
    assert all(group["basis"] == "singleton" and group["destination"] is None
               and group["unresolved_reason"] == reason for group in result["results"])
    assert scoped["results"] == [] and scoped["status"] == "ok" and not scoped["has_more"]
    assert "/withheld/guide.md" not in json.dumps(responses)
    assert responses == harness.mcp(home, requests)
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert not (tmp_path / "never-created-source").exists()
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_literal_kind_and_source_filters_preserve_group_identity(tmp_path: Path) -> None:
    home, database = navigation_home(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    args = {"graph_id": GRAPH, "query": "beacon", "scope": "docs", "grouping": "source_document",
            "source_binding_id": BINDING, "source_path_prefix": "docs/naïve_%", "limit": 50}
    requests = [initialize(), tool(2, "repomap_navigation_search", args),
                tool(3, "repomap_navigation_search", {**args, "source_path_prefix": "docs/naïve%"}),
                tool(4, "repomap_navigation_search", {**args, "kind": "doc.section"}),
                tool(5, "repomap_navigation_search", {**args, "graph_id": "unpublished"})]
    responses = harness.mcp(home, requests)
    full, empty, sections, absent = (structured(responses, mid) for mid in range(2, 6))
    assert full["results"] and sections["results"]
    assert all(group["destination"]["source_relative_path"] == "docs/naïve_%/guide.md"
               for result in (full, sections) for group in result["results"])
    assert all(member["kind"] == "doc.section" for group in sections["results"] for member in group["members"])
    assert empty["results"] == [] and not empty["has_more"]
    assert absent["status"] == "unavailable" and absent["reason"] == "publication_absent"
    assert absent["results"] == [] and not absent["has_more"]
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


@pytest.mark.parametrize("direction", ["in", "out", "both"])
def test_neighborhood_windows_preserve_only_disclosed_source_identities(tmp_path: Path, direction: str) -> None:
    home, database = navigation_home(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    # Static extraction defines pages and sections from their source file.
    node = file_key("root/docs/beta.md") if direction == "out" else BETA_DOC
    args = {"graph_id": GRAPH, "node": node, "direction": direction}
    limits = [{"node_limit": 1}, {"edge_limit": 1}, {"node_limit": 1, "edge_limit": 1},
              {"node_limit": 100, "edge_limit": 100}]
    requests = [initialize(), tool(2, "repomap_neighborhood", args),
                *(tool(mid, "repomap_neighborhood", {**args, **options})
                  for mid, options in enumerate(limits, 3)),
                tool(10, "repomap_neighborhood", {**args, "node": "doc.page:absent", "node_limit": 1}),
                tool(11, "repomap_neighborhood", {**args, "node_limit": None})]
    responses = harness.mcp(home, requests)
    full = structured(responses, 2)["result"]
    assert full["center"]["canonical_key"] == node and full["edges"]
    assert "bounds" not in full
    assert any(edge[field] == node for edge in full["edges"] for field in ("source_key", "target_key"))
    for mid, options in enumerate(limits, 3):
        result = structured(responses, mid)["result"]
        assert result["center"] == full["center"]
        visible = {node, *(row["canonical_key"] for row in result["nodes"])}
        assert any(edge[field] in visible for edge in result["edges"] for field in ("source_key", "target_key"))
        for name, option in (("nodes", "node_limit"), ("edges", "edge_limit")):
            limit = options.get(option)
            count = len(full[name]) if limit is None else min(limit, len(full[name]))
            more = count < len(full[name])
            assert len(result[name]) == count
            assert result["bounds"][name] == dict(requested_limit=limit, returned_count=count,
                has_more=more, completeness="truncated" if more else "complete")
        assert result["nodes"] == full["nodes"][:len(result["nodes"])]
        assert result["edges"] == [
            {key: value if key not in {"source_key", "target_key"} or value in visible else "[REDACTED]"
             for key, value in edge.items()} for edge in full["edges"][:len(result["edges"])]]
    absent = structured(responses, 10)["result"]
    assert absent["center"] is None and absent["nodes"] == absent["edges"] == []
    assert all(bound["has_more"] is False and bound["completeness"] == "complete"
               for bound in absent["bounds"].values())
    assert "node_limit" in refusal(responses, 11)
    assert responses == harness.mcp(home, requests)
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert not (tmp_path / "never-created-source").exists()
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""
