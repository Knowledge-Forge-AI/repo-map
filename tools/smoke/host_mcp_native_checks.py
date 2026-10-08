"""Provider-free stdio checks for the host MCP native runner, with independent oracles.

Every expected payload is computed before the first MCP child starts, from the
maintained owners on the same fixture records, never from the MCP read stores:

- canonical: ``query_canonical_node_records``/``query_canonical_neighborhood``
  with the public page serializers, and in-process ``repomap-kg storage``
  edges/explanations in version 1 and legacy version 0;
- investigation: the maintained search SQL owner and storage summary as the
  fixture admin (reusing the incumbent projection helpers), plus
  ``query_refresh_status`` for the MCP-visible graphs in ``host_only`` mode (the
  CLI-default container fallback could reach a container this run does not own);
- status: graph/refresh status of both visible graphs also compared with the
  fixture-admin ``stored_repository_facts`` (selected by configured identity),
  so a parity-only absent result cannot pass;
- source/feed: the ``query_source_*``/``query_ingested_source_records`` owners
  and their serializers as the fixture admin.

``build_plan``/``build_domain_plan`` are not reused: they hard-code the
``host-one``/``host-mixed`` fixtures and the container-fallback refresh mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from typing import Any

from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.ops.refresh import query_refresh_status
from repomap_kg.server._mcp_dispatch import MCP_PROTOCOL_VERSION
from repomap_kg.server._ops_records import McpOpsGraphContext
from repomap_kg.server._ops_sanitization import sanitize_jsonable
from repomap_kg.server.mcp_schemas import tool_definitions
from repomap_kg.server.ops import list_graphs_payload, refresh_graph_status_payload
from repomap_kg.storage import (
    canonical_neighborhood_to_jsonable, canonical_node_records_to_jsonable, ingested_source_records_to_jsonable,
    public_embedded_read_result_to_jsonable, public_read_page, public_read_page_to_jsonable,
    query_canonical_neighborhood, query_canonical_node_records, query_canonical_storage_summary,
    query_ingested_source_records, query_source_feed_item_explanation, query_source_feed_item_records,
    query_source_reference_records, query_source_run_records, query_source_summary,
    source_feed_item_records_to_jsonable, source_reference_records_to_jsonable, source_run_records_to_jsonable,
    source_summary_to_jsonable,
)
from repomap_test_support.host_mcp_domain_reads import _status
from repomap_test_support.host_mcp_investigation import (
    _edge_identity, _explain_args, _explain_tool, _search, _search_projection, _summary, _without_warnings,
)
from repomap_test_support.host_mcp_publication import cli, jsonable
from repomap_test_support.host_mcp_stdio import initialize_request, tool_request, tools_list_request

from .host_mcp_native_fixture import FEED_SOURCE_ID, VISIBLE_GRAPHS, NativeFixture, stored_repository_facts
from .host_mcp_native_launch import Expectation

CATALOG_SHA256 = "c38abd4f5e4da60a3ad3031e4476ff0c0e95552fc7dff149f6a920120a232dde"  # unchanged 27 tools
BAD_ITEM = "python.module:not-a-feed-item"
HIDDEN = "graph 'host-hidden' is not MCP-visible"
RESTART_IDS = (20, 33, 45)  # one canonical, investigation and source/feed read
OUTAGE_READS = {20: "canonical", 30: "investigation", 41: "source"}


@dataclass
class NativePlan:
    calls: dict[int, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    expectations: dict[int, Expectation] = field(default_factory=dict)
    chain: dict[str, Any] = field(default_factory=dict)

    def positive(self, mid: int, name: str, args: dict[str, Any], expected: Any, *, project: Any = None,
                 nonempty: Any = bool) -> None:
        self.calls[mid] = (name, args)
        self.expectations[mid] = Expectation("positive", jsonable(expected), project, nonempty)

    def refusal(self, mid: int, name: str, args: dict[str, Any], text: str) -> None:
        self.calls[mid] = (name, args)
        self.expectations[mid] = Expectation("refusal", text)

    def oracle(self) -> dict[str, Any]:
        return {str(mid): {"tool": self.calls[mid][0] if mid in self.calls else None,
                           "arguments": self.calls[mid][1] if mid in self.calls else None,
                           "kind": expectation.kind, "expected": expectation.expected}
                for mid, expectation in sorted(self.expectations.items())}


def catalog_digest(tools: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(tools, sort_keys=True).encode()).hexdigest()


def build_native_plan(fixture: NativeFixture) -> NativePlan:
    plan = NativePlan()
    plan.expectations[1] = Expectation("protocol", MCP_PROTOCOL_VERSION, lambda result: result["protocolVersion"])
    plan.expectations[2] = Expectation("protocol", _by_name(tool_definitions()), lambda result: _by_name(result["tools"]))
    plan.chain["catalog_sha256"] = catalog_digest(tool_definitions())
    plan.positive(10, "repomap_list_graphs", {}, list_graphs_payload(config_path=str(fixture.home)),
                  nonempty=lambda payload: bool(payload["graphs"]))
    plan.positive(11, "repomap_projects", {}, {"projects": [], "graph_registry_available": True,
                                               "graph_ids": list(VISIBLE_GRAPHS)},
                  project=lambda p: {"projects": p["projects"], "graph_registry_available": p["graph_registry_available"],
                                     "graph_ids": [graph["graph_id"] for graph in p["graphs"]]})
    edge = _canonical(plan, fixture)
    _investigation(plan, fixture, edge["source_key"])
    _source(plan, fixture)
    for mid, name, args, text in (
        (90, "repomap_canonical_nodes", {"project": "no-such-graph"},
         "unknown legacy MCP project or graph-registry graph_id: no-such-graph"),
        (91, "repomap_search_nodes", {"graph_id": "no-such-graph", "query": "sh"}, "unknown graph_id: no-such-graph"),
        (92, "repomap_canonical_nodes", {"project": "host-hidden"}, HIDDEN),
        (93, "repomap_project_summary", {"graph_id": "host-hidden"}, HIDDEN),
        (94, "repomap_ingested_sources", {"project": "host-hidden"}, HIDDEN),
        (95, "repomap_canonical_nodes", {"project": "host-multi", "limit": 201}, "limit must be between 1 and 200"),
        (96, "repomap_search_files", {"graph_id": "host-multi", "query": "   "}, "query is required"),
        (97, "repomap_source_feed_items", {"project": "host-feed", "source_id": FEED_SOURCE_ID, "limit": 0},
         "limit must be between 1 and 500"),
        (98, "repomap_explain_source_feed_item", {"project": "host-feed", "item_key": BAD_ITEM},
         "item_key must use the feed.item namespace"),
    ):
        plan.refusal(mid, name, args, text)
    return plan


def _canonical(plan: NativePlan, fixture: NativeFixture) -> dict[str, Any]:
    gid, home, database = "host-multi", fixture.home, fixture.databases["host-multi"]
    common = {"root_path": fixture.roots[gid], "repository_identity": f"repo1:{gid}",
              "psql_command": database.psql_command}
    records = query_canonical_node_records(database.psql_args, limit=2, offset=0, **common)
    page = public_read_page(records, limit=1, offset=0)
    project = {"project": gid}
    plan.positive(20, "repomap_canonical_nodes", {**project, "limit": 1, "offset": 0},
                  public_read_page_to_jsonable(page, result_kind="canonical_nodes",
                                               serialize_items=canonical_node_records_to_jsonable),
                  nonempty=lambda payload: bool(payload["items"]))
    edges = cli(home, gid, "edges", "--limit", "200")
    edge = edges["items"][0]
    plan.positive(21, "repomap_canonical_edges", {**project, "limit": 200}, edges,
                  nonempty=lambda payload: bool(payload["items"]))
    plan.positive(22, "repomap_canonical_edges", {**project, "limit": 200, "result_schema_version": 0},
                  cli(home, gid, "edges", "--limit", "200", "--legacy-json-array"))
    explain = {**project, **_explain_tool(edge), "evidence_limit": 1}
    plan.positive(23, "repomap_explain_canonical_edge", explain,
                  cli(home, gid, "explain-canonical-edge", *_explain_args(edge, "--evidence-limit", "1")),
                  nonempty=lambda payload: bool(payload["result"]["evidence"]))
    plan.positive(24, "repomap_explain_canonical_edge", {**explain, "result_schema_version": 0},
                  cli(home, gid, "explain-canonical-edge", *_explain_args(edge, "--evidence-limit", "1"),
                      "--legacy-json-object"))
    record = query_canonical_neighborhood(database.psql_args, node=edge["source_key"], direction="both", depth=1,
                                          graph_key_version=1, node_limit=2, node_offset=0, edge_limit=2,
                                          edge_offset=0, **common)
    nodes, links = public_read_page(record.nodes, limit=1, offset=0), public_read_page(record.edges, limit=1, offset=0)
    plan.positive(25, "repomap_canonical_neighborhood",
                  {**project, "node": edge["source_key"], "direction": "both", "node_limit": 1, "edge_limit": 1},
                  public_embedded_read_result_to_jsonable(
                      canonical_neighborhood_to_jsonable(replace(record, nodes=nodes.items, edges=links.items)),
                      result_kind="canonical_neighborhood", collection_pages={"nodes": nodes, "edges": links}),
                  nonempty=lambda payload: bool(payload["result"]["nodes"]))
    plan.chain.update(edge=list(_edge_identity(edge)), key=edge["source_key"])
    return edge


def _investigation(plan: NativePlan, fixture: NativeFixture, key: str) -> None:
    gid, pub = "host-multi", fixture.publication()
    config = load_ops_config_home(fixture.home)
    graphs = {graph.id: graph for graph in config.graphs}
    context = McpOpsGraphContext(config=config, graph=graphs[gid], psql_command=None)
    statuses = query_refresh_status(config, graph_ids=list(VISIBLE_GRAPHS), readback_mode="host_only")

    def listed(graph_id: str) -> Any:
        payload = refresh_graph_status_payload(statuses[graph_id], graph=graphs[graph_id])
        return sanitize_jsonable({name: value for name, value in payload.items() if name != "warnings"})

    def found(payload: Any) -> bool:
        return payload["result_count"] > 0

    plan.positive(30, "repomap_search_nodes", {"graph_id": gid, "query": key},
                  _search(pub, context, gid, "nodes", query=key), project=_search_projection, nonempty=found)
    plan.positive(31, "repomap_search_files", {"graph_id": gid, "query": "lib"},
                  _search(pub, context, gid, "files", query="lib"), project=_search_projection, nonempty=found)
    plan.positive(32, "repomap_project_summary", {"graph_id": gid}, _summary(pub, context, gid),
                  project=lambda payload: payload["summary"],
                  nonempty=lambda payload: payload["summary"]["counts"]["canonical_nodes"] > 0)

    def exists(payload: Any) -> bool:
        return bool(payload["storage"]["repository_exists"])

    def all_exist(payload: Any) -> bool:
        return bool(payload["graphs"]) and all(graph["repository_exists"] for graph in payload["graphs"])

    for mid, status_graph in ((33, "host-feed"), (36, gid)):
        plan.positive(mid, "repomap_graph_status", {"graph_id": status_graph},
                      refresh_graph_status_payload(statuses[status_graph], graph=graphs[status_graph]),
                      project=lambda payload: payload["storage"], nonempty=exists)
    for mid, status_graph in ((34, "host-feed"), (37, gid)):
        plan.positive(mid, "repomap_refresh_status", {"graph_id": status_graph}, [listed(status_graph)],
                      project=_without_warnings, nonempty=all_exist)
    plan.positive(35, "repomap_refresh_status", {}, [listed(graph_id) for graph_id in VISIBLE_GRAPHS],
                  project=_without_warnings, nonempty=all_exist)
    plan.chain["stored_status"] = {graph_id: stored_repository_facts(fixture.databases[graph_id], graph_id)
                                   for graph_id in VISIBLE_GRAPHS}
    plan.chain["configured_repository_names"] = {graph_id: graphs[graph_id].repository_name
                                                 for graph_id in VISIBLE_GRAPHS}


def _source(plan: NativePlan, fixture: NativeFixture) -> None:
    gid, database = "host-feed", fixture.databases["host-feed"]

    def admin(owner: Any, **filters: Any) -> Any:
        return owner(database.psql_args, root_path=fixture.roots[gid], repository_identity=f"repo1:{gid}",
                     psql_command=database.psql_command, **filters)

    feed, source = {"project": gid}, {"project": gid, "source_id": FEED_SOURCE_ID}
    plan.positive(40, "repomap_ingested_sources", {**feed, "source_type": "feed.rss"},
                  ingested_source_records_to_jsonable(admin(query_ingested_source_records, source_type="feed.rss",
                                                            policy_status=None, limit=50)))
    plan.positive(41, "repomap_source_summary", source,
                  source_summary_to_jsonable(admin(query_source_summary, source_id=FEED_SOURCE_ID)),
                  nonempty=lambda payload: payload["feed_items"] >= 1)
    runs = admin(query_source_run_records, source_id=FEED_SOURCE_ID, limit=25)
    plan.positive(42, "repomap_source_runs", source, source_run_records_to_jsonable(runs))
    run_id = runs[0].source_run_id
    items = admin(query_source_feed_item_records, source_id=FEED_SOURCE_ID, source_run_id=run_id, limit=50)
    plan.positive(43, "repomap_source_feed_items", {**source, "source_run_id": run_id},
                  source_feed_item_records_to_jsonable(items))
    references = admin(query_source_reference_records, source_id=FEED_SOURCE_ID, source_run_id=None,
                       target_kind="external.url", limit=50)
    plan.positive(44, "repomap_source_references", {**source, "target_kind": "external.url"},
                  source_reference_records_to_jsonable(references))
    item_key = next(item.item_key for item in items if item.item_key in {ref.source_item_key for ref in references})
    plan.positive(45, "repomap_explain_source_feed_item", {**feed, "item_key": item_key, "source_id": FEED_SOURCE_ID},
                  admin(query_source_feed_item_explanation, item_key=item_key, source_id=FEED_SOURCE_ID),
                  nonempty=lambda payload: bool(payload["item"]))
    plan.positive(46, "repomap_status", feed, _status(admin(query_canonical_storage_summary), gid),
                  nonempty=lambda payload: payload["counts"]["canonical_nodes"] > 0)
    plan.chain.update(run_id=run_id, item_key=item_key)


def requests_for(plan: NativePlan, mids: Any = None) -> list[dict[str, Any]]:
    """``initialize`` then the chosen calls; the full plan also lists tools."""
    chosen = sorted(plan.calls) if mids is None else list(mids)
    head = [initialize_request(1), tools_list_request(2)] if mids is None else [initialize_request(1)]
    return [*head, *(tool_request(mid, *plan.calls[mid]) for mid in chosen)]


def chain_checks(plan: NativePlan, responses: dict[int, dict[str, Any]]) -> dict[str, bool]:
    """Cross-message assertions: same edge/node across families, catalog, source qualification."""
    return {**_family_checks(plan, responses), **status_checks(plan, responses)}


def _family_checks(plan: NativePlan, responses: dict[int, dict[str, Any]]) -> dict[str, bool]:
    def payload(mid: int) -> Any:
        return responses[mid]["result"]["structuredContent"]

    try:
        tools = responses[2]["result"]["tools"]
        edge, key = tuple(plan.chain["edge"]), plan.chain["key"]
        files = json.dumps(payload(31)["results"])
        neighborhood = payload(25)["result"]
        return {
            "catalog_is_27_tools": len(tools) == 27,
            "catalog_sha256_pinned": plan.chain["catalog_sha256"] == CATALOG_SHA256,
            "edges_contain_chained_edge": edge in [_edge_identity(item) for item in payload(21)["items"]],
            "explanation_is_chained_edge": _edge_identity(payload(23)["result"]["edge"]) == edge,
            "neighborhood_centers_chained_node": neighborhood["center"]["canonical_key"] == key,
            "search_finds_chained_node": any(row.get("canonical_key") == key for row in payload(30)["results"]),
            "files_are_source_qualified": "alpha/" in files and "beta/" in files,
            "graph_latest_run_complete": payload(33)["storage"]["latest_run_status"] == "complete",
            "refresh_lists_visible_graphs": [g["graph_id"] for g in payload(35)["graphs"]] == list(VISIBLE_GRAPHS),
            "feed_explanation_is_chained_item": payload(45)["item"]["canonical_key"] == plan.chain["item_key"],
            "references_not_fetched": all(ref["not_fetched"] and ref["target_key"].startswith("external.url:")
                                          for ref in payload(44)),
        }
    except (KeyError, TypeError, IndexError, AttributeError) as error:
        return {f"chain_unreadable:{type(error).__name__}": False}


STATUS_COUNTS = ("raw_observations", "canonical_nodes", "canonical_edges")  # repository totals, also in summary


def status_checks(plan: NativePlan, responses: dict[int, dict[str, Any]]) -> dict[str, bool]:
    """Status reads against the fixture-admin stored facts; each check is False on any missing data.

    Kept apart from ``_family_checks`` so one unreadable message cannot hide
    the individual named status checks.
    """
    stored: dict[str, Any] = plan.chain.get("stored_status") or {}
    names: dict[str, Any] = plan.chain.get("configured_repository_names") or {}

    def member(mid: int, name: str) -> Any:
        content = ((responses.get(mid) or {}).get("result") or {}).get("structuredContent")
        return content.get(name) if isinstance(content, dict) else None

    def matches(entry: Any, graph_id: str) -> bool:
        facts = stored.get(graph_id)
        if not isinstance(entry, dict) or not isinstance(facts, dict) or facts.get("repository_rows") != 1:
            return False
        return (entry.get("graph_id") == graph_id and entry.get("repository_exists") is True
                and entry.get("error") is None and facts.get("latest_run_id") is not None
                and entry.get("latest_run_id") == facts["latest_run_id"]
                and entry.get("latest_run_status") == facts.get("latest_run_status") == "complete"
                and all(isinstance(entry.get(name), int) and entry[name] == facts.get(name) and entry[name] > 0
                        for name in STATUS_COUNTS))

    multi = "host-multi"
    graph_status, summary = member(36, "storage"), member(32, "summary")
    selected, visible = member(37, "graphs"), member(35, "graphs")
    selected, visible = (value if isinstance(value, list) else [] for value in (selected, visible))
    counts = summary.get("counts") if isinstance(summary, dict) else None
    listed_ids = [entry.get("graph_id") if isinstance(entry, dict) else None for entry in visible]
    return {
        "multi_graph_status_matches_stored": matches(graph_status, multi),
        "multi_refresh_status_matches_stored": len(selected) == 1 and matches(selected[0], multi),
        "all_visible_status_matches_stored": (listed_ids == list(VISIBLE_GRAPHS)
                                              and all(map(matches, visible, listed_ids))),
        "multi_status_agrees_with_summary": (
            matches(graph_status, multi) and isinstance(counts, dict)
            and summary.get("latest_run_id") == graph_status["latest_run_id"]
            and all(counts.get(name) == graph_status[name] for name in STATUS_COUNTS)),
        "multi_stored_name_is_configured": (isinstance(stored.get(multi), dict) and names.get(multi) is not None
                                            and stored[multi].get("name") == names[multi]),
    }


def _by_name(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(tools, key=lambda tool: tool["name"])
