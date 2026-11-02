"""Unit tests for W4 context_contracts and context_work."""

from __future__ import annotations

import pytest

from common_lore_index.retrieval.context_contracts import (
    CONTEXT_FRESHNESS_OBS_KEYS,
    CONTEXT_ITEM_KEYS,
    CONTEXT_LOCATION_KEYS,
    CONTEXT_RELATION_KEYS,
    OMISSION_COUNT_KEYS,
    PACKET_TOP_LEVEL_KEYS,
    ContextRequest,
    ContextRequestError,
    ExpectedPublicationPin,
    valid_source_path_prefix,
)
from common_lore_index.retrieval.context_work import (
    MAX_SQL_STATEMENTS_POSTGRES,
    MAX_SQL_STATEMENTS_SQLITE,
    SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT,
    SQLITE_PROGRESS_HANDLER_INTERVAL,
    WORK_LEDGER_KEYS,
    WorkLedger,
)


def test_locked_key_orders_match_spec() -> None:
    assert PACKET_TOP_LEVEL_KEYS == (
        "schema", "status", "requested_mode", "effective_mode", "fallback",
        "consistency_mode", "request", "scope", "publication", "ordering",
        "expansion", "omission_counts", "work_ledger", "freshness", "absence_basis",
        "items", "neighbors", "relations", "omissions",
    )
    assert CONTEXT_ITEM_KEYS == (
        "item_id", "item_role", "canonical_key", "kind", "display_name",
        "subject_family", "match_surface", "rank", "match_class", "rank_tiers",
        "rank_reasons", "identity_state", "locations", "omitted_location_count",
    )
    assert CONTEXT_LOCATION_KEYS == (
        "source_binding_id", "binding_revision", "snapshot_id", "source_relative_path",
        "run_id", "publication_relation", "path_namespace", "graph_path",
        "start_line", "end_line", "evidence_link_kind", "evidence_raw_kind",
        "evidence_confidence", "freshness",
    )
    assert CONTEXT_FRESHNESS_OBS_KEYS == ("state", "reason", "limits", "inspected_span")
    assert CONTEXT_RELATION_KEYS == (
        "source_key", "edge_kind", "target_key", "match_surface", "support",
    )
    assert len(OMISSION_COUNT_KEYS) == 11
    assert len(WORK_LEDGER_KEYS) == 16


def test_context_request_validation_modes_and_targets() -> None:
    req = ContextRequest(
        graph_id="repo", mode="ranked_discovery", query="InvoiceService", intent="definition"
    ).validate()
    assert req.effective_intent() == "definition"
    assert req.effective_expand_depth() == 0

    gi = ContextRequest(
        graph_id="repo", mode="graph_investigation", canonical_key="py:pkg.A"
    ).validate()
    assert gi.effective_expand_depth() == 1

    with pytest.raises(ContextRequestError) as exc:
        ContextRequest(graph_id="repo", mode="").validate()
    assert exc.value.refusal_reason == "missing_mode"

    with pytest.raises(ContextRequestError) as exc:
        ContextRequest(graph_id="repo", mode="unknown_mode", query="x").validate()
    assert exc.value.refusal_reason == "invalid_mode"

    with pytest.raises(ContextRequestError) as exc:
        ContextRequest(graph_id="repo", mode="exact_identity", query="x").validate()
    assert exc.value.refusal_reason == "invalid_target_flags"

    with pytest.raises(ContextRequestError) as exc:
        ContextRequest(
            graph_id="repo", mode="ranked_discovery", query="x", canonical_key="py:a"
        ).validate()
    assert exc.value.refusal_reason == "invalid_target_flags"

    with pytest.raises(ContextRequestError) as exc:
        ContextRequest(graph_id="repo", mode="ranked_discovery").validate()
    assert exc.value.refusal_reason == "invalid_target_flags"


