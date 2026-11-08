"""Real PostgreSQL/SQLite depth-1 context expansion parity and boundary tests."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

import psycopg

from common_lore_index.retrieval.context_assembly import build_compact_context
from common_lore_index.retrieval.context_contracts import ContextRequest
from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.server.context_read_postgres import PostgresContextReadAdapter
from common_lore_index.storage.row_helpers import identity_metadata_hash
from repomap_test_support.context_assertions import (
    assert_valid_context_packet,
    build_postgres_context_fixture,
)
from repomap_test_support.context_fixture import (
    BINDING_CORE,
    CTX_GRAPH_ID,
    SNAP_CORE,
    build_sqlite_context_fixture,
)
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres


SEED = "py:pkg.billing.InvoiceService"
EMPTY_HASH = identity_metadata_hash({})


def _subject(key: str, display_name: str | None = None) -> dict[str, Any]:
    name = display_name or key.rsplit(":", 1)[-1]
    return {
        "canonical_key": key,
        "kind": "python.function",
        "display_name": name,
        "raw_kind": "python.function",
        "binding_id": BINDING_CORE,
        "snapshot_id": SNAP_CORE,
        "path": f"src/context/{name}.py",
        "start_line": 1,
        "end_line": 2,
    }


def _content(packet: Mapping[str, Any]) -> tuple[Any, ...]:
    def item_rows(key: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return tuple(
            sorted(
                (
                    str(item["canonical_key"]),
                    tuple(
                        sorted(
                            str(loc.get("source_relative_path", ""))
                            for loc in item.get("locations", ())
                        )
                    ),
                )
                for item in packet[key]
            )
        )

    relations = tuple(
        sorted(
            (
                str(rel["source_key"]),
                str(rel["edge_kind"]),
                str(rel["target_key"]),
                str(rel["support"]["explanation_ref"]["identity_metadata_hash"]),
            )
            for rel in packet["relations"]
        )
    )
    return item_rows("items"), item_rows("neighbors"), relations


def _request(**overrides: Any) -> ContextRequest:
    values: dict[str, Any] = {
        "graph_id": CTX_GRAPH_ID,
        "mode": "graph_investigation",
        "canonical_key": SEED,
        "expand_depth": 1,
        "expand_seeds": 1,
        "node_limit": 8,
        "edge_limit": 16,
        "budget_bytes": 65536,
        "locations_per_item": 1,
    }
    values.update(overrides)
    return ContextRequest(**values)


def test_postgres_sqlite_expansion_preserves_empty_hash_relations_and_self_loop(
    tmp_path: Path,
) -> None:
    """Distinct four-tuples sharing SHA256({}) survive, including a two-window self-loop."""
    require_postgres_binaries()
    extra_edges = (("links_to", SEED, SEED),)
    _, _, _, _, sqlite_adapter = build_sqlite_context_fixture(
        tmp_path / "sqlite", extra_edges=extra_edges,
    )
    with temporary_postgres() as postgres:
        _, postgres_adapter = build_postgres_context_fixture(
            tmp_path / "postgres", postgres, extra_edges=extra_edges,
        )
        request = _request(edge_kinds=("contains", "links_to", "references"))
        with sqlite_adapter:
            sqlite_packet = build_compact_context(request, sqlite_adapter)
        with postgres_adapter:
            postgres_packet = build_compact_context(request, postgres_adapter)

    assert_valid_context_packet(sqlite_packet)
    assert_valid_context_packet(postgres_packet)
    assert _content(sqlite_packet) == _content(postgres_packet)
    relations = set(_content(postgres_packet)[2])
    assert relations == {
        (SEED, "contains", "py:pkg.billing.InvoiceService.compute_total", EMPTY_HASH),
        ("py:tests.test_invoice.test_invoice_service", "references", SEED, EMPTY_HASH),
        ("doc:adr/0010-billing-architecture", "links_to", SEED, EMPTY_HASH),
        ("doc:section/billing-guide#invoicing", "links_to", SEED, EMPTY_HASH),
        (SEED, "links_to", SEED, EMPTY_HASH),
    }
    assert sum(row[:3] == (SEED, "links_to", SEED) for row in relations) == 1


def _counter_rows() -> tuple[tuple[dict[str, Any], ...], tuple[tuple[str, str, str], ...]]:
    seed0, seed1 = "py:counter.Seed0", "py:counter.Seed1"
    subjects = tuple(_subject(key, name) for key, name in (
        (seed0, "CounterSeed0"), (seed1, "CounterSeed1"),
        ("py:counter.A", "CounterA"), ("py:counter.B", "CounterB"),
        ("py:counter.C", "CounterC"),
    ))
    edges = (
        ("calls", seed0, "py:counter.A"), ("calls", seed0, "py:counter.B"),
        ("calls", seed1, "py:counter.A"), ("calls", seed1, "py:counter.B"),
        ("calls", seed1, "py:counter.C"),
        ("contains", seed0, "py:counter.B"),
    )
    return subjects, edges


def test_postgres_sqlite_expansion_matches_greedy_global_neighbor_charge_and_kind_filter(
    tmp_path: Path,
) -> None:
    """Existing neighbors do not consume seed-1's node slots, and non-selected kinds stay out."""
    require_postgres_binaries()
    subjects, edges = _counter_rows()
    _, _, _, _, sqlite_adapter = build_sqlite_context_fixture(
        tmp_path / "sqlite", extra_subjects=subjects, extra_edges=edges,
    )
    with temporary_postgres() as postgres:
        _, postgres_adapter = build_postgres_context_fixture(
            tmp_path / "postgres", postgres,
            extra_subjects=subjects, extra_edges=edges,
        )
        request = _request(
            mode="ranked_discovery", canonical_key=None, query="CounterSeed",
            kinds=("python.function",), max_items=2, expand_seeds=2,
            node_limit=2, edge_limit=8, edge_kinds=("calls",),
        )
        with sqlite_adapter:
            sqlite_packet = build_compact_context(request, sqlite_adapter)
        with postgres_adapter:
            postgres_packet = build_compact_context(request, postgres_adapter)

    assert_valid_context_packet(sqlite_packet)
    assert_valid_context_packet(postgres_packet)
    assert _content(sqlite_packet) == _content(postgres_packet)
    neighbor_keys = {key for key, _ in _content(postgres_packet)[1]}
    assert neighbor_keys == {"py:counter.A", "py:counter.B", "py:counter.C"}
    assert all(row[1] == "calls" for row in _content(postgres_packet)[2])
    assert postgres_packet["expansion"]["seeds_expanded"] == 2


