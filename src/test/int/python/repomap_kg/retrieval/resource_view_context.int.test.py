"""Real SQLite/PostgreSQL compact-context packets projected into resource views."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from common_lore_index.retrieval.context_assembly import build_compact_context
from common_lore_index.retrieval.context_budget import serialize_compact_json
from common_lore_index.retrieval.context_contracts import ContextRequest
from common_lore_index.retrieval.context_work import WorkLedger
# The Local-safe projection owner; ``_projections`` re-exports it for compatibility.
from common_lore_index.ops.resource_view._context_projection import project_compact_context
from repomap_test_support.context_assertions import (
    assert_valid_budget_error,
    assert_valid_context_packet,
    build_postgres_context_fixture,
)
from repomap_test_support.context_fixture import (
    BINDING_CORE,
    BINDING_DOCS,
    CTX_GRAPH_ID,
    build_sqlite_context_fixture,
)
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres


def _project(packet: dict[str, Any], *, ledger: WorkLedger | None = None) -> dict[str, Any]:
    before = deepcopy(packet)
    payload: dict[str, Any] = project_compact_context(packet, work_ledger=ledger).to_payload()
    assert packet == before
    assert payload["schema"] == "cloe-resource-view-v1"
    assert payload["operation"] == "compact_context"
    assert payload["outcome"] == packet["status"]
    assert len(payload["metrics"]) <= 24 and len(payload["limits"]) <= 16
    encoded = json.dumps(payload, sort_keys=True)
    assert all(
        marker not in encoded
        for marker in ("InvoiceService", BINDING_CORE, BINDING_DOCS, "invoice.py")
    )
    return payload


def _assert_packet_projection(packet: dict[str, Any], backend: str) -> None:
    assert_valid_context_packet(packet)
    payload = _project(packet)
    assert payload["backend"] == backend
    metrics = {item["name"]: item for item in payload["metrics"]}
    ledger = packet["work_ledger"]
    for name in (
        "config_revalidations_executed", "logical_read_units", "sql_statements_executed",
        "scan_units_executed", "seed_expansions_executed", "candidate_rows_scanned",
        "evidence_rows_scanned", "elapsed_ms", "actual_bytes",
    ):
        assert metrics[name]["value"] == ledger[name]
    assert metrics["actual_bytes"]["value"] == len(serialize_compact_json(packet))
    if backend == "postgresql":
        for name in ("sqlite_progress_callbacks", "sqlite_vm_steps_estimate", "sqlite_progress_interval_ops"):
            assert metrics[name]["availability"] == "unavailable"
            assert metrics[name]["reason"] == "backend_not_applicable"
    else:
        assert metrics["sqlite_progress_callbacks"]["value"] == ledger["sqlite_progress_callbacks"]


def test_sqlite_and_postgres_packets_keep_real_ledgers_and_byte_counts(tmp_path: Path) -> None:
    _path, _config, _graph, _binding, sqlite_adapter = build_sqlite_context_fixture(tmp_path / "sqlite")
    request = ContextRequest(
        graph_id=CTX_GRAPH_ID, mode="ranked_discovery", query="InvoiceService",
        intent="implementation", bindings=(BINDING_CORE, BINDING_DOCS), budget_bytes=16384,
    )
    with sqlite_adapter:
        sqlite_packet = build_compact_context(request, sqlite_adapter)
    _assert_packet_projection(sqlite_packet, "sqlite")

    require_postgres_binaries()
    with temporary_postgres() as postgres:
        _home, postgres_adapter = build_postgres_context_fixture(tmp_path / "postgres", postgres)
        with postgres_adapter:
            postgres_packet = build_compact_context(request, postgres_adapter)
        _assert_packet_projection(postgres_packet, "postgresql")


def test_budget_error_never_reads_or_projects_a_caller_ledger(tmp_path: Path) -> None:
    _path, _config, _graph, _binding, adapter = build_sqlite_context_fixture(tmp_path)
    packet = build_compact_context(
        ContextRequest(graph_id=CTX_GRAPH_ID, query="InvoiceService", budget_bytes=4095), adapter
    )
    assert_valid_budget_error(packet)
    supplied = WorkLedger(
        backend="sqlite", max_logical_read_units=1, max_sql_statements=1,
        max_scan_units=1, max_seed_expansions=1, deadline_ms=1,
        sqlite_progress_callback_limit=1,
    )
    payload = _project(packet, ledger=supplied)
    assert payload["backend"] is None
    assert payload["limits"] == []
    assert all(item["availability"] == "unavailable" for item in payload["metrics"])
    assert all(item["reason"] == "not_reached" for item in payload["metrics"])
