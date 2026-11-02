"""Integration tests for SQLite Local compact-context publication consistency, expansion, and non-regression."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import sqlite3
from typing import Any

from common_lore_index.retrieval.context_assembly import (
    build_compact_context,
    select_context_sources,
)
from common_lore_index.retrieval.context_contracts import ContextRequest
from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.server.context_read_sqlite import SqliteContextReadAdapter
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.node_locations import NodeLocationsQuery
from common_lore_index.storage.sqlite_local.context_expansion_queries import expand_seed_incident_edges
from common_lore_index.storage.sqlite_local.navigation_queries import navigation_candidates
from common_lore_index.storage.sqlite_local.node_location_queries import node_locations
from repomap_test_support.context_assertions import assert_valid_context_packet
from repomap_test_support.context_fixture import (
    BINDING_CORE,
    BINDING_DOCS,
    CTX_GRAPH_ID,
    SNAP_CORE,
    SNAP_DOCS,
    build_sqlite_context_fixture,
)

def _advance_sqlite_publication(sqlite_path: Path) -> None:
    """Insert a second complete run and advance accepted_publication to generation 2."""
    new_vec = [[BINDING_CORE, 1, "snap1:" + "9" * 64], [BINDING_DOCS, 1, SNAP_DOCS]]
    conn = sqlite3.connect(sqlite_path)
    try:
        with conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT INTO runs (id, previous_run_id, status, started_at, finished_at, "
                "publisher, execution_route, portable_protocol_version, snapshot_manifest_id, "
                "snapshot_vector_json, extraction_receipt_id, publication_bundle_id, "
                "graph_candidate_id, resolver_identity, portable_canonicalizer_identity, "
                "semantic_contract_identity, quality_rule_identity, worker_capability_identity, "
                "portable_stage_id, portable_execution_mode, source_generation, config_generation, "
                "extractor_generation, canonicalizer_generation, publication_job_id, "
                "publication_attempt, family_receipts_json, privacy) VALUES ("
                "2, 1, 'complete', '2026-11-01T01:00:00Z', '2026-11-01T01:00:01Z', "
                "'sqlite-local-direct-v1', 'portable-worker-v1', '1.0', "
                "'snapmanifest1:' || replace(hex(zeroblob(32)), '00', 'e5'), ?, "
                "'receipt1:' || replace(hex(zeroblob(32)), '00', 'f6'), "
                "'bundle1:' || replace(hex(zeroblob(32)), '00', 'a7'), "
                "'cand1:' || replace(hex(zeroblob(32)), '00', 'b8'), "
                "'resolver1:nix-static-v2', 'canon1:graph-key-v1-binding-path', "
                "'semantic1:multi-source-v1', 'quality1:default', 'cap1:portable-python-worker-v1', "
                "'stage-ctx-2', 'direct', 'sg1:' || replace(hex(zeroblob(32)), '00', '55'), "
                "'cg1:' || replace(hex(zeroblob(32)), '00', '66'), "
                "'eg1:' || replace(hex(zeroblob(32)), '00', '77'), "
                "'kg1:' || replace(hex(zeroblob(32)), '00', '88'), 'job-ctx-2', 1, '{}', 'public')",
                (json.dumps(new_vec, separators=(",", ":")),),
            )
            conn.execute("UPDATE accepted_publication SET generation = 2, run_id = 2 WHERE singleton = 1")
            conn.execute(
                "INSERT INTO canonical_nodes VALUES (999, 1, 'py:pkg.billing.InvoiceServiceV2', "
                "'python.class', 'InvoiceServiceV2', '{}', 'high', 0, 2, 2)"
            )
            conn.execute(
                "INSERT INTO raw_observations VALUES (2, 1, 1, 'python.class', 'src-v2', "
                "'adr/0099.md', '{}', 'hash-v2')"
            )
            meta_v2 = json.dumps(
                {
                    "binding_id": BINDING_DOCS,
                    "binding_revision": 1,
                    "snapshot_id": SNAP_DOCS,
                    "source_relative_path": "adr/0099.md",
                },
                separators=(",", ":"),
            )
            conn.execute(
                "INSERT INTO canonical_evidence VALUES (999, 2, 1, 'ev:999', 1, 1, "
                "'python.class', 'src-v2', 'adr/0099.md', 1, 5, 'polyglot', '1.0', 'high', ?)",
                (meta_v2,),
            )
            conn.execute("INSERT INTO canonical_node_evidence VALUES (999, 999, 'observed')")
    finally:
        conn.close()


def test_sqlite_single_read_transaction_snapshot_consistency_during_concurrent_publish(
    tmp_path: Path,
) -> None:
    """Verify SQLite single_read_transaction sees a consistent snapshot when a writer advances publication."""
    sqlite_path, _cfg, _graph, _binding, adapter = build_sqlite_context_fixture(tmp_path)
    conn = sqlite3.connect(sqlite_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()

    published_mid_assembly = False
    seen_scan_generations: list[int] = []
    seen_scan_runs: list[int] = []

    class _ConcurrentPublishAdapter(SqliteContextReadAdapter):
        def query_candidates_unit(
            self,
            query: NavigationSearchQuery,
            *,
            ledger: WorkLedger,
            expected_identity: Any,
        ) -> dict[str, Any]:
            nonlocal published_mid_assembly
            res = super().query_candidates_unit(
                query, ledger=ledger, expected_identity=expected_identity
            )
            acc = res.get("accepted_publication") or {}
            seen_scan_generations.append(int(acc.get("generation", 0)))
            seen_scan_runs.append(int(acc.get("run_id", 0)))
            if not published_mid_assembly:
                published_mid_assembly = True
                _advance_sqlite_publication(sqlite_path)
            return res

    conc_adapter = _ConcurrentPublishAdapter(
        graph_id=CTX_GRAPH_ID,
        db_path=sqlite_path,
        binding=_binding,
        configured_bindings=adapter.configured_bindings_by_id(),
        private_markers=adapter.private_markers,
    )
    with conc_adapter:
        req = ContextRequest(
            graph_id=CTX_GRAPH_ID,
            mode="ranked_discovery",
            query="InvoiceService",
            intent="definition",
            bindings=(BINDING_CORE, BINDING_DOCS),
            path_prefixes={BINDING_CORE: ("src", "tests"), BINDING_DOCS: ("adr", "guides")},
            budget_bytes=16384,
        )
        pkt = build_compact_context(req, conc_adapter)
        assert published_mid_assembly is True
        assert seen_scan_generations == [1, 1, 1, 1]
        assert seen_scan_runs == [1, 1, 1, 1]
        assert_valid_context_packet(pkt)
        assert pkt["status"] in {"complete", "partial"}
        assert pkt["publication"]["generation"] == 1
        assert pkt["publication"]["accepted_run_id"] == 1
        assert "py:pkg.billing.InvoiceServiceV2" not in [
            it["canonical_key"] for it in pkt["items"]
        ]
        assert all(
            loc["run_id"] == 1 for it in pkt["items"] for loc in it["locations"]
        )


def test_sqlite_owned_adapter_escapes_paths_and_refuses_untrusted_stores(tmp_path: Path) -> None:
    db_path, _cfg, graph, binding, adapter = build_sqlite_context_fixture(tmp_path)
    adapter.close()
    special = tmp_path / "owned?mode=ro#fragment%literal.sqlite3"
    special.write_bytes(db_path.read_bytes())
    with sqlite3.connect(special) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    assert not (tmp_path / "owned").exists()
    with SqliteContextReadAdapter(graph_id=graph.id, db_path=special, binding=binding) as candidate:
        assert candidate.read_initial_identity(WorkLedger())["status"] == "ok"
    missing = tmp_path / "missing.sqlite3"
    with SqliteContextReadAdapter(graph_id=graph.id, db_path=missing, binding=binding) as candidate:
        assert candidate.read_initial_identity(WorkLedger()) == {
            "status": "unavailable", "reason": "database_unavailable"
        }

    drift = tmp_path / "drift.sqlite3"
    drift.write_bytes(db_path.read_bytes())
    with sqlite3.connect(drift) as conn:
        conn.execute("PRAGMA user_version = 999")
    non_wal = tmp_path / "non-wal.sqlite3"
    non_wal.write_bytes(db_path.read_bytes())
    with sqlite3.connect(non_wal) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
    mismatched = replace(binding, graph_id="graph-swapped")
    for path, expected in ((drift, binding), (non_wal, binding), (db_path, mismatched)):
        with SqliteContextReadAdapter(graph_id=graph.id, db_path=path, binding=expected) as candidate:
            result = candidate.read_initial_identity(WorkLedger())
        assert result == {"status": "unavailable", "reason": "accepted_publication_unverified"}


def test_sqlite_pinned_vs_unpinned_selection_after_publication_advances(tmp_path: Path) -> None:
    """Verify pinned selection turns stale after publication advances while unpinned follows new state."""
    sqlite_path, _cfg, _graph, _binding, adapter = build_sqlite_context_fixture(tmp_path)
    pinned_path = tmp_path / "pinned.json"
    unpinned_path = tmp_path / "unpinned.json"
    with adapter:
        select_context_sources(
            port=adapter,
            bindings=(BINDING_CORE,),
            path_prefixes={BINDING_CORE: ("src",)},
            pin_publication=True,
            output_path=pinned_path,
        )
        select_context_sources(
            port=adapter,
            bindings=(BINDING_CORE,),
            path_prefixes={BINDING_CORE: ("src",)},
            pin_publication=False,
            output_path=unpinned_path,
        )

    _advance_sqlite_publication(sqlite_path)
    adapter_v2 = SqliteContextReadAdapter(
        graph_id=CTX_GRAPH_ID,
        db_path=sqlite_path,
        binding=_binding,
        configured_bindings=adapter.configured_bindings_by_id(),
    )
    with adapter_v2:
        stale_pkt = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="ranked_discovery",
                query="InvoiceService",
                intent="definition",
                selection_path=pinned_path,
            ),
            adapter_v2,
        )
        assert_valid_context_packet(stale_pkt)
        assert stale_pkt["status"] == "stale"
        assert stale_pkt["reason"] == "selection_publication_advanced"
        assert stale_pkt["items"] == []

        fresh_pkt = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="ranked_discovery",
                query="InvoiceService",
                intent="definition",
                selection_path=unpinned_path,
            ),
            adapter_v2,
        )
        assert_valid_context_packet(fresh_pkt)
        assert fresh_pkt["publication"]["generation"] == 2
        assert fresh_pkt["publication"]["accepted_run_id"] == 2


def test_sqlite_expansion_progress_limit_and_statement_37_interception(tmp_path: Path) -> None:
    """Verify SQLite depth-1 expansion, progress callback limit, and statement 37 interception."""
    extra_subjs = [
        {
            "canonical_key": f"py:pkg.fanout.Node{i:03d}",
            "kind": "python.function",
            "display_name": f"Node{i:03d}",
            "raw_kind": "python.function",
            "binding_id": BINDING_CORE,
            "snapshot_id": SNAP_CORE,
            "path": "src/billing/invoice.py",
            "start_line": 1,
            "end_line": 2,
        }
        for i in range(40)
    ]
    extra_edges = [
        ("calls", "py:pkg.billing.InvoiceService", f"py:pkg.fanout.Node{i:03d}")
        for i in range(40)
    ]
    sqlite_path, _cfg, _graph, _binding, adapter = build_sqlite_context_fixture(
        tmp_path, extra_subjects=extra_subjs, extra_edges=extra_edges
    )
    with sqlite3.connect(sqlite_path) as conn:
        kinds = ("defines", "links_to", "references")
        lexical = expand_seed_incident_edges(conn, seed_canonical_key="py:pkg.billing.InvoiceService", edge_kinds=kinds, per_seed_limit=1)
        reverse = expand_seed_incident_edges(conn, seed_canonical_key="py:pkg.billing.InvoiceService", edge_kinds=tuple(reversed(kinds)), per_seed_limit=1)
        assert reverse == lexical
        assert lexical["edges"][0]["edge_kind"] == "defines"

    with adapter:
        pkt_cap = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="graph_investigation",
                canonical_key="py:pkg.billing.InvoiceService",
                intent="implementation",
                expand_depth=1,
                expand_seeds=1,
                node_limit=5,
                edge_limit=8,
            ),
            adapter,
        )
        assert_valid_context_packet(pkt_cap)
        assert pkt_cap["status"] == "partial"
        assert len(pkt_cap["neighbors"]) <= 5
        assert pkt_cap["omission_counts"]["expansion_node_limit"] > 0

    with adapter:
        pkt_prog = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="graph_investigation",
                canonical_key="py:pkg.billing.InvoiceService",
                intent="implementation",
                expand_depth=1,
            ),
            adapter,
            work_ledger=WorkLedger(
                backend="sqlite",
                sqlite_progress_callback_limit=1,
                sqlite_progress_interval_ops=1,
            ),
        )
        assert_valid_context_packet(pkt_prog)
        assert pkt_prog["status"] == "partial"
        assert pkt_prog["work_ledger"]["sqlite_progress_callbacks"] >= 1
        ident_res = adapter.read_initial_identity(WorkLedger(backend="sqlite"))
        exp_prog = adapter.expand_seeds_depth1(
            ("py:pkg.billing.InvoiceService",),
            edge_kinds=("imports", "calls", "defines", "contains", "tests", "documents", "configures"),
            node_limit=12,
            edge_limit=24,
            ledger=WorkLedger(
                backend="sqlite",
                sqlite_progress_callback_limit=1,
                sqlite_progress_interval_ops=1,
            ),
            expected_identity=ident_res["accepted_publication"],
        )
        assert exp_prog["status"] == "partial"

    # Statement-37 interception: 6 scan units x 2 locatable kinds (1 + 12*3 = 37 stmts, 13 logical units) -> intercepted at 36!
    with adapter:
        pkt_stmt = build_compact_context(
            ContextRequest(
                graph_id=CTX_GRAPH_ID,
                mode="ranked_discovery",
                query="InvoiceService",
                intent="implementation",
                kinds=("python.class", "python.function"),
                bindings=(BINDING_CORE, BINDING_DOCS),
                path_prefixes={
                    BINDING_CORE: ("src", "tests", "nix", "shared"),
                    BINDING_DOCS: ("adr", "skills"),
                },
                expand_depth=1,
                expand_seeds=5,
            ),
            adapter,
        )
        assert_valid_context_packet(pkt_stmt)
        assert pkt_stmt["status"] == "partial"
        assert pkt_stmt["work_ledger"]["sql_statements_executed"] == 36


def test_sqlite_default_navigation_and_node_locations_wire_non_regression(
    tmp_path: Path,
) -> None:
    """Verify default navigation_candidates and node_locations keep legacy serialized payload shapes."""
    sqlite_path, _cfg, _graph, _binding, _adapter = build_sqlite_context_fixture(tmp_path)
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        nav = navigation_candidates(
            conn,
            NavigationSearchQuery(query="InvoiceService", limit=10),
        )
        assert nav["status"] == "ok"
        assert set(nav.keys()) == {"status", "reason", "nodes", "accepted_publication", "scan"}
        assert set(nav["accepted_publication"].keys()) == {"generation", "run_id", "publication_bundle_id"}
        assert set(nav["scan"].keys()) == {"complete", "nodes", "evidence", "node_limit", "evidence_limit"}
        inv_node = next(n for n in nav["nodes"] if n["canonical_key"] == "py:pkg.billing.InvoiceService")
        assert set(inv_node.keys()) == {
            "canonical_key", "kind", "display_name", "first_seen_run_id", "last_seen_run_id", "locations",
        }
        assert set(inv_node["locations"][0].keys()) == {
            "basis", "evidence_key", "link_kind", "run_id", "publication_relation", "raw_observation",
            "path", "start_line", "end_line", "path_namespace", "extractor", "extractor_version",
            "confidence", "source", "publication", "evidence_role", "source_identity_status",
        }
        loc_ok = node_locations(
            conn,
            NodeLocationsQuery(canonical_key="py:pkg.billing.InvoiceService", evidence_role="direct", limit=10),
        )
        assert set(loc_ok.keys()) == {
            "status", "reason", "locations", "historical_locations", "historical_has_more",
            "location_run_id", "location_scope", "metadata_location", "has_more",
            "node_first_seen_run_id", "node_last_seen_run_id", "accepted_publication",
        }
        assert set(loc_ok["accepted_publication"].keys()) == {"generation", "run_id", "publication_bundle_id"}
        loc = node_locations(
            conn,
            NodeLocationsQuery(
                canonical_key="bats.test_case:tests/cli.bats#invokes%20InvoiceService",
                evidence_role="direct",
                limit=10,
            ),
        )
        # Under default MCP _EVIDENCE_ROLE_SQL, bats.test_case is not direct evidence
        assert loc["locations"] == []
    finally:
        conn.close()
