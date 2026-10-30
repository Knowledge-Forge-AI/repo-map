"""Opt-in windows over real static extraction/publication and the public call."""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

import pytest

from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.server import _ops_summaries, mcp, ops
from common_lore_index.server.mcp_core import RepoMapMcpError
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.jsonable_rows import canonical_neighborhood_to_jsonable
from common_lore_index.storage.sqlite_local import neighborhood_queries
from common_lore_index.storage.sqlite_local.connection import initialize_graph_database
from common_lore_index.storage.sqlite_local.publisher import publish_generation
from common_lore_index.storage.sqlite_local.queries import canonical_neighborhood
from common_lore_index.storage.sqlite_local.schema import LocalStoreError, PUBLICATION_ABSENT
from repomap_test_support.navigation_search_fixtures import navigation_bundle
from repomap_test_support.sqlite_local_fixtures import graph_toml, local_binding, publication_for, write_sqlite_home
from repomap_test_support.host_read_store_config import setup_owned_config

GRAPH = "bounded"
CENTER = "python.module:pkg.center"


def published_home(root: Path) -> tuple[Path, Path]:
    """Source text is parsed statically; the deliberate exception never runs."""
    home = write_sqlite_home(root / "home", graph_toml(GRAPH, root / "unread-source")
        + graph_toml("disabled", root / "unread-source", enabled=False)
        + graph_toml("hidden", root / "unread-source", visible=False))
    sources = {"pkg/center.py": "import pkg.alpha\nimport pkg.beta\nimport pkg.gamma\n"
               "import pkg.delta\nraise RuntimeError('source must never execute')\n",
               "pkg/caller.py": "import pkg.center\n",
               **{f"pkg/{name}.py": "# fixture\n" for name in ("alpha", "beta", "gamma", "delta")}}
    bundle = navigation_bundle(GRAPH, python_sources=sources)
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    config.graph_store_root.mkdir(parents=True)
    database = config.graph_store_root / f"{GRAPH}.sqlite3"
    initialize_graph_database(database, local_binding(GRAPH), applied_at="2026-10-17T00:00:00Z")
    publish_generation(database, publication_for(bundle, GRAPH), bundle.families, expected_generation=0)
    return home, database


@pytest.fixture
def bounded_home(tmp_path, monkeypatch):
    home, database = published_home(tmp_path)
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    monkeypatch.setenv("REPOMAP_MCP_CONFIG", str(tmp_path / "empty-registry.json"))
    return home, database


def public_call(**options):
    reply = mcp.handle_tool_call("repomap_neighborhood", dict(graph_id=GRAPH, node=CENTER, **options))
    assert json.loads(reply["content"][0]["text"]) == reply["structuredContent"]
    return reply


@pytest.mark.parametrize("direction", ["in", "out", "both"])
def test_independent_windows_preserve_direction_order_and_completeness(bounded_home, direction):
    default = public_call(direction=direction)["structuredContent"]["result"]
    nodes, edges = default["nodes"], default["edges"]
    expected_in = {"file:root/pkg/center.py", "python.module:pkg.caller"}
    expected_out = {f"python.module:pkg.{name}" for name in ("alpha", "beta", "delta", "gamma")}
    expected = expected_in if direction == "in" else expected_out if direction == "out" else expected_in | expected_out
    assert {n["canonical_key"] for n in nodes} == expected
    assert len(nodes) > 1 and len(edges) > 1
    assert [n["canonical_key"] for n in nodes] == sorted(n["canonical_key"] for n in nodes)
    for limits in ({"node_limit": 1}, {"edge_limit": 1}, {"node_limit": 1, "edge_limit": 1},
                   {"node_limit": 100, "edge_limit": 100}):
        reply = public_call(direction=direction, **limits)
        assert public_call(direction=direction, **limits) == reply
        result = reply["structuredContent"]["result"]
        for plural, option, original in (("nodes", "node_limit", nodes), ("edges", "edge_limit", edges)):
            count = min(len(original), limits.get(option, len(original)))
            more = count < len(original)
            assert len(result[plural]) == count
            assert result["bounds"][plural] == dict(requested_limit=limits.get(option),
                returned_count=count, has_more=more, completeness="truncated" if more else "complete")
        assert result["nodes"] == nodes[:len(result["nodes"])]
        # Independent edges keep the same records/order; only endpoint disclosure can shrink.
        for original, bounded in zip(edges, result["edges"]):
            assert {k: v for k, v in bounded.items() if k not in {"source_key", "target_key"}} == {
                k: v for k, v in original.items() if k not in {"source_key", "target_key"}}
    assert "bounds" not in default