def test_context_request_limits_and_scan_unit_caps() -> None:
    with pytest.raises(ContextRequestError) as exc:
        ContextRequest(
            graph_id="repo", mode="ranked_discovery", query="x", expand_depth=2
        ).validate()
    assert exc.value.refusal_reason == "invalid_expand_depth"

    with pytest.raises(ContextRequestError) as exc:
        ContextRequest(
            graph_id="repo",
            mode="ranked_discovery",
            query="x",
            bindings=tuple(f"bind1:{i}" for i in range(9)),
        ).validate()
    assert exc.value.refusal_reason == "binding_limit_exceeded"

    with pytest.raises(ContextRequestError) as exc:
        ContextRequest(
            graph_id="repo",
            mode="ranked_discovery",
            query="x",
            bindings=("bind1:a",),
            path_prefixes={"bind1:a": ("p1", "p2", "p3", "p4", "p5")},
        ).validate()
    assert exc.value.refusal_reason == "prefix_limit_exceeded"

    with pytest.raises(ContextRequestError) as exc:
        ContextRequest(
            graph_id="repo",
            mode="ranked_discovery",
            query="x",
            bindings=("bind1:a", "bind1:b", "bind1:c"),
            path_prefixes={
                "bind1:a": ("p1", "p2", "p3"),
                "bind1:b": ("p1", "p2", "p3"),
                "bind1:c": ("p1", "p2", "p3"),
            },
        ).validate()
    assert exc.value.refusal_reason == "scan_unit_limit_exceeded"

    assert valid_source_path_prefix("src/main/python/")
    assert not valid_source_path_prefix("../src")
    assert not valid_source_path_prefix("/abs/path")


def test_expected_publication_pin_strict_validation() -> None:
    pin = ExpectedPublicationPin(
        accepted_run_id=1,
        publication_bundle_id="bundle1:aa",
        snapshot_manifest_id="manifest1:bb",
        generation=2,
        job_id="job-1",
        attempt=1,
        extraction_receipt_id="receipt1:cc",
    ).validate()
    assert pin.matches_accepted(pin.to_dict())

    with pytest.raises(ContextRequestError) as exc:
        ExpectedPublicationPin(
            accepted_run_id=True,
            publication_bundle_id="bundle1:aa",
            snapshot_manifest_id="manifest1:bb",
            generation=1,
            job_id="job-1",
            attempt=1,
            extraction_receipt_id="receipt1:cc",
        ).validate()
    assert exc.value.refusal_reason == "invalid_selection_record"


def test_work_ledger_statement_and_progress_accounting() -> None:
    now = [100.0]
    sq_ledger = WorkLedger(backend="sqlite", clock=lambda: now[0])
    assert sq_ledger.max_sql_statements == MAX_SQL_STATEMENTS_SQLITE == 36
    assert sq_ledger.record_statement_start()
    handler = sq_ledger.make_sqlite_progress_handler()
    for _ in range(SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT - 1):
        assert handler() == 0
    assert handler() == 1
    assert sq_ledger.exhausted_reason == "work_budget_exhausted"
    d = sq_ledger.to_dict()
    assert d["sqlite_progress_callbacks"] == SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT
    assert d["sqlite_progress_interval_ops"] == SQLITE_PROGRESS_HANDLER_INTERVAL
    assert (
        d["sqlite_vm_steps_estimate"]
        == SQLITE_CONTEXT_PROGRESS_CALLBACK_LIMIT * SQLITE_PROGRESS_HANDLER_INTERVAL
    )

    pg_ledger = WorkLedger(backend="postgresql", clock=lambda: now[0])
    assert pg_ledger.max_sql_statements == MAX_SQL_STATEMENTS_POSTGRES == 12
    pg_d = pg_ledger.to_dict()
    assert pg_d["sqlite_progress_callbacks"] is None
    assert pg_d["sqlite_progress_interval_ops"] is None
    assert pg_d["sqlite_vm_steps_estimate"] is None

    now[0] = 115.0
    assert not pg_ledger.check_deadline()
    assert pg_ledger.exhausted_reason == "deadline_exceeded"
