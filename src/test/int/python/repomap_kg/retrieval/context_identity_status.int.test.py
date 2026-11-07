"""Real SQLite/PostgreSQL source-identity status and publication-vector proofs."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
import sqlite3
from typing import Any

import psycopg

from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.server.context_read_sqlite import SqliteContextReadAdapter
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from repomap_test_support.context_assertions import build_postgres_context_fixture
from repomap_test_support.context_fixture import (
    BINDING_CORE,
    SNAP_CORE,
    build_sqlite_context_fixture,
)
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres


CANONICAL_KEY = "py:pkg.billing.InvoiceService"
EVIDENCE_KEY = "ev:1"


def _read_accepted(adapter: Any) -> Mapping[str, Any]:
    identity = adapter.read_initial_identity(WorkLedger(backend=adapter.backend))
    assert identity["status"] == "ok"
    accepted = identity.get("accepted_publication")
    assert isinstance(accepted, Mapping)
    return accepted


def _assert_status(
    adapter: Any,
    accepted: Mapping[str, Any],
    expected_status: str,
    *,
    expected_revision: int,
    expected_binding_id: str = BINDING_CORE,
    expected_snapshot_id: str = SNAP_CORE,
) -> None:
    query = NavigationSearchQuery(query="InvoiceService", limit=10)
    navigation = adapter.query_candidates_unit(
        query,
        ledger=WorkLedger(backend=adapter.backend),
        expected_identity=accepted,
    )
    assert navigation["status"] == "ok"
    nav_node = next(node for node in navigation["nodes"] if node["canonical_key"] == CANONICAL_KEY)
    assert len(nav_node["locations"]) == 1
    nav_location = nav_node["locations"][0]

    node_result = adapter.query_node_by_canonical_key(
        CANONICAL_KEY,
        ledger=WorkLedger(backend=adapter.backend),
        expected_identity=accepted,
    )
    assert node_result["status"] == "ok"
    node = node_result["node"]
    assert node is not None and len(node["locations"]) == 1
    node_location = node["locations"][0]

    for location in (nav_location, node_location):
        assert location["source_identity_status"] == expected_status
        assert location["source"]["binding_id"] == expected_binding_id
        assert location["source"]["binding_revision"] == expected_revision
        assert location["source"]["snapshot_id"] == expected_snapshot_id


def _reset_metadata(metadata: dict[str, Any]) -> None:
    metadata["binding_id"] = BINDING_CORE
    metadata["binding_revision"] = 1
    metadata["snapshot_id"] = SNAP_CORE


def _missing_revision(metadata: dict[str, Any]) -> None:
    _reset_metadata(metadata)
    metadata.pop("binding_revision")


def _wrong_revision(metadata: dict[str, Any]) -> None:
    _reset_metadata(metadata)
    metadata["binding_revision"] = 2


def _wrong_snapshot(metadata: dict[str, Any]) -> None:
    _reset_metadata(metadata)
    metadata["snapshot_id"] = "snap1:wrong"


def _foreign_binding(metadata: dict[str, Any]) -> None:
    _reset_metadata(metadata)
    metadata["binding_id"] = "bind1:foreign"


def _mutate_sqlite_metadata(
    db_path: Path, update: Callable[[dict[str, Any]], None],
) -> None:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT metadata_json FROM canonical_evidence WHERE evidence_key = ?",
            (EVIDENCE_KEY,),
        ).fetchone()
        assert row is not None
        metadata = json.loads(str(row[0]))
        assert isinstance(metadata, dict)
        update(metadata)
        connection.execute(
            "UPDATE canonical_evidence SET metadata_json = ? WHERE evidence_key = ?",
            (json.dumps(metadata, separators=(",", ":")), EVIDENCE_KEY),
        )


def _mutate_postgres_metadata(
    postgres: Any, update: Callable[[dict[str, Any]], None],
) -> None:
    with psycopg.connect(
        host=postgres.host,
        port=postgres.port,
        dbname=postgres.database,
        user=postgres.user,
        password=postgres.password,
    ) as connection:
        row = connection.execute(
            "SELECT metadata_json FROM canonical_evidence WHERE evidence_key = %s",
            (EVIDENCE_KEY,),
        ).fetchone()
        assert row is not None
        raw_metadata = row[0]
        metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else dict(raw_metadata)
        assert isinstance(metadata, dict)
        update(metadata)
        connection.execute(
            "UPDATE canonical_evidence SET metadata_json = %s::jsonb WHERE evidence_key = %s",
            (json.dumps(metadata, separators=(",", ":")), EVIDENCE_KEY),
        )


def test_sqlite_source_identity_status_tracks_vector_and_metadata_mutations(tmp_path: Path) -> None:
    db_path, _config, graph, binding, initial_adapter = build_sqlite_context_fixture(tmp_path)
    configured = initial_adapter.configured_bindings_by_id()

    def open_adapter() -> SqliteContextReadAdapter:
        return SqliteContextReadAdapter(
            graph_id=graph.id,
            db_path=db_path,
            binding=binding,
            configured_bindings=configured,
        )

    with initial_adapter:
        accepted = _read_accepted(initial_adapter)
        _assert_status(initial_adapter, accepted, "verified_vector", expected_revision=1)

    _mutate_sqlite_metadata(db_path, _missing_revision)
    with open_adapter() as adapter:
        accepted = _read_accepted(adapter)
        _assert_status(adapter, accepted, "verified_vector", expected_revision=1)

    _mutate_sqlite_metadata(db_path, _wrong_revision)
    with open_adapter() as adapter:
        accepted = _read_accepted(adapter)
        _assert_status(adapter, accepted, "unbound_or_conflicting_vector", expected_revision=2)

    _mutate_sqlite_metadata(db_path, _wrong_snapshot)
    with open_adapter() as adapter:
        accepted = _read_accepted(adapter)
        _assert_status(
            adapter,
            accepted,
            "unbound_or_conflicting_vector",
            expected_revision=1,
            expected_snapshot_id="snap1:wrong",
        )

    _mutate_sqlite_metadata(db_path, _foreign_binding)
    with open_adapter() as adapter:
        accepted = _read_accepted(adapter)
        _assert_status(
            adapter,
            accepted,
            "unbound_or_conflicting_vector",
            expected_revision=1,
            expected_binding_id="bind1:foreign",
        )


def test_postgres_source_identity_status_tracks_vector_and_metadata_mutations(tmp_path: Path) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _home, adapter = build_postgres_context_fixture(tmp_path, postgres)
        with adapter:
            accepted = _read_accepted(adapter)
            _assert_status(adapter, accepted, "verified_vector", expected_revision=1)

        _mutate_postgres_metadata(postgres, _missing_revision)
        with adapter:
            accepted = _read_accepted(adapter)
            _assert_status(adapter, accepted, "verified_vector", expected_revision=1)

        _mutate_postgres_metadata(postgres, _wrong_revision)
        with adapter:
            accepted = _read_accepted(adapter)
            _assert_status(adapter, accepted, "unbound_or_conflicting_vector", expected_revision=2)

        _mutate_postgres_metadata(postgres, _wrong_snapshot)
        with adapter:
            accepted = _read_accepted(adapter)
            _assert_status(
                adapter,
                accepted,
                "unbound_or_conflicting_vector",
                expected_revision=1,
                expected_snapshot_id="snap1:wrong",
            )

        _mutate_postgres_metadata(postgres, _foreign_binding)
        with adapter:
            accepted = _read_accepted(adapter)
            _assert_status(
                adapter,
                accepted,
                "unbound_or_conflicting_vector",
                expected_revision=1,
                expected_binding_id="bind1:foreign",
            )
