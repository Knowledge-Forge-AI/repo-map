"""Lexical query/revoke observer outcomes across normal, degraded, unbegun and unfinished paths."""

from __future__ import annotations

import itertools
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from common_lore_index.ops.resource_view import ResourceObserver, begin
from common_lore_index.ops.resource_view._lexical_views import (
    finish_lexical_query, finish_lexical_revoke, note_lexical_query_controls, note_lexical_revoke,
)
from common_lore_index.ops.resource_view._slots import METRIC_SLOTS, check_report_domain
from common_lore_index.retrieval.query_contracts import CapabilityState

_EFFECTS = ("revoked_generations", "revoked_authority_rows", "purged_documents", "purged_chunks",
            "purged_omissions")


def _observer() -> ResourceObserver:
    return ResourceObserver(
        _monotonic_ns=itertools.count(0, 100).__next__,
        _process_time_ns=itertools.count(0, 10).__next__,
    )


def _payload(observer: ResourceObserver) -> dict[str, Any]:
    report = observer.report()
    check_report_domain(report)
    return report.to_payload()


def _metrics(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in payload["metrics"]}


def _query(state: object, *, immediate: bool, hits: object = (), omissions: object = ()) -> dict[str, Any]:
    observer = _observer()
    begin(observer, "lexical_query", "postgresql")
    note_lexical_query_controls(observer, limit=20, max_occurrences_per_file=3, statement_timeout_ms=5000)
    envelope = SimpleNamespace(capability_state=state, hits=hits, omissions=omissions)
    assert finish_lexical_query(observer, envelope, immediate=immediate) is envelope
    return _payload(observer)


@pytest.mark.parametrize("state", list(CapabilityState))
def test_every_envelope_state_is_a_distinct_closed_query_outcome(state: CapabilityState) -> None:
    payload = _query(state, immediate=False, hits=(1, 2), omissions=(1,))
    assert payload["outcome"] == state.value
    metrics = _metrics(payload)
    assert metrics["query_hits_returned"]["value"] == 2
    assert metrics["query_omissions_returned"]["value"] == 1
    assert payload["instrumentation"] == "complete"


def test_available_and_not_run_are_not_merged_and_sql_applicability_stays_unknown() -> None:
    available = _query(CapabilityState.AVAILABLE, immediate=False)
    not_run = _query(CapabilityState.NOT_RUN, immediate=True)
    assert (available["outcome"], not_run["outcome"]) == ("available", "not_run")
    assert {item["applies_this_call"] for item in available["limits"]} == {None}
    assert {item["applies_this_call"] for item in not_run["limits"]} == {False}
    assert [item["name"] for item in available["limits"]] == [
        "query_result_limit", "query_max_occurrences_per_file", "lexical_query_statement_timeout",
    ]


def test_unknown_state_and_invalid_owner_values_never_raise() -> None:
    payload = _query("private-canary", immediate=False, hits=object(), omissions=None)
    assert payload["outcome"] == "unclassified"
    assert {item["reason"] for item in payload["metrics"][2:]} == {"invalid_owner_value"}
    assert "private-canary" not in str(payload)


def _revoke(summary: object, *, dry_run: bool) -> dict[str, Any]:
    observer = _observer()
    begin(observer, "lexical_revoke", "postgresql")
    note_lexical_revoke(observer, dry_run=dry_run, statement_timeout_ms=60000)
    assert finish_lexical_revoke(observer, summary) is summary
    return _payload(observer)


