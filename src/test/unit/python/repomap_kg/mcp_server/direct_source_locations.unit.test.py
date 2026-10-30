"""Direct evidence selection through real canonicalization, publication and callable."""

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
from common_lore_index.storage.sqlite_local.publisher import publish_generation
from repomap_test_support.host_read_store_config import (
    NO_FALLBACK_GUARDS, patched_guards, setup_owned_config,
)
from repomap_test_support.node_location_fixtures import (
    DOC, GRAPH, SYMBOL, locator_home, publish_locator_generation,
)
from repomap_test_support.sqlite_local_fixtures import generation_bundle, publication_for


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home, database = locator_home(tmp_path, reference_count=5)
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    return database


def call(key: str = DOC, **options: Any) -> dict[str, Any]:
    return mcp.handle_tool_call("repomap_node_locations", {
        "graph_id": GRAPH, "canonical_key": key, **options,
    })["structuredContent"]


def edit(database: Path, sql: str, params: tuple = ()) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(sql, params)


@pytest.mark.parametrize("key", [DOC, SYMBOL])
@pytest.mark.parametrize("limit", [1, 2])
def test_direct_subject_survives_more_than_a_full_window_of_references(
    store: Path, tmp_path: Path, key: str, limit: int,
) -> None:
    before = hashlib.sha256(store.read_bytes()).hexdigest()
    default = call(key, limit=limit)
    assert all(row["link_kind"] == "inferred_from_edge" for row in default["locations"])
    direct = call(key, evidence_role="direct", limit=limit)
    assert direct["status"] == "located" and direct["evidence_role"] == "direct"
    assert all(row["evidence_role"] == "direct" for row in direct["locations"])
    assert direct["locations"][0]["link_kind"] == "observed"
    assert direct["locations"][0]["path"] == (
        "root/docs/guide.md" if key == DOC else "root/src/service.py"
    )
    assert direct["has_more"] is (key == SYMBOL and limit == 1)
    assert direct["ambiguity"] == (
        "truncated" if key == SYMBOL and limit == 1 else
        "multiple_stored_locations" if key == SYMBOL else "single_stored_location"
    )
    assert default == call(key, limit=limit) == call(key, evidence_role="all", limit=limit)
    assert "evidence_role" not in default and "evidence_role" not in default["locations"][0]
    assert hashlib.sha256(store.read_bytes()).hexdigest() == before
    assert not (tmp_path / "never-created-source").exists()


def test_mixed_document_window_keeps_reference_ranges_on_referrers(store: Path) -> None:
    mixed = call(limit=4)
    assert [row["path"] for row in mixed["locations"]] == [
        f"root/docs/reference-{index}.md" for index in range(4)
    ]
    assert mixed["ambiguity"] == "multiple_stored_locations" and mixed["has_more"] is True
    direct = call(evidence_role="direct", limit=1)
    row = direct["locations"][0]
    assert row["raw_observation"]["kind"] == "markdown.document"
    assert row["start_line"] is row["end_line"] is None
    assert row["range_status"] == "missing_or_invalid" and direct["freshness"] == "unverified"
    assert row["source"]["binding_alias"] == "root"
    assert row["source"]["source_relative_path"] == "docs/guide.md"
    references = call(evidence_role="reference", limit=2)
    assert references["has_more"] is True
    assert all(row["evidence_role"] == "reference" and row["start_line"] == 1
               for row in references["locations"])
    assert call(evidence_role="unknown")["locations"] == []


def test_three_references_then_path_only_document_shape(store: Path) -> None:
    publish_locator_generation(store, 2, reference_count=3, trailing_reference=True)
    result = call(limit=4)
    assert [row["link_kind"] for row in result["locations"]] == [
        "inferred_from_edge", "inferred_from_edge", "inferred_from_edge", "observed",
    ]
    assert result["locations"][-1]["path"] == "root/docs/guide.md"
    assert result["locations"][-1]["start_line"] is None
    assert result["has_more"] is True and result["ambiguity"] == "multiple_stored_locations"
    assert call(evidence_role="direct", limit=1)["locations"][0]["path"] == "root/docs/guide.md"