def _bulk_rows() -> tuple[tuple[dict[str, Any], ...], tuple[tuple[str, str, str], ...]]:
    seeds = tuple(f"py:bulk.Seed{index}" for index in range(5))
    neighbors = tuple(f"py:bulk.Neighbor{index:03d}" for index in range(140))
    subjects = tuple(
        [_subject(seed, f"BulkSeed{index}") for index, seed in enumerate(seeds)]
        + [
            _subject(neighbor, f"BulkNeighbor{index:03d}")
            for index, neighbor in enumerate(neighbors)
        ]
    )
    edges = tuple(
        ("calls", seed, neighbor) for seed in seeds for neighbor in neighbors
    ) + (("calls", seeds[0], seeds[0]),)
    return subjects, edges


def test_postgres_sqlite_expansion_five_seed_high_degree_caps_and_statement_bound(
    tmp_path: Path,
) -> None:
    """Five seeds exercise filters, 128 neighbors, 256 relations and one PG SQL."""
    require_postgres_binaries()
    subjects, edges = _bulk_rows()
    _, _, _, _, sqlite_adapter = build_sqlite_context_fixture(
        tmp_path / "sqlite", extra_subjects=subjects, extra_edges=edges,
    )
    with temporary_postgres() as postgres:
        _, postgres_adapter = build_postgres_context_fixture(
            tmp_path / "postgres", postgres,
            extra_subjects=subjects, extra_edges=edges,
        )
        request = _request(
            mode="ranked_discovery", canonical_key=None, query="BulkSeed",
            kinds=("python.function",), max_items=5, expand_seeds=5,
            node_limit=32, edge_limit=64, edge_kinds=("calls",),
        )
        with sqlite_adapter:
            sqlite_packet = build_compact_context(request, sqlite_adapter)
        with postgres_adapter:
            postgres_packet = build_compact_context(request, postgres_adapter)

    assert_valid_context_packet(sqlite_packet)
    assert_valid_context_packet(postgres_packet)
    assert _content(sqlite_packet) == _content(postgres_packet)
    assert postgres_packet["work_ledger"]["sql_statements_executed"] <= 12
    assert postgres_packet["work_ledger"]["logical_read_units"] <= 16
    assert postgres_packet["expansion"]["neighbors_admitted"] <= 128
    assert postgres_packet["expansion"]["relations_admitted"] <= 256
    assert postgres_packet["omission_counts"]["expansion_node_limit"] > 0
    assert postgres_packet["omission_counts"]["expansion_edge_limit"] > 0


