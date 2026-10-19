"""Limits, bounds, windows, and reduction checks for related-source context."""

from __future__ import annotations

import copy
import related_source_context as context_module
from pathlib import Path
from unittest.mock import Mock

import pytest

from repomap_test_support.related_context_fixtures import (
    GRAPH, GUIDE, OTHER, START, CapturedCalls, related_home,
)

ROOT = Path(__file__).resolve().parents[5]
assert Path(context_module.__file__).resolve() == ROOT / "tools/related_source_context.py"
API = vars(context_module)
inspect = API["inspect_related"]
project = API["project_neighborhood"]
expand = API["expand_selected"]


@pytest.fixture
def environment(tmp_path, monkeypatch):
    home, _, workspace = related_home(tmp_path)
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    return workspace, CapturedCalls()


def node(key="neighbor", kind="python.module"):
    return {"canonical_key": key, "kind": kind, "graph_key_version": 1, "conflict": False}


def edge(source="center", target="neighbor", kind="imports", identity=None):
    return dict(source_key=source, target_key=target, edge_kind=kind,
                identity_metadata={} if identity is None else identity, graph_key_version=1)


def response(nodes=None, edges=None):
    """Synthetic public-envelope mutation fixture, never producer evidence."""
    return {"structuredContent": {"read_only": True, "depth": 1,
            "graph": {"graph_id": GRAPH, "repository_name": GRAPH},
            "result": {"center": node("center"),
                       "nodes": [node()] if nodes is None else nodes,
                       "edges": [edge()] if edges is None else edges}}}


def view(reply=None, **options):
    return project(response() if reply is None else reply, graph_id=GRAPH,
                   canonical_key="center", **options)


def test_real_neighbor_outside_display_window_cannot_authorize_locator(environment):
    _, calls = environment
    captured = inspect(graph_id=GRAPH, canonical_key=START, direction="out", node_limit=1, tool_call=calls)
    returned = {row["canonical_key"] for row in calls.calls[0]["response"]["structuredContent"]["result"]["nodes"]}
    assert returned == {GUIDE, OTHER}
    shown = {row["canonical_key"] for row in captured["nodes"]}
    outside, = returned - shown
    assert captured["display_window"]["nodes_truncated"] is True
    assert any(row["target_key"] == outside and row["target_node_status"] == "outside_display_window"
               for row in captured["edges"])
    refused = expand(captured, (outside,), tool_call=calls)
    assert refused["status"] == "invalid_selection" and refused["locations"] == []
    assert refused["source_verification"] == "not_performed"
    assert refused["next_action"]["action"] == "native_navigation_or_review"
    assert refused["graph_calls"] == len(calls.calls) == 1


@pytest.mark.parametrize("options", [dict(direction="sideways"), dict(node_limit=9),
    dict(edge_limit=17), dict(node_limit=True), dict(graph_id=""), dict(canonical_key=""),
    dict(repository_identity=42)])
def test_invalid_explicit_options_spend_no_graph_calls(options):
    call = Mock(side_effect=AssertionError("no call authorized"))
    result = inspect(**(dict(graph_id=GRAPH, canonical_key="center", tool_call=call) | options))
    assert result["graph_calls"] == 0 and result["status"] == "invalid_options"
    call.assert_not_called()


def test_node_edge_windows_and_missing_conflicting_endpoints_are_independent():
    reply = response(nodes=[node(str(i)) for i in range(10)],
                     edges=[edge(target=str(i)) for i in range(18)])
    payload = reply["structuredContent"]
    payload["result"].update(nodes_has_more=True, edges_has_more=False, node_offset=5)
    captured = view(reply)
    assert len(captured["nodes"]) == 8 and len(captured["edges"]) == 16
    assert captured["display_window"]["nodes_truncated"] is True
    assert captured["display_window"]["edges_truncated"] is True
    assert captured["edges"][9]["target_node_status"] == "outside_display_window"
    assert captured["edges"][12]["target_node_status"] == "not_returned"
    assert captured["backend_window"]["result"] == dict(nodes_has_more=True, edges_has_more=False, node_offset=5)
    duplicate = view(response(nodes=[node(), node(kind="doc.page"), {"canonical_key": "unknown"}],
                              edges=[edge(), edge(target="unknown"), edge(target="not-returned")]))
    assert len(duplicate["nodes"]) == 3 and duplicate["eligible_keys"] == []
    assert duplicate["edges"][0]["target_node_status"] == "conflicting_or_unknown"
    assert duplicate["edges"][-1]["target_node_status"] == "not_returned"
    assert view(response(nodes=[], edges=[]))["backend_completeness"] == "unknown"


@pytest.mark.parametrize("history_more", [True, False, None])
def test_current_and_historical_location_windows_retain_independent_flags(environment, history_more):
    _, calls = environment
    captured = inspect(graph_id=GRAPH, canonical_key=START, tool_call=calls)
    def mutate(name, arguments):
        reply = copy.deepcopy(calls(name, arguments))
        lead = reply["structuredContent"]
        lead["historical_locations"] = [dict(lead["locations"][0],
            source_relative_path=path, publication_relation="historical_run")
            for path in ("earlier/guide.md", "older/guide.md")]
        lead["has_more"] = False
        if history_more is None:
            lead.pop("historical_has_more", None)
        else:
            lead["historical_has_more"] = history_more
        return reply
    result = expand(captured, (GUIDE,), tool_call=mutate)
    location = result["locations"][0]
    assert location["lookup"] == "returned" and len(location["historical_locations"]) == 2
    assert location["has_more"] is False and result["graph_calls"] == 2
    assert ("historical_has_more" in location) is (history_more is not None)
    if history_more is not None:
        assert location["historical_has_more"] is history_more


def test_large_capture_requires_local_reduction_without_truncating_identity():
    reply = response()
    reply["structuredContent"]["result"]["nodes"][0]["canonical_key"] = "x" * API["MAX_CAPTURE_BYTES"]
    assert view(reply)["status"] == "unusable_or_reduction_needed"


def test_withheld_nodes_absent_center_and_noncallable_helpers_never_expand():
    captured = view(response(nodes=[node("[REDACTED]"), node("long...[truncated]")]))
    assert captured["eligible_keys"] == []
    missing = response()
    missing["structuredContent"]["result"]["center"] = None
    assert view(missing)["eligible_keys"] == []
    assert inspect(graph_id=GRAPH, canonical_key="center", tool_call=42)["graph_calls"] == 0
    assert expand(view(), ("neighbor",), tool_call=42)["status"] == "invalid_options"
    assert expand(view(), [])["status"] == "invalid_selection"
