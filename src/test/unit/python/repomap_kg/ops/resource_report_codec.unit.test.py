"""Strict canonical codec, domain tables and producer round trips for report files."""

from __future__ import annotations

import itertools
import sys
from types import SimpleNamespace
from typing import Any, cast

import pytest

from common_lore_index.ops.resource_reports._codec import (
    MAX_FILE_BYTES, ResourceReportError, decode_report, encode_report,
)
from common_lore_index.ops.resource_reports._render import render_check_text, render_report_text
from common_lore_index.ops.resource_view import (
    Instrumentation, ResourceMetric, ResourceObserver, ResourceReport, SCHEMA, begin,
    end_stage, finish_local, mark, note_lexical_limits, note_manifest,
)
from common_lore_index.ops.resource_view._context_projection import (
    project_compact_context, unfinished_compact_context,
)
from common_lore_index.ops.resource_view._lexical_views import (
    finish_lexical_query, finish_lexical_revoke, note_lexical_query_controls, note_lexical_revoke,
)
from common_lore_index.ops.resource_view._projections import finish_lexical, finish_server
from common_lore_index.ops.resource_view._slots import LIMIT_SLOTS, METRIC_SLOTS

_LEDGER = {
    "config_revalidations_executed": 1, "logical_read_units": 2, "sql_statements_executed": 3,
    "scan_units_executed": 1, "seed_expansions_executed": 0, "candidate_rows_scanned": 4,
    "evidence_rows_scanned": 5, "elapsed_ms": 6, "actual_bytes": 700,
    "sqlite_progress_callbacks": 2, "sqlite_vm_steps_estimate": 2000,
    "sqlite_progress_interval_ops": 1000, "max_logical_read_units": 10, "max_sql_statements": 20,
    "max_scan_units": 8, "max_seed_expansions": 5,
}


def _observer() -> ResourceObserver:
    return ResourceObserver(
        _monotonic_ns=itertools.count(0, 100).__next__,
        _process_time_ns=itertools.count(0, 10).__next__,
    )


def _v1(report: object) -> ResourceReport:
    """Default observers build v1 reports; narrow the observer's two-schema return."""
    assert type(report) is ResourceReport
    return report


def _context(**ledger: Any) -> ResourceReport:
    packet = {
        "status": "complete", "scope": {"backend": "sqlite"},
        "work_ledger": {**_LEDGER, **ledger}, "request": {"budget_bytes": 16384},
    }
    return project_compact_context(packet)


def _local() -> ResourceReport:
    observer = _observer()
    begin(observer, "local_refresh", "sqlite")
    for stage in ("lock_and_reconcile", "capture"):
        mark(observer, stage)
        end_stage(observer, stage)
    note_manifest(observer, SimpleNamespace(total_files=3, total_bytes=99))
    finish_local(observer, SimpleNamespace(reconciled=True))
    return _v1(observer.report())


def _server(*, degrade: bool = False) -> ResourceReport:
    observer = _observer()
    begin(observer, "server_refresh", "postgresql")
    if degrade:
        mark(observer, "not-a-stage")
    finish_server(observer, SimpleNamespace(result="success", publication_state="committed"))
    return _v1(observer.report())


def _lexical_build() -> ResourceReport:
    observer = _observer()
    begin(observer, "lexical_build", "postgresql")
    note_lexical_limits(
        observer, max_projected_files=1, max_aggregate_input_bytes=2, max_input_artifact_bytes=3,
        max_projected_file_bytes=4, max_chunk_lines=5, max_chunk_bytes=6, statement_timeout_ms=7,
    )
    plan = SimpleNamespace(
        aggregate_input_bytes=10, aggregate_projected_bytes=9, documents=(1, 2), omissions=(),
    )
    finish_lexical(observer, SimpleNamespace(result="published", plan=plan))
    return _v1(observer.report())


def _query() -> ResourceReport:
    observer = _observer()
    begin(observer, "lexical_query", "postgresql")
    note_lexical_query_controls(observer, limit=20, max_occurrences_per_file=3, statement_timeout_ms=5000)
    envelope = SimpleNamespace(capability_state=SimpleNamespace(value="not_run"), hits=(), omissions=(1,))
    finish_lexical_query(observer, envelope, immediate=False)
    return _v1(observer.report())