def _latest_run_id(postgres: Any, repository_identity: str) -> int:
    with psycopg.connect(
        host=postgres.host, port=postgres.port, dbname=postgres.database,
        user=postgres.user, password=postgres.password,
    ) as conn:
        row = conn.execute(
            "SELECT id FROM runs WHERE repository_id = ("
            "SELECT id FROM repositories WHERE repository_identity = %s) "
            "ORDER BY id DESC LIMIT 1",
            (repository_identity,),
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_postgres_expansion_stale_cross_repository_absent_and_malformed_publication(
    tmp_path: Path,
) -> None:
    """Actual publication mutations map to stale, isolated, absent and malformed outcomes."""
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _, postgres_adapter = build_postgres_context_fixture(tmp_path / "primary", postgres)
        foreign_subject = (_subject("py:foreign.only", "ForeignOnly"),)
        build_postgres_context_fixture(
            tmp_path / "foreign", postgres, graph_id="foreign", apply_schema=False,
            extra_subjects=foreign_subject,
            extra_edges=(("calls", SEED, "py:foreign.only"),),
        )
        request = _request(edge_kinds=("calls",))
        with postgres_adapter:
            isolated = build_compact_context(request, postgres_adapter)
        assert_valid_context_packet(isolated)
        assert "py:foreign.only" not in {key for key, _ in _content(isolated)[1]}

        advanced = False

        class _MutatingAdapter(PostgresContextReadAdapter):
            def query_node_by_canonical_key(
                self, canonical_key: str, *, ledger: WorkLedger,
                expected_identity: Mapping[str, Any],
            ) -> dict[str, Any]:
                nonlocal advanced
                result = super().query_node_by_canonical_key(
                    canonical_key, ledger=ledger, expected_identity=expected_identity,
                )
                if not advanced:
                    run_id = _latest_run_id(postgres, f"repo1:{CTX_GRAPH_ID}")
                    with psycopg.connect(
                        host=postgres.host, port=postgres.port, dbname=postgres.database,
                        user=postgres.user, password=postgres.password,
                    ) as conn:
                        conn.execute(
                            "UPDATE runs SET publication_bundle_id = %s WHERE id = %s",
                            ("bundle1:" + "e5" * 32, run_id),
                        )
                    advanced = True
                return result

        drifting = _MutatingAdapter(
            graph_id=CTX_GRAPH_ID, repository_id=f"repo1:{CTX_GRAPH_ID}",
            root_path=f"graph:{CTX_GRAPH_ID}", psql_args=postgres.psql_args,
            psql_command=postgres.psql_command, password=postgres.password,
            configured_bindings=postgres_adapter.configured_bindings_by_id(),
        )
        stale = build_compact_context(_request(edge_kinds=("contains",)), drifting)
        assert_valid_context_packet(stale)
        assert stale["status"] == "stale"
        assert stale["items"] == [] and stale["neighbors"] == [] and stale["relations"] == []

        run_id = _latest_run_id(postgres, f"repo1:{CTX_GRAPH_ID}")
        with psycopg.connect(
            host=postgres.host, port=postgres.port, dbname=postgres.database,
            user=postgres.user, password=postgres.password,
        ) as conn:
            conn.execute("UPDATE runs SET status = 'failed' WHERE id = %s", (run_id,))
        absent = build_compact_context(_request(edge_kinds=("contains",)), postgres_adapter)
        assert_valid_context_packet(absent)
        assert absent["status"] == "unavailable"
        assert absent["reason"] == "publication_absent"
        with psycopg.connect(
            host=postgres.host, port=postgres.port, dbname=postgres.database,
            user=postgres.user, password=postgres.password,
        ) as conn:
            conn.execute("UPDATE runs SET status = 'complete' WHERE id = %s", (run_id,))
            conn.execute(
                "UPDATE runs SET snapshot_vector_json = %s::jsonb WHERE id = %s",
                (json.dumps({}), run_id),
            )
        malformed = build_compact_context(_request(edge_kinds=("contains",)), postgres_adapter)
        assert_valid_context_packet(malformed)
        assert malformed["status"] == "unavailable"
        assert malformed["reason"] == "accepted_publication_unverified"


def test_postgres_transport_overflow_returns_closed_empty_expansion(
    tmp_path: Path,
) -> None:
    """An oversized real location is withheld by the SQL envelope before packet admission."""
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _, postgres_adapter = build_postgres_context_fixture(tmp_path / "postgres", postgres)
        with psycopg.connect(
            host=postgres.host, port=postgres.port, dbname=postgres.database,
            user=postgres.user, password=postgres.password,
        ) as conn:
            row = conn.execute(
                "SELECT e.id FROM canonical_evidence e "
                "JOIN canonical_node_evidence link ON link.canonical_evidence_id = e.id "
                "JOIN canonical_nodes n ON n.id = link.canonical_node_id "
                "WHERE n.repository_id = (SELECT id FROM repositories "
                "WHERE repository_identity = %s) "
                "AND n.canonical_key = %s LIMIT 1",
                (f"repo1:{CTX_GRAPH_ID}", "py:pkg.billing.InvoiceService.compute_total"),
            ).fetchone()
            assert row is not None
            conn.execute(
                "UPDATE canonical_evidence SET metadata_json = "
                "jsonb_build_object('payload', repeat('x', 34000000)) WHERE id = %s",
                (int(row[0]),),
            )
        with postgres_adapter:
            packet = build_compact_context(
                _request(edge_kinds=("contains",)), postgres_adapter,
            )

    assert_valid_context_packet(packet)
    assert packet["status"] == "partial"
    assert packet["expansion"]["reason"] == "work_budget_exhausted"
    assert packet["neighbors"] == []
    assert packet["relations"] == []


def test_postgres_statement_cap_and_native_empty_node_are_closed_packets(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _, adapter = build_postgres_context_fixture(tmp_path / "postgres", postgres)
        with adapter:
            capped = build_compact_context(
                _request(edge_kinds=("contains",)), adapter,
                work_ledger=WorkLedger(backend="postgresql", max_sql_statements=2),
            )
            assert_valid_context_packet(capped)
            assert capped["status"] == "partial"
            assert capped["expansion"]["reason"] == "statement_limit"
            assert capped["expansion"]["seeds_expanded"] == 0
            assert capped["neighbors"] == [] and capped["relations"] == []
            empty = build_compact_context(
                _request(canonical_key="py:pkg.billing.DoesNotExist"), adapter,
            )
    assert_valid_context_packet(empty)
    assert empty["status"] == "complete"
    assert empty["effective_mode"] == "graph_investigation"
    assert empty["items"] == empty["neighbors"] == empty["relations"] == []
    assert empty["expansion"]["seeds_expanded"] == 0
    assert empty["expansion"]["reason"] is None
