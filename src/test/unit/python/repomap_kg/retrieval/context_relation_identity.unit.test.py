"""Regression tests for SQLite context relation identity (REPOMAP-CLOE-SERVER-PARITY1)."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.server.context_read_sqlite import SqliteContextReadAdapter
from common_lore_index.storage.row_helpers import identity_metadata_hash
from repomap_test_support.context_fixture import (
    DEFAULT_VECTOR,
    build_sqlite_context_fixture,
)


SEED = "py:pkg.billing.InvoiceService"
EMPTY_METADATA_HASH = identity_metadata_hash({})


def _relation_identity(edge: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(edge["source_canonical_key"]),
        str(edge["edge_kind"]),
        str(edge["target_canonical_key"]),
        str(edge["edge_key"]),
    )


def _result_relations(result: dict[str, Any]) -> list[dict[str, Any]]:
    return list(result["seed_to_seed_edges"]) + [
        edge
        for unit in result["neighbor_units"]
        for edge in unit["edges"]
    ]


def _shared_hash_fixture(tmp_path: Path) -> tuple[SqliteContextReadAdapter, str]:
    db_path, _, _, _, adapter = build_sqlite_context_fixture(tmp_path)
    shared_relations = (
        (SEED, "contains", "py:pkg.billing.InvoiceService.compute_total"),
        ("py:tests.test_invoice.test_invoice_service", "references", SEED),
        ("doc:adr/0010-billing-architecture", "links_to", SEED),
        ("doc:section/billing-guide#invoicing", "links_to", SEED),
    )
    with sqlite3.connect(db_path) as conn:
        for source_key, edge_kind, target_key in shared_relations:
            conn.execute(
                "UPDATE canonical_edges SET identity_metadata_json = '{}', "
                "identity_metadata_hash = ? WHERE graph_key_version = 1 "
                "AND source_canonical_key = ? AND edge_kind = ? "
                "AND target_canonical_key = ?",
                (EMPTY_METADATA_HASH, source_key, edge_kind, target_key),
            )
        next_edge_id = conn.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM canonical_edges"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO canonical_edges (id, graph_key_version, "
            "source_canonical_key, edge_kind, target_canonical_key, "
            "identity_metadata_json, identity_metadata_hash, metadata_json, "
            "confidence, conflict, first_seen_run_id, last_seen_run_id) "
            "VALUES (?, 1, ?, 'links_to', ?, '{}', ?, '{}', 'extracted', 0, 1, 1)",
            (next_edge_id, SEED, SEED, EMPTY_METADATA_HASH),
        )
    return adapter, EMPTY_METADATA_HASH


def _expand_shared_hash_fixture(
    tmp_path: Path,
) -> tuple[dict[str, Any], str]:
    adapter, empty_hash = _shared_hash_fixture(tmp_path)
    try:
        result = adapter.expand_seeds_depth1(
            (SEED,),
            edge_kinds=("contains", "links_to", "references"),
            node_limit=8,
            edge_limit=16,
            ledger=WorkLedger(backend="sqlite"),
            expected_identity={
                "accepted_run_id": 1,
                "snapshot_vector": DEFAULT_VECTOR,
            },
        )
    finally:
        adapter.close()
    return result, empty_hash


def test_sqlite_expansion_keeps_distinct_relations_with_shared_empty_metadata_hash(
    tmp_path: Path,
) -> None:
    result, empty_hash = _expand_shared_hash_fixture(tmp_path)

    assert result["status"] == "ok"
    assert len(empty_hash) == 64
    assert all(char in "0123456789abcdef" for char in empty_hash)
    expected = {
        (SEED, "contains", "py:pkg.billing.InvoiceService.compute_total", empty_hash),
        ("py:tests.test_invoice.test_invoice_service", "references", SEED, empty_hash),
        ("doc:adr/0010-billing-architecture", "links_to", SEED, empty_hash),
        ("doc:section/billing-guide#invoicing", "links_to", SEED, empty_hash),
        (SEED, "links_to", SEED, empty_hash),
    }
    actual = {
        _relation_identity(edge)
        for edge in _result_relations(result)
        if edge["edge_key"] == empty_hash
    }
    assert actual == expected


def test_sqlite_expansion_deduplicates_self_loop_seen_in_both_directions(
    tmp_path: Path,
) -> None:
    result, empty_hash = _expand_shared_hash_fixture(tmp_path)
    self_loop = (SEED, "links_to", SEED, empty_hash)

    matching = [
        _relation_identity(edge)
        for edge in _result_relations(result)
        if _relation_identity(edge) == self_loop
    ]
    assert matching == [self_loop]