def test_probe_and_truncated_nodes_never_authorize_endpoints(bounded_home):
    full = public_call(direction="out")["structuredContent"]["result"]
    bounded = public_call(direction="out", node_limit=1, edge_limit=100)["structuredContent"]["result"]
    visible = {CENTER, bounded["nodes"][0]["canonical_key"]}
    assert len(full["nodes"]) > 2
    withheld = 0
    for original, edge in zip(full["edges"], bounded["edges"]):
        for field in ("source_key", "target_key"):
            expected = original[field] if original[field] in visible else "[REDACTED]"
            assert edge[field] == expected
            withheld += expected == "[REDACTED]"
    assert withheld > 0


@pytest.mark.parametrize("option", ["node_limit", "edge_limit"])
@pytest.mark.parametrize("value", [None, True, False, 0, -1, 101, 1.0, 1.5, "2", [], {}])
def test_invalid_limits_refuse_public_and_python_calls_before_store(bounded_home, option, value):
    with patch("common_lore_index.server.sqlite_read_binding.read_transaction", side_effect=AssertionError("opened")):
        with pytest.raises(RepoMapMcpError, match=option + " must be an integer between 1 and 100"):
            public_call(**{option: value})
        with pytest.raises(RepoMapMcpError, match=option + " must be an integer between 1 and 100"):
            mcp.repomap_neighborhood(graph_id=GRAPH, node=CENTER, **{option: value})


@pytest.mark.parametrize("graph,message", [("hidden", "not MCP-visible"), ("disabled", "not enabled"),
                                          ("missing", "unknown graph_id")])
def test_bounded_selection_refusals_precede_store(bounded_home, graph, message):
    with patch("common_lore_index.server.sqlite_read_binding.read_transaction", side_effect=AssertionError("opened")):
        with pytest.raises(RepoMapMcpError, match=message):
            mcp.handle_tool_call("repomap_neighborhood", dict(graph_id=graph, node=CENTER, node_limit=1))


def test_unsupported_postgres_refuses_bounded_but_default_read_stays_exact(tmp_path, monkeypatch):
    home = tmp_path / "pg"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config())
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    config = ops.load_mcp_ops_config()
    graph = config.graphs[0].id
    with patch("common_lore_index.server.investigation_read_store.read_configured_graph",
               side_effect=AssertionError("PG read")) as read:
        with pytest.raises(RepoMapMcpError, match="supported only by SQLite Local"):
            mcp.handle_tool_call("repomap_neighborhood", dict(graph_id=graph, node=CENTER, edge_limit=1))
        read.assert_not_called()
        with pytest.raises(AssertionError, match="PG read"):
            mcp.handle_tool_call("repomap_neighborhood", dict(graph_id=graph, node=CENTER))
        assert read.call_args.kwargs == dict(root_path=config.graphs[0].root_path,
            node=CENTER, direction="both", depth=1, graph_key_version=1)


def test_complete_empty_scope_and_missing_center(bounded_home):
    for node in ("python.module:pkg.absent", "malformed:key", "file:/synthetic/private"):
        reply = mcp.handle_tool_call("repomap_neighborhood", dict(graph_id=GRAPH, node=node,
            node_limit=1, edge_limit=1))
        assert json.loads(reply["content"][0]["text"]) == reply["structuredContent"]
        result = reply["structuredContent"]["result"]
        assert result["center"] is None and result["nodes"] == result["edges"] == []
        assert all(b["has_more"] is False and b["completeness"] == "complete" for b in result["bounds"].values())


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("candidate", ["python.module:unseen", "python.module:a/b", "file:/synthetic/private",
                                      "doc.page:file%3aroot%2fprivate.md"])
def test_bounded_mixed_kinds_and_private_endpoints_stay_sanitized(bounded_home, monkeypatch, private, candidate):
    home, _ = bounded_home
    if private:
        path = home / "repomap.rp.toml"
        path.write_text(path.read_text().replace('privacy = "public-dev"', 'privacy = "private-ops"'))
    raw = dict(center=dict(canonical_key=CENTER, graph_key_version=1),
        nodes=[] if candidate == "python.module:unseen" else [dict(canonical_key=candidate, graph_key_version=1)],
        edges=[dict(source_key=CENTER, target_key=candidate, graph_key_version=1,
                    edge_kind="imports", metadata={"source_key": CENTER})],
        bounds=dict(nodes=dict(requested_limit=1, returned_count=1, has_more=True, completeness="truncated")))
    # Synthetic store mutation isolates sanitation; it is not claimed as an extracted relation.
    monkeypatch.setattr("common_lore_index.server.sqlite_read_binding.configured_neighborhood", lambda *a, **k: copy.deepcopy(raw))
    result = public_call(node_limit=1)["structuredContent"]["result"]
    edge = result["edges"][0]
    assert edge["target_key"] == "[REDACTED]"
    assert edge["source_key"] == ("[REDACTED]" if private else CENTER)
    assert edge["metadata"]["source_key"] == "[REDACTED]"


