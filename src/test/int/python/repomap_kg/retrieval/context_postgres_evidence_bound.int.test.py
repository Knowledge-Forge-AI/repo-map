"""Persisted direct-evidence overflow at the Server expansion boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import psycopg
from psycopg.conninfo import make_conninfo

from common_lore_index.retrieval.context_assembly import build_compact_context
from common_lore_index.retrieval.context_contracts import ContextRequest
from common_lore_index.retrieval.context_work import (
    MAX_SQL_STATEMENTS_SQLITE, SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT,
)
from common_lore_index.storage.readback_driver import _psycopg_connection_params_from_psql_args
from repomap_test_support.context_assertions import assert_valid_context_packet, build_postgres_context_fixture
from repomap_test_support.context_fixture import BINDING_CORE, CTX_GRAPH_ID, SNAP_CORE, build_sqlite_context_fixture
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres

SEED = "py:pkg.billing.InvoiceService"
NEIGHBOR = "py:scanbound.Neighbor"
SOURCE_PATH = "src/billing/invoice.py"
SUBJECT = {
    "canonical_key": NEIGHBOR, "kind": "python.class", "display_name": "ScanBoundNeighbor",
    "raw_kind": "python.class", "binding_id": BINDING_CORE, "snapshot_id": SNAP_CORE,
    "path": SOURCE_PATH, "start_line": 1, "end_line": 2,
}
META = json.dumps({
    "binding_id": BINDING_CORE, "binding_revision": 1,
    "snapshot_id": SNAP_CORE, "source_relative_path": SOURCE_PATH,
}, separators=(",", ":"))
PAYLOAD_HASH = hashlib.sha256(b"{}").hexdigest()


def _populate_postgres(connection) -> None:
    row = connection.execute(
        "SELECT n.id, n.repository_id, n.last_seen_run_id FROM canonical_nodes n "
        "WHERE n.canonical_key = %s", (NEIGHBOR,),
    ).fetchone()
    assert row is not None
    node_id, repository_id, run_id = row
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO raw_observations (repository_id, run_id, ordinal, schema_version, kind, "
            "source_id, path, payload_json, payload_hash) VALUES (%s,%s,%s,1,'python.class',%s,%s,'{}',%s)",
            [(repository_id, run_id, ordinal, f"scanbound-{ordinal}", SOURCE_PATH, PAYLOAD_HASH)
             for ordinal in range(100000, 110000)],
        )
    connection.execute(
        "INSERT INTO canonical_evidence (repository_id, run_id, graph_key_version, raw_observation_id, "
        "evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id, path, "
        "start_line, end_line, extractor, extractor_version, confidence, metadata_json) "
        "SELECT repository_id, run_id, 1, id, 'ev:scanbound:' || ordinal, ordinal, 1, kind, source_id, "
        "path, 1, 2, 'polyglot', '1.0', 'extracted', %s::jsonb FROM raw_observations "
        "WHERE repository_id = %s AND run_id = %s AND ordinal BETWEEN 100000 AND 109999",
        (META, repository_id, run_id),
    )
    connection.execute(
        "INSERT INTO canonical_node_evidence (canonical_node_id, canonical_evidence_id, link_kind) "
        "SELECT %s, id, 'observed' FROM canonical_evidence WHERE repository_id = %s AND run_id = %s "
        "AND raw_observation_ordinal BETWEEN 100000 AND 109999", (node_id, repository_id, run_id),
    )
    assert connection.execute(
        "SELECT count(*) FROM canonical_node_evidence link JOIN canonical_evidence e "
        "ON e.id=link.canonical_evidence_id WHERE link.canonical_node_id=%s AND e.run_id=%s",
        (node_id, run_id),
    ).fetchone() == (10001,)


def _populate_sqlite(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT id FROM canonical_nodes WHERE canonical_key = ?", (NEIGHBOR,)).fetchone()
        assert row is not None
        node_id = row[0]
        connection.executemany(
            "INSERT INTO raw_observations (run_id, ordinal, schema_version, kind, source_id, path, "
            "payload_json, payload_hash) VALUES (1,?,1,'python.class',?,?,'{}',?)",
            [(ordinal, f"scanbound-{ordinal}", SOURCE_PATH, PAYLOAD_HASH) for ordinal in range(100000, 110000)],
        )
        connection.executemany(
            "INSERT INTO canonical_evidence (id, run_id, graph_key_version, evidence_key, raw_observation_ordinal, "
            "raw_schema_version, raw_kind, raw_source_id, path, start_line, end_line, extractor, "
            "extractor_version, confidence, metadata_json) VALUES (?,1,1,?,?,1,'python.class',?,?,1,2,'polyglot','1.0','extracted',?)",
            [(ordinal, f"ev:scanbound:{ordinal}", ordinal, f"scanbound-{ordinal}", SOURCE_PATH, META)
             for ordinal in range(100000, 110000)],
        )
        connection.executemany(
            "INSERT INTO canonical_node_evidence (canonical_node_id,canonical_evidence_id,link_kind) "
            "VALUES (?,?,'observed')", [(node_id, ordinal) for ordinal in range(100000, 110000)],
        )
        assert connection.execute(
            "SELECT count(*) FROM canonical_node_evidence WHERE canonical_node_id = ?", (node_id,),
        ).fetchone() == (10001,)


def test_postgres_evidence_limit_and_sqlite_vm_guard_preserve_bounds(tmp_path: Path) -> None:
    require_postgres_binaries()
    sqlite_path, _config, _graph, _binding, sqlite_adapter = build_sqlite_context_fixture(
        tmp_path / "sqlite", extra_subjects=(SUBJECT,), extra_edges=(("calls", SEED, NEIGHBOR),),
    )
    _populate_sqlite(sqlite_path)
    request = ContextRequest(
        graph_id=CTX_GRAPH_ID, mode="graph_investigation", canonical_key=SEED,
        expand_depth=1, expand_seeds=1, node_limit=8, edge_limit=8,
        edge_kinds=("calls",), locations_per_item=5, budget_bytes=65536,
    )
    with temporary_postgres() as postgres:
        _, postgres_adapter = build_postgres_context_fixture(
            tmp_path / "postgres", postgres, extra_subjects=(SUBJECT,), extra_edges=(("calls", SEED, NEIGHBOR),),
        )
        conninfo = make_conninfo(**_psycopg_connection_params_from_psql_args(postgres.psql_args))
        with psycopg.connect(conninfo) as connection:
            _populate_postgres(connection)
        with postgres_adapter:
            server = build_compact_context(request, postgres_adapter)
        with sqlite_adapter:
            local = build_compact_context(request, sqlite_adapter)
    for packet, statements in ((server, 12), (local, MAX_SQL_STATEMENTS_SQLITE)):
        assert_valid_context_packet(packet)
        assert packet["status"] == "partial"
        expected_reason = "evidence_scan_limit" if statements == 12 else "work_budget_exhausted"
        assert packet["expansion"]["reason"] == expected_reason
        assert packet["scope"]["scope_complete"] is False
        ledger = packet["work_ledger"]
        assert ledger["max_sql_statements"] == statements and ledger["sql_statements_executed"] <= statements
        assert ledger["max_logical_read_units"] == 16 and ledger["logical_read_units"] <= 16
        assert ledger["max_scan_units"] == 8 and ledger["scan_units_executed"] <= 8
        if statements != 12:
            # The unchanged SQLite VM ceiling stops this expensive evidence sort
            # before it can deliver rows. No partially sourced neighbor escapes.
            assert ledger["sqlite_progress_callbacks"] >= SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT
            assert ledger["evidence_rows_scanned"] < 10001
            assert packet["neighbors"] == [] and packet["relations"] == []
            continue
        assert packet["omission_counts"]["candidate_scan_incomplete"] == 1
        assert [item["canonical_key"] for item in packet["neighbors"]] == [NEIGHBOR]
        assert len(packet["relations"]) == 1
        assert ledger["evidence_rows_scanned"] == 10001
        locations = packet["neighbors"][0]["locations"]
        assert 1 <= len(locations) <= 5
        for location in locations:
            assert location["path_namespace"] == "source_relative"
            assert location["source_relative_path"] == SOURCE_PATH
            assert location["source_binding_id"] == BINDING_CORE and location["binding_revision"] == 1
            assert location["snapshot_id"] == SNAP_CORE
            assert location["evidence_link_kind"] == "observed"
            assert location["evidence_raw_kind"] == "python.class"
