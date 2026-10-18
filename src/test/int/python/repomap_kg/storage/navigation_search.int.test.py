"""Container-guarded stdio ownership for optional scoped navigation search."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from repomap_test_support.navigation_search_fixtures import BINDING, GRAPH, navigation_home
from repomap_test_support.sqlite_local_harness import LocalHarness, initialize, structured, tool
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
