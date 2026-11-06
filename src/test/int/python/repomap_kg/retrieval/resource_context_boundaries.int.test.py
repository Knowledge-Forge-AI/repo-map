"""Real SQLite refusal and output admission keep resource projections honest."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

import pytest

from common_lore_index.ops.resource_view._projections import project_compact_context
from common_lore_index.retrieval.context_assembly import build_compact_context
from common_lore_index.retrieval.context_budget import serialize_compact_json
from common_lore_index.retrieval.context_contracts import ContextRequest
from common_lore_index.retrieval.context_work import WorkLedger
from repomap_test_support.context_assertions import assert_valid_context_packet
from repomap_test_support.context_fixture import (
    BINDING_CORE, CTX_GRAPH_ID, SNAP_CORE, build_sqlite_context_fixture,
)
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free


def _publication(database: Path) -> tuple[int, int]:
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        row = connection.execute("SELECT generation, run_id FROM accepted_publication").fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def _project(packet: dict[str, Any], ledger: WorkLedger) -> dict[str, Any]:
    before = deepcopy(packet)
    view: dict[str, Any] = project_compact_context(packet, work_ledger=ledger).to_payload()
    assert packet == before
    assert view["operation"] == "compact_context" and view["backend"] == "sqlite"
    assert view["outcome"] == packet["status"]
    metrics = {row["name"]: row for row in view["metrics"]}
    for name in (
        "logical_read_units", "sql_statements_executed", "scan_units_executed",
        "seed_expansions_executed", "candidate_rows_scanned", "evidence_rows_scanned",
        "actual_bytes", "sqlite_progress_callbacks",
    ):
        assert metrics[name]["value"] == packet["work_ledger"][name]
    limits = {row["name"]: row for row in view["limits"]}
    for count, ceiling in (
        ("logical_read_units", "max_logical_read_units"),
        ("sql_statements_executed", "max_sql_statements"),
        ("scan_units_executed", "max_scan_units"),
        ("seed_expansions_executed", "max_seed_expansions"),
    ):
        assert 0 <= metrics[count]["value"] <= limits[ceiling]["value"]
        assert limits[ceiling]["applies_this_call"] is True
    assert metrics["actual_bytes"]["value"] == len(serialize_compact_json(packet))
    assert metrics["actual_bytes"]["value"] <= packet["request"]["budget_bytes"]
    assert limits["wall_clock_deadline"]["value"] == ledger.deadline_ms
    assert limits["sqlite_progress_callback_limit"]["value"] == ledger.sqlite_progress_callback_limit
    encoded = json.dumps(view, sort_keys=True)
    assert "InvoiceService" not in encoded and BINDING_CORE not in encoded
    assert_canary_free(view)
    return view


@pytest.mark.parametrize("case,status,reason", [
    ("literal", "unavailable", "capability_not_admitted"),
    ("semantic", "unavailable", "capability_not_admitted"),
    ("scoped_kind", "unavailable", "unlocatable_kind_in_scoped_selection"),
    ("selection", "refused", "invalid_selection_record"),
    ("statements", "partial", "statement_limit"),
    ("logical", "partial", "work_budget_exhausted"),
])
def test_real_refusal_projection_preserves_publication_and_allows_fresh_recovery(
    tmp_path: Path, case: str, status: str, reason: str,
) -> None:
    database, _config, _graph, _binding, adapter = build_sqlite_context_fixture(tmp_path)
    accepted = _publication(database)
    arguments: dict[str, Any] = {"graph_id": CTX_GRAPH_ID, "query": "InvoiceService"}
    if case in {"literal", "semantic"}:
        arguments["mode"] = "literal_captured_text" if case == "literal" else "semantic_discovery"
    elif case == "scoped_kind":
        arguments.update(bindings=(BINDING_CORE,), path_prefixes={BINDING_CORE: ("src",)}, kinds=("tool",))
    elif case == "selection":
        malformed = tmp_path / "malformed-selection.json"
        malformed.write_text('{"schema":"wrong"}\n')
        arguments["selection_path"] = malformed
    ledger = WorkLedger(
        backend="sqlite", max_sql_statements=0 if case == "statements" else 36,
        max_logical_read_units=0 if case == "logical" else 16,
    )
    with adapter:
        packet = build_compact_context(ContextRequest(**arguments), adapter, work_ledger=ledger)
    assert_valid_context_packet(packet)
    assert packet["status"] == status
    if status == "partial":
        assert ledger.exhausted_reason == reason
        assert {"reason": reason, "count": 1} in packet["omissions"]
    else:
        assert packet["reason"] == reason
    assert packet["items"] == packet["neighbors"] == packet["relations"] == []
    _project(packet, ledger)
    assert _publication(database) == accepted
    with adapter:
        recovered = build_compact_context(
            ContextRequest(graph_id=CTX_GRAPH_ID, query="InvoiceService"), adapter,
        )
    assert_valid_context_packet(recovered)
    assert recovered["status"] == "complete" and recovered["items"]
    assert _publication(database) == accepted


def test_budget_compaction_projects_delivered_bytes_and_opens_only_admitted_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = tuple(f"item_{index:02}.py" for index in range(12))
    subjects: list[dict[str, Any]] = [
        {"canonical_key": f"py:budget.Budget{index:02}", "kind": "python.function",
         "display_name": "Budget" + str(index) + "LongPublicName" * 12,
         "raw_kind": "python.function", "binding_id": BINDING_CORE,
         "snapshot_id": SNAP_CORE, "path": "src/" + name, "start_line": 1, "end_line": 2}
        for index, name in enumerate(names)
    ]
    database, _config, _graph, _binding, adapter = build_sqlite_context_fixture(
        tmp_path / "fixture", extra_subjects=subjects,
    )
    accepted = _publication(database)
    root = tmp_path / "selected"
    (root / "src").mkdir(parents=True)
    for name in names:
        (root / "src" / name).write_text("one\ntwo\n")
    opened: list[str] = []
    real_open = os.open

    def track(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        if dir_fd is not None and str(path) in names:
            opened.append(str(path))
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", track)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {track})
    ledger = WorkLedger(backend="sqlite")
    with adapter:
        packet = build_compact_context(ContextRequest(
            graph_id=CTX_GRAPH_ID, query="Budget", freshness="check",
            source_roots={BINDING_CORE: root}, budget_bytes=4096, max_items=20,
        ), adapter, work_ledger=ledger)
    assert_valid_context_packet(packet)
    assert packet["status"] == "partial" and packet["omission_counts"]["output_budget"] > 0
    admitted = [Path(location["source_relative_path"]).name
        for item in (*packet["items"], *packet["neighbors"]) for location in item["locations"]]
    assert sorted(opened) == sorted(admitted)
    assert len(opened) == packet["freshness"]["files_checked"]
    view = _project(packet, ledger)
    assert view["outcome"] == "partial"
    assert _publication(database) == accepted
