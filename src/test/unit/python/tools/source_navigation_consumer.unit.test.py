"""Executable optional consumer branches; real SQLite calls, separate local reads."""

from __future__ import annotations

import json
import source_navigation_consumer as consumer_module
import sqlite3
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from common_lore_index.server import mcp
from common_lore_index.storage.sqlite_local.publisher import publish_generation
from repomap_test_support.node_location_fixtures import (
    BINDING, DOC, GRAPH, SYMBOL, locator_home, publish_locator_generation,
)
from repomap_test_support.host_read_store_config import NO_FALLBACK_GUARDS, patched_guards, setup_owned_config
from repomap_test_support.sqlite_local_fixtures import generation_bundle, publication_for

assert Path(consumer_module.__file__).resolve() == Path(__file__).resolve().parents[5] / "tools/source_navigation_consumer.py"
navigate = vars(consumer_module)["navigate"]


@pytest.fixture
def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, dict[str, Any]]:
    home, database = locator_home(tmp_path, reference_count=5)
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    workspace = tmp_path / "caller-workspace"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs/guide.md").write_text("Fixture guide.\n", encoding="utf-8")
    options = {"graph_id": GRAPH, "repository_identity": "repo1:locator",
               "bindings": {BINDING: workspace}, "tool_call": mcp.handle_tool_call,
               "source_check": lambda text: text == "Fixture guide.\n"}
    return database, workspace, options


def actions(result: dict[str, Any], action: str) -> list[dict[str, Any]]:
    return [event for event in result["trace"] if event["action"] == action]


def test_known_nonpilot_handoff_verifies_source_with_zero_graph_calls(environment: tuple) -> None:
    _, workspace, options = environment
    (workspace / "helpers.py").write_text("def normalize_label(value):\n    return value.strip()\n", encoding="utf-8")
    handoff = {"repository_identity": "repo1:locator", "binding_id": BINDING,
               "source_relative_path": "helpers.py", "start_line": 1, "end_line": 2}
    options["source_check"] = lambda text: text == "def normalize_label(value):\n    return value.strip()\n"
    with patch.object(mcp, "handle_tool_call", side_effect=AssertionError("unnecessary graph call")):
        options["tool_call"] = mcp.handle_tool_call
        result = navigate(handoff=handoff, **options)
    assert result["branch"] == "handoff" and result["outcome"] == "verified"
    assert result["graph_calls"] == 0 and len(actions(result, "source_read")) == 1
    assert actions(result, "source_read")[0]["verified"] is True


def test_selected_node_uses_compact_direct_then_one_bounded_source_read(environment: tuple) -> None:
    _, _, options = environment
    result = navigate(canonical_key=DOC, **options)
    assert result["branch"] == "locator" and result["outcome"] == "verified"
    assert result["graph_calls"] == 1
    assert [row["action"] for row in result["trace"]] == ["tool_call", "source_read"]
    assert actions(result, "tool_call")[0]["arguments"]["detail"] == "compact"
    assert actions(result, "source_read")[0]["start_line"] is None


def test_unknown_node_searches_then_locates_exact_python_range(environment: tuple) -> None:
    database, workspace, options = environment
    publish_locator_generation(database, 2, alternatives=False, reference_count=5)
    (workspace / "src").mkdir()
    text = "# header\n" * 4 + 'def serve():\n    return "ok"\n' + "# body\n" * 9
    (workspace / "src/service.py").write_text(text, encoding="utf-8")
    options["source_check"] = lambda selected: selected == "".join(text.splitlines(keepends=True)[4:15])
    result = navigate(query="sample.service", **options)
    assert result["branch"] == "search_locator" and result["outcome"] == "verified"
    assert result["graph_calls"] == 2
    assert [row["tool"] for row in actions(result, "tool_call")] == ["repomap_search_nodes", "repomap_node_locations"]
    assert [(row["start_line"], row["end_line"]) for row in actions(result, "source_read")] == [(5, 15)]


@pytest.mark.parametrize("state", ["ambiguous", "historical_only", "historical_primary", "metadata", "unbound", "missing_raw"])
def test_uncertain_evidence_is_not_promoted_to_verified_source(environment: tuple, state: str) -> None:
    database, _, options = environment
    key = SYMBOL if state == "ambiguous" else DOC
    if state == "historical_only":
        publish_locator_generation(database, 2, definitions=False, reference_count=5)
    elif state == "historical_primary":
        bundle = generation_bundle(1)
        publish_generation(database, publication_for(bundle, GRAPH), bundle.families, expected_generation=1)
    elif state in {"metadata", "unbound", "missing_raw"}:
        with sqlite3.connect(database) as connection:
            if state == "metadata":
                connection.execute("UPDATE canonical_nodes SET metadata_json = ? WHERE canonical_key = ?",
                                   (json.dumps({"doc_path": "docs/guide.md"}), DOC))
                connection.execute("DELETE FROM canonical_node_evidence")
            elif state == "unbound":
                connection.execute("UPDATE canonical_evidence SET metadata_json = '{}'")
            else:
                connection.execute("DELETE FROM raw_observations")
    result = navigate(canonical_key=key, **options)
    assert result["outcome"] == "native_search" and result["graph_calls"] == 1
    assert actions(result, "source_read") == [] and len(actions(result, "native_search")) == 1


