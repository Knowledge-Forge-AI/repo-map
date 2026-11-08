"""Unit tests for W4 context_assembly and context_admission (Epics A-C)."""

from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3

from common_lore_index.retrieval.context_assembly import build_compact_context
from common_lore_index.retrieval.context_contracts import ContextRequest
from common_lore_index.retrieval.context_work import WorkLedger
from repomap_test_support.context_assertions import (
    assert_valid_budget_error,
    assert_valid_context_packet,
)
from repomap_test_support.context_fixture import (
    BINDING_CORE,
    BINDING_DOCS,
    build_sqlite_context_fixture,
)
from common_lore_index.server.context_read_postgres import PostgresContextReadAdapter


def test_build_compact_context_modes_and_source_deletion_invariance(tmp_path: Path) -> None:
    _, _, _, _, adapter = build_sqlite_context_fixture(
        tmp_path, include_private_binding=True
    )
    req = ContextRequest(
        graph_id=adapter.graph_id,
        mode="ranked_discovery",
        query="InvoiceService",
        intent="definition",
        expand_depth=1,
        budget_bytes=16384,
    )
    pkt1 = build_compact_context(req, adapter)
    assert_valid_context_packet(pkt1, forbidden_substrings=adapter.private_markers)
    assert pkt1["status"] == "complete"
    assert pkt1["items"][0]["canonical_key"] == "py:pkg.billing.InvoiceService"
    assert len(pkt1["neighbors"]) >= 1
    assert len(pkt1["relations"]) >= 1
    assert pkt1["freshness"]["files_checked"] == 0

    # Delete source trees on disk: default freshness=none packet must be identical
    shutil.rmtree(tmp_path / "src_core")
    shutil.rmtree(tmp_path / "src_docs")
    pkt2 = build_compact_context(req, adapter)
    assert_valid_context_packet(pkt2, forbidden_substrings=adapter.private_markers)
    assert {k: v for k, v in pkt1.items() if k != "work_ledger"} == {
        k: v for k, v in pkt2.items() if k != "work_ledger"
    }
    # Metadata and deterministic work are invariant; measured VM work is per invocation.
    for packet in (pkt1, pkt2):
        work = packet["work_ledger"]
        assert 0 <= work["sqlite_progress_callbacks"] <= 250 * work["sql_statements_executed"]
        assert work["sqlite_vm_steps_estimate"] == work["sqlite_progress_callbacks"] * work["sqlite_progress_interval_ops"]
    before = {k: v for k, v in pkt1["work_ledger"].items() if k not in {"elapsed_ms", "actual_bytes", "sqlite_progress_callbacks", "sqlite_vm_steps_estimate"}}
    after = {k: v for k, v in pkt2["work_ledger"].items() if k not in {"elapsed_ms", "actual_bytes", "sqlite_progress_callbacks", "sqlite_vm_steps_estimate"}}
    assert before == after, {key: (value, after.get(key)) for key, value in before.items() if value != after.get(key)}


def test_unsupported_modes_and_postgresql_refusal_need_no_storage(tmp_path: Path) -> None:
    _, _, _, _, sq_adapter = build_sqlite_context_fixture(tmp_path)
    def unexpected_sql(_sql: str):
        raise AssertionError("unsupported mode must not read storage")

    pg_adapter = PostgresContextReadAdapter(graph_id=sq_adapter.graph_id, executor=unexpected_sql)
    pg_adapter.supports_depth1_expansion = False

    for unadmitted in ("literal_captured_text", "semantic_discovery"):
        pkt = build_compact_context(
            ContextRequest(graph_id=sq_adapter.graph_id, mode=unadmitted, query="x"),
            sq_adapter,
        )
        assert_valid_context_packet(pkt)
        assert pkt["status"] == "unavailable"
        assert pkt["reason"] == "capability_not_admitted"

    # An explicitly unsupported PostgreSQL port retains the refusal without storage.
    pg_no_fb = build_compact_context(
        ContextRequest(
            graph_id=pg_adapter.graph_id,
            mode="graph_investigation",
            canonical_key="py:pkg.billing.InvoiceService",
        ),
        pg_adapter,
    )
    assert_valid_context_packet(pg_no_fb)
    assert pg_no_fb["status"] == "unavailable"
    assert pg_no_fb["reason"] == "backend_unsupported"

    # Actual fallback and expansion behavior is proved by the real PostgreSQL
    # integration owner; this unit case makes no emulated PostgreSQL claim.


