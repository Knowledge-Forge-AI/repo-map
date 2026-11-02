"""Raw database publication metadata must fail closed before context normalization."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any

import psycopg
import pytest

from common_lore_index.retrieval.context_assembly import build_compact_context, select_context_sources
from common_lore_index.retrieval.context_contracts import ContextRequest, ContextRequestError
from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.server.context_read_sqlite import SqliteContextReadAdapter
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.node_locations import NodeLocationsQuery
from common_lore_index.storage.postgres_navigation_sql import PG_SCOPED_TRANSPORT_BYTE_CAP
from common_lore_index.storage.postgres_node_locations import read_postgres_node_locations_with_executor
from common_lore_index.storage.readback_driver import execute_json_readback
from repomap_test_support.context_assertions import build_postgres_context_fixture
from repomap_test_support.context_fixture import (
    BINDING_CORE, BINDING_DOCS, CTX_GRAPH_ID, SNAP_CORE, SNAP_DOCS,
    build_sqlite_context_fixture,
)
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres


def _valid_vector() -> list[list[Any]]:
    return [[BINDING_CORE, 1, SNAP_CORE], [BINDING_DOCS, 1, SNAP_DOCS]]


def _malformed_vectors() -> list[list[Any]]:
    vectors: list[list[Any]] = [
        [[BINDING_CORE, value, SNAP_CORE], [BINDING_DOCS, 1, SNAP_DOCS]]
        for value in (True, 1.0, 1.5, "1")
    ]
    vectors.extend([
        _valid_vector() + [[BINDING_CORE, 1, SNAP_CORE]],
        _valid_vector() + [["bind1:unselected"]],
        [[BINDING_CORE, 1, None], [BINDING_DOCS, 1, SNAP_DOCS]],
        [[BINDING_CORE, 1, SNAP_CORE], [BINDING_DOCS, 0, SNAP_DOCS]],
    ])
    return vectors


def _assert_unverified(adapter: Any) -> None:
    packet = build_compact_context(
        ContextRequest(graph_id=CTX_GRAPH_ID, query="InvoiceService"), adapter,
    )
    assert packet["status"] == "unavailable"
    assert packet["reason"] == "accepted_publication_unverified"
    assert packet["items"] == packet["neighbors"] == packet["relations"] == []
    with pytest.raises(ContextRequestError) as exc:
        select_context_sources(
            port=adapter, bindings=(BINDING_CORE,), path_prefixes={}, pin_publication=True,
        )
    assert exc.value.refusal_reason == "accepted_publication_unverified"


HISTORICAL_KEY = "py:pkg.billing.HistoricalOnly"


def _assert_historical_row_contract(adapter: Any, *, malformed: bool) -> None:
    identity_ledger = WorkLedger(backend=adapter.backend)
    initial = adapter.read_initial_identity(identity_ledger)
    assert initial["status"] == "ok"
    expected = initial["accepted_publication"]

    nav = adapter.query_candidates_unit(
        NavigationSearchQuery(query="HistoricalOnly", scope="all", limit=5),
        ledger=WorkLedger(backend=adapter.backend),
        expected_identity=expected,
    )
    node = adapter.query_node_by_canonical_key(
        HISTORICAL_KEY,
        ledger=WorkLedger(backend=adapter.backend),
        expected_identity=expected,
    )
    if malformed:
        assert nav == {"status": "unavailable", "reason": "accepted_publication_unverified"}
        assert node == {"status": "unavailable", "reason": "accepted_publication_unverified"}
    else:
        assert nav["status"] == "ok"
        assert nav["nodes"] and nav["nodes"][0]["locations"]
        assert node["status"] == "ok"
        assert node["node"] is not None and node["node"]["locations"]


def _seed_sqlite_historical_row(db_path: Path, vector: Any) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs ("
            "id, previous_run_id, status, started_at, finished_at, publisher, execution_route, "
            "portable_protocol_version, snapshot_manifest_id, snapshot_vector_json, "
            "extraction_receipt_id, publication_bundle_id, graph_candidate_id, resolver_identity, "
            "portable_canonicalizer_identity, semantic_contract_identity, quality_rule_identity, "
            "worker_capability_identity, portable_stage_id, portable_execution_mode, source_generation, "
            "config_generation, extractor_generation, canonicalizer_generation, publication_job_id, "
            "publication_attempt, family_receipts_json, privacy) "
            "SELECT ?, id, status, started_at, finished_at, publisher, execution_route, "
            "portable_protocol_version, snapshot_manifest_id, snapshot_vector_json, "
            "extraction_receipt_id, publication_bundle_id, graph_candidate_id, resolver_identity, "
            "portable_canonicalizer_identity, semantic_contract_identity, quality_rule_identity, "
            "worker_capability_identity, portable_stage_id, portable_execution_mode, source_generation, "
            "config_generation, extractor_generation, canonicalizer_generation, publication_job_id, "
            "publication_attempt, family_receipts_json, privacy FROM runs WHERE id = 1",
            (2,),
        )
        conn.execute("UPDATE runs SET snapshot_vector_json = ? WHERE id = 2", (json.dumps(vector),))
        conn.execute(
            "INSERT INTO canonical_nodes (id, graph_key_version, canonical_key, kind, display_name, "
            "metadata_json, confidence, conflict, first_seen_run_id, last_seen_run_id) "
            "VALUES (1000, 1, ?, 'python.class', 'HistoricalOnly', '{}', 'extracted', 0, 2, 2)",
            (HISTORICAL_KEY,),
        )
        conn.execute(
            "INSERT INTO raw_observations (run_id, ordinal, schema_version, kind, source_id, path, "
            "payload_json, payload_hash) VALUES (2, 1000, 1, 'python.class', 'src-historical', "
            "'src/billing/historical.py', '{}', 'hash-historical')",
        )
        metadata = json.dumps(
            {
                "binding_id": BINDING_CORE,
                "binding_revision": 1,
                "snapshot_id": SNAP_CORE,
                "source_relative_path": "src/billing/historical.py",
            },
            separators=(",", ":"),
        )
        conn.execute(
            "INSERT INTO canonical_evidence (id, run_id, graph_key_version, evidence_key, "
            "raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id, path, "
            "start_line, end_line, extractor, extractor_version, confidence, metadata_json) "
            "VALUES (1000, 2, 1, 'ev:historical', 1000, 1, 'python.class', 'src-historical', "
            "'src/billing/historical.py', 1, 2, 'polyglot', '1.0', 'extracted', ?)",
            (metadata,),
        )
        conn.execute(
            "INSERT INTO canonical_node_evidence (canonical_node_id, canonical_evidence_id, link_kind) "
            "VALUES (1000, 1000, 'observed')",
        )


def _seed_postgres_historical_row(connection: Any, vector: Any) -> None:
    run_row = connection.execute(
        "INSERT INTO runs (repository_id, status, execution_route, portable_protocol_version, "
        "snapshot_manifest_id, snapshot_vector_json, extraction_receipt_id, publication_bundle_id, "
        "graph_candidate_id, resolver_identity, portable_canonicalizer_identity, "
        "semantic_contract_identity, quality_rule_identity, worker_capability_identity, "
        "portable_stage_id, portable_execution_mode, portable_singleton_fencing_epoch, "
        "portable_graph_lease_fencing_epoch, source_generation, config_generation, "
        "extractor_generation, canonicalizer_generation, publication_job_id, publication_attempt, "
        "family_receipts_json) "
        "SELECT repository_id, 'failed', execution_route, portable_protocol_version, "
        "snapshot_manifest_id, %s, extraction_receipt_id, publication_bundle_id, graph_candidate_id, "
        "resolver_identity, portable_canonicalizer_identity, semantic_contract_identity, "
        "quality_rule_identity, worker_capability_identity, portable_stage_id, portable_execution_mode, "
        "portable_singleton_fencing_epoch, portable_graph_lease_fencing_epoch, source_generation, "
        "config_generation, extractor_generation, canonicalizer_generation, publication_job_id || '-historical', "
        "publication_attempt, family_receipts_json FROM runs WHERE id = 1 RETURNING id",
        (json.dumps(vector),),
    ).fetchone()
    assert run_row is not None
    run_id = int(run_row[0])
    repo_id = int(
        connection.execute("SELECT repository_id FROM runs WHERE id = %s", (run_id,)).fetchone()[0]
    )
    node_row = connection.execute(
        "INSERT INTO canonical_nodes (repository_id, graph_key_version, canonical_key, kind, "
        "display_name, metadata_json, confidence, conflict, first_seen_run_id, last_seen_run_id) "
        "VALUES (%s, 1, %s, 'python.class', 'HistoricalOnly', '{}'::jsonb, 'extracted', false, %s, %s) "
        "RETURNING id",
        (repo_id, HISTORICAL_KEY, run_id, run_id),
    ).fetchone()
    assert node_row is not None
    node_id = int(node_row[0])
    raw_row = connection.execute(
        "INSERT INTO raw_observations (repository_id, run_id, ordinal, schema_version, kind, "
        "source_id, path, payload_json, payload_hash) VALUES (%s, %s, 1000, 1, 'python.class', "
        "'src-historical', 'src/billing/historical.py', '{}'::jsonb, %s) RETURNING id",
        (repo_id, run_id, "a" * 64),
    ).fetchone()
    assert raw_row is not None
    metadata = {
        "binding_id": BINDING_CORE,
        "binding_revision": 1,
        "snapshot_id": SNAP_CORE,
        "source_relative_path": "src/billing/historical.py",
    }
    evidence_row = connection.execute(
        "INSERT INTO canonical_evidence (repository_id, run_id, graph_key_version, raw_observation_id, "
        "evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id, path, "
        "start_line, end_line, extractor, extractor_version, confidence, metadata_json) "
        "VALUES (%s, %s, 1, %s, 'ev:historical', 1000, 1, 'python.class', 'src-historical', "
        "'src/billing/historical.py', 1, 2, 'polyglot', '1.0', 'extracted', %s::jsonb) RETURNING id",
        (repo_id, run_id, int(raw_row[0]), json.dumps(metadata, separators=(",", ":"))),
    ).fetchone()
    assert evidence_row is not None
    connection.execute(
        "INSERT INTO canonical_node_evidence (canonical_node_id, canonical_evidence_id, link_kind) "
        "VALUES (%s, %s, 'observed')",
        (node_id, int(evidence_row[0])),
    )


def test_sqlite_context_rejects_bad_historical_vectors_before_ranked_and_node_paths(
    tmp_path: Path,
) -> None:
    db_path, _cfg, _graph, binding, original = build_sqlite_context_fixture(tmp_path)
    _seed_sqlite_historical_row(db_path, 1.5)
    with SqliteContextReadAdapter(
        graph_id=CTX_GRAPH_ID, db_path=db_path, binding=binding,
        configured_bindings=original.configured_bindings_by_id(),
    ) as adapter:
        _assert_historical_row_contract(adapter, malformed=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE runs SET snapshot_vector_json = ? WHERE id = 2", (json.dumps(_valid_vector()),))
    with SqliteContextReadAdapter(
        graph_id=CTX_GRAPH_ID, db_path=db_path, binding=binding,
        configured_bindings=original.configured_bindings_by_id(),
    ) as adapter:
        _assert_historical_row_contract(adapter, malformed=False)


def test_postgres_context_rejects_bad_historical_vectors_before_ranked_and_node_paths(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _home, adapter = build_postgres_context_fixture(tmp_path, postgres)
        with psycopg.connect(
            host=postgres.host, port=postgres.port, dbname=postgres.database,
            user=postgres.user, password=postgres.password,
        ) as conn:
            _seed_postgres_historical_row(conn, 1.5)
        _assert_historical_row_contract(adapter, malformed=True)
        with psycopg.connect(
            host=postgres.host, port=postgres.port, dbname=postgres.database,
            user=postgres.user, password=postgres.password,
        ) as conn:
            row = conn.execute(
                "SELECT max(id) FROM runs WHERE status = 'failed'"
            ).fetchone()
            assert row is not None and type(row[0]) is int
            run_id = row[0]
            conn.execute(
                "UPDATE runs SET snapshot_vector_json = %s WHERE id = %s",
                (json.dumps(_valid_vector()), run_id),
            )
        _assert_historical_row_contract(adapter, malformed=False)


def test_sqlite_rejects_malformed_raw_json_vectors_and_recovers_on_valid_metadata(
    tmp_path: Path,
) -> None:
    db_path, _cfg, _graph, _binding, original = build_sqlite_context_fixture(tmp_path)
    for vector in _malformed_vectors():
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE runs SET snapshot_vector_json = ?", (json.dumps(vector),))
        with SqliteContextReadAdapter(
            graph_id=CTX_GRAPH_ID, db_path=db_path,
            binding=_binding,
            configured_bindings=original.configured_bindings_by_id(),
        ) as adapter:
            _assert_unverified(adapter)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE runs SET snapshot_vector_json = ?", (json.dumps(_valid_vector()),))
    with original:
        record = select_context_sources(
            port=original, bindings=(BINDING_CORE,), path_prefixes={}, pin_publication=True,
        )
        assert record.bindings[0].snapshot_id == SNAP_CORE


def test_postgres_rejects_malformed_raw_json_vectors_without_normalization(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _home, adapter = build_postgres_context_fixture(tmp_path, postgres)
        for vector in _malformed_vectors():
            with psycopg.connect(
                host=postgres.host, port=postgres.port, dbname=postgres.database,
                user=postgres.user, password=postgres.password,
            ) as conn:
                conn.execute("UPDATE runs SET snapshot_vector_json = %s", (json.dumps(vector),))
            _assert_unverified(adapter)
        with psycopg.connect(
            host=postgres.host, port=postgres.port, dbname=postgres.database,
            user=postgres.user, password=postgres.password,
        ) as conn:
            conn.execute("UPDATE runs SET snapshot_vector_json = %s", (json.dumps(_valid_vector()),))
        record = select_context_sources(
            port=adapter, bindings=(BINDING_CORE,), path_prefixes={}, pin_publication=True,
        )
        assert record.bindings[0].snapshot_id == SNAP_CORE


def test_legacy_postgres_locations_ignore_unrequested_display_name_transport_cost(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        build_postgres_context_fixture(tmp_path, postgres)
        with psycopg.connect(
            host=postgres.host, port=postgres.port, dbname=postgres.database,
            user=postgres.user, password=postgres.password,
        ) as conn:
            conn.execute(
                "UPDATE canonical_nodes SET display_name = repeat('x', %s) "
                "WHERE canonical_key = 'py:pkg.billing.InvoiceService'",
                (PG_SCOPED_TRANSPORT_BYTE_CAP + 1,),
            )

        def read(sql: str) -> Any:
            return execute_json_readback(
                sql, psql_args=postgres.psql_args, psql_command=postgres.psql_command,
                password=postgres.password, expected_shape="object", label="controlled locations",
            )

        query = NodeLocationsQuery(
            canonical_key="py:pkg.billing.InvoiceService", evidence_role="direct", limit=10,
        )
        kwargs: dict[str, Any] = {"executor": read, "repository_identity": f"repo1:{CTX_GRAPH_ID}"}
        legacy = read_postgres_node_locations_with_executor(query, **kwargs)
        assert legacy["status"] == "ok"
        assert legacy["locations"]
        assert "node_display_name" not in legacy
        context = read_postgres_node_locations_with_executor(query, context_identity=True, **kwargs)
        assert context["status"] == "unavailable"
        assert context["reason"] == "admission_work_limit"