class CountingCursor:
    def __init__(self, cursor, record):
        self.cursor, self.record = cursor, record

    def fetchone(self):
        row = self.cursor.fetchone()
        self.record["fetched"] += row is not None
        return row

    def fetchall(self):
        rows = self.cursor.fetchall()
        self.record["fetched"] += len(rows)
        return rows

    def __iter__(self):
        for row in self.cursor:
            self.record["fetched"] += 1
            yield row


class CountingConnection(sqlite3.Connection):
    reads: list[dict[str, Any]]

    def __init__(self, database: Path) -> None:
        super().__init__(database)
        self.reads = []

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        record = dict(sql=sql, parameters=parameters, fetched=0)
        self.reads.append(record)
        return CountingCursor(super().execute(sql, parameters), record)


def synthetic_connection(root, size=2000, *, neighbors=None, direction="out"):
    """Synthetic SQL-seam rows over a published product schema, with no extra indexes."""
    database = root / "synthetic.sqlite3"
    bundle = navigation_bundle(GRAPH, python_sources={"pkg/center.py": "# fixture\n"})
    initialize_graph_database(database, local_binding(GRAPH), applied_at="2026-10-17T00:00:00Z")
    publish_generation(database, publication_for(bundle, GRAPH), bundle.families, expected_generation=0)
    connection = CountingConnection(database)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("DELETE FROM canonical_edge_evidence")
    connection.execute("DELETE FROM canonical_edges")
    keys = [f"python.module:neighbor{i:05}" for i in range(size)]
    connection.executemany("INSERT INTO canonical_nodes (canonical_key,graph_key_version,kind,display_name,confidence,conflict,metadata_json,first_seen_run_id,last_seen_run_id) VALUES(?,1,'python.module',?,'extracted',0,'{}',1,1)", [(key, key) for key in keys])
    pairs = [(key, CENTER) if direction == "in" or (direction == "both" and i % 2) else (CENTER, key) for i, key in enumerate(keys[:size if neighbors is None else neighbors])]
    connection.executemany("INSERT INTO canonical_edges (source_canonical_key,edge_kind,target_canonical_key,graph_key_version,identity_metadata_json,identity_metadata_hash,metadata_json,confidence,conflict,first_seen_run_id,last_seen_run_id) VALUES(?,'imports',?,1,'{}','hash','{}','extracted',0,1,1)", pairs)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    return connection


@pytest.mark.parametrize("direction", ["in", "out", "both"])
@pytest.mark.parametrize("neighbors", [2, 2000])
def test_large_neighborhood_bounds_candidates_in_sql_not_presentation(tmp_path, direction, neighbors):
    with synthetic_connection(tmp_path, neighbors=neighbors, direction=direction) as connection:
        counter = connection
        counter.reads.clear()
        result = neighborhood_queries.configured_neighborhood(counter, node=CENTER,
            direction=direction, depth=1, graph_key_version=1, node_limit=3, edge_limit=5)
        assert isinstance(result, dict)
        assert len(result["nodes"]) == min(neighbors, 3) and len(result["edges"]) == min(neighbors, 5)
        for name in ("nodes", "edges"):
            assert result["bounds"][name]["has_more"] is (neighbors == 2000)
            assert result["bounds"][name]["completeness"] == ("truncated" if neighbors == 2000 else "complete")
        node_reads = [r for r in counter.reads if "WITH neighbor_keys" in r["sql"]]
        edge_reads = [r for r in counter.reads if "ORDER BY" in r["sql"] and "WITH neighbor_keys" not in r["sql"]]
        assert len(node_reads) == len(edge_reads) == 1
        assert node_reads[0]["fetched"] == min(neighbors, 4) and edge_reads[0]["fetched"] == min(neighbors, 6)
        assert all("LIMIT" in r["sql"] for r in node_reads + edge_reads)
        plan = connection.execute("EXPLAIN QUERY PLAN " + node_reads[0]["sql"], node_reads[0]["parameters"])
        details = [row[3] for row in plan]
        assert any("canonical_nodes" in row and "canonical_key=?" in row for row in details), details
        assert not any("CORRELATED" in row for row in details), details