def test_reference_only_current_run_does_not_promote_older_direct_evidence(store: Path) -> None:
    publish_locator_generation(store, 2, reference_count=5, definitions=False)
    result = call(evidence_role="direct", limit=1)
    assert result["locations"] == [] and result["has_more"] is False
    assert result["location_scope"] == "accepted_run" and result["location_run_id"] == 2
    assert result["historical_locations"][0]["run_id"] == 1
    assert result["historical_locations"][0]["publication_relation"] == "historical_run"
    assert result["historical_has_more"] is False
    assert result["status"] == "unavailable" and result["metadata_location"] is None
    assert result["reason"] == "historical_locations_only"
    assert result["fallback"] == "native_search"
    assert len(call(evidence_role="reference", limit=1)["locations"]) == 1
    # An unbound metadata path remains an explicitly unknown partial lead.
    edit(store, "UPDATE canonical_nodes SET metadata_json = ? WHERE canonical_key = ?",
         (json.dumps({"doc_path": "docs/guide.md"}), DOC))
    partial = call(evidence_role="direct", limit=1)
    assert partial["status"] == "metadata_only" and partial["locations"] == []
    assert partial["ambiguity"] == "metadata_only"
    assert partial["metadata_location"]["evidence_role"] == "unknown"


@pytest.mark.parametrize("role", ["direct", "reference", "unknown"])
def test_unbound_metadata_is_not_a_stored_location_in_filtered_views(store: Path, role: str) -> None:
    edit(store, "UPDATE canonical_nodes SET metadata_json = ? WHERE canonical_key = ?",
         (json.dumps({"doc_path": "docs/guide.md"}), DOC))
    edit(store, "DELETE FROM canonical_node_evidence WHERE canonical_node_id = "
         "(SELECT id FROM canonical_nodes WHERE canonical_key = ?)", (DOC,))
    result = call(evidence_role=role, limit=1)
    assert result["status"] == result["reason"] == result["ambiguity"] == "metadata_only"
    assert result["locations"] == result["historical_locations"] == []
    assert result["metadata_location"]["evidence_role"] == "unknown"
    assert result["fallback"] == "native_search"
    default = call(limit=1)
    assert default["status"] == "metadata_only" and default["ambiguity"] == "single_stored_location"
    assert "evidence_role" not in default and "evidence_role" not in default["metadata_location"]


def test_withheld_historical_paths_do_not_advertise_a_usable_lead(store: Path) -> None:
    publish_locator_generation(store, 2, reference_count=5, definitions=False)
    edit(store, "UPDATE canonical_evidence SET path = '/Users/example/private.md'")
    result = call(evidence_role="direct", limit=1)
    assert result["status"] == "unavailable" and result["reason"] == "no_usable_location"
    assert result["historical_locations"][0]["path"] is None
    assert result["fallback"] == "native_search"


def test_historical_fallback_anchors_to_latest_linked_run_even_without_direct(store: Path) -> None:
    publish_locator_generation(store, 2, reference_count=5, definitions=False)
    bundle = generation_bundle(2)
    publish_generation(store, publication_for(bundle, GRAPH), bundle.families, expected_generation=2)
    result = call(evidence_role="direct", limit=1)
    assert result["location_scope"] == "historical_run" and result["location_run_id"] == 2
    assert result["locations"] == []
    assert result["historical_locations"][0]["run_id"] == 1


def test_moved_direct_ranges_and_historical_bounds_are_separate(store: Path) -> None:
    for generation in range(2, 6):
        publish_locator_generation(store, generation, start_line=40, alternatives=False, reference_count=5)
    result = call(SYMBOL, evidence_role="direct", limit=2)
    assert result["location_scope"] == "accepted_run" and result["location_run_id"] == 5
    assert [(row["start_line"], row["end_line"]) for row in result["locations"]] == [(40, 50)]
    assert result["ambiguity"] == "single_stored_location" and result["has_more"] is False
    assert [row["run_id"] for row in result["historical_locations"]] == [4, 3]
    assert result["historical_has_more"] is True
    old = call(SYMBOL, evidence_role="direct", limit=10)["historical_locations"]
    assert [(row["start_line"], row["end_line"]) for row in old[-2:]] == [(5, 15), (20, 23)]


def test_contradictory_direct_ranges_remain_multiple_and_truncation_is_explicit(store: Path) -> None:
    edit(store, "UPDATE canonical_evidence SET path = 'root/src/service.py' WHERE raw_kind = 'python.function'")
    one = call(SYMBOL, evidence_role="direct", limit=1)
    both = call(SYMBOL, evidence_role="direct", limit=2)
    assert one["has_more"] is True and one["ambiguity"] == "truncated"
    assert both["has_more"] is False and both["ambiguity"] == "multiple_stored_locations"
    assert [(row["start_line"], row["end_line"]) for row in both["locations"]] == [(5, 15), (20, 23)]


