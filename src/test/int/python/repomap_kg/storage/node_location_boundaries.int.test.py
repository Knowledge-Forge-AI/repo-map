"""Guarded SQLite Local boundary contracts for node locations and multi-binding."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from repomap_kg.storage.node_locations import NodeLocationsQuery
from repomap_kg.storage.sqlite_local.connection import read_transaction
from repomap_kg.storage.sqlite_local.node_location_queries import node_locations
from repomap_test_support.node_location_fixtures import (
    DOC,
    GRAPH,
    SYMBOL,
    locator_home,
)
from repomap_test_support.sqlite_local_fixtures import local_binding
from repomap_test_support.sqlite_local_harness import LocalHarness, initialize, refusal, structured, tool


def test_node_locations_multi_binding_and_absent_relative_path(tmp_path: Path) -> None:
    home, database = locator_home(tmp_path)
    with sqlite3.connect(database) as connection:
        # Prepend non-matching bindings to snapshot_vector_json to exercise vector loop continuation:
        raw_vector = connection.execute("SELECT snapshot_vector_json FROM runs WHERE id=1").fetchone()[0]
        vector = json.loads(raw_vector)
        multi_vector = [
            ["bind-extra-001", 1, "snap-extra-001"],
            ["bind-extra-002", 2, "snap-extra-002"],
            *vector,
        ]
        connection.execute("UPDATE runs SET snapshot_vector_json = ? WHERE id=1", (json.dumps(multi_vector),))

        # Update one canonical_evidence record to omit source_relative_path:
        ev_id, raw_metadata = connection.execute(
            "SELECT e.id, e.metadata_json FROM canonical_evidence e "
            "JOIN canonical_node_evidence link ON link.canonical_evidence_id = e.id "
            "WHERE link.canonical_node_id = (SELECT id FROM canonical_nodes WHERE canonical_key = ?) "
            "LIMIT 1",
            (SYMBOL,),
        ).fetchone()
        meta_no_rel_path = json.loads(raw_metadata)
        meta_no_rel_path.pop("source_relative_path", None)
        meta_no_rel_path.pop("binding_revision", None)
        connection.execute(
            "UPDATE canonical_evidence SET metadata_json = ? WHERE id = ?",
            (json.dumps(meta_no_rel_path), ev_id),
        )

    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    args = {"graph_id": GRAPH, "canonical_key": SYMBOL, "limit": 5}
    requests = [
        initialize(),
        tool(2, "repomap_node_locations", {**args, "detail": "full"}),
        tool(3, "repomap_node_locations", {**args, "detail": "compact"}),
    ]
    responses = harness.mcp(home, requests)
    assert responses == harness.mcp(home, requests)

    full = structured(responses, 2)
    assert full["status"] == "located" and full["locations"]
    # At least one location has matching binding_revision resolved from the multi-binding vector:
    assert any("source_relative_path" not in row["source"]
               and row["source"].get("binding_revision") == vector[0][1]
               for row in full["locations"])

    compact = structured(responses, 3)
    assert compact["status"] == "located"
    assert compact["detail"] == "compact" and compact["schema_version"] == 1
    assert "bindings" in compact
    # Ensure compact location with absent source_relative_path does not emit that field:
    locs_without_rel = [row for row in compact["locations"] if "source_relative_path" not in row]
    assert len(locs_without_rel) >= 1

    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_node_locations_relative_path_sanitization_boundaries(tmp_path: Path) -> None:
    home, database = locator_home(tmp_path)
    # Mutate evidence path and source_relative_path to non-source-relative formats:
    with sqlite3.connect(database) as connection:
        invalid_meta = {
            "binding_id": "root",
            "binding_alias": "root",
            "snapshot_id": "snap-root",
            "source_relative_path": "docs/../escape.md",
        }
        connection.execute(
            "UPDATE canonical_evidence SET metadata_json = ?, path = '/etc/passwd' "
            "WHERE id = (SELECT min(id) FROM canonical_evidence)",
            (json.dumps(invalid_meta),),
        )

    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    requests = [
        initialize(),
        tool(2, "repomap_node_locations", {"graph_id": GRAPH, "canonical_key": DOC, "detail": "compact"}),
        tool(3, "repomap_node_locations", {"graph_id": GRAPH, "canonical_key": SYMBOL}),
    ]
    responses = harness.mcp(home, requests)
    assert responses == harness.mcp(home, requests)

    doc_compact = structured(responses, 2)
    # The escaped/absolute path is not admitted as a valid source relative path:
    assert "/etc/passwd" not in json.dumps(doc_compact)

    sym_full = structured(responses, 3)
    assert sym_full["status"] == "located"
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_node_locations_validation_and_refusal_boundaries(tmp_path: Path) -> None:
    home, database = locator_home(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    base_args = {"graph_id": GRAPH, "canonical_key": SYMBOL}

    invalid_options: list[tuple[dict[str, Any], str]] = [
        ({"canonical_key": ""}, "canonical_key must be a nonempty bounded node identity"),
        ({"canonical_key": "bad\x00key"}, "canonical_key must be a nonempty bounded node identity"),
        ({"canonical_key": "x" * 4097}, "canonical_key must be a nonempty bounded node identity"),
        ({"limit": 0}, "location limit must be between 1 and 100"),
        ({"limit": 101}, "location limit must be between 1 and 100"),
        ({"limit": True}, "location limit must be between 1 and 100"),
        ({"evidence_role": "unsupported"}, "evidence_role must be all, direct, reference, or unknown"),
        ({"detail": "invalid"}, "detail must be full or compact"),
    ]
    requests = [
        initialize(),
        *(tool(mid, "repomap_node_locations", {**base_args, **opts})
          for mid, (opts, _) in enumerate(invalid_options, 2)),
        tool(30, "repomap_node_locations", base_args),
    ]
    responses = harness.mcp(home, requests)
    for mid, (_, expected_msg) in enumerate(invalid_options, 2):
        assert expected_msg in refusal(responses, mid)

    valid = structured(responses, 30)
    assert valid["status"] == "located"
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_node_locations_publication_absent_refusal(tmp_path: Path) -> None:
    home, database = locator_home(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM accepted_publication")
        direct_result = node_locations(
            connection, NodeLocationsQuery(canonical_key=SYMBOL, limit=10, evidence_role="all")
        )
        assert direct_result["status"] == "unavailable"
        assert direct_result["reason"] == "publication_absent"

    harness = LocalHarness(tmp_path / "harness", block_psycopg=True)
    requests = [
        initialize(),
        tool(2, "repomap_node_locations", {"graph_id": GRAPH, "canonical_key": SYMBOL}),
    ]
    responses = harness.mcp(home, requests)
    mcp_result = structured(responses, 2)
    assert mcp_result["status"] == "unavailable"
    assert mcp_result["reason"] == "publication_absent"
    assert harness.forbidden_events() == [] and harness.shim_invocations() == ""


def test_persisted_node_without_evidence_has_no_invented_location(tmp_path: Path) -> None:
    _home, database = locator_home(tmp_path)
    with closing(sqlite3.connect(database, autocommit=True)) as writer:
        removed = writer.execute(
            "DELETE FROM canonical_node_evidence WHERE canonical_node_id = "
            "(SELECT id FROM canonical_nodes WHERE canonical_key = ?)", (SYMBOL,),
        ).rowcount
    assert removed > 0
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with read_transaction(database, local_binding(GRAPH)) as reader:
        result = node_locations(reader, NodeLocationsQuery(canonical_key=SYMBOL, evidence_role="all"))
    assert result["status"] == "ok" and result["accepted_publication"]["generation"] == 1
    assert result["locations"] == result["historical_locations"] == []
    assert result["location_run_id"] is None and result["location_scope"] == "unavailable"
    assert result["has_more"] is result["historical_has_more"] is False
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
