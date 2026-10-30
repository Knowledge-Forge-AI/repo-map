"""Optional related-source composition; real routes plus disclosed mutation cases."""

from __future__ import annotations

import copy
import json
import related_source_context as context_module
import source_navigation_consumer as consumer_module
import sys
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from common_lore_index.server import mcp
from repomap_test_support.navigation_search_fixtures import navigation_bundle
from repomap_test_support.related_context_fixtures import (
    BINDING, EXPECTED_IMPORTS, EXPECTED_LINKS, GRAPH, GUIDE, IMPORTED, MODULE,
    OTHER, REPOSITORY, SOURCES, START, CapturedCalls, related_home,
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


def test_real_extractors_independent_oracle_and_routed_selected_source(environment):
    workspace, calls = environment
    bundle = navigation_bundle(GRAPH,
        markdown_sources={p: s for p, s in SOURCES.items() if p.endswith(".md")},
        python_sources={p: s for p, s in SOURCES.items() if p.endswith(".py")})
    actual = {(row["source_canonical_key"], row["edge_kind"], row["target_canonical_key"])
              for row in bundle.families["canonical_edges"] if row["edge_kind"] in {"imports", "links_to"}}
    assert actual == EXPECTED_IMPORTS | EXPECTED_LINKS
    assert SOURCES["pkg/alpha.py"].startswith("import pkg.beta\nraise RuntimeError")
    captured = inspect(graph_id=GRAPH, canonical_key=START, direction="out", tool_call=calls)
    assert captured["graph_calls"] == 1 and captured["locations"] == []
    assert {row["canonical_key"] for row in captured["nodes"]} == {GUIDE, OTHER}
    # Producer discloses only endpoints already visible in this same public view.
    assert {(row["source_key"], row["edge_kind"], row["target_key"])
            for row in captured["edges"]} == EXPECTED_LINKS
    assert all(row["direction"] == "out" for row in captured["edges"])
    assert captured["backend_completeness"] == "unknown"
    expanded = expand(captured, (GUIDE,), tool_call=calls)
    assert [event["tool"] for event in calls.calls] == ["repomap_neighborhood", "repomap_node_locations"]
    assert expanded["graph_calls"] == 2 and expanded["locations"][0]["lookup"] == "returned"
    lead = calls.calls[-1]["response"]["structuredContent"]
    # Separate accepted reader operation over an explicit binding mapping.
    old = vars(consumer_module)
    direct = old["_direct_location"](lead, GRAPH, GUIDE, REPOSITORY)
    assert direct is not None and direct["binding_id"] == BINDING
    trace: list[dict[str, Any]] = []
    assert old["_verify_source"](direct, {BINDING: workspace}, REPOSITORY,
                                  lambda text: text == SOURCES["docs/guide.md"], trace)
    assert trace[0]["action"] == "source_read" and trace[0]["verified"] is True
    assert expanded["source_verification"] == "not_performed"


@pytest.mark.parametrize("center,direction,expected", [
    (MODULE, "out", {IMPORTED}), (IMPORTED, "in", {MODULE}),
    (MODULE, "in", set()), (MODULE, "both", {IMPORTED}),
])
def test_real_direction_filters_remain_exact(environment, center, direction, expected):
    _, calls = environment
    captured = inspect(graph_id=GRAPH, canonical_key=center, direction=direction, tool_call=calls)
    assert {row["canonical_key"] for row in captured["nodes"] if row["kind"] == "python.module"} == expected
    assert sum(row["edge_kind"] == "imports" for row in captured["edges"]) == bool(expected)
    assert calls.calls[0]["arguments"] == dict(graph_id=GRAPH, node=center, direction=direction, depth=1)
    assert captured["absence_scope"] == "only returned relations in this selected read and direction"


def test_two_selected_successes_and_no_second_expansion_or_retry(environment):
    _, calls = environment
    captured = inspect(graph_id=GRAPH, canonical_key=START, tool_call=calls)
    public = calls.calls[0]["response"]["structuredContent"]
    assert {(row["source_key"], row["edge_kind"], row["target_key"])
            for row in public["result"]["edges"] if row["edge_kind"] == "links_to"} == EXPECTED_LINKS
    assert {(row["source_key"], row["edge_kind"], row["target_key"], row["direction"])
            for row in captured["edges"] if row["edge_kind"] == "links_to"} == {(*r, "out") for r in EXPECTED_LINKS}
    assert expand(captured)["graph_calls"] == 1
    result = expand(captured, (OTHER, GUIDE), tool_call=calls)
    assert result["graph_calls"] == 3
    assert [row["canonical_key"] for row in result["locations"]] == [OTHER, GUIDE]
    assert all(row["lookup"] == "returned" for row in result["locations"])
    assert result["edges"] == captured["edges"]
    assert [event["arguments"] for event in calls.calls[1:]] == [
        dict(graph_id=GRAPH, canonical_key=key, evidence_role="direct", detail="compact", limit=2)
        for key in (OTHER, GUIDE)]
    for event in calls.calls:
        assert json.loads(event["response"]["content"][0]["text"]) == event["response"]["structuredContent"]
    assert expand(result, (GUIDE,), tool_call=calls)["status"] == "invalid_selection"
    assert len(calls.calls) == 3


def test_real_python_composition_and_separate_known_location_source_read(environment):
    workspace, calls = environment
    captured = inspect(graph_id=GRAPH, canonical_key=MODULE, direction="out", tool_call=calls)
    public = calls.calls[0]["response"]["structuredContent"]
    assert public["graph"]["privacy"] == "public-dev"
    assert public["result"]["center"]["canonical_key"] == MODULE
    assert IMPORTED in {row["canonical_key"] for row in public["result"]["nodes"]}
    assert {(row["source_key"], row["edge_kind"], row["target_key"])
            for row in public["result"]["edges"] if row["edge_kind"] == "imports"} == EXPECTED_IMPORTS
    assert {(row["source_key"], row["edge_kind"], row["target_key"], row["direction"])
            for row in captured["edges"] if row["edge_kind"] == "imports"} == {(*r, "out") for r in EXPECTED_IMPORTS}
    result = expand(captured, (IMPORTED,), tool_call=calls)
    assert result["edges"] == captured["edges"] and result["graph_calls"] == 2
    assert calls.calls[-1]["arguments"] == dict(
        graph_id=GRAPH, canonical_key=IMPORTED, evidence_role="direct", detail="compact", limit=2)
    for event in calls.calls:
        assert json.loads(event["response"]["content"][0]["text"]) == event["response"]["structuredContent"]
    consumer = vars(consumer_module)
    lead = calls.calls[-1]["response"]["structuredContent"]
    handoff = consumer["_direct_location"](lead, GRAPH, IMPORTED, REPOSITORY)
    assert handoff is not None and handoff["binding_id"] == BINDING
    assert handoff["source_relative_path"] == "pkg/beta.py"
    native = consumer["navigate"](
        graph_id=GRAPH, repository_identity=REPOSITORY, bindings={BINDING: workspace},
        handoff=handoff, source_check=lambda text: text == SOURCES["pkg/beta.py"], tool_call=calls)
    assert native["outcome"] == "verified" and native["graph_calls"] == 0
    assert native["trace"] == [dict(action="source_read", source_relative_path="pkg/beta.py",
                                     start_line=handoff["start_line"], end_line=handoff["end_line"], verified=True)]
    assert len(calls.calls) == 2
    assert captured["backend_completeness"] == "unknown"
    assert result["snapshot_relation"] == "not_guaranteed"
    assert result["source_verification"] == "not_performed"
    assert result["locations"][0]["freshness"] == "unverified"


def test_partial_failure_preserves_independent_result_and_relationships(environment):
    _, calls = environment
    captured = inspect(graph_id=GRAPH, canonical_key=START, tool_call=calls)
    def partial(name, arguments):
        if arguments["canonical_key"] == GUIDE:
            raise RuntimeError("private failure detail")
        return calls(name, arguments)
    result = expand(captured, (GUIDE, OTHER), tool_call=partial)
    assert result["graph_calls"] == 3 and result["edges"] == captured["edges"]
    assert result["locations"][0]["lookup"].startswith("failed")
    assert result["locations"][0]["next_action"]["action"] == "native_navigation_or_review"
    assert result["locations"][1]["lookup"] == "returned"
    assert "private failure" not in API["export"](result)


@pytest.mark.parametrize("keys", [("unknown",), ("neighbor", "neighbor"),
    ("neighbor", "other", "third"), ["neighbor"], ("center",), ("[REDACTED]",)])
def test_bad_selection_is_atomic_and_never_guesses(keys):
    call = Mock()
    result = expand(view(), keys, tool_call=call)
    assert result["status"] == "invalid_selection" and result["graph_calls"] == 0
    call.assert_not_called()


def test_pure_projection_export_and_helper_absence_have_no_io():
    reply = response()
    reply["structuredContent"]["result"]["nodes"][0]["display_name"] = '$(touch NEVER); `echo inert`'
    original = copy.deepcopy(reply)
    with patch("builtins.open", side_effect=AssertionError("file I/O")), \
         patch("pathlib.Path.open", side_effect=AssertionError("file I/O")), \
         patch("subprocess.Popen", side_effect=AssertionError("process I/O")), \
         patch("socket.socket", side_effect=AssertionError("network I/O")):
        captured = view(reply)
        assert json.loads(API["export"](expand(captured))) == captured
        assert expand(captured, ("neighbor",))["status"] == "helper_absent"
        assert inspect(graph_id=GRAPH, canonical_key="center")["graph_calls"] == 0
    assert reply == original and "$(touch NEVER)" in API["export"](captured)
    # Also check the standalone import with no already imported runtime to mask it.
    with patch.dict(sys.modules, {name: None for name in sys.modules if name.startswith("common_lore_index")}):
        with pytest.MonkeyPatch.context() as isolated:
            isolated.delitem(sys.modules, "related_source_context", raising=False)
            import related_source_context as standalone
            assert standalone.MAX_VIEW_BYTES == 65_536


def test_self_loop_multiple_edges_and_identity_metadata_are_not_collapsed():
    rows = [edge(), edge(kind="links_to"), edge(target="center"),
            edge(identity={"variant": "second"}), edge(source="neighbor", target="center")]
    captured = view(response(edges=rows))
    assert [e["direction"] for e in captured["edges"]] == ["out", "out", "self", "out", "in"]
    assert captured["edges"][3]["identity_metadata"] == {"variant": "second"}
    assert all(e["explanation"]["status"] == "unavailable" for e in captured["edges"])
    assert len(captured["edges"]) == len(rows)
    filtered = view(response(edges=rows), direction="out")
    assert filtered["edges"][-1]["in_requested_direction"] is False
    assert filtered["eligible_keys"] == []


@pytest.mark.parametrize("graph", ["hidden", "disabled", "missing"])
def test_real_unavailable_graphs_do_not_fall_back(environment, graph):
    _, calls = environment
    result = inspect(graph_id=graph, canonical_key=START, tool_call=calls)
    assert result["status"] == "neighborhood_failed" and len(calls.calls) == 1
    assert result["next_action"]["action"] == "native_navigation_or_review"


@pytest.mark.parametrize("mutation", ["wrong_graph", "unbound_graph", "wrong_center", "wrong_repo", "node_repo"])
def test_neighborhood_identity_never_licenses_hidden_expansion(mutation):
    reply = response()
    payload = reply["structuredContent"]
    if mutation == "wrong_graph":
        payload["graph"]["graph_id"] = "hidden"
    elif mutation == "unbound_graph":
        del payload["graph"]["graph_id"]
    elif mutation == "wrong_center":
        payload["result"]["center"]["canonical_key"] = "other"
    elif mutation == "wrong_repo":
        payload["repository_identity"] = "repo1:other"
    else:
        payload["result"]["nodes"][0]["repository_identity"] = "repo1:other"
    captured = view(reply, repository_identity=REPOSITORY)
    assert captured.get("eligible_keys", []) == []
    callback = Mock()
    assert expand(captured, ("neighbor",), tool_call=callback)["status"] == "invalid_selection"
    callback.assert_not_called()


@pytest.mark.parametrize("mutation", ["wrong_graph", "wrong_repository", "wrong_key", "missing_graph", "wrong_version"])
def test_locator_identity_mismatch_is_local(environment, mutation):
    _, calls = environment
    captured = inspect(graph_id=GRAPH, canonical_key=START, repository_identity=REPOSITORY, tool_call=calls)
    def mutate(name, arguments):
        reply = copy.deepcopy(calls(name, arguments))
        lead = reply["structuredContent"]
        if mutation == "wrong_graph":
            lead["graph"]["graph_id"] = "hidden"
        elif mutation == "missing_graph":
            del lead["graph"]["graph_id"]
        elif mutation == "wrong_repository":
            lead["repository_identity"] = "repo1:other"
        elif mutation == "wrong_version":
            lead["graph_key_version"] = 2
        else:
            lead["canonical_key"] = OTHER
        return reply
    result = expand(captured, (GUIDE,), tool_call=mutate)
    assert result["edges"] == captured["edges"] and result["locations"][0]["lookup"].startswith("failed")


@pytest.mark.parametrize("condition", ["historical", "ambiguous", "missing", "withheld", "truncated"])
def test_uncertain_location_labels_and_contradictions_survive(environment, condition):
    _, calls = environment
    captured = inspect(graph_id=GRAPH, canonical_key=START, tool_call=calls)
    def mutate(name, arguments):
        reply = copy.deepcopy(calls(name, arguments))
        lead = reply["structuredContent"]
        if condition == "historical":
            lead["historical_locations"] = lead["locations"]
            lead["locations"] = []
            lead.update(status="unavailable", location_scope="historical_run")
            lead["historical_locations"][0]["publication_relation"] = "historical_run"
        elif condition == "ambiguous":
            lead["locations"].append(dict(lead["locations"][0], source_relative_path="other/guide.md"))
            lead["ambiguity"] = "multiple_stored_locations"
        elif condition == "missing":
            lead.update(locations=[], status="unavailable", ambiguity="unavailable")
        elif condition == "withheld":
            lead["locations"][0].update(path=None, source_relative_path=None, path_status="missing_or_withheld")
        else:
            lead.update(has_more=True, ambiguity="truncated")
        return reply
    location = expand(captured, (GUIDE,), tool_call=mutate)["locations"][0]
    assert location["lookup"] == "returned" and location["freshness"] == "unverified"
    assert location["publication_comparison"] == "unavailable"
    if condition == "historical":
        assert location["historical_locations"][0]["publication_relation"] == "historical_run"
    if condition == "ambiguous":
        assert len(location["locations"]) == 2 and location["ambiguity"] == "multiple_stored_locations"


@pytest.mark.parametrize("key", ["[private-path]", "python.module:[private-path].neighbor"])
def test_private_path_placeholder_keys_never_spend_a_graph_call(key):
    captured = view(response(nodes=[node(key)], edges=[edge(target=key)]))
    assert captured["nodes"][0]["canonical_key"] == key
    assert captured["eligible_keys"] == []
    callback = Mock()
    assert expand(captured, (key,), tool_call=callback)["status"] == "invalid_selection"
    result = inspect(graph_id=GRAPH, canonical_key=key, tool_call=callback)
    assert result["status"] == "invalid_options" and result["graph_calls"] == 0
    callback.assert_not_called()


@pytest.mark.parametrize("different", [True, False])
def test_publication_labels_do_not_establish_shared_snapshot(environment, different):
    _, calls = environment
    captured = inspect(graph_id=GRAPH, canonical_key=START, tool_call=calls)
    real = mcp.handle_tool_call("repomap_node_locations", dict(graph_id=GRAPH, canonical_key=GUIDE,
                                                              evidence_role="direct", detail="compact"))
    publication = copy.deepcopy(real["structuredContent"]["accepted_publication"])
    if different:
        publication["generation"] += 1
    captured["facts"]["accepted_publication"] = publication  # Disclosed synthetic cross-call labels.
    result = expand(captured, (GUIDE,), tool_call=calls)
    assert result["snapshot_relation"] == "not_guaranteed"
    assert result["locations"][0]["publication_comparison"] == ("different" if different else "equal_labels_only")