def test_scoped_unlocatable_patterns_and_explicit_unlocatable_kind(tmp_path: Path) -> None:
    _, _, _, _, adapter = build_sqlite_context_fixture(tmp_path)

    # Scoped + explicit unlocatable --kind tool -> unavailable
    unloc = build_compact_context(
        ContextRequest(
            graph_id=adapter.graph_id,
            mode="ranked_discovery",
            query="pytest",
            kinds=("tool",),
            bindings=(BINDING_CORE,),
        ),
        adapter,
    )
    assert_valid_context_packet(unloc)
    assert unloc["status"] == "unavailable"
    assert unloc["reason"] == "unlocatable_kind_in_scoped_selection"

    # Scoped + definition without --kind -> partial because open prefixes (go.* etc.) are excluded
    scoped_def = build_compact_context(
        ContextRequest(
            graph_id=adapter.graph_id,
            mode="ranked_discovery",
            query="InvoiceService",
            intent="definition",
            bindings=(BINDING_CORE,),
        ),
        adapter,
    )
    assert_valid_context_packet(scoped_def)
    assert scoped_def["status"] == "partial"
    assert scoped_def["scope"]["scope_complete"] is False
    assert "go.*" in scoped_def["scope"]["unlocatable_kind_patterns_excluded"]
    assert scoped_def["omission_counts"]["unlocatable_kind_pattern_excluded"] == len(
        scoped_def["scope"]["unlocatable_kind_patterns_excluded"]
    )

    # Scoped + docs without --kind -> complete because all 4 doc affinity kinds are directly locatable
    scoped_docs = build_compact_context(
        ContextRequest(
            graph_id=adapter.graph_id,
            mode="ranked_discovery",
            query="ADR 0010",
            intent="docs",
            bindings=(BINDING_DOCS,),
        ),
        adapter,
    )
    assert_valid_context_packet(scoped_docs)
    assert scoped_docs["status"] == "complete"
    assert scoped_docs["scope"]["unlocatable_kind_patterns_excluded"] == []
    assert scoped_docs["omission_counts"]["unlocatable_kind_pattern_excluded"] == 0


def test_duplicate_path_identity_and_withheld_privacy_isolation(tmp_path: Path) -> None:
    db_path, _, _, _, adapter = build_sqlite_context_fixture(
        tmp_path, include_private_binding=True
    )
    # Add a private subject in BINDING_PRIV with same query token "SharedReadme"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO canonical_nodes VALUES (99, 1, 'py:priv.SharedReadme', 'python.class', "
            "'SharedReadme Secret', '{}', 'high', 0, 1, 1)"
        )
        conn.execute(
            "INSERT INTO raw_observations VALUES (1, 99, 1, 'python.class', 'src-99', "
            "'secret.py', '{}', 'hash-0099')"
        )
        conn.execute(
            "INSERT INTO canonical_evidence VALUES (99, 1, 1, 'ev:99', 99, 1, 'python.class', "
            "'src-99', ?, 1, 2, 'polyglot', '1.0', 'high', '{}')",
            (f"{adapter.private_markers[0]}/secret.py",),
        )
        conn.execute("INSERT INTO canonical_node_evidence VALUES (99, 99, 'observed')")

    pkt = build_compact_context(
        ContextRequest(
            graph_id=adapter.graph_id,
            mode="ranked_discovery",
            query="SharedReadme",
            intent="docs",
            locations_per_item=5,
        ),
        adapter,
    )
    assert_valid_context_packet(pkt, forbidden_substrings=adapter.private_markers)
    locs = [loc for it in pkt["items"] for loc in it["locations"] if loc["source_relative_path"] == "shared/README.md"]
    assert {loc["source_binding_id"] for loc in locs} == {BINDING_CORE, BINDING_DOCS}
    priv_items = [it for it in pkt["items"] if it["canonical_key"] == "py:priv.SharedReadme"]
    assert len(priv_items) == 1
    assert priv_items[0]["identity_state"] == "withheld"


def test_budget_validation_before_io_and_sqlite_statement_ceiling(tmp_path: Path) -> None:
    _, _, _, _, adapter = build_sqlite_context_fixture(tmp_path)
    err = build_compact_context(
        ContextRequest(
            graph_id=adapter.graph_id,
            mode="ranked_discovery",
            query="InvoiceService",
            budget_bytes=2048,
        ),
        adapter,
    )
    assert_valid_budget_error(err)
    assert err["reason"] == "budget_out_of_range"
    assert err["required_min_bytes"] is None

    # Test statement ceiling interception (e.g. max_sql_statements=5 with 2 scan units needing 1 + 3 + 3 = 7)
    pkt = build_compact_context(
        ContextRequest(
            graph_id=adapter.graph_id,
            mode="ranked_discovery",
            query="InvoiceService",
            bindings=(BINDING_CORE, BINDING_DOCS),
        ),
        adapter,
        work_ledger=WorkLedger(backend="sqlite", max_sql_statements=5),
    )
    assert_valid_context_packet(pkt)
    assert pkt["status"] == "partial"
    assert pkt["work_ledger"]["sql_statements_executed"] <= 5
