"""Unit tests for W4 SQLite context_expansion_queries and SqliteContextReadAdapter."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.server.context_read_sqlite import SqliteContextReadAdapter
from common_lore_index.storage.sqlite_local.context_expansion_queries import (
    batch_neighbor_direct_locations,
    expand_seed_incident_edges,
    read_sqlite_context_publication,
)
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from repomap_test_support.context_fixture import build_sqlite_context_fixture


def test_read_sqlite_context_publication_full_identity(tmp_path: Path) -> None:
    db_path, _, graph, _, _ = build_sqlite_context_fixture(tmp_path)
    with sqlite3.connect(db_path) as conn:
        pub = read_sqlite_context_publication(conn)
        assert pub is not None
        assert pub.graph_id == graph.id
        assert pub.repository_id == f"repo1:{graph.id}"
        assert pub.generation == 1
        assert pub.run_id == 1
        assert pub.publication_job_id == "job-ctx-1"
        assert pub.publication_attempt == 1
        assert pub.snapshot_manifest_id.startswith("snapmanifest1:")
        assert pub.extraction_receipt_id.startswith("receipt1:")
        assert len(pub.snapshot_vector) == 2


def test_expand_seed_incident_edges_and_batch_neighbor_locations(tmp_path: Path) -> None:
    db_path, _, _, _, _ = build_sqlite_context_fixture(tmp_path)
    with sqlite3.connect(db_path) as conn:
        res = expand_seed_incident_edges(
            conn,
            seed_canonical_key="py:pkg.billing.InvoiceService",
            edge_kinds=("contains", "defines", "references", "links_to"),
            per_seed_limit=10,
        )
        assert not res["truncated"]
        assert len(res["edges"]) >= 3
        nbr_ids: list[int] = []
        for e in res["edges"]:
            assert e["edge_key"].startswith("sha256:")
            nbr_ids.append(int(e["neighbor_id"]))

        # Truncation when per_seed_limit=1
        res_lim = expand_seed_incident_edges(
            conn,
            seed_canonical_key="py:pkg.billing.InvoiceService",
            edge_kinds=("contains", "defines", "references", "links_to"),
            per_seed_limit=1,
        )
        assert res_lim["truncated"]
        assert len(res_lim["edges"]) == 1
        kinds = ("contains", "defines", "links_to", "references")
        lexical = expand_seed_incident_edges(conn, seed_canonical_key="py:pkg.billing.InvoiceService", edge_kinds=kinds, per_seed_limit=1)
        reverse = expand_seed_incident_edges(conn, seed_canonical_key="py:pkg.billing.InvoiceService", edge_kinds=tuple(reversed(kinds)), per_seed_limit=1)
        assert reverse == lexical
        assert lexical["edges"][0]["edge_kind"] == "contains"

        # Single batched SQL query for neighbor direct locations
        nbr_map = batch_neighbor_direct_locations(
            conn, neighbor_ids=nbr_ids, accepted_run_id=1
        )
        assert not nbr_map["incomplete"]
        for nid in nbr_ids:
            assert len(nbr_map["locations_by_node_id"][nid]) >= 1


def test_sqlite_adapter_progress_handler_interrupt_discards_partial_statement(
    tmp_path: Path,
) -> None:
    _, _, _, _, adapter = build_sqlite_context_fixture(tmp_path)
    ledger = WorkLedger(
        backend="sqlite",
        sqlite_progress_callback_limit=0,
        sqlite_progress_interval_ops=1,
    )
    res = adapter.expand_seeds_depth1(
        ("py:pkg.billing.InvoiceService",),
        edge_kinds=("contains", "defines", "references"),
        node_limit=8,
        edge_limit=16,
        ledger=ledger,
        expected_identity={"accepted_run_id": 1},
    )
    assert res["status"] == "partial"
    assert res["reason"] == "work_budget_exhausted"
    assert res["neighbor_units"] == []

    # Missing accepted_run_id in expected_identity refuses to fabricate run_id=1
    res_unver = adapter.expand_seeds_depth1(
        ("py:pkg.billing.InvoiceService",),
        edge_kinds=("contains", "defines", "references"),
        node_limit=8,
        edge_limit=16,
        ledger=WorkLedger(backend="sqlite"),
        expected_identity={},
    )
    assert res_unver["status"] == "partial"
    assert res_unver["reason"] == "accepted_publication_unverified"
    assert res_unver["neighbor_units"] == []


def test_owned_adapter_requires_binding_before_opening_store(tmp_path: Path) -> None:
    db_path, _, graph, _, adapter = build_sqlite_context_fixture(tmp_path)
    adapter.close()
    missing_binding = SqliteContextReadAdapter(graph_id=graph.id, db_path=db_path)
    try:
        result = missing_binding.read_initial_identity(WorkLedger(backend="sqlite"))
    finally:
        missing_binding.close()
    assert result == {"status": "unavailable", "reason": "database_unavailable"}


def test_ordinary_sqlite_errors_are_unavailable_not_exhausted() -> None:
    connection = sqlite3.connect(":memory:")
    adapter = SqliteContextReadAdapter(graph_id="graph-test", connection=connection)
    try:
        result = adapter.query_candidates_unit(
            NavigationSearchQuery(query="InvoiceService"),
            ledger=WorkLedger(backend="sqlite"),
            expected_identity={},
        )
    finally:
        adapter.close()
        connection.close()
    assert result == {"status": "unavailable", "reason": "database_unavailable"}
