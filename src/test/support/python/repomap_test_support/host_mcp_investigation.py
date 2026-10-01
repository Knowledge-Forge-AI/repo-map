"""Seven investigation tools over one host publication, with independent oracles.

Expected values never come from the investigation read store. They come from:

- the CLI-default ``query_refresh_status`` owner (``host_then_container`` mode,
  all configured graphs) plus the maintained status serializer;
- the maintained search SQL owner executed directly as the harness admin;
- ``query_canonical_storage_summary`` and ``query_canonical_neighborhood``
  executed directly as the harness admin;
- in-process ``repomap-kg storage`` CLI commands for canonical edges and
  explanations (advisory B paging and the investigation chain).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
import json
from typing import Any

from repomap_kg.graph.keys import GRAPH_KEY_VERSION
from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.ops.refresh import query_refresh_status
from repomap_kg.server._ops_records import McpOpsGraphContext
from repomap_kg.server._ops_sanitization import readback_path_markers, sanitize_jsonable, summary_root_value
from repomap_kg.server._ops_search import build_mcp_search_sql
from repomap_kg.server.ops import refresh_graph_status_payload
from repomap_kg.storage import (
    canonical_neighborhood_to_jsonable, public_read_page, query_canonical_neighborhood,
    query_canonical_storage_summary,
)
from repomap_kg.storage.readback_driver import execute_json_readback
from repomap_test_support.host_mcp_publication import HostPublication, cli, jsonable

SEARCH_TOOLS = {"nodes": "repomap_search_nodes", "files": "repomap_search_files",
                "observations": "repomap_search_observations"}
VISIBLE_GRAPHS = ("host-one", "host-multi", "host-absent")


@dataclass
class InvestigationPlan:
    requests: dict[int, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    checks: list[tuple[int, Callable[[Any], Any], Any]] = field(default_factory=list)
    chain: dict[str, Any] = field(default_factory=dict)
    paging: dict[str, Any] = field(default_factory=dict)

    def add(self, mid: int, name: str, args: dict[str, Any], project: Callable[[Any], Any], expected: Any) -> None:
        self.requests[mid] = (name, args)
        self.checks.append((mid, project, jsonable(expected)))


def build_plan(pub: HostPublication) -> InvestigationPlan:
    config = load_ops_config_home(pub.home)
    graphs = {graph.id: graph for graph in config.graphs}
    contexts = {gid: McpOpsGraphContext(config=config, graph=graphs[gid], psql_command=None) for gid in pub.databases}
    statuses = query_refresh_status(config)  # CLI default mode, every configured graph
    plan = InvestigationPlan()

    def status(gid: str) -> dict[str, Any]:
        return refresh_graph_status_payload(statuses[gid], graph=graphs[gid])

    def listed(gid: str) -> Any:
        return sanitize_jsonable({key: value for key, value in status(gid).items() if key != "warnings"})

    for mid, gid in zip((301, 302, 303), VISIBLE_GRAPHS):
        plan.add(mid, "repomap_graph_status", {"graph_id": gid}, lambda p: p["storage"], status(gid))
    plan.add(304, "repomap_refresh_status", {"graph_id": "host-multi"}, _without_warnings, [listed("host-multi")])
    plan.add(305, "repomap_refresh_status", {}, _without_warnings, [listed(gid) for gid in VISIBLE_GRAPHS])

    edge = cli(pub.home, "host-one", "edges", "--limit", "200")["items"][0]
    multi_edges = cli(pub.home, "host-multi", "edges", "--limit", "200")["items"]
    key, multi_key = edge["source_key"], multi_edges[0]["source_key"]
    plan.chain = {"key": key, "edge": _edge_identity(edge), "hash": edge["identity_metadata_hash"]}
    searches = (
        (310, "host-one", "nodes", {"query": key}),
        (311, "host-multi", "nodes", {"query": "sh", "limit": 1, "offset": 0}),
        (312, "host-multi", "nodes", {"query": "sh", "limit": 1, "offset": 1}),
        (313, "host-multi", "files", {"query": "lib"}),
        (314, "host-multi", "files", {"query": "%"}),
        (315, "host-multi", "files", {"query": "l%b"}),
        (316, "host-one", "observations", {"query": "shell"}),
        (317, "host-one", "observations", {"query": "shell", "include_raw": True}),
    )
    for mid, gid, target, args in searches:
        expected = _search(pub, contexts[gid], gid, target, **args)
        plan.add(mid, SEARCH_TOOLS[target], {"graph_id": gid, **args}, _search_projection, expected)
    for mid, gid in ((320, "host-one"), (321, "host-multi")):
        plan.add(mid, "repomap_project_summary", {"graph_id": gid}, lambda p: p["summary"],
                 _summary(pub, contexts[gid], gid))
    for mid, gid, node in ((322, "host-one", key), (323, "host-multi", multi_key)):
        plan.add(mid, "repomap_neighborhood", {"graph_id": gid, "node": node}, lambda p: p["result"],
                 _neighborhood(pub, contexts[gid], gid, node))
    plan.add(330, "repomap_canonical_edges", {"project": "host-one", "source_key": key, "limit": 200},
             lambda p: p, cli(pub.home, "host-one", "edges", "--source-key", key, "--limit", "200"))
    plan.add(331, "repomap_explain_canonical_edge", {"project": "host-one", **_explain_tool(edge), "evidence_limit": 1},
             lambda p: p, cli(pub.home, "host-one", "explain-canonical-edge",
                              *_explain_args(edge, "--evidence-limit", "1")))
    _advisory_b(plan, pub, multi_edges)
    return plan


def _advisory_b(plan: InvestigationPlan, pub: HostPublication, edges: list[dict[str, Any]]) -> None:
    gid = "host-multi"
    rich = next((item for item in edges if len(cli(pub.home, gid, "explain-canonical-edge", *_explain_args(
        item, "--evidence-limit", "200"))["result"]["evidence"]) >= 2), None)
    assert rich is not None, "fixture has no canonical edge with two evidence rows"
    plan.paging = {"graph": gid, "edge": _edge_identity(rich)}
    for mid, offset in ((341, 0), (342, 1)):
        plan.add(mid, "repomap_canonical_edges", {"project": gid, "limit": 1, "offset": offset}, lambda p: p,
                 cli(pub.home, gid, "edges", "--limit", "1", "--offset", str(offset)))
    for mid, offset in ((343, 0), (344, 1)):
        plan.add(mid, "repomap_explain_canonical_edge",
                 {"project": gid, **_explain_tool(rich), "evidence_limit": 1, "evidence_offset": offset}, lambda p: p,
                 cli(pub.home, gid, "explain-canonical-edge",
                     *_explain_args(rich, "--evidence-limit", "1", "--evidence-offset", str(offset))))
    database = pub.databases[gid]
    record = query_canonical_neighborhood(
        database.psql_args, root_path=pub.roots[gid], node=rich["source_key"], direction="both", depth=1,
        graph_key_version=GRAPH_KEY_VERSION, node_limit=2, node_offset=0, edge_limit=2, edge_offset=0,
        repository_identity=f"repo1:{gid}", psql_command=database.psql_command)
    nodes, links = public_read_page(record.nodes, limit=1, offset=0), public_read_page(record.edges, limit=1, offset=0)
    plan.add(340, "repomap_canonical_neighborhood",
             {"project": gid, "node": rich["source_key"], "node_limit": 1, "edge_limit": 1, "result_schema_version": 0},
             lambda p: p, canonical_neighborhood_to_jsonable(replace(record, nodes=nodes.items, edges=links.items)))


def verify_plan(plan: InvestigationPlan, structured: Callable[[int], Any]) -> dict[str, Any]:
    for mid, project, expected in plan.checks:
        assert jsonable(project(structured(mid))) == expected, mid
    by_id = {mid: structured(mid) for mid in plan.requests}
    for mid in (301, 320, 321, 322, 323, 310, 311, 312, 313, 316, 317, 330, 331):
        assert _nonempty(mid, by_id[mid]), mid
    assert by_id[303]["storage"]["error"] and not by_id[303]["storage"]["repository_exists"]
    assert by_id[301]["storage"]["latest_run_status"] == "complete" and by_id[301]["storage"]["canonical_nodes"]
    assert [g["graph_id"] for g in by_id[305]["graphs"]] == list(VISIBLE_GRAPHS)
    assert by_id[311]["has_more"] and by_id[311]["results"] != by_id[312]["results"]
    assert (by_id[314]["result_count"], by_id[315]["result_count"]) == (0, 0) and by_id[313]["result_count"] >= 1
    assert all("payload" not in row for row in by_id[316]["results"])
    assert all("payload" in row for row in by_id[317]["results"])
    assert by_id[317]["raw_payload_policy"]["payload_included"] is True
    edge = plan.chain["edge"]
    assert any(row["canonical_key"] == plan.chain["key"] for row in by_id[310]["results"])
    assert edge in [_edge_identity(item) for item in by_id[330]["items"]]
    assert _edge_identity(by_id[331]["result"]["edge"]) == edge
    # The configured neighborhood sanitizer redacts ``*_key`` edge fields (existing
    # behavior), so the chained edge is matched by center, kind, identity hash and target.
    neighborhood = by_id[322]["result"]
    assert neighborhood["center"]["canonical_key"] == edge[0]
    assert (edge[1], plan.chain["hash"]) in [(e["edge_kind"], e["identity_metadata_hash"]) for e in neighborhood["edges"]]
    assert edge[2] in [node["canonical_key"] for node in neighborhood["nodes"]]
    pages = [by_id[mid]["items"] for mid in (341, 342)]
    assert pages[0] and pages[1] and pages[0] != pages[1] and by_id[341]["page"]["truncated"]
    evidence = [by_id[mid]["result"]["evidence"] for mid in (343, 344)]
    assert evidence[0] and evidence[1] and evidence[0] != evidence[1]
    assert by_id[343]["collections"]["evidence"]["truncated"]
    return {
        "checked_messages": len(plan.checks),
        "chain": plan.chain["edge"],
        "paging_edge": plan.paging["edge"],
        "search_counts": {mid: by_id[mid]["result_count"] for mid in range(310, 318)},
        "summary_counts": {mid: by_id[mid]["summary"]["counts"] for mid in (320, 321)},
        "status_graphs": [g["graph_id"] for g in by_id[305]["graphs"]],
        # Parity-checked against the CLI-default owner; recorded, not asserted positive.
        "status_fields": {by_id[mid]["graph"]["graph_id"]: {key: by_id[mid]["storage"].get(key) for key in (
            "repository_name", "repository_exists", "latest_run_status", "canonical_nodes", "publication", "error")}
            for mid in (301, 302, 303)},
    }


def seven_tool_requests(start: int, graph_id: str, node: str) -> dict[int, tuple[str, dict[str, Any]]]:
    calls: tuple[tuple[str, dict[str, Any]], ...] = (
        ("repomap_graph_status", {"graph_id": graph_id}),
        ("repomap_refresh_status", {"graph_id": graph_id}),
        ("repomap_refresh_status", {}),
        ("repomap_search_nodes", {"graph_id": graph_id, "query": "sh"}),
        ("repomap_search_files", {"graph_id": graph_id, "query": "sh"}),
        ("repomap_search_observations", {"graph_id": graph_id, "query": "sh"}),
        ("repomap_project_summary", {"graph_id": graph_id}),
        ("repomap_neighborhood", {"graph_id": graph_id, "node": node}),
    )
    return {start + index: call for index, call in enumerate(calls)}


def _search(pub: HostPublication, context: McpOpsGraphContext, gid: str, target: str, *, query: str,
            limit: int = 20, offset: int = 0, include_raw: bool = False) -> dict[str, Any]:
    database = pub.databases[gid]
    sql = build_mcp_search_sql(root_path=pub.roots[gid], target=target, query=query.strip(), limit=limit,
                               offset=offset, include_raw=include_raw, repository_identity=f"repo1:{gid}")
    rows = execute_json_readback(sql, psql_args=database.psql_args, psql_command=database.psql_command,
                                 label="incumbent search", expected_shape="array")
    assert isinstance(rows, list)
    page = rows[:limit]
    return {"results": sanitize_jsonable(page, private_markers=readback_path_markers(context)),
            "result_count": len(page), "total": offset + len(page), "has_more": len(rows) > limit}


def _summary(pub: HostPublication, context: McpOpsGraphContext, gid: str) -> dict[str, Any]:
    database = pub.databases[gid]
    summary = query_canonical_storage_summary(database.psql_args, root_path=pub.roots[gid],
                                              repository_identity=f"repo1:{gid}", psql_command=database.psql_command)
    return {
        "root_path": summary_root_value(summary.root_path, context.graph),
        "repository_name": summary.repository_name, "latest_run_id": summary.latest_run_id,
        "storage_model": "canonical",
        "counts": {name: getattr(summary, name) for name in (
            "runs", "files", "raw_observations", "canonical_nodes", "canonical_edges", "canonical_evidence")},
    }


def _neighborhood(pub: HostPublication, context: McpOpsGraphContext, gid: str, node: str) -> Any:
    database = pub.databases[gid]
    record = query_canonical_neighborhood(
        database.psql_args, root_path=pub.roots[gid], node=node, direction="both", depth=1,
        graph_key_version=GRAPH_KEY_VERSION, repository_identity=f"repo1:{gid}", psql_command=database.psql_command)
    return sanitize_jsonable(canonical_neighborhood_to_jsonable(record), private_markers=readback_path_markers(context))


def _search_projection(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload[key] for key in ("results", "result_count", "total", "has_more")}


def _without_warnings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [{key: value for key, value in graph.items() if key != "warnings"} for graph in payload["graphs"]]


def _edge_identity(edge: dict[str, Any]) -> tuple[str, str, str]:
    return (edge["source_key"], edge["edge_kind"], edge["target_key"])


def _explain_tool(edge: dict[str, Any]) -> dict[str, Any]:
    return {"source_key": edge["source_key"], "kind": edge["edge_kind"], "target_key": edge["target_key"],
            "identity_metadata": edge["identity_metadata"]}


def _explain_args(edge: dict[str, Any], *extra: str) -> tuple[str, ...]:
    return ("--source-key", edge["source_key"], "--kind", edge["edge_kind"], "--target-key", edge["target_key"],
            "--identity-metadata-json", json.dumps(edge["identity_metadata"]), *extra)


def _nonempty(mid: int, payload: Any) -> bool:
    if 301 <= mid <= 303:
        return bool(payload["storage"]["repository_exists"])
    if mid in (320, 321):
        return payload["summary"]["counts"]["canonical_nodes"] > 0
    if mid in (322, 323):
        return bool(payload["result"]["nodes"])
    if 310 <= mid <= 317:
        return payload["result_count"] > 0
    if mid == 330:
        return bool(payload["items"])
    return bool(payload["result"]["evidence"])