def test_bounded_sanitizer_uses_only_returned_nodes(bounded_home, monkeypatch):
    real = _ops_summaries._preserve_visible_endpoints
    observed = []
    def preserve(raw, public, markers):
        observed.append(copy.deepcopy(raw))
        return real(raw, public, markers)
    monkeypatch.setattr(_ops_summaries, "_preserve_visible_endpoints", preserve)
    public_call(node_limit=1, edge_limit=2)
    assert len(observed) == 1 and len(observed[0]["nodes"]) == 1


def _measure_vm(connection: sqlite3.Connection, query_fn: Callable[[], Any], step_granularity: int = 100) -> tuple[Any, int]:
    steps = [0]
    def progress():
        steps[0] += step_granularity
        return 0
    connection.set_progress_handler(progress, step_granularity)
    try:
        return query_fn(), steps[0]
    finally:
        connection.set_progress_handler(None, 0)


@pytest.mark.parametrize("direction", ["in", "out", "both"])
def test_fixed_degree_scaling_and_predecessor_negative_control(tmp_path, direction):
    baselines: dict[int, int] = {}
    for unrelated in (0, 100, 2000, 20000):
        root = tmp_path / f"scale_{direction}_{unrelated}"
        root.mkdir()
        conn = synthetic_connection(root, size=max(unrelated + 3, 200), neighbors=2, direction=direction)
        try:
            pairs = [(f"python.module:neighbor{i+2:05}", f"python.module:neighbor{i+3:05}") for i in range(unrelated)]
            conn.executemany("INSERT INTO canonical_edges (source_canonical_key,edge_kind,target_canonical_key,"
                "graph_key_version,identity_metadata_json,identity_metadata_hash,metadata_json,confidence,"
                "conflict,first_seen_run_id,last_seen_run_id) VALUES(?,'imports',?,1,'{}','hash','{}','extracted',0,1,1)", pairs)
            result, steps = _measure_vm(conn, lambda: neighborhood_queries.configured_neighborhood(
                conn, node=CENTER, direction=direction, depth=1, graph_key_version=1, node_limit=1, edge_limit=1))
            assert isinstance(result, dict)
            assert len(result["nodes"]) == 1 and len(result["edges"]) == 1
            assert all(result["bounds"][k]["has_more"] and result["bounds"][k]["completeness"] == "truncated" for k in ("nodes", "edges"))
            baselines[unrelated] = steps
            if unrelated == 20000 and direction in {"in", "both"}:
                _, scan_steps = _measure_vm(conn, lambda: canonical_neighborhood(
                    conn, node=CENTER, direction=direction, depth=1, graph_key_version=1,
                    node_limit=2, node_offset=0, edge_limit=2, edge_offset=0, incident_selective=False))
                assert scan_steps > steps * 3 + 200, f"predecessor scan steps {scan_steps} <= threshold"
        finally:
            conn.close()
    threshold = baselines[0] * 3 + 200
    for unrelated, steps in baselines.items():
        assert steps <= threshold, f"{direction} {unrelated} steps {steps} > threshold {threshold}"


def _build_dense_connection(root: Path, degree: int, direction: str) -> sqlite3.Connection:
    conn = synthetic_connection(root, size=max(degree, 2), neighbors=0)
    keys = [f"python.module:neighbor{i:05}" for i in range(max(degree, 2))]
    edges = [(CENTER, "imports", CENTER, "self_0")]
    if degree >= 2:
        edges.append((CENTER, "imports", CENTER, "self_1"))
    if degree >= 4:
        edges.extend([(CENTER, "imports", keys[0], "c0"), (keys[1], "imports", CENTER, "c2"),
                      (CENTER, "imports", keys[0], "p0")])
    for i in range(len(edges), degree):
        target = keys[i % len(keys)]
        src, tgt = (target, CENTER) if direction == "in" or (direction == "both" and not i % 2) else (CENTER, target)
        edges.append((src, "imports", tgt, f"h_{i}"))
    conn.executemany("INSERT INTO canonical_edges (source_canonical_key,edge_kind,target_canonical_key,"
        "graph_key_version,identity_metadata_json,identity_metadata_hash,metadata_json,confidence,conflict,"
        "first_seen_run_id,last_seen_run_id) VALUES(?,?,?,1,'{}',?,'{}','extracted',0,1,1)", edges[:degree])
    if degree >= 4:  # complete the cycle without counting its nonincident edge toward degree
        conn.execute("INSERT INTO canonical_edges (source_canonical_key,edge_kind,target_canonical_key,"
            "graph_key_version,identity_metadata_json,identity_metadata_hash,metadata_json,confidence,conflict,"
            "first_seen_run_id,last_seen_run_id) VALUES(?,'imports',?,1,'{}','cycle','{}','extracted',0,1,1)", keys[:2])
    assert conn.execute("SELECT count(*) FROM canonical_edges WHERE source_canonical_key=? OR target_canonical_key=?", (CENTER, CENTER)).fetchone()[0] == degree
    return conn


