"""User-invocable SQLite Local loop: init -> refresh -> stdio MCP (REPOMAP-PRODUCT3-SQLITE-LOCAL1).

Every SQLite child runs through the guarded launcher: no PostgreSQL
environment, recording shims for PostgreSQL/container/service executables,
and denial of any socket connection, forbidden spawn or psycopg connect. A
one-source shell graph and a two-binding Nix graph with overlapping
source-relative file names are indexed through the real portable semantic
path, their source roots are removed, and the 23 database-reading tools read
the accepted generation over real stdio MCP serialization. The one-source graph
is a small polyglot tree (shell, Python, Terraform, OpenAPI, Express/Jest and
a flake) so every summary family and the configured neighborhood return
nonempty results (LOCAL4); it has no feed source, so the six source/feed tools
return the empty source contract (LOCAL5; ``sqlite_local_source_feed_loop``
proves them over real feed publications).

This is containerized integration evidence (Linux sandbox), not a new macOS
host qualification.

LOCAL3 adds three direct CLI proofs through the same guarded children:

* a real publisher write error (a competing writer holds the database) returns
  exactly ``ERROR: graph-database-busy``, keeps the accepted generation and
  settles the attempt failed;
* an unreadable database or a conflicting retained identity refuses with
  ``graph-publication-reconciliation-required`` and preserves the pending
  attempt;
* an implicit-PostgreSQL home with a later SQLite overlay makes ``ops
  sqlite-init`` and ``ops refresh-graph`` exit 1 with ``storage-backend-conflict``
  before any store, attempt, capture, worker or PostgreSQL connection.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import sqlite3
from pathlib import Path
from typing import Any

from repomap_kg.server.mcp_schemas import tool_definitions
from repomap_test_support.cli_in_process import FIXTURE_ROOT
from repomap_test_support.host_read_store_config import setup_owned_config
from repomap_test_support.sqlite_local_fixtures import (
    graph_toml,
    multi_graph_toml,
    write_sqlite_home,
)
from repomap_test_support.sqlite_local_read_corpus import write_polyglot_source
from repomap_test_support.sqlite_local_harness import (
    LocalHarness,
    await_ready,
    initialize,
    refusal,
    remove_database,
    structured,
    tool,
)

ONE, MULTI, HIDDEN, ABSENT = "sqlite-one", "sqlite-multi", "sqlite-hidden", "sqlite-absent"
CONSTELLATION = FIXTURE_ROOT / "multi_source_nix_constellation"
CENTERS = {ONE: "file:root/flake.nix", MULTI: "file:entry/flake.nix"}
SUMMARIES = ("python", "terraform", "openapi", "js_framework", "nix")
SOURCE_ARGUMENTS: dict[str, dict[str, Any]] = {
    "repomap_ingested_sources": {"project": ONE},
    "repomap_source_summary": {"project": ONE, "source_id": "feed"},
    "repomap_source_runs": {"project": ONE, "source_id": "feed"},
    "repomap_source_feed_items": {"project": ONE, "source_id": "feed"},
    "repomap_explain_source_feed_item": {
        "project": ONE,
        "item_key": "feed.item:feed.channel%3Afeed.document%253Afile%25253Arss.xml%3Aself:item-1",
    },
    "repomap_source_references": {"project": ONE, "source_id": "feed"},
}


def _write_sources(sources: Path, *, extra: bool = False) -> None:
    write_polyglot_source(sources / "one")
    for alias in ("entry", "composition"):
        shutil.copytree(CONSTELLATION / alias, sources / alias, dirs_exist_ok=True)
    if extra:
        (sources / "one" / "extra.sh").write_text("extra() {\n  helper\n}\n", encoding="utf-8")


def _home(tmp_path: Path) -> tuple[Path, Path]:
    sources = tmp_path / "sources"
    _write_sources(sources)
    graphs = (
        graph_toml(ONE, sources / "one")
        + multi_graph_toml(MULTI, (("entry", sources / "entry"), ("composition", sources / "composition")))
        + graph_toml(HIDDEN, sources / "one", visible=False)
        + graph_toml(ABSENT, sources / "one")
    )
    return write_sqlite_home(tmp_path / "home", graphs), sources


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dump(path: Path) -> str:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return "\n".join(connection.iterdump())
    finally:
        connection.close()


def _plan(base: int, graph: str, query: str, file_query: str) -> list[dict[str, Any]]:
    return [
        tool(base + 1, "repomap_canonical_nodes", {"project": graph, "limit": 2}),
        tool(base + 2, "repomap_canonical_nodes", {"project": graph, "limit": 2, "offset": 2}),
        tool(base + 3, "repomap_canonical_nodes", {"project": graph, "result_schema_version": 0}),
        tool(base + 4, "repomap_canonical_edges", {"project": graph}),
        tool(base + 5, "repomap_canonical_edges", {"project": graph, "kind": "sources"}),
        tool(base + 6, "repomap_graph_status", {"graph_id": graph}),
        tool(base + 7, "repomap_refresh_status", {"graph_id": graph}),
        tool(base + 8, "repomap_project_summary", {"graph_id": graph}),
        tool(base + 9, "repomap_search_nodes", {"graph_id": graph, "query": query, "limit": 1}),
        tool(base + 10, "repomap_search_files", {"graph_id": graph, "query": file_query}),
        tool(base + 11, "repomap_status", {"project": graph}),
        tool(base + 12, "repomap_search_observations", {"graph_id": graph, "query": "nix", "limit": 1}),
        tool(base + 13, "repomap_search_observations",
             {"graph_id": graph, "query": "nix", "limit": 1, "offset": 1}),
        tool(base + 14, "repomap_neighborhood", {"graph_id": graph, "node": CENTERS[graph]}),
        *(tool(base + 15 + index, f"repomap_{family}_summary", {"graph_id": graph})
          for index, family in enumerate(SUMMARIES)),
        tool(base + 20, "repomap_search_observations",
             {"graph_id": graph, "query": "flake.nix", "kind": "file", "include_raw": True}),
    ]


def _assert_new_reads(responses: dict[int, dict[str, Any]], base: int, graph: str) -> None:
    """The eight LOCAL4 tools return meaningful, not merely well-formed, results."""
    legacy = structured(responses, base + 11)
    assert legacy["project"] == graph and legacy["storage_model"] == "canonical", legacy
    assert legacy["counts"] == structured(responses, base + 8)["summary"]["counts"], legacy
    first, second = structured(responses, base + 12), structured(responses, base + 13)
    assert first["result_count"] == second["result_count"] == 1 and first["has_more"] is True
    assert first["results"][0]["ordinal"] != second["results"][0]["ordinal"] and "payload" not in first["results"][0]
    around = structured(responses, base + 14)["result"]
    assert around["center"]["canonical_key"] == CENTERS[graph] and around["edges"], around
    summaries = {family: structured(responses, base + 15 + index)["summary"]
                 for index, family in enumerate(SUMMARIES)}
    nix = summaries["nix"]
    assert nix["nix_observations"] > 0 and nix["edges"]["import_sources"] > 0, nix
    flakes = structured(responses, base + 20)["results"]
    assert all(row["payload"]["path"] == row["path"] for row in flakes), flakes
    if graph == MULTI:  # overlapping source-relative names stay binding-qualified
        assert sorted(row["path"] for row in flakes) == ["composition/flake.nix", "entry/flake.nix"]
        assert len({row["source_id"] for row in flakes}) == 2 and nix["flake_files"] == 2
        return
    assert summaries["python"]["frameworks"]["flask_apps"] and summaries["python"]["generic_python"]["classes"]
    assert summaries["terraform"]["terraform"]["resources"] >= 1, summaries["terraform"]
    assert summaries["terraform"]["references"]["local_module_refs"] >= 1, summaries["terraform"]
    assert summaries["openapi"]["methods"]["GET"] >= 1, summaries["openapi"]
    assert summaries["openapi"]["openapi"]["operations"] >= 1, summaries["openapi"]
    assert summaries["js_framework"]["express"]["routes"] >= 1, summaries["js_framework"]
    assert summaries["js_framework"]["jest"]["tests"] >= 1, summaries["js_framework"]
    assert nix["programs"]["local"] >= 1 and nix["output_sections"]["total"] >= 1, nix
    assert [row["path"] for row in flakes] == ["root/flake.nix"], flakes


def test_sqlite_local_loop_indexes_and_serves_database_tools_without_postgres(tmp_path: Path) -> None:
    home, sources = _home(tmp_path)
    harness = LocalHarness(tmp_path / "harness")
    store = home / "state" / "sqlite-local" / "graphs"
    for graph in (ONE, MULTI):
        init = harness.cli_json("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", graph)
        assert init["result"] == "initialized", init
    gen1 = {
        graph: harness.cli_json("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", graph)
        for graph in (ONE, MULTI)
    }
    assert {graph: result["accepted_generation"] for graph, result in gen1.items()} == {ONE: 1, MULTI: 1}
    assert gen1[MULTI]["publication"]["source_binding_count"] == 2
    shutil.rmtree(sources)  # source-blind reads: only config and graph databases remain
    databases = {graph: store / f"{graph}.sqlite3" for graph in (ONE, MULTI)}
    before = {graph: (_digest(path), _dump(path)) for graph, path in databases.items()}

    requests = [initialize(1), {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                tool(3, "repomap_refresh_status", {}), tool(4, "repomap_list_graphs", {}),
                tool(5, "repomap_projects", {}),
                tool(6, "repomap_canonical_nodes", {"project": "no-such-graph"}),
                tool(7, "repomap_search_nodes", {"graph_id": HIDDEN, "query": "x"}),
                tool(8, "repomap_canonical_nodes", {"project": ABSENT}),
                tool(9, "repomap_neighborhood", {"graph_id": ONE, "node": CENTERS[ONE], "depth": 2}),
                tool(10, "repomap_python_summary", {"graph_id": HIDDEN}),
                tool(11, "repomap_status", {"project": ONE, "pg_database": "elsewhere"})]
    requests += _plan(100, ONE, "SH", ".sh") + _plan(200, MULTI, "flake", "flake.nix")
    source_ids = {900 + index: name for index, name in enumerate(SOURCE_ARGUMENTS)}
    requests += [tool(mid, name, SOURCE_ARGUMENTS[name]) for mid, name in source_ids.items()]
    first = harness.mcp(home, requests)

    assert first[1]["result"]["protocolVersion"] == "2024-11-05"
    assert first[2]["result"]["tools"] == tool_definitions() and len(first[2]["result"]["tools"]) == 27
    statuses = {row["graph_id"]: row for row in structured(first, 3)["graphs"]}
    assert set(statuses) == {ONE, MULTI, ABSENT}, statuses.keys()
    assert statuses[ABSENT]["error"] == "graph-database-not-initialized"
    assert statuses[ABSENT]["repository_exists"] is False
    assert {row["database_source"] for row in structured(first, 4)["graphs"]} == {"sqlite-graph-file"}
    projects = structured(first, 5)
    assert projects["graph_registry_available"] is True and projects["graph_count"] == 3, projects
    assert refusal(first, 6) == "unknown legacy MCP project or graph-registry graph_id: no-such-graph"
    assert refusal(first, 7) == f"graph '{HIDDEN}' is not MCP-visible"
    assert refusal(first, 8) == "graph-database-not-initialized"
    assert refusal(first, 9) == "neighborhood depth is capped at 1 in MCP-OPS4"
    assert refusal(first, 10) == f"graph '{HIDDEN}' is not MCP-visible"
    assert refusal(first, 11) == (
        "graph-registry project routing cannot be combined with explicit connection overrides")
    empty = {name: structured(first, mid) for mid, name in source_ids.items()}
    assert empty["repomap_source_summary"]["known_limitations"] == ["source metadata unavailable"], empty
    assert empty["repomap_explain_source_feed_item"]["item"] is None, empty
    assert [empty[name] for name in SOURCE_ARGUMENTS if name.endswith(("sources", "runs", "items", "references"))
            ] == [[], [], [], []], empty

    for base, graph in ((100, ONE), (200, MULTI)):
        page1, page2 = structured(first, base + 1), structured(first, base + 2)
        assert page1["page"]["truncated"] is True and page1["items"] and page2["items"], (page1, page2)
        keys1 = [item["canonical_key"] for item in page1["items"]]
        assert not set(keys1) & {item["canonical_key"] for item in page2["items"]}
        assert isinstance(structured(first, base + 3), list) and structured(first, base + 3)
        edges = structured(first, base + 4)["items"]
        sources_edges = structured(first, base + 5)["items"]
        assert edges and sources_edges and {edge["edge_kind"] for edge in sources_edges} == {"sources"}, graph
        status = structured(first, base + 6)["storage"]
        publication = gen1[graph]["publication"]
        assert status["publication"] == publication, (status["publication"], publication)
        assert status["latest_run_id"] == 1 and status["latest_run_status"] == "complete", status
        assert structured(first, base + 7)["graphs"][0]["repository_exists"] is True, graph
        counts = structured(first, base + 8)["summary"]["counts"]
        assert counts["runs"] == 1 and counts["files"] == gen1[graph]["family_counts"]["files"], counts
        search = structured(first, base + 9)
        assert search["results"] and search["has_more"] is True, search
        assert structured(first, base + 10)["results"]
        _assert_new_reads(first, base, graph)
    multi_files = [row["path"] for row in structured(first, 210)["results"]]
    assert multi_files == ["composition/flake.nix", "entry/flake.nix"], multi_files

    edge = structured(first, 104)["items"][0]
    second = harness.mcp(home, [
        initialize(1),
        tool(2, "repomap_explain_canonical_edge", {
            "project": ONE, "source_key": edge["source_key"], "kind": edge["edge_kind"],
            "target_key": edge["target_key"], "identity_metadata": edge["identity_metadata"],
            "evidence_limit": 1,
        }),
        tool(3, "repomap_canonical_neighborhood", {"project": ONE, "node": edge["source_key"]}),
        *_plan(100, ONE, "SH", ".sh"),
    ])
    explained = structured(second, 2)
    assert explained["result"]["edge"]["source_key"] == edge["source_key"]
    assert explained["result"]["evidence"] and explained["collections"]["evidence"]["limit"] == 1, explained
    assert structured(second, 3)["result"]["center"]["canonical_key"] == edge["source_key"]
    for mid in range(101, 121):  # restart after EOF: identical reads of the same generation
        assert structured(second, mid) == structured(first, mid), mid

    after = {graph: (_digest(path), _dump(path)) for graph, path in databases.items()}
    assert after == before, "reads changed a main file or a logical row"

    _write_sources(sources, extra=True)
    gen2 = harness.cli_json("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", ONE)
    assert (gen2["accepted_generation"], gen2["previous_run_id"]) == (2, 1), gen2
    third = harness.mcp(home, [initialize(1), tool(2, "repomap_graph_status", {"graph_id": ONE}),
                               tool(3, "repomap_search_files", {"graph_id": ONE, "query": "extra"}),
                               tool(4, "repomap_project_summary", {"graph_id": MULTI})])
    assert structured(third, 2)["storage"]["latest_run_id"] == 2, structured(third, 2)
    extra_paths = [row["path"] for row in structured(third, 3)["results"]]
    assert extra_paths == ["root/extra.sh"], extra_paths
    assert structured(third, 4) == structured(first, 208), "an independent graph is untouched"

    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert harness.shim_invocations() == ""
    for path in databases.values():
        remove_database(path)
    assert not any(store.iterdir())


def _records(home: Path, graph: str) -> dict[str, Path]:
    parent = home / "state" / "portable-publication" / "sqlite-local" / graph / "attempts"
    return {record.parent.name: record for record in sorted(parent.glob("*/portable-result.json"))}


def _retention(record: Path) -> str:
    return str(json.loads(record.read_text(encoding="utf-8"))["retention_class"])


def _one_home(tmp_path: Path) -> tuple[Path, LocalHarness, Path]:
    home, _ = _home(tmp_path)
    harness = LocalHarness(tmp_path / "harness")
    harness.cli_json("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", ONE)
    assert harness.cli_json("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", ONE)[
        "accepted_generation"] == 1
    return home, harness, home / "state" / "sqlite-local" / "graphs" / f"{ONE}.sqlite3"


def _bounded(stderr: str, tmp_path: Path) -> None:
    assert "Traceback" not in stderr and str(tmp_path) not in stderr and "SELECT" not in stderr, stderr


def test_publisher_write_error_is_bounded_and_keeps_the_accepted_generation(tmp_path: Path) -> None:
    home, harness, path = _one_home(tmp_path)
    before, earlier = _dump(path), set(_records(home, ONE))
    holder = sqlite3.connect(path, autocommit=True)
    try:
        holder.execute("BEGIN IMMEDIATE")  # a real competing writer: the publisher's BEGIN IMMEDIATE is busy
        blocked = harness.run("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", ONE, "--json")
    finally:
        holder.close()
    assert blocked.returncode == 1 and blocked.stdout == "", (blocked.returncode, blocked.stdout)
    assert blocked.stderr.strip().splitlines()[-1] == "ERROR: graph-database-busy", blocked.stderr
    _bounded(blocked.stderr, tmp_path)
    assert _dump(path) == before
    failed = {name: _retention(record) for name, record in _records(home, ONE).items() if name not in earlier}
    assert list(failed.values()) == ["terminal-failed"], failed
    after = harness.cli_json("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", ONE)
    assert (after["accepted_generation"], after["previous_run_id"]) == (2, 1), after
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""
    remove_database(path)


def _replace_owner_only(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".test-tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, data)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def test_unreadable_or_conflicting_state_refuses_and_preserves_the_pending_attempt(tmp_path: Path) -> None:
    home, harness, path = _one_home(tmp_path)
    barrier = tmp_path / "after-commit-barrier"
    writer = harness.start(
        "ops", "refresh-graph", "--repo-map-home", str(home), "--graph", ONE,
        extra_env=harness.paused_env("after_commit", barrier),
    )
    try:
        await_ready(barrier, writer)
        os.kill(writer.pid, signal.SIGKILL)
    finally:
        writer.communicate()
    pending = [record for record in _records(home, ONE).values() if _retention(record) == "publication-reconciliation"]
    assert len(pending) == 1, pending
    record, names = pending[0], set(_records(home, ONE))
    pristine = record.read_bytes()

    def refused(reason: str) -> None:
        expected = record.read_bytes()
        completed = harness.run("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", ONE)
        assert completed.returncode == 1, completed.stdout
        assert completed.stderr.strip().splitlines()[-1] == (
            f"ERROR: graph-publication-reconciliation-required: {reason}"), completed.stderr
        _bounded(completed.stderr, tmp_path)
        assert record.read_bytes() == expected and set(_records(home, ONE)) == names

    owned = [path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")]
    for item in owned:
        if item.exists():
            item.rename(item.with_name(item.name + ".away"))
    path.write_bytes(b"not a database, just public-safe bytes" * 200)
    refused("graph-database-unrecognized")
    path.unlink()
    for item in owned:
        if item.with_name(item.name + ".away").exists():
            item.with_name(item.name + ".away").rename(item)

    tampered = json.loads(pristine)
    tampered["sqlite_local_publication"]["publication_bundle_id"] = "bundle1:" + "0" * 64
    _replace_owner_only(record, json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode())
    refused("publication-identity-conflict")
    status = harness.mcp(home, [initialize(1), tool(2, "repomap_graph_status", {"graph_id": ONE})])
    assert structured(status, 2)["storage"]["latest_run_id"] == 2  # the committed generation is intact

    _replace_owner_only(record, pristine)  # the operator restores the true record
    replay = harness.cli_json("ops", "refresh-graph", "--repo-map-home", str(home), "--graph", ONE)
    assert (replay["accepted_generation"], replay["previous_run_id"]) == (2, 1), replay
    assert _retention(record) == "terminal-accepted" and set(_records(home, ONE)) == names
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""
    remove_database(path)


def test_implicit_postgres_home_with_sqlite_overlay_refuses_both_commands_directly(tmp_path: Path) -> None:
    home = tmp_path / "pg-home"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    (home / "zz-local.rpl.toml").write_text('schema_version = 1\n[storage]\nbackend = "sqlite"\n', encoding="utf-8")
    harness = LocalHarness(tmp_path / "harness")
    for command in ("sqlite-init", "refresh-graph"):
        completed = harness.run("ops", command, "--repo-map-home", str(home), "--graph", "host-one")
        assert completed.returncode == 1 and completed.stdout == "", (command, completed.returncode, completed.stdout)
        assert "storage-backend-conflict: " in completed.stderr, (command, completed.stderr)
        assert "conflicts with the postgresql backend of repomap.rpl.toml" in completed.stderr, completed.stderr
        _bounded(completed.stderr, tmp_path)
    assert sorted(item.name for item in home.iterdir()) == ["repomap.rpl.toml", "zz-local.rpl.toml"]
    assert harness.forbidden_events() == [], harness.forbidden_events()
    assert harness.shim_invocations() == ""
