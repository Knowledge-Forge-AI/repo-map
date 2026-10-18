"""Pre-cap admission through the real callable/configured read adapter."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from repomap_kg.server import mcp
from repomap_kg.server._navigation_groups import group_page, location_in_scope
from repomap_kg.storage.navigation_search import NavigationSearchQuery
from repomap_kg.storage.sqlite_local import navigation_queries as queries
from repomap_kg.storage.sqlite_local.connection import read_transaction
from repomap_test_support.navigation_pushdown_fixtures import add_alternatives, fixture_oracle, pushdown_home
from repomap_test_support.navigation_search_fixtures import BINDING, GRAPH


def call(**options):
    return mcp.handle_tool_call("repomap_navigation_search", {
        "graph_id": GRAPH, "query": "needle", "scope": "docs", "source_binding_id": BINDING, **options,
    })["structuredContent"]


def member_keys(result):
    return [m["canonical_key"] for g in result["results"] for m in g["members"]]


def activate(monkeypatch, home):
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)


def test_production_cap_same_binding_subtree_and_empty_scope(tmp_path, monkeypatch):
    home, database = pushdown_home(tmp_path, noise=2105, other_noise=2105)
    activate(monkeypatch, home)
    expected = fixture_oracle(database, BINDING, "docs/zzz")
    assert len(expected) == 2
    result = call(source_path_prefix="docs/zzz", limit=50)
    assert result["status"] == "ok" and result["scan"]["complete"]
    assert member_keys(result) == list(expected)
    assert result["scan"]["nodes"] == result["scan"]["evidence"] == 2
    assert result["scan"]["node_limit"] == 2000 and result["scan"]["evidence_limit"] == 10000
    assert result["scope_excluded_count"] is None
    assert result["scope_excluded_count_basis"] == "not_counted_before_admission"
    assert result["post_admission_scope_excluded_count"] == 0
    grouped = call(source_path_prefix="docs/zzz", grouping="source_document", member_limit=20)
    assert member_keys(grouped) == list(expected) and grouped["result_count"] == 1
    assert grouped["results"][0]["matched_member_count"] == 2
    empty = call(source_path_prefix="docs/missing")
    assert empty["status"] == "ok" and empty["results"] == [] and not empty["has_more"]
    assert empty["scan"]["nodes"] == empty["scan"]["evidence"] == 0
    for offset in (0, 10000):
        overflow = call(offset=offset)
        assert overflow["status"] == "incomplete" and overflow["reason"] == "node_scan_limit"
        assert overflow["results"] == [] and overflow["has_more"]
    assert call(source_binding_id=None)["reason"] == "node_scan_limit"


def test_binding_only_prunes_other_binding_before_cap(tmp_path, monkeypatch):
    home, database = pushdown_home(tmp_path, noise=0, other_noise=2105)
    activate(monkeypatch, home)
    expected = fixture_oracle(database, BINDING)
    result = call(limit=50)
    assert result["status"] == "ok" and member_keys(result) == list(expected)
    assert call(source_binding_id=BINDING.upper())["results"] == []
    assert call(source_binding_id=None)["reason"] == "node_scan_limit"


def test_unrelated_evidence_does_not_spend_selected_budget(tmp_path, monkeypatch):
    home, database = pushdown_home(tmp_path, noise=1)
    activate(monkeypatch, home)
    outside = next(k for k in fixture_oracle(database, BINDING) if "aaa.md" in k)
    add_alternatives(database, outside, 10005)
    assert call()["reason"] == "evidence_scan_limit"
    result = call(source_path_prefix="docs/zzz")
    assert result["status"] == "ok" and result["scan"]["evidence"] == 2
    assert member_keys(result) == list(fixture_oracle(database, BINDING, "docs/zzz"))
    assert result["scan"]["admission"]["checks"] > 10000


@pytest.mark.parametrize("withheld", [False, True])
def test_fourth_conflicting_or_withheld_alternative_remains_visible(tmp_path, monkeypatch, withheld):
    home, database = pushdown_home(tmp_path, noise=0, other_noise=1)
    activate(monkeypatch, home)
    key = next(iter(fixture_oracle(database, BINDING, "docs/zzz")))
    add_alternatives(database, key, 2)
    with sqlite3.connect(database) as connection:
        metadata = json.loads(connection.execute(
            "SELECT metadata_json FROM canonical_evidence WHERE raw_kind='markdown.heading' "
            "AND path LIKE 'other/%' LIMIT 1").fetchone()[0])
    # Deliberately fourth in stable evidence-key order, beyond displayed hints.
    add_alternatives(database, key, 1, path="[REDACTED]" if withheld else "other/docs/aaa.md", metadata=metadata)
    result = call(source_path_prefix="docs/zzz", grouping="source_document")
    group = next(g for g in result["results"] if key in [m["canonical_key"] for m in g["members"]])
    member = group["members"][0]
    assert group["basis"] == "singleton" and group["destination"] is None
    assert member["source_hint_count"] == 4 and len(member["source_hints"]) == 3
    assert member["source_hints_has_more"]


def test_admitted_alternatives_exceed_unchanged_evidence_cap(tmp_path, monkeypatch):
    home, database = pushdown_home(tmp_path, noise=0)
    activate(monkeypatch, home)
    key = next(iter(fixture_oracle(database, BINDING, "docs/zzz")))
    add_alternatives(database, key, 10000, path="root/docs/outside.md")
    result = call(source_path_prefix="docs/zzz", grouping="source_document")
    assert result["status"] == "incomplete" and result["reason"] == "evidence_scan_limit"
    assert result["scan"]["evidence"] == 10000 and result["results"] == [] and result["has_more"]


def test_one_bound_read_snapshot_fixed_queries_and_no_payloads(tmp_path, monkeypatch):
    home, _ = pushdown_home(tmp_path, noise=30)
    activate(monkeypatch, home)
    statements: list[str] = []
    entries = []

    @contextmanager
    def traced(path, binding):
        entries.append((path, binding))
        with read_transaction(path, binding) as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    with patch("repomap_kg.server.sqlite_read_binding.read_transaction", traced):
        result = call(source_path_prefix="docs/zzz")
    assert result["status"] == "ok" and len(entries) == 1
    reads = [s for s in statements if s.lstrip().startswith(("SELECT", "WITH"))]
    assert len(reads) == 3
    assert not any("payload_json" in s for s in statements)
    assert "repomap_navigation_admits" in reads[1] and "repomap_navigation_admits" not in reads[2]
    assert "subject.id IN (" in reads[2]


@pytest.mark.parametrize("budget", ["ADMISSION_CHECK_LIMIT", "ADMISSION_BYTE_LIMIT"])
def test_admission_exhaustion_cannot_claim_empty_and_unregisters_predicate(tmp_path, monkeypatch, budget):
    home, database = pushdown_home(tmp_path, noise=10)
    activate(monkeypatch, home)
    with patch.object(queries, budget, 1):
        result = call(source_path_prefix="docs/missing")
    assert result["status"] == "incomplete" and result["reason"] == "admission_work_limit"
    assert result["has_more"] and not result["scan"]["complete"] and result["results"] == []
    query = NavigationSearchQuery("needle", source_binding_id=BINDING)
    with sqlite3.connect(database) as connection:
        with patch.object(queries, budget, 1):
            scan = queries.navigation_candidates(connection, query, admits_location=lambda row: location_in_scope(row, query, ()))
        assert scan["reason"] == "admission_work_limit"
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("SELECT repomap_navigation_admits(2, '', '{}', '[]')").fetchall()
    assert call(source_path_prefix="docs/missing")["status"] == "ok"


def test_small_pages_group_after_admission_agree_with_independent_oracle(tmp_path, monkeypatch):
    home, database = pushdown_home(tmp_path, noise=9)
    activate(monkeypatch, home)
    expected = fixture_oracle(database, BINDING)
    full = call(limit=50)
    assert member_keys(full) == list(expected)
    for grouping in ("none", "source_document"):
        result = call(grouping=grouping, limit=50, member_limit=20)
        expected_groups = len(set(expected.values())) if grouping == "source_document" else len(expected)
        assert result["result_count"] == expected_groups
        for size in (1, 2):
            pages = [call(grouping=grouping, limit=size, member_limit=20, offset=i)
                     for i in range(0, result["result_count"], size)]
            assert [g for p in pages for g in p["results"]] == result["results"]
            assert not pages[-1]["has_more"]
        assert sorted(member_keys(result)) == list(expected)


@pytest.mark.parametrize("vector_case", ["absent", "duplicate", "revision", "snapshot"])
def test_unusable_vector_cannot_admit_subjects(tmp_path, monkeypatch, vector_case):
    home, database = pushdown_home(tmp_path, noise=1)
    activate(monkeypatch, home)
    with sqlite3.connect(database) as connection:
        vector = json.loads(connection.execute("SELECT snapshot_vector_json FROM runs WHERE id=2").fetchone()[0])
        if vector_case == "absent":
            vector = []
        elif vector_case == "duplicate":
            vector += vector[:1]
        elif vector_case == "revision":
            for row_id, text in connection.execute("SELECT id,metadata_json FROM canonical_evidence").fetchall():
                metadata = json.loads(text)
                metadata["binding_revision"] = 99
                connection.execute("UPDATE canonical_evidence SET metadata_json=? WHERE id=?",
                                   (json.dumps(metadata), row_id))
        else:
            vector[0][2] = "snapshot-mismatch"
        connection.execute("UPDATE runs SET snapshot_vector_json=? WHERE id=2", (json.dumps(vector),))
    result = call(source_path_prefix="docs/zzz")
    assert result["status"] == "ok" and result["results"] == [] and result["scan"]["nodes"] == 0


@pytest.mark.parametrize("prefix,expected", [("docs/zzz", 2), ("docs/zzz/", 2), ("docs/zz", 0),
                                           ("docs/ZZZ", 0), ("docs/zzz_extra", 0), ("docs\\zzz", 0)])
def test_exact_component_and_case_scope(tmp_path, monkeypatch, prefix, expected):
    home, _ = pushdown_home(tmp_path, noise=1)
    activate(monkeypatch, home)
    result = call(source_path_prefix=prefix)
    assert result["status"] == "ok" and result["scan"]["nodes"] == expected


def test_newest_history_chosen_before_source_not_older_convenient_path(tmp_path, monkeypatch):
    from repomap_kg.storage.sqlite_local.publisher import publish_generation
    from repomap_test_support.navigation_search_fixtures import navigation_bundle, navigation_home
    from repomap_test_support.sqlite_local_fixtures import publication_for

    home, database = navigation_home(tmp_path)
    activate(monkeypatch, home)
    for generation, path in ((2, "docs/adr/old/0012-needle.md"), (3, "docs/adr/new/0012-needle.md"), (4, None)):
        documents = {"docs/unrelated.md": "# Unrelated\n"} if path is None else {
            path: "# ADR 0012: Needle\n## Status\nAccepted\n"}
        bundle = navigation_bundle(generation=generation, markdown_sources=documents, python_sources={})
        publish_generation(database, publication_for(bundle, GRAPH), bundle.families, expected_generation=generation-1)
    assert call(kind="doc.adr", source_path_prefix="docs/adr/old")["results"] == []
    result = call(kind="doc.adr", source_path_prefix="docs/adr/new")
    assert result["status"] == "ok" and len(member_keys(result)) == 1
    hint = result["results"][0]["members"][0]["source_hints"][0]
    assert hint["publication_relation"] == "historical_run" and hint["run_id"] == 3


def test_many_binding_vector_is_decoded_and_charged_once_per_run(tmp_path, monkeypatch):
    home, database = pushdown_home(tmp_path, noise=2105)
    activate(monkeypatch, home)
    with sqlite3.connect(database) as connection:
        vector = json.loads(connection.execute("SELECT snapshot_vector_json FROM runs WHERE id=2").fetchone()[0])
        vector += [[f"binding-generic-{i:04d}", 1, f"snapshot-generic-{i:04d}"] for i in range(512)]
        encoded = json.dumps(vector)
        connection.execute("UPDATE runs SET snapshot_vector_json=? WHERE id=2", (encoded,))
    with patch.object(queries.json, "loads", wraps=json.loads) as loads:
        result = call(source_path_prefix="docs/zzz")
    assert sum(item.args[0] == encoded for item in loads.call_args_list) == 1
    assert result["status"] == "ok" and member_keys(result) == list(fixture_oracle(database, BINDING, "docs/zzz"))
    admission = result["scan"]["admission"]
    assert admission["checks"] * len(encoded.encode()) > queries.ADMISSION_BYTE_LIMIT
    assert admission["vector_decodes"] == 1 and admission["vector_bytes"] == len(encoded.encode())
    assert admission["decoded_bytes"] < queries.ADMISSION_BYTE_LIMIT
    assert admission["input_bytes"] > queries.ADMISSION_BYTE_LIMIT


def test_nonbudget_callback_error_keeps_python_error_and_unregisters(tmp_path, monkeypatch):
    home, database = pushdown_home(tmp_path, noise=1)
    activate(monkeypatch, home)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("UPDATE canonical_evidence SET metadata_json='{' WHERE path='root/docs/aaa.md'")
    query = NavigationSearchQuery("needle", scope="docs", source_binding_id=BINDING,
                                  source_path_prefix="docs/zzz")
    with sqlite3.connect(database) as connection:
        with pytest.raises(json.JSONDecodeError):
            queries.navigation_candidates(connection, query, admits_location=lambda row: location_in_scope(row, query, ()))
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("SELECT repomap_navigation_admits(2, '', '{}', '[]')").fetchall()
    with pytest.raises(mcp.RepoMapMcpError, match="Expecting property name"):
        call(source_path_prefix="docs/zzz")


def test_definitive_scope_reports_residuals_from_conservative_admission(tmp_path):
    _, database = pushdown_home(tmp_path, noise=1)
    query = NavigationSearchQuery("needle", scope="docs", source_binding_id=BINDING,
                                  source_path_prefix="docs/zzz")
    with sqlite3.connect(database) as connection:
        scan = queries.navigation_candidates(connection, query, admits_location=lambda row: True)
    page = group_page(scan, query, ())
    assert scan["scan"]["nodes"] == 3 and len(member_keys(page)) == 2
    assert page["scope_excluded_count"] is None
    assert page["post_admission_scope_excluded_count"] == 1