def _summary(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = dict(
        repository_id=1, revoked_generation_ids=("a", "b"), authority_rows_removed=2,
        purged_document_count=3, purged_chunk_count=4, purged_omission_count=0, purge_rows=True,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_completed_revoke_reports_returned_aggregate_effects() -> None:
    payload = _revoke(_summary(), dry_run=False)
    assert payload["outcome"] == "revoked"
    assert [_metrics(payload)[name]["value"] for name in _EFFECTS] == [2, 2, 3, 4, 0]
    [timeout] = payload["limits"]
    assert (timeout["name"], timeout["value"], timeout["applies_this_call"]) == (
        "lexical_revoke_statement_timeout", 60000, None,
    )


def test_preview_and_purge_disabled_zeros_are_not_selected_not_measured() -> None:
    preview = _revoke(_summary(purge_rows=False), dry_run=True)
    assert preview["outcome"] == "preview"
    assert {_metrics(preview)[name]["reason"] for name in _EFFECTS} == {"not_selected"}
    disabled = _revoke(_summary(purge_rows=False, purged_document_count=0, purged_chunk_count=0), dry_run=False)
    metrics = _metrics(disabled)
    assert metrics["revoked_authority_rows"]["value"] == 2
    assert {metrics[name]["reason"] for name in _EFFECTS[2:]} == {"not_selected"}


def test_repository_miss_records_truthful_zero_work_and_negative_rowcounts_are_invalid() -> None:
    miss = _revoke(_summary(
        repository_id=None, revoked_generation_ids=(), authority_rows_removed=0,
        purged_document_count=0, purged_chunk_count=0, purged_omission_count=0,
    ), dry_run=False)
    assert [_metrics(miss)[name]["value"] for name in _EFFECTS] == [0, 0, 0, 0, 0]
    negative = _revoke(_summary(authority_rows_removed=-1, purge_rows="ambiguous"), dry_run=False)
    metrics = _metrics(negative)
    assert metrics["revoked_authority_rows"]["reason"] == "invalid_owner_value"
    assert {metrics[name]["reason"] for name in _EFFECTS[2:]} == {"invalid_owner_value"}


@pytest.mark.parametrize("operation", ("lexical_query", "lexical_revoke"))
def test_unbegun_unfinished_and_degraded_paths_use_the_explicit_tables(operation: str) -> None:
    unbegun = ResourceObserver()
    if operation == "lexical_query":
        finish_lexical_query(unbegun, SimpleNamespace(), immediate=True)
    else:
        finish_lexical_revoke(unbegun, SimpleNamespace())
    assert _payload(unbegun)["operation"] is None

    unfinished = _observer()
    begin(unfinished, operation, "postgresql")
    payload = _payload(unfinished)
    assert (payload["outcome"], payload["instrumentation"]) == ("not_recorded", "incomplete")
    assert [item["name"] for item in payload["metrics"]] == [name for name, _, _ in METRIC_SLOTS[operation]]

    degraded = _observer()
    begin(degraded, operation, "postgresql")
    if operation == "lexical_query":
        note_lexical_query_controls(degraded, limit=1, max_occurrences_per_file=1, statement_timeout_ms=1)
        note_lexical_query_controls(degraded, limit=1, max_occurrences_per_file=1, statement_timeout_ms=1)
    else:
        finish_lexical_revoke(degraded, _summary())  # mode was never noted
    payload = _payload(degraded)
    assert payload["instrumentation"] == "degraded"
    assert {item["reason"] for item in payload["metrics"]} == {"observer_failed"}
    assert all(item["applies_this_call"] is None for item in payload["limits"])


def test_wrong_backend_cross_thread_and_repeat_finish_degrade_without_subject_change() -> None:
    wrong = _observer()
    begin(wrong, "lexical_query", "sqlite")
    assert _payload(wrong)["operation"] is None

    foreign = _observer()
    begin(foreign, "lexical_revoke", "postgresql")
    worker = threading.Thread(target=note_lexical_revoke, args=(foreign,), kwargs={
        "dry_run": False, "statement_timeout_ms": 1,
    })
    worker.start()
    worker.join()
    assert _payload(foreign)["instrumentation"] == "degraded"

    repeated = _observer()
    begin(repeated, "lexical_query", "postgresql")
    envelope = SimpleNamespace(capability_state="available", hits=(), omissions=())
    finish_lexical_query(repeated, envelope, immediate=False)
    assert finish_lexical_query(repeated, envelope, immediate=False) is envelope
    assert _payload(repeated)["instrumentation"] == "degraded"
    assert finish_lexical_query(None, envelope, immediate=True) is envelope
    assert finish_lexical_revoke(object(), envelope) is envelope
