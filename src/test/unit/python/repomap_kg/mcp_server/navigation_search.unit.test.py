"""Scoped/grouped callable contracts over a real disposable SQLite publication."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from common_lore_index.server import mcp
from common_lore_index.server.mcp_core import RepoMapMcpError
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.sqlite_local.navigation_queries import navigation_candidates
from common_lore_index.storage.sqlite_local.publisher import publish_generation
from repomap_test_support.navigation_search_fixtures import (
    ALPHA_DOC, BINDING, GRAPH, navigation_bundle, navigation_home, publish_navigation_generation,
)
from repomap_test_support.sqlite_local_fixtures import publication_for
from repomap_test_support.host_read_store_config import NO_FALLBACK_GUARDS, patched_guards, setup_owned_config


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home, database = navigation_home(tmp_path)
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    return database


def call(**options: Any) -> dict[str, Any]:
    return mcp.handle_tool_call("repomap_navigation_search", {
        "graph_id": GRAPH, "query": "beacon", **options,
    })["structuredContent"]


def members(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [member for group in result["results"] for member in group["members"]]


def edit(database: Path, sql: str, params: tuple = ()) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(sql, params)


def test_scope_precedes_page_and_never_widens(store: Path) -> None:
    raw = mcp.repomap_search_nodes(graph_id=GRAPH, query="beacon", limit=1)
    assert raw["results"][0]["kind"].startswith("doc.")
    code, docs = call(scope="code", limit=1), call(scope="docs", limit=1)
    assert members(code)[0]["kind"].startswith("python.")
    assert members(docs)[0]["kind"].startswith("doc.")
    assert call(scope="code", kind="doc.page")["results"] == []
    assert call(scope="docs", query="unmatched-exact-scope")["results"] == []
    assert code["count_unit"] == "nodes" and docs["scan"]["complete"]
    # Synthetic key ordering exercises the reverse of producer doc.* < python.*.
    edit(store, "UPDATE canonical_nodes SET canonical_key = 'aaa:' || canonical_key "
         "WHERE kind LIKE 'python.%'")
    reverse = mcp.repomap_search_nodes(graph_id=GRAPH, query="beacon", limit=2)
    assert len(reverse["results"]) == 2 and all(row["kind"].startswith("python.") for row in reverse["results"])
    assert members(call(scope="docs", limit=1))[0]["kind"].startswith("doc.")


def test_group_membership_precedes_group_page(store: Path) -> None:
    options = {"scope": "docs", "grouping": "source_document", "member_limit": 2}
    full = call(**options, limit=50)
    pages = [call(**options, limit=1, offset=i) for i in range(full["result_count"])]
    assert [page["results"][0] for page in pages] == full["results"]
    assert all(page["has_more"] for page in pages[:-1]) and not pages[-1]["has_more"]
    assert call(**options, limit=2)["results"] + call(**options, limit=50, offset=2)["results"] == full["results"]
    paths = [row["destination"]["source_relative_path"] for row in full["results"] if row["destination"]]
    assert {"docs/alpha.md", "docs/beta.md", "docs/gamma.md"} <= set(paths)
    assert len(paths) == len(set(paths))
    alpha = next(row for row in full["results"] if row["destination"]["source_relative_path"] == "docs/alpha.md")
    assert alpha["matched_member_count"] > 25 and len(alpha["members"]) == 2 and alpha["member_has_more"]
    assert all(member["matched"] for member in members(full))
    assert all(group["context"] == [] for group in full["results"])
    # No unmatched parent is substituted for a matching section.
    keys = {member["canonical_key"] for member in members(call(scope="docs", limit=50))}
    assert all(member["canonical_key"] in keys for member in members(full))


def test_bound_subtree_uses_direct_source_and_component_boundary(store: Path) -> None:
    reference = mcp.repomap_node_locations(graph_id=GRAPH, canonical_key=ALPHA_DOC, evidence_role="reference")
    assert any(row["path"] == "root/src/pkg/link.md" for row in reference["locations"])
    assert any(row["canonical_key"] == ALPHA_DOC for row in members(call(scope="docs", limit=50)))
    result = call(scope="code", source_binding_id=BINDING, source_path_prefix="src/pkg/", limit=50)
    assert result["results"]
    assert all(row["source_hints"][0]["source"]["source_relative_path"].startswith("src/pkg/")
               for row in members(result))
    assert not any("pkg_extra" in row["canonical_key"] for row in members(result))
    docs = call(scope="docs", source_binding_id=BINDING, source_path_prefix="src/pkg", grouping="source_document")
    assert docs["results"] and all(row["destination"]["source_relative_path"] == "src/pkg/link.md"
                                   for row in docs["results"])
    assert ALPHA_DOC not in {row["canonical_key"] for row in members(docs)}
    assert call(source_binding_id="binding-absent", source_path_prefix="src/pkg")["results"] == []


@pytest.mark.parametrize("query", ["%", "_", "\\", "café", "'", "naïve", "%2F"])
def test_literal_search_agrees_with_raw_membership(store: Path, query: str) -> None:
    raw = mcp.repomap_search_nodes(graph_id=GRAPH, query=query, limit=100)
    nav = call(query=query, limit=50)
    assert [row["canonical_key"] for row in members(nav)] == [row["canonical_key"] for row in raw["results"]]
    assert nav == call(query=query, limit=50)


def test_literal_subtree_is_not_sql_pattern(store: Path) -> None:
    result = call(scope="docs", source_binding_id=BINDING, source_path_prefix="docs/naïve_%", limit=50)
    assert result["results"]
    assert all(row["source_hints"][0]["source"]["source_relative_path"].startswith("docs/naïve_%/")
               for row in members(result))
    assert call(source_binding_id=BINDING, source_path_prefix="docs/naïve%", limit=50)["results"] == []
    assert call(source_binding_id=BINDING, source_path_prefix="docs\\naïve_%", limit=50)["results"] == []


def test_unknown_kind_and_missing_evidence_remain_distinct(store: Path) -> None:
    edit(store, "UPDATE canonical_nodes SET kind = 'unknown.fixture' WHERE kind = 'doc.page'")
    unknown = call(kind="unknown.fixture", grouping="source_document")
    assert len(unknown["results"]) >= 3
    assert all(row["basis"] == "singleton" and row["unresolved_reason"] == "no_direct_evidence"
               for row in unknown["results"])
    assert call(scope="docs", kind="unknown.fixture")["results"] == []
    edit(store, "DELETE FROM canonical_node_evidence")
    all_rows = call(grouping="source_document", limit=50)
    assert all(row["basis"] == "singleton" for row in all_rows["results"])
    assert call(source_binding_id=BINDING, source_path_prefix="docs")["results"] == []


@pytest.mark.parametrize("field,value", [("path", ""), ("path", "/private/withheld.md"),
                                        ("metadata_json", "{}")])
def test_withheld_or_unbound_path_cannot_group_or_qualify(store: Path, field: str, value: str) -> None:
    edit(store, f"UPDATE canonical_evidence SET {field} = ?", (value,))
    result = call(scope="docs", grouping="source_document", limit=50)
    assert all(row["basis"] == "singleton" for row in result["results"])
    assert call(source_binding_id=BINDING, source_path_prefix="docs")["results"] == []
    assert "/private/withheld.md" not in json.dumps(result)


def test_historical_run_does_not_merge_into_current(store: Path) -> None:
    before = call(scope="docs", grouping="source_document", limit=50)
    publish_navigation_generation(store, 2)
    after = call(scope="docs", grouping="source_document", limit=50)
    assert before["accepted_publication"] != after["accepted_publication"]
    assert all(row["destination"]["run_id"] == after["accepted_publication"]["run_id"]
               for row in after["results"] if row["destination"])
    # Retain canonical subjects and old evidence, but remove the new direct links.
    edit(store, "DELETE FROM canonical_node_evidence WHERE canonical_evidence_id IN "
         "(SELECT id FROM canonical_evidence WHERE run_id = 2)")
    history = call(scope="docs", grouping="source_document", limit=50)
    assert all(row["destination"]["publication_relation"] == "historical_run"
               for row in history["results"] if row["destination"])


def test_missing_raw_payload_is_disclosed_without_losing_direct_identity(store: Path) -> None:
    edit(store, "DELETE FROM raw_observations")
    result = call(scope="docs", grouping="source_document")
    assert any(row["basis"] == "direct_source_document" for row in result["results"])
    assert all(hint["raw_observation"]["status"] == "unavailable" for member in members(result)
               for hint in member["source_hints"])


def test_scan_caps_fail_explicitly_and_use_constant_query_count(store: Path) -> None:
    statements: list[str] = []
    with sqlite3.connect(store) as connection:
        connection.set_trace_callback(statements.append)
        scan = navigation_candidates(connection, NavigationSearchQuery("beacon"))
    assert scan["scan"]["complete"] and len(statements) <= 5
    assert not any("payload_json" in statement for statement in statements)
    for cap in ("NODE_SCAN_LIMIT", "EVIDENCE_SCAN_LIMIT"):
        with patch("common_lore_index.storage.sqlite_local.navigation_queries." + cap, 1):
            result = call(grouping="source_document")
        assert result["status"] == "incomplete" and result["has_more"]
        assert result["results"] == [] and not result["scan"]["complete"]
    with patch("common_lore_index.storage.sqlite_local.navigation_queries.NODE_SCAN_LIMIT", 1):
        narrow = call(source_binding_id=BINDING, source_path_prefix="docs/beta.md")
    assert narrow["status"] == "ok" and narrow["scan"]["nodes"] == 1 and not narrow["has_more"]


@pytest.mark.parametrize("options", [{"scope": "tests"}, {"grouping": "title"}, {"limit": True},
                                    {"limit": 51}, {"offset": -1}, {"member_limit": 0},
                                    {"source_path_prefix": "src"}, {"source_binding_id": ""},
                                    {"source_binding_id": "b", "source_path_prefix": "../src"}])
def test_invalid_options_precede_io(store: Path, options: dict[str, Any]) -> None:
    with patch("common_lore_index.server.sqlite_read_binding.read_transaction", side_effect=AssertionError("IO")):
        with pytest.raises(RepoMapMcpError):
            call(**options)


def test_graph_repository_and_optional_backend_boundaries(store: Path, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    sibling = call(graph_id="sibling", grouping="source_document")
    assert sibling["results"] and sibling["repository_identity"] != call()["repository_identity"]
    assert all(row["destination"]["source_relative_path"] == "docs/only-sibling.md" for row in sibling["results"])
    assert not any("only-sibling" in row["canonical_key"] for row in members(call()))
    assert not any("alpha.md" in row["canonical_key"] for row in members(sibling))
    assert call(graph_id="unpublished")["reason"] == "publication_absent"
    for graph in ("hidden", "disabled", "unknown"):
        with pytest.raises(RepoMapMcpError):
            call(graph_id=graph)
    edit(store, "UPDATE graph_binding SET repository_identity = 'repo1:foreign'")
    with pytest.raises(RepoMapMcpError, match="graph-database-graph-mismatch"):
        call()
    home = tmp_path / "pg-home"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config())
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    with patched_guards(NO_FALLBACK_GUARDS):
        result = call(graph_id="host-one")
    assert result["reason"] == "backend_unsupported" and result["status"] == "unavailable"


def test_schema_discovery_and_new_tool_default_equivalence(store: Path) -> None:
    schema = mcp.tool_input_schema("repomap_navigation_search")
    assert schema["additionalProperties"] is False
    assert schema["properties"]["grouping"]["default"] == "none"
    assert call() == call(scope="all", grouping="none", limit=20, offset=0, member_limit=5)
    with pytest.raises(RepoMapMcpError, match="unexpected argument"):
        call(hidden_group_key="unavailable")
    before = hashlib.sha256(store.read_bytes()).hexdigest()
    call()
    assert hashlib.sha256(store.read_bytes()).hexdigest() == before


def test_captured_entry_responses_and_errors_remain_byte_equal(tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    from repomap_test_support.node_location_fixtures import locator_home

    home, _ = locator_home(tmp_path)
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    golden = Path("src/test/resources/navigation_search_entry.json")
    cases = json.loads(golden.read_text())["cases"]
    for case in cases:
        try:
            actual = {"payload": mcp.handle_tool_call(case["tool"], case["arguments"])["structuredContent"]}
        except RepoMapMcpError as error:
            actual = {"error_type": type(error).__name__, "error": str(error)}
        expected = {key: value for key, value in case.items() if key not in {"tool", "arguments"}}
        assert json.dumps(actual, sort_keys=True, ensure_ascii=False) == json.dumps(expected, sort_keys=True, ensure_ascii=False)


def publish_custom(database: Path, documents: dict[str, str], **options: Any) -> None:
    bundle = navigation_bundle(generation=2, markdown_sources=documents, python_sources={}, **options)
    publish_generation(database, publication_for(bundle, GRAPH), bundle.families, expected_generation=1)


def test_duplicate_heavy_raw_pages_cannot_hide_later_document_groups(store: Path) -> None:
    documents = {"docs/alpha.md": "# Parent Alpha\n" + "\n".join(f"## Needle {i}\n" for i in range(31)),
                 "docs/beta.md": "# Parent Beta\n## Needle B\n", "docs/gamma.md": "# Parent Gamma\n## Needle C\n"}
    publish_custom(store, documents)
    raw = mcp.repomap_search_nodes(graph_id=GRAPH, query="needle", limit=6)
    assert raw["has_more"] and all("alpha.md" in row["canonical_key"] for row in raw["results"])
    args = {"query": "needle", "scope": "docs", "grouping": "source_document", "member_limit": 1}
    full = call(**args, limit=50)
    assert len(full["results"]) == 3
    assert full["results"][0]["matched_member_count"] == 31
    assert all(group["members"][0]["kind"] == "doc.section" for group in full["results"])
    assert [call(**args, limit=1, offset=i)["results"][0] for i in range(3)] == full["results"]
    assert call(**args, limit=2)["results"] + call(**args, limit=2, offset=2)["results"] == full["results"]


def test_multi_source_same_path_titles_and_ambiguous_adr_are_not_merged(store: Path) -> None:
    text = "# ADR 0010: Needle\n\n## Status\nAccepted\n## Needle Decision\n"
    path = "docs/adr/0010-needle.md"
    publish_custom(store, {path: text}, additional_markdown={"other": {path: text}})
    result = call(query="needle", scope="docs", grouping="source_document", limit=50)
    proven = [group for group in result["results"] if group["destination"]]
    assert len(proven) == 2
    assert len({group["destination"]["source_binding_id"] for group in proven}) == 2
    assert {group["destination"]["source_relative_path"] for group in proven} == {path}
    ambiguous = next(group for group in result["results"] if group["destination"] is None)
    assert ambiguous["basis"] == "singleton" and ambiguous["unresolved_reason"] == "conflicting_direct_identities"
    assert ambiguous["members"][0]["source_hint_count"] == 2
    bound = call(query="needle", source_binding_id=BINDING, source_path_prefix=path, limit=50)
    # Both direct alternatives stay visible even when one proves scope membership.
    assert any(member["source_hint_count"] == 2 for member in members(bound))


def test_moved_document_and_incompatible_revisions_keep_historical_singletons(store: Path) -> None:
    publish_custom(store, {"docs/moved.md": "# Beacon Moved\n## Beacon Part\n"}, revision=2)
    result = call(scope="docs", grouping="source_document", limit=50)
    old = next(group for group in result["results"] if group["destination"]
               and group["destination"]["source_relative_path"] == "docs/alpha.md")
    new = next(group for group in result["results"] if group["destination"]
               and group["destination"]["source_relative_path"] == "docs/moved.md")
    assert old["destination"]["publication_relation"] == "historical_run"
    assert new["destination"]["publication_relation"] == "accepted_run"
    assert old["destination"]["binding_revision"] == 1 and new["destination"]["binding_revision"] == 2


def test_accepted_references_only_do_not_borrow_historical_direct_paths(store: Path) -> None:
    publish_custom(store, {"src/pkg/link.md": "# Beacon Link\n[Beacon](../../docs/alpha.md)\n",
                           "docs/alpha.md": "# Unrelated\n"})
    # Remove the accepted direct evidence for the page, retaining its incoming link.
    edit(store, "DELETE FROM canonical_node_evidence WHERE canonical_evidence_id IN "
         "(SELECT id FROM canonical_evidence WHERE run_id = 2 AND raw_kind = 'markdown.document')")
    result = call(query="alpha.md", scope="docs", grouping="source_document")
    page = next(member for member in members(result) if member["kind"] == "doc.page")
    assert page["source_hints"] == []
    assert call(query="alpha.md", kind="doc.page", source_binding_id=BINDING,
                source_path_prefix="docs/alpha.md")["results"] == []


def test_many_direct_alternatives_are_bounded_and_cannot_manufacture_group_identity(store: Path) -> None:
    documents = {f"docs/adr/{i:02d}/0012-needle.md": "# ADR 0012: Needle\n## Status\nAccepted\n"
                 for i in range(12)}
    publish_custom(store, documents)
    result = call(query="needle", scope="docs", grouping="source_document", limit=50)
    adr = next(member for member in members(result) if member["kind"] == "doc.adr")
    assert adr["source_hint_count"] == 12 and len(adr["source_hints"]) == 3 and adr["source_hints_has_more"]
    group = next(group for group in result["results"] if adr in group["members"])
    assert group["basis"] == "singleton" and group["unresolved_reason"] == "conflicting_direct_identities"


def test_vector_conflicts_and_stored_redaction_remain_unresolved(store: Path) -> None:
    with sqlite3.connect(store) as connection:
        rows = connection.execute("SELECT id, metadata_json FROM canonical_evidence").fetchall()
        for row_id, text in rows:
            metadata = json.loads(text)
            metadata["binding_revision"] = 99
            connection.execute("UPDATE canonical_evidence SET metadata_json = ? WHERE id = ?",
                               (json.dumps(metadata), row_id))
    result = call(scope="docs", grouping="source_document", limit=50)
    assert all(group["destination"] is None for group in result["results"])
    assert call(source_binding_id=BINDING, source_path_prefix="docs")["results"] == []
    edit(store, "UPDATE canonical_evidence SET path = '[REDACTED]'")
    assert all(group["destination"] is None for group in call(scope="docs", grouping="source_document")["results"])


def test_compact_navigation_hints_expand_via_existing_locator(store: Path) -> None:
    member = members(call(scope="docs", limit=1))[0]
    hint = member["source_hints"][0]
    assert not {"evidence_key", "publication", "extractor", "extractor_version"} & hint.keys()
    assert set(hint["raw_observation"]) == {"status", "ordinal", "kind"}
    full = mcp.repomap_node_locations(graph_id=GRAPH, canonical_key=member["canonical_key"], evidence_role="direct")
    row = full["locations"][0]
    assert hint["source"] == row["source"] and hint["path"] == row["path"]
    assert hint["start_line"] == row["start_line"] and hint["publication_relation"] == row["publication_relation"]
    assert row["evidence_key"] and row["publication"]


def test_withheld_canonical_key_stays_explicit_singleton(store: Path) -> None:
    edit(store, "UPDATE canonical_nodes SET canonical_key = '[REDACTED]:beacon' "
         "WHERE canonical_key = ?", (ALPHA_DOC,))
    result = call(scope="docs", grouping="source_document", limit=50)
    group = next(row for row in result["results"] if row["members"][0]["identity_status"] == "withheld")
    assert group["basis"] == "singleton" and group["unresolved_reason"] == "canonical_identity_withheld"
    assert group["destination"] is not None and group["matched_member_count"] == 1
    assert group["members"][0]["canonical_key"] == "[REDACTED]:beacon"
