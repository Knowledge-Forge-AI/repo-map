"""Integration tests for PostgreSQL compact-context identity verification, fallbacks, and SQLite parity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg
import pytest

from common_lore_index.retrieval.context_assembly import (
    build_compact_context,
    select_context_sources,
)
from common_lore_index.retrieval.context_contracts import ContextRequest
from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.server.context_read_postgres import PostgresContextReadAdapter
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.node_locations import NodeLocationsQuery
from common_lore_index.storage.postgres_navigation_search import (
    read_postgres_navigation_search_with_executor,
)
from common_lore_index.storage.postgres_node_locations import (
    read_postgres_node_locations_with_executor,
)
from common_lore_index.storage.readback_driver import execute_json_readback
from repomap_test_support.context_assertions import (
    assert_valid_context_packet,
    build_postgres_context_fixture,
)
from repomap_test_support.context_fixture import (
    BINDING_CORE,
    BINDING_DOCS,
    CTX_GRAPH_ID,
    SNAP_DOCS,
    build_sqlite_context_fixture,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _advance_postgres_publication(postgres: Any, graph_id: str = CTX_GRAPH_ID) -> None:
    """Insert a second complete run for repo1:<graph_id> in PostgreSQL."""
    fams = {
        k: {"count": 1, "byte_length": 1, "digest": "sha256:" + "0" * 64}
        for k in (
            "files", "raw_observations", "canonical_nodes", "canonical_edges",
            "canonical_evidence", "canonical_node_evidence", "canonical_edge_evidence",
        )
    }
    vec = [[BINDING_CORE, 2, "snap1:" + "9" * 64], [BINDING_DOCS, 1, SNAP_DOCS]]
    with psycopg.connect(
        host=postgres.host, port=postgres.port, dbname=postgres.database,
        user=postgres.user, password=postgres.password,
    ) as conn:
        row = conn.execute(
            "SELECT id FROM repositories WHERE repository_identity = %s",
            (f"repo1:{graph_id}",),
        ).fetchone()
        assert row is not None
        repo_id = int(row[0])
        conn.execute(
            "INSERT INTO runs (repository_id, status, execution_route, portable_protocol_version, "
            "snapshot_manifest_id, snapshot_vector_json, extraction_receipt_id, publication_bundle_id, "
            "graph_candidate_id, resolver_identity, portable_canonicalizer_identity, "
            "semantic_contract_identity, quality_rule_identity, worker_capability_identity, "
            "portable_stage_id, portable_execution_mode, portable_singleton_fencing_epoch, "
            "portable_graph_lease_fencing_epoch, source_generation, config_generation, "
            "extractor_generation, canonicalizer_generation, publication_job_id, publication_attempt, "
            "family_receipts_json) VALUES (%s, 'complete', 'portable-worker-v1', '1.0', %s, %s, %s, %s, "
            "%s, 'resolver1:nix-static-v2', 'canon1:graph-key-v1-binding-path', "
            "'semantic1:multi-source-v1', 'quality1:default', 'cap1:portable-python-worker-v1', "
            "'stage-ctx-2', 'direct', 0, 0, %s, %s, %s, %s, 'job-ctx-2', 1, %s)",
            (
                repo_id, "snapmanifest1:" + "e5" * 32, json.dumps(vec, separators=(",", ":")),
                "receipt1:" + "f6" * 32, "bundle1:" + "a7" * 32, "cand1:" + "b8" * 32,
                "sg1:" + "55" * 32, "cg1:" + "66" * 32, "eg1:" + "77" * 32, "kg1:" + "88" * 32,
                json.dumps(fams, separators=(",", ":")),
            ),
        )


def test_postgres_seed_ranking_parity_with_sqlite_and_wire_non_regression(
    tmp_path: Path,
) -> None:
    """Verify PostgreSQL seed ranking and locations match SQLite Local and preserve legacy wire shapes."""
    require_postgres_binaries()
    _sq_path, _cfg, _graph, _binding, sq_adapter = build_sqlite_context_fixture(
        tmp_path / "sqlite"
    )
    with temporary_postgres() as postgres:
        _pg_home, pg_adapter = build_postgres_context_fixture(
            tmp_path / "postgres", postgres
        )
        for intent in ("definition", "implementation", "tests", "docs", "messages"):
            req = ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="ranked_discovery",
                query="InvoiceService",
                intent=intent,
                bindings=(BINDING_CORE, BINDING_DOCS),
                budget_bytes=16384,
            )
            with sq_adapter:
                sq_pkt = build_compact_context(req, sq_adapter)
            with pg_adapter:
                pg_pkt = build_compact_context(req, pg_adapter)
            assert_valid_context_packet(sq_pkt)
            assert_valid_context_packet(pg_pkt)
            assert pg_pkt["consistency_mode"] == "per_statement_identity_checked"
            assert pg_pkt["work_ledger"]["sqlite_progress_callbacks"] is None
            assert pg_pkt["work_ledger"]["sqlite_progress_interval_ops"] is None
            assert pg_pkt["work_ledger"]["sqlite_vm_steps_estimate"] is None
            assert pg_pkt["work_ledger"]["sql_statements_executed"] <= 12
            assert [it["canonical_key"] for it in pg_pkt["items"]] == [
                it["canonical_key"] for it in sq_pkt["items"]
            ]
            assert [it["rank_reasons"] for it in pg_pkt["items"]] == [
                it["rank_reasons"] for it in sq_pkt["items"]
            ]

        # Verify default PostgreSQL navigation_search and node_locations keep legacy serialized payload shapes
        from common_lore_index.storage.postgres_node_locations import (
            build_postgres_node_locations_sql,
        )

        default_loc_sql = build_postgres_node_locations_sql(
            NodeLocationsQuery(
                canonical_key="py:pkg.billing.InvoiceService",
                evidence_role="direct",
                limit=10,
            ),
            repository_identity=f"repo1:{CTX_GRAPH_ID}",
            root_path=f"graph:{CTX_GRAPH_ID}",
            context_identity=False,
        )
        assert "display_name" not in default_loc_sql

        nav = read_postgres_navigation_search_with_executor(
            NavigationSearchQuery(query="InvoiceService", limit=10),
            executor=lambda sql: execute_json_readback(
                sql,
                psql_args=postgres.psql_args,
                psql_command=postgres.psql_command,
                label="legacy nav",
                expected_shape="object",
                password=postgres.password,
            ),
            root_path=f"graph:{CTX_GRAPH_ID}",
            repository_identity=f"repo1:{CTX_GRAPH_ID}",
        )
        assert nav["status"] == "ok"
        assert set(nav.keys()) == {"status", "reason", "nodes", "accepted_publication", "scan"}
        assert set(nav["accepted_publication"].keys()) == {
            "generation",
            "run_id",
            "publication_bundle_id",
        }
        loc_ok = read_postgres_node_locations_with_executor(
            NodeLocationsQuery(
                canonical_key="py:pkg.billing.InvoiceService",
                evidence_role="direct",
                limit=10,
            ),
            executor=lambda sql: execute_json_readback(
                sql,
                psql_args=postgres.psql_args,
                psql_command=postgres.psql_command,
                label="legacy loc ok",
                expected_shape="object",
                password=postgres.password,
            ),
            root_path=f"graph:{CTX_GRAPH_ID}",
            repository_identity=f"repo1:{CTX_GRAPH_ID}",
        )
        assert set(loc_ok.keys()) == {
            "status",
            "reason",
            "locations",
            "historical_locations",
            "historical_has_more",
            "location_run_id",
            "location_scope",
            "metadata_location",
            "has_more",
            "node_first_seen_run_id",
            "node_last_seen_run_id",
            "accepted_publication",
        }
        assert set(loc_ok["accepted_publication"].keys()) == {
            "generation",
            "run_id",
            "publication_bundle_id",
        }
        loc = read_postgres_node_locations_with_executor(
            NodeLocationsQuery(
                canonical_key="bats.test_case:tests/cli.bats#invokes%20InvoiceService",
                evidence_role="direct",
                limit=10,
            ),
            executor=lambda sql: execute_json_readback(
                sql,
                psql_args=postgres.psql_args,
                psql_command=postgres.psql_command,
                label="legacy loc",
                expected_shape="object",
                password=postgres.password,
            ),
            root_path=f"graph:{CTX_GRAPH_ID}",
            repository_identity=f"repo1:{CTX_GRAPH_ID}",
        )
        assert loc["locations"] == []


def test_postgres_mid_assembly_drift_and_same_db_second_repository_isolation(
    tmp_path: Path,
) -> None:
    """Verify PostgreSQL detects mid-assembly publication drift and isolates same-DB repositories."""
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _pg_home, pg_adapter = build_postgres_context_fixture(
            tmp_path / "pg1", postgres, graph_id=CTX_GRAPH_ID
        )
        # Seed a second repository in the same PostgreSQL database
        _pg_home2, pg_adapter2 = build_postgres_context_fixture(
            tmp_path / "pg2", postgres, graph_id="second-repo", apply_schema=False
        )
        sel_other = tmp_path / "other_sel.json"
        select_context_sources(
            port=pg_adapter2,
            bindings=tuple(pg_adapter2.configured_bindings_by_id().keys())[:1],
            path_prefixes={},
            pin_publication=True,
            output_path=sel_other,
        )
        # Using second-repo selection against polyglot-ctx must fail with selection_graph_mismatch
        mismatch_pkt = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="ranked_discovery",
                query="InvoiceService",
                selection_path=sel_other,
            ),
            pg_adapter,
        )
        assert_valid_context_packet(mismatch_pkt)
        assert mismatch_pkt["status"] == "refused"
        assert mismatch_pkt["reason"] == "selection_graph_mismatch"
        assert mismatch_pkt["items"] == []

        # Mid-assembly publication drift across scan units
        advanced = False

        class _DriftingPostgresAdapter(PostgresContextReadAdapter):
            def query_candidates_unit(
                self,
                query: NavigationSearchQuery,
                *,
                ledger: WorkLedger,
                expected_identity: Any,
            ) -> dict[str, Any]:
                nonlocal advanced
                res = super().query_candidates_unit(
                    query, ledger=ledger, expected_identity=expected_identity
                )
                if not advanced:
                    advanced = True
                    _advance_postgres_publication(postgres, CTX_GRAPH_ID)
                return res

        drift_adapter = _DriftingPostgresAdapter(
            graph_id=CTX_GRAPH_ID,
            repository_id=f"repo1:{CTX_GRAPH_ID}",
            root_path=f"graph:{CTX_GRAPH_ID}",
            psql_args=postgres.psql_args,
            psql_command=postgres.psql_command,
            password=postgres.password,
            configured_bindings=pg_adapter.configured_bindings_by_id(),
        )
        drift_pkt = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="ranked_discovery",
                query="InvoiceService",
                intent="definition",
                bindings=(BINDING_CORE, BINDING_DOCS),
            ),
            drift_adapter,
        )
        assert_valid_context_packet(drift_pkt)
        assert drift_pkt["status"] == "stale"
        assert drift_pkt["reason"] == "publication_advanced_during_assembly"
        assert drift_pkt["items"] == []


def test_postgres_fallbacks_expansion_policy_and_missing_job_provenance(
    tmp_path: Path,
) -> None:
    """Verify built-in PostgreSQL graph expansion and missing job_id refusal."""
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _pg_home, pg_adapter = build_postgres_context_fixture(
            tmp_path / "pg", postgres
        )
        # Built-in PostgreSQL now expands graph_investigation natively.
        native_graph = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="graph_investigation",
                canonical_key="py:pkg.billing.InvoiceService",
            ),
            pg_adapter,
        )
        assert_valid_context_packet(native_graph)
        assert native_graph["status"] in {"complete", "partial"}
        assert native_graph["effective_mode"] == "graph_investigation"
        assert native_graph["fallback"] is None
        assert native_graph["expansion"]["reason"] != "backend_unsupported"

        # A fallback request does not override a capable built-in port.
        capable_with_fallback = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="graph_investigation",
                canonical_key="py:pkg.billing.InvoiceService",
                fallback_to="exact_identity",
            ),
            pg_adapter,
        )
        assert_valid_context_packet(capable_with_fallback)
        assert capable_with_fallback["status"] in {"complete", "partial"}
        assert capable_with_fallback["effective_mode"] == "graph_investigation"
        assert capable_with_fallback["fallback"] is None
        assert capable_with_fallback["expansion"]["reason"] != "backend_unsupported"
        assert len(capable_with_fallback["items"]) == 1

        # Explicit depth 1 remains native even when fallback_to is supplied.
        native_depth_one = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="graph_investigation",
                canonical_key="py:pkg.billing.InvoiceService",
                fallback_to="exact_identity",
                expand_depth=1,
            ),
            pg_adapter,
        )
        assert_valid_context_packet(native_depth_one)
        assert native_depth_one["status"] in {"complete", "partial"}
        assert native_depth_one["effective_mode"] == "graph_investigation"
        assert native_depth_one["fallback"] is None
        assert native_depth_one["expansion"]["reason"] != "backend_unsupported"
        assert len(native_depth_one["items"]) == 1

        # Null out publication_job_id and publication_attempt in runs -> strong pinning must refuse
        with psycopg.connect(
            host=postgres.host, port=postgres.port, dbname=postgres.database,
            user=postgres.user, password=postgres.password,
        ) as conn:
            conn.execute(
                "UPDATE runs SET publication_job_id = NULL, publication_attempt = NULL, "
                "source_generation = NULL, config_generation = NULL, "
                "extractor_generation = NULL, canonicalizer_generation = NULL"
            )
        with pytest.raises(
            ValueError, match="accepted_publication_unverified|cannot pin publication"
        ):
            select_context_sources(
                port=pg_adapter,
                bindings=(BINDING_CORE,),
                path_prefixes={},
                pin_publication=True,
                output_path=tmp_path / "bad_pin.json",
            )