@pytest.mark.parametrize("degree", [1, 2, 100, 2000])
@pytest.mark.parametrize("direction", ["in", "out", "both"])
def test_dense_local_degree_semantics_and_ordering(tmp_path, degree, direction):
    conn = _build_dense_connection(tmp_path, degree=degree, direction=direction)
    try:
        default = canonical_neighborhood_to_jsonable(canonical_neighborhood(conn, node=CENTER, direction=direction,
            depth=1, graph_key_version=1, node_limit=None, node_offset=0, edge_limit=None, edge_offset=0))
        bounded = neighborhood_queries.configured_neighborhood(conn, node=CENTER, direction=direction,
            depth=1, graph_key_version=1, node_limit=2, edge_limit=3)
        assert isinstance(bounded, dict)
        for name, limit in (("nodes", 2), ("edges", 3)):
            assert bounded[name] == default[name][:limit]
            assert bounded["bounds"][name] == dict(requested_limit=limit, returned_count=min(limit, len(default[name])),
                has_more=len(default[name]) > limit, completeness="truncated" if len(default[name]) > limit else "complete")
        for lim_kw, bound_key, unb_key in [({"node_limit": 1}, "nodes", "edges"), ({"edge_limit": 1}, "edges", "nodes")]:
            part = neighborhood_queries.configured_neighborhood(conn, node=CENTER, direction=direction,
                depth=1, graph_key_version=1, **lim_kw)
            assert isinstance(part, dict)
            assert part[bound_key] == default[bound_key][:1]
            assert part[unb_key] == default[unb_key]
            assert part["bounds"][unb_key]["has_more"] is False and part["bounds"][unb_key]["completeness"] == "complete"
    finally:
        conn.close()


@pytest.mark.parametrize("direction", ["in", "out", "both"])
def test_selective_version_transaction_publication_and_empty_scope(tmp_path, direction):
    conn = synthetic_connection(tmp_path, size=2, neighbors=2, direction=direction)
    try:
        args: dict[str, Any] = dict(direction=direction, depth=1, graph_key_version=1, node_limit=2, edge_limit=2)
        baseline = neighborhood_queries.configured_neighborhood(conn, node=CENTER, **args)
        for table in ("canonical_nodes", "canonical_edges"):
            columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})") if r[1] != "id"]
            selected = ["2" if c == "graph_key_version" else c for c in columns]
            conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) SELECT {', '.join(selected)} FROM {table} WHERE graph_key_version=1")
        changes = conn.total_changes
        assert conn.in_transaction
        assert neighborhood_queries.configured_neighborhood(conn, node=CENTER, **args) == baseline
        assert conn.in_transaction and conn.total_changes == changes
        conn.execute("DELETE FROM canonical_edges")
        for node, expected_center in ((CENTER, CENTER), ("python.module:absent", None)):
            res = neighborhood_queries.configured_neighborhood(conn, node=node, **args)
            assert isinstance(res, dict)
            assert (res["center"] is None if expected_center is None else res["center"]["canonical_key"] == expected_center)
            assert res["nodes"] == [] and res["edges"] == []
            assert all(b["has_more"] is False and b["returned_count"] == 0 for b in res["bounds"].values())
        conn.execute("DELETE FROM accepted_publication")
        with pytest.raises(LocalStoreError, match=PUBLICATION_ABSENT):
            neighborhood_queries.configured_neighborhood(conn, node=CENTER, **args)
    finally:
        conn.close()


@pytest.mark.parametrize("field,args,pattern", [
    ("version", dict(graph_key_version=0), "unsupported graph key version"),
    ("version", dict(graph_key_version=2), "unsupported graph key version"),
    ("direction", dict(direction="invalid"), "direction must be one of both, in, out"),
    ("depth", dict(depth=2), "storage neighborhood only supports depth 1"),
])
def test_configured_neighborhood_validation_refusals(tmp_path, field, args, pattern):
    conn = synthetic_connection(tmp_path, size=2, neighbors=1)
    call_args: dict[str, Any] = {
        "node": CENTER, "direction": "both", "depth": 1, "graph_key_version": 1, "node_limit": 1, "edge_limit": 1, **args}
    try:
        with pytest.raises(StorageSchemaError, match=pattern):
            neighborhood_queries.configured_neighborhood(conn, **call_args)
    finally:
        conn.close()