def _revoke(*, dry_run: bool) -> ResourceReport:
    observer = _observer()
    begin(observer, "lexical_revoke", "postgresql")
    note_lexical_revoke(observer, dry_run=dry_run, statement_timeout_ms=60000)
    finish_lexical_revoke(observer, SimpleNamespace(
        revoked_generation_ids=("a",), authority_rows_removed=1, purged_document_count=2,
        purged_chunk_count=3, purged_omission_count=0, purge_rows=not dry_run,
    ))
    return _v1(observer.report())


def _unbegun() -> ResourceReport:
    return _v1(ResourceObserver().report())


def _unfinished_lexical_query() -> ResourceReport:
    observer = _observer()
    begin(observer, "lexical_query", "postgresql")
    return _v1(observer.report())


PRODUCERS = {
    "context": _context, "context_unfinished": unfinished_compact_context, "local": _local,
    "server": _server, "server_degraded": lambda: _server(degrade=True),
    "lexical_build": _lexical_build, "lexical_query": _query,
    "lexical_query_unfinished": _unfinished_lexical_query,
    "revoke": lambda: _revoke(dry_run=False), "revoke_preview": lambda: _revoke(dry_run=True),
    "unbegun": _unbegun,
}


@pytest.mark.parametrize("name", sorted(PRODUCERS))
def test_every_producer_round_trips_byte_exactly(name: str) -> None:
    report = PRODUCERS[name]()
    data = encode_report(report)
    assert data.endswith(b"\n") and data.count(b"\n") == 1 and len(data) <= MAX_FILE_BYTES
    decoded = decode_report(data)
    assert decoded == report
    assert encode_report(decoded) == data
    assert render_check_text(decoded).startswith(f"valid {SCHEMA}")


def test_tables_cover_every_operation_and_bounds() -> None:
    assert set(METRIC_SLOTS) == set(LIMIT_SLOTS) == {
        "local_refresh", "server_refresh", "lexical_build", "compact_context",
        "lexical_query", "lexical_revoke",
    }
    assert all(len(rows) <= 24 for rows in METRIC_SLOTS.values())
    assert all(len(rows) <= 16 for rows in LIMIT_SLOTS.values())


def _mutated(old: bytes, new: bytes, base: bytes | None = None) -> bytes:
    data = base if base is not None else encode_report(_context())
    assert data.count(old) >= 1, old
    return data.replace(old, new, 1)


