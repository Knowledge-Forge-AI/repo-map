"""Twelve READSTORE3 MCP reads over one host publication, with independent oracles.

Expected values never come from the read stores. They come from the maintained
PostgreSQL query owners executed directly as the fixture admin on the same
published records, followed by the maintained serializers (and, for configured
language summaries, the maintained summary sanitizer).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from repomap_kg import __version__
from repomap_kg.graph.keys import GRAPH_KEY_VERSION
from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.server._ops_sanitization import sanitize_summary_jsonable
from repomap_kg.storage import (
    ingested_source_records_to_jsonable, js_framework_summary_to_jsonable, nix_summary_to_jsonable,
    openapi_summary_to_jsonable, python_summary_to_jsonable, query_canonical_storage_summary,
    query_ingested_source_records, query_js_framework_summary, query_nix_summary, query_openapi_summary,
    query_python_summary, query_source_feed_item_explanation, query_source_feed_item_records,
    query_source_reference_records, query_source_run_records, query_source_summary, query_terraform_summary,
    source_feed_item_records_to_jsonable, source_reference_records_to_jsonable, source_run_records_to_jsonable,
    source_summary_to_jsonable, terraform_summary_to_jsonable,
)
from repomap_test_support.host_mcp_domain_publication import FEED_SOURCE_ID, HostDomainPublication
from repomap_test_support.host_mcp_publication import jsonable

SUMMARIES: dict[str, tuple[Callable[..., Any], Callable[[Any], Any]]] = {
    "python": (query_python_summary, python_summary_to_jsonable),
    "terraform": (query_terraform_summary, terraform_summary_to_jsonable),
    "openapi": (query_openapi_summary, openapi_summary_to_jsonable),
    "js_framework": (query_js_framework_summary, js_framework_summary_to_jsonable),
    "nix": (query_nix_summary, nix_summary_to_jsonable),
}
# Count fields that must be positive for each family on the tiny mixed tree.
SUMMARY_POSITIVE = {"python": "python_observations", "terraform": "terraform_files",
                    "openapi": "openapi_documents", "js_framework": "framework_observations", "nix": "nix_files"}


@dataclass
class DomainPlan:
    requests: dict[int, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    expected: dict[int, Any] = field(default_factory=dict)
    projections: dict[int, Callable[[Any], Any]] = field(default_factory=dict)
    chain: dict[str, Any] = field(default_factory=dict)

    def add(self, mid: int, name: str, args: dict[str, Any], expected: Any,
            project: Callable[[Any], Any] = lambda payload: payload) -> None:
        self.requests[mid] = (name, args)
        self.expected[mid] = jsonable(expected)
        self.projections[mid] = project


def build_domain_plan(pub: HostDomainPublication) -> DomainPlan:
    graphs = {graph.id: graph for graph in load_ops_config_home(pub.home).graphs}
    plan = DomainPlan()

    def admin(graph_id: str, owner: Callable[..., Any], **filters: Any) -> Any:
        database = pub.databases[graph_id]
        return owner(database.psql_args, root_path=pub.roots[graph_id], repository_identity=f"repo1:{graph_id}",
                     psql_command=database.psql_command, **filters)

    for offset, (family, (owner, serialize)) in enumerate(SUMMARIES.items()):
        summary = sanitize_summary_jsonable(serialize(admin("host-mixed", owner)), graphs["host-mixed"])
        plan.add(400 + offset, f"repomap_{family}_summary", {"graph_id": "host-mixed"}, summary,
                 lambda payload: payload["summary"])

    feed = {"project": "host-feed"}
    source = {**feed, "source_id": FEED_SOURCE_ID}
    plan.add(410, "repomap_ingested_sources", {**feed, "source_type": "feed.rss"},
             ingested_source_records_to_jsonable(admin("host-feed", query_ingested_source_records,
                                                       source_type="feed.rss", policy_status=None, limit=50)))
    plan.add(411, "repomap_source_summary", source,
             source_summary_to_jsonable(admin("host-feed", query_source_summary, source_id=FEED_SOURCE_ID)))
    runs = admin("host-feed", query_source_run_records, source_id=FEED_SOURCE_ID, limit=25)
    plan.add(412, "repomap_source_runs", source, source_run_records_to_jsonable(runs))
    run_id = runs[0].source_run_id
    items = admin("host-feed", query_source_feed_item_records, source_id=FEED_SOURCE_ID, source_run_id=run_id,
                  limit=50)
    plan.add(413, "repomap_source_feed_items", {**source, "source_run_id": run_id},
             source_feed_item_records_to_jsonable(items))
    plan.add(414, "repomap_source_feed_items", {**source, "limit": 1},
             source_feed_item_records_to_jsonable(admin("host-feed", query_source_feed_item_records,
                                                        source_id=FEED_SOURCE_ID, source_run_id=None, limit=1)))
    references = admin("host-feed", query_source_reference_records, source_id=FEED_SOURCE_ID, source_run_id=None,
                       target_kind="external.url", limit=50)
    plan.add(416, "repomap_source_references", {**source, "target_kind": "external.url"},
             source_reference_records_to_jsonable(references))
    # Chain: a listed feed item that has an external reference -> explanation.
    referenced = {reference.source_item_key for reference in references}
    item_key = next(item.item_key for item in items if item.item_key in referenced)
    plan.add(415, "repomap_explain_source_feed_item", {**feed, "item_key": item_key, "source_id": FEED_SOURCE_ID},
             admin("host-feed", query_source_feed_item_explanation, item_key=item_key, source_id=FEED_SOURCE_ID))
    # Empty-but-valid reads: a mismatched source id and an unknown run id.
    plan.add(417, "repomap_explain_source_feed_item", {**feed, "item_key": item_key, "source_id": "other-feed"},
             admin("host-feed", query_source_feed_item_explanation, item_key=item_key, source_id="other-feed"))
    plan.add(418, "repomap_source_feed_items", {**source, "source_run_id": "no-such-run"},
             source_feed_item_records_to_jsonable(admin("host-feed", query_source_feed_item_records,
                                                        source_id=FEED_SOURCE_ID, source_run_id="no-such-run",
                                                        limit=50)))
    for mid, graph_id in ((420, "host-mixed"), (421, "host-feed")):
        plan.add(mid, "repomap_status", {"project": graph_id}, _status(admin(graph_id, query_canonical_storage_summary),
                                                                      graph_id))
    plan.chain = {"run_id": run_id, "item_key": item_key, "items": len(items)}
    return plan


def verify_domain_plan(plan: DomainPlan, structured: Callable[[int], Any]) -> dict[str, Any]:
    by_id = {mid: structured(mid) for mid in plan.requests}
    for mid, expected in plan.expected.items():
        assert jsonable(plan.projections[mid](by_id[mid])) == expected, mid
    for offset, family in enumerate(SUMMARIES):
        payload = by_id[400 + offset]
        assert payload["summary_kind"] == family and payload["summary"][SUMMARY_POSITIVE[family]] > 0, family
        assert payload["summary"]["root_path"] == "[graph-root]", family
    assert [row["source_id"] for row in by_id[410]] == [FEED_SOURCE_ID]
    assert by_id[411]["feed_items"] >= 1 and by_id[412][0]["source_run_id"] == plan.chain["run_id"]
    assert plan.chain["items"] >= 2 and len(by_id[413]) == plan.chain["items"], "fixture needs >= 2 feed items"
    assert by_id[414] == by_id[413][:1]
    explanation = by_id[415]
    assert explanation["item"]["canonical_key"] == plan.chain["item_key"]
    assert explanation["source"]["source_id"] == FEED_SOURCE_ID
    references = by_id[416]
    assert references and all(ref["target_key"].startswith("external.url:") and ref["not_fetched"]
                              for ref in references)
    assert plan.chain["item_key"] in {ref["source_item_key"] for ref in references}
    assert by_id[417]["item"] is None and by_id[418] == []
    for mid in (420, 421):
        assert by_id[mid]["counts"]["canonical_nodes"] > 0 and by_id[mid]["root_path"] == "[graph-root]", mid
    return {
        "checked_messages": len(plan.expected),
        "summary_counts": {family: by_id[400 + offset]["summary"][SUMMARY_POSITIVE[family]]
                           for offset, family in enumerate(SUMMARIES)},
        "feed_chain": {"run_id": plan.chain["run_id"], "items": plan.chain["items"],
                       "references": len(references)},
        "status_counts": {by_id[mid]["project"]: by_id[mid]["counts"] for mid in (420, 421)},
    }


def twelve_tool_requests(start: int, *, summary_graph: str, feed_project: str,
                         item_key: str) -> dict[int, tuple[str, dict[str, Any]]]:
    source = {"project": feed_project, "source_id": FEED_SOURCE_ID}
    calls: tuple[tuple[str, dict[str, Any]], ...] = (
        *((f"repomap_{family}_summary", {"graph_id": summary_graph}) for family in SUMMARIES),
        ("repomap_ingested_sources", {"project": feed_project}),
        ("repomap_source_summary", source),
        ("repomap_source_runs", source),
        ("repomap_source_feed_items", source),
        ("repomap_explain_source_feed_item", {"project": feed_project, "item_key": item_key}),
        ("repomap_source_references", source),
        ("repomap_status", {"project": feed_project}),
    )
    return {start + index: call for index, call in enumerate(calls)}


def _status(summary: Any, graph_id: str) -> dict[str, Any]:
    return {
        "server": "repomap-kg", "version": __version__, "read_only": True, "root_path": "[graph-root]",
        "repository_name": summary.repository_name, "graph_key_version": GRAPH_KEY_VERSION,
        "storage_model": "canonical", "project": graph_id,
        "counts": {name: getattr(summary, name) for name in (
            "runs", "files", "raw_observations", "canonical_nodes", "canonical_edges", "canonical_evidence")},
    }