@pytest.mark.parametrize("fault", ["raw", "metadata", "both"])
def test_missing_provenance_does_not_erase_persisted_supported_role(store: Path, fault: str) -> None:
    if fault in {"raw", "both"}:
        edit(store, "DELETE FROM raw_observations")
    if fault in {"metadata", "both"}:
        edit(store, "UPDATE canonical_evidence SET metadata_json = '{}'")
        edit(store, "UPDATE canonical_nodes SET metadata_json = '{}'")
    for key in (DOC, SYMBOL):
        result = call(key, evidence_role="direct", limit=1)
        row = result["locations"][0]
        assert result["status"] == "located" and row["evidence_role"] == "direct"
        if fault in {"raw", "both"}:
            assert row["raw_observation"]["status"] == "unavailable"
            assert row["raw_observation"]["payload_hash"] is None
        if fault in {"metadata", "both"}:
            assert row["source"] == {} and result["metadata_location"] is None


@pytest.mark.parametrize("fault", ["raw_kind", "subject_kind", "link_kind"])
def test_unknown_role_is_explicit_and_never_becomes_direct(store: Path, fault: str) -> None:
    if fault == "raw_kind":
        edit(store, "UPDATE canonical_evidence SET raw_kind = 'unsupported.definition' WHERE raw_kind = 'python.function'")
    elif fault == "subject_kind":
        edit(store, "UPDATE canonical_nodes SET kind = 'unknown' WHERE canonical_key = ?", (SYMBOL,))
    else:
        edit(store, "UPDATE canonical_node_evidence SET link_kind = 'unrecognized' WHERE link_kind = 'observed'")
    result = call(SYMBOL, evidence_role="direct")
    assert result["locations"] == [] and result["status"] == "unavailable"
    assert result["fallback"] == "native_search"
    unknown = call(SYMBOL, evidence_role="unknown", limit=1)
    assert unknown["locations"][0]["evidence_role"] == "unknown" and unknown["has_more"] is True
    assert call(SYMBOL, evidence_role="reference", limit=1)["has_more"] is True


@pytest.mark.parametrize("role", ["definition", "", None, True, [], {}])
def test_invalid_role_is_bounded_error_before_io(store: Path, role: Any) -> None:
    with patch("common_lore_index.server.sqlite_read_binding.read_transaction", side_effect=AssertionError("open")):
        with pytest.raises(RepoMapMcpError, match="evidence_role must be"):
            call(evidence_role=role)


def test_filtered_views_preserve_search_visibility_identity_and_redaction(store: Path) -> None:
    before = mcp.repomap_search_nodes(graph_id=GRAPH, query="root", limit=2)
    for role in ("all", "direct", "reference", "unknown"):
        call(evidence_role=role)
        assert call(evidence_role=role, graph_id="sibling")["reason"] == "node_not_found"
        with pytest.raises(RepoMapMcpError, match="not MCP-visible"):
            call(evidence_role=role, graph_id="hidden")
    assert mcp.repomap_search_nodes(graph_id=GRAPH, query="root", limit=2) == before
    edit(store, "UPDATE canonical_evidence SET path = '/Users/example/private.md'")
    result = call(SYMBOL, evidence_role="direct", limit=1)
    assert result["status"] == "incomplete" and result["locations"][0]["path"] is None
    assert "/Users/example/private.md" not in json.dumps(result)
    edit(store, "UPDATE graph_binding SET repository_identity = 'repo1:foreign'")
    with pytest.raises(RepoMapMcpError, match="graph-database-graph-mismatch"):
        call(evidence_role="direct")


def test_direct_view_postgres_remains_unsupported_without_io(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "postgres-home"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    monkeypatch.setenv("REPOMAP_HOME", str(home))
    monkeypatch.delenv("REPOMAP_OPS_CONFIG", raising=False)
    with patched_guards(NO_FALLBACK_GUARDS):
        result = call(evidence_role="direct", graph_id="host-one")
    assert result["reason"] == "backend_unsupported" and result["locations"] == []
    assert result["evidence_role"] == "direct" and result["fallback"] == "native_search"


def test_existing_tool_advertises_one_optional_role_selector() -> None:
    from common_lore_index.server._mcp_locations import node_locations_tool_definition

    schema = node_locations_tool_definition()["inputSchema"]
    assert schema["required"] == ["graph_id", "canonical_key"]
    assert schema["properties"]["evidence_role"] == {
        "type": "string", "enum": ["all", "direct", "reference", "unknown"], "default": "all",
    }