REFUSALS: dict[str, tuple[Any, str]] = {
    "whitespace": (lambda: _mutated(b'{"backend"', b'{ "backend"'), "not_canonical"),
    "crlf": (lambda: encode_report(_context())[:-1] + b"\r\n", "not_canonical"),
    "missing_lf": (lambda: encode_report(_context())[:-1], "not_canonical"),
    "two_lf": (lambda: encode_report(_context()) + b"\n", "not_canonical"),
    "escaped": (lambda: _mutated(b'"sqlite"', b'"sqlit\\u0065"'), "not_canonical"),
    "reordered": (lambda: _mutated(
        b'{"backend":"sqlite","instrumentation"', b'{"instrumentation"'
    ).replace(b'"limits"', b'"backend":"sqlite","limits"', 1), "not_canonical"),
    "bom": (lambda: b"\xef\xbb\xbf" + encode_report(_context()), "malformed_json"),
    "not_utf8": (lambda: _mutated(b'"sqlite"', b'"sql\xffite"'), "not_utf8"),
    "two_documents": (lambda: encode_report(_context())[:-1] + b"{}\n", "malformed_json"),
    "minus_zero": (lambda: _mutated(b'"value":0', b'"value":-0'), "invalid_domain"),
    "negative": (lambda: _mutated(b'"value":700', b'"value":-700'), "invalid_domain"),
    "float": (lambda: _mutated(b'"value":700', b'"value":700.0'), "non_integer_number"),
    "exponent": (lambda: _mutated(b'"value":700', b'"value":7e2'), "non_integer_number"),
    "nan": (lambda: _mutated(b'"value":700', b'"value":NaN'), "non_integer_number"),
    "bool_count": (lambda: _mutated(b'"value":700', b'"value":true'), "invalid_domain"),
    "duplicate_top_key": (lambda: _mutated(b'{"backend":"sqlite"', b'{"backend":"sqlite","backend":"sqlite"'),
                          "duplicate_key"),
    "duplicate_nested_key": (lambda: _mutated(b'"unit":"bytes"', b'"unit":"bytes","unit":"bytes"'),
                             "duplicate_key"),
    "extra_key": (lambda: _mutated(b'{"backend"', b'{"aaa":1,"backend"'), "invalid_shape"),
    "missing_key": (lambda: _mutated(b'"backend":"sqlite",', b""), "invalid_shape"),
    "limit_row_shape": (lambda: _mutated(b'"limits":[{', b'"limits":[1,{'), "invalid_shape"),
    "metrics_not_list": (lambda: _mutated(b'"metrics":[{', b'"metrics":"x","unused":[{'), "invalid_shape"),
    "unknown_closed_value": (lambda: _mutated(b'"outcome":"complete"', b'"outcome":"privatecanary"'),
                             "invalid_domain"),
    "operation_backend_pair": (lambda: _mutated(b'"operation":"compact_context"',
                                                b'"operation":"local_refresh"'), "invalid_domain"),
    "metric_unit": (lambda: _mutated(b'"unit":"bytes","value":700', b'"unit":"count","value":700'),
                    "invalid_domain"),
    "limit_enforcement": (lambda: _mutated(b'"enforcement":"owner_enforced"',
                                           b'"enforcement":"post_capture_validation"'), "invalid_domain"),
    "too_deep": (lambda: _mutated(b'"value":700', b'"value":[[[700]]]'), "too_deep"),
    "too_large": (lambda: b" " * (MAX_FILE_BYTES + 1), "too_large"),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_decoder_refuses_noncanonical_and_out_of_domain_bytes(case: str) -> None:
    factory, category = REFUSALS[case]
    with pytest.raises(ResourceReportError) as raised:
        decode_report(factory())
    assert raised.value.category == category
    assert str(raised.value) == f"resource-report-invalid: {category}"
    assert "privatecanary" not in str(raised.value)


def test_duplicate_and_reordered_slots_refuse_even_when_closed() -> None:
    report = _context()
    metrics = report.metrics
    with pytest.raises(ValueError):
        ResourceReport(SCHEMA, "compact_context", "sqlite", "complete", "complete", (metrics[0], metrics[0]))
    swapped = (metrics[1], metrics[0], *metrics[2:])
    manual = ResourceReport(SCHEMA, "compact_context", "sqlite", "complete", "complete", swapped)
    with pytest.raises(ResourceReportError) as raised:
        encode_report(manual)
    assert raised.value.category == "invalid_domain"


def test_manually_constructed_partial_report_cannot_bypass_domain_tables() -> None:
    lone = ResourceMetric.measured("actual_bytes", 1, "bytes", "ledger_counter")
    manual = ResourceReport(SCHEMA, "compact_context", "sqlite", "complete", Instrumentation.COMPLETE, (lone,))
    with pytest.raises(ResourceReportError, match="invalid_domain"):
        encode_report(manual)
    with pytest.raises(ResourceReportError, match="invalid_shape"):
        encode_report(cast(ResourceReport, SimpleNamespace(**{"operation": None})))


def test_huge_counts_are_bounded_by_bytes_not_the_global_digit_limit() -> None:
    previous = sys.get_int_max_str_digits()
    huge = 10**5000 + 7
    try:
        sys.set_int_max_str_digits(640)  # test-only: prove product independence
        report = _context(actual_bytes=huge)
        data = encode_report(report)
        assert sys.get_int_max_str_digits() == 640, "product must not change process globals"
        decoded = decode_report(data)
        value = next(item.value for item in decoded.metrics if item.name == "actual_bytes")
        assert value == huge
        text = render_report_text(decoded)
        assert len(text) < 5001 + 4000, "a huge count is rendered once, not per row"
        assert sum(len(line) > 5000 for line in text.splitlines()) == 1
    finally:
        sys.set_int_max_str_digits(previous)
    with pytest.raises(ValueError, match="8192"):
        _context(actual_bytes=10**9000)


def test_human_rendering_states_validity_limits_and_unavailable_rows() -> None:
    text = render_report_text(_revoke(dry_run=True))
    assert "not authenticity" in text
    assert "outcome: preview" in text
    assert "revoked_generations: unavailable count (unavailable: not_selected)" in text
    assert "lexical_revoke_statement_timeout: 60000 milliseconds" in text
    assert "applies this call: unknown" in text