@pytest.mark.parametrize("mode", ["absent", "broken", "unsupported", "old_schema", "malformed"])
def test_optional_helper_failure_falls_back_without_loop(environment: tuple, mode: str) -> None:
    _, _, options = environment
    if mode == "absent":
        options["tool_call"] = None
    else:
        def helper(name: str, args: dict[str, Any]) -> dict[str, Any]:
            if mode == "broken":
                raise RuntimeError("private helper diagnostic must not leak")
            if mode == "malformed":
                return {"structuredContent": {"detail": "compact", "schema_version": 1}}
            if mode == "old_schema":
                return mcp.handle_tool_call(name, {key: value for key, value in args.items() if key != "detail"})
            return {"structuredContent": {"detail": "compact", "schema_version": 1,
                                          "status": "unavailable", "reason": "backend_unsupported"}}
        options["tool_call"] = helper
    result = navigate(canonical_key=DOC, **options)
    assert result["outcome"] == "native_search" and result["graph_calls"] == (mode != "absent")
    assert actions(result, "source_read") == [] and len(actions(result, "native_search")) == 1
    assert "private helper diagnostic" not in json.dumps(result)


def test_real_postgresql_unsupported_callable_falls_back(environment: tuple, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, options = environment
    home = tmp_path / "unsupported-home"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    options["graph_id"] = "host-one"
    with patched_guards(NO_FALLBACK_GUARDS):
        result = navigate(canonical_key=DOC, **options)
    assert result["outcome"] == "native_search" and result["graph_calls"] == 1
    assert actions(result, "source_read") == []


def test_changed_source_range_falls_back_after_one_read_without_requery(environment: tuple) -> None:
    database, workspace, options = environment
    publish_locator_generation(database, 2, alternatives=False)
    (workspace / "src").mkdir()
    (workspace / "src/service.py").write_text("# moved definition\n" * 20, encoding="utf-8")
    options["source_check"] = lambda text: 'def serve():' in text
    result = navigate(canonical_key=SYMBOL, **options)
    assert result["outcome"] == "native_search" and result["graph_calls"] == 1
    assert len(actions(result, "source_read")) == 1
    assert actions(result, "source_read")[0]["verified"] is False
    assert len(actions(result, "native_search")) == 1


def test_unknown_ambiguous_search_stops_before_locator(environment: tuple) -> None:
    _, _, options = environment
    result = navigate(query="root", **options)
    assert result["outcome"] == "native_search" and result["graph_calls"] == 1
    assert actions(result, "tool_call")[0]["tool"] == "repomap_search_nodes"
    assert actions(result, "source_read") == []


def test_truncated_direct_window_never_selects_the_first_lead(environment: tuple) -> None:
    database, _, options = environment
    # Deliberate synthetic producer-kind/link fault creates >2 direct alternatives.
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE canonical_evidence SET raw_kind = 'markdown.document' WHERE raw_kind = 'markdown.link'")
        connection.execute("UPDATE canonical_node_evidence SET link_kind = 'observed'")
    result = navigate(canonical_key=DOC, **options)
    assert result["outcome"] == "native_search" and result["graph_calls"] == 1
    assert actions(result, "source_read") == []


@pytest.mark.parametrize("path", ["../outside.py", "/outside.py", "root/docs/guide.md"])
def test_handoff_never_infers_path_or_strips_root(environment: tuple, path: str) -> None:
    _, _, options = environment
    result = navigate(handoff={"repository_identity": "repo1:locator", "binding_id": BINDING,
                               "source_relative_path": path, "start_line": None, "end_line": None}, **options)
    assert result["outcome"] == "native_search" and result["graph_calls"] == 0


def test_workspace_escape_symlink_and_out_of_file_range_are_refused(environment: tuple, tmp_path: Path) -> None:
    _, workspace, options = environment
    outside = tmp_path / "outside.md"
    outside.write_text("Fixture guide.\n", encoding="utf-8")
    (workspace / "escape.md").symlink_to(outside)
    for relative, start, end in (("escape.md", None, None), ("docs/guide.md", 2, 3)):
        result = navigate(handoff={"repository_identity": "repo1:locator", "binding_id": BINDING,
                                   "source_relative_path": relative, "start_line": start, "end_line": end}, **options)
        assert result["outcome"] == "native_search" and result["graph_calls"] == 0


@pytest.mark.parametrize("literal", ["__all__", "exported_names =", "# source comment", "'; $(touch marker) \\"])
def test_explicit_source_text_returns_literal_scoped_plan_without_io(tmp_path: Path, literal: str) -> None:
    paths = (tmp_path / "workspace with spaces" / "src", tmp_path / "other" / "tests")
    with (patch.object(subprocess, "run", side_effect=AssertionError("must not execute search")) as execute,
          patch.object(Path, "open", side_effect=AssertionError("must not read source")) as read,
          patch.object(mcp, "handle_tool_call", side_effect=AssertionError("must not call graph")) as graph):
        result = navigate(graph_id="absent", repository_identity="repo1:example", bindings={},
                          source_check=lambda _: False, tool_call=graph,
                          query=literal, source_text_paths=paths)
    assert result == {"branch": "source_text", "outcome": "native_search", "graph_calls": 0, "trace": [{
        "action": "native_search", "reason": "caller_declared_source_text", "literal": literal,
        "paths": [str(path) for path in paths], "max_matches": 20, "ready": True,
    }]}
    graph.assert_not_called()
    execute.assert_not_called()
    read.assert_not_called()


@pytest.mark.parametrize("query,paths", [("literal", ()), (None, (Path("chosen/src"),))])
def test_incomplete_source_text_plan_never_supplies_implicit_scope(query: str | None, paths: tuple[Path, ...]) -> None:
    result = navigate(graph_id="absent", repository_identity="repo1:example", bindings={},
                      source_check=lambda _: False, query=query, source_text_paths=paths)
    assert result["graph_calls"] == 0 and result["branch"] == "source_text"
    assert result["trace"][0]["ready"] is False
    assert result["trace"][0]["paths"] == [str(path) for path in paths]


def test_explicit_source_text_purpose_precedes_selected_key() -> None:
    with patch.object(mcp, "handle_tool_call", side_effect=AssertionError("must not call graph")) as graph:
        result = navigate(graph_id="absent", repository_identity="repo1:example", bindings={},
                          source_check=lambda _: False, tool_call=graph, canonical_key=DOC,
                          query="literal", source_text_paths=(Path("chosen/src"),))
    assert result["branch"] == "source_text" and result["graph_calls"] == 0
    assert actions(result, "native_search")[0]["paths"] == ["chosen/src"]
    graph.assert_not_called()


@pytest.mark.parametrize("paths", ["chosen/src", Path("chosen/src"), [Path("chosen/src")]])
def test_source_text_paths_rejects_non_tuple_without_graph_calls(paths: Any) -> None:
    with patch.object(mcp, "handle_tool_call", side_effect=AssertionError("must not call graph")) as graph:
        with pytest.raises(TypeError, match="source_text_paths must be a tuple of paths"):
            navigate(graph_id="absent", repository_identity="repo1:example", bindings={},
                     source_check=lambda _: False, tool_call=graph, query="literal", source_text_paths=paths)
    graph.assert_not_called()


def test_source_text_with_supplied_location_verifies_handoff_first(environment: tuple) -> None:
    _, workspace, options = environment
    handoff = {"repository_identity": "repo1:locator", "binding_id": BINDING,
               "source_relative_path": "docs/guide.md", "start_line": None, "end_line": None}
    with patch.object(mcp, "handle_tool_call", side_effect=AssertionError("unnecessary graph call")) as graph:
        result = navigate(**{**options, "tool_call": graph}, handoff=handoff, query="Fixture guide",
                          source_text_paths=(workspace / "docs",))
    assert result["branch"] == "handoff" and result["outcome"] == "verified" and result["graph_calls"] == 0
    assert actions(result, "native_search") == []
    graph.assert_not_called()


def test_source_text_failed_handoff_preserves_native_search_boundaries(environment: tuple) -> None:
    _, workspace, options = environment
    handoff = {"repository_identity": "repo1:locator", "binding_id": BINDING,
               "source_relative_path": "docs/guide.md", "start_line": None, "end_line": None}
    with patch.object(mcp, "handle_tool_call", side_effect=AssertionError("unnecessary graph call")) as graph:
        result = navigate(**{**options, "tool_call": graph, "source_check": lambda _: False},
                          handoff=handoff, query="expected content", source_text_paths=(workspace / "docs",))
    assert result["graph_calls"] == 0 and result["branch"] == "source_text"
    assert actions(result, "source_read")[0]["verified"] is False
    assert actions(result, "native_search") == [{
        "action": "native_search", "reason": "caller_declared_source_text", "literal": "expected content",
        "paths": [str(workspace / "docs")], "max_matches": 20, "ready": True,
    }]
    graph.assert_not_called()


@pytest.mark.parametrize("mode", ["empty", "error"])
def test_indexed_subject_no_match_or_error_falls_back_once_without_spelling_rule(mode: str) -> None:
    calls = []

    def graph(name: str, args: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, args))
        if mode == "error":
            raise RuntimeError("helper unavailable")
        return {"structuredContent": {"results": [], "has_more": False}}

    result = navigate(graph_id="example", repository_identity="repo1:example", bindings={},
                      source_check=lambda _: False, query="__all__", tool_call=graph)
    assert calls == [("repomap_search_nodes", {"graph_id": "example", "query": "__all__", "limit": 2})]
    assert result["graph_calls"] == 1 and result["outcome"] == "native_search"
    assert len(actions(result, "native_search")) == 1
