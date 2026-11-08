"""Strict v1/v2 decode matrix, per-schema bounds and v2 file custody."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from common_lore_index.ops.resource_reports._codec import (
    MAX_FILE_BYTES, MAX_FILE_BYTES_V2, ResourceReportError, decode_report, encode_report,
)
from common_lore_index.ops.resource_reports._files import read_report_file
from common_lore_index.ops.resource_reports._render import render_check_text, render_report_text
from common_lore_index.ops.resource_view._contracts import SCHEMA, ResourceReport
from common_lore_index.ops.resource_view._contracts_v2 import (
    SCHEMA_V2, ResourceLimitV2, ResourceMetricV2, ResourceReportV2,
)
from common_lore_index.ops.resource_view._slots_v2 import LIMIT_SLOTS_V2, METRIC_SLOTS_V2


def _report(operation: str = "local_refresh", value: int = 3) -> ResourceReportV2:
    metrics = tuple(
        ResourceMetricV2.measured(name, value, unit, sorted(item for item in bases if item)[0])
        for name, unit, bases in METRIC_SLOTS_V2[operation]
    )
    limits = tuple(
        ResourceLimitV2(name, value, unit, next(iter(sorted(enforcement - {"absent"}))), True)
        for name, unit, enforcement in LIMIT_SLOTS_V2[operation]
    )
    backend = "sqlite" if operation == "local_refresh" else "postgresql"
    return ResourceReportV2(SCHEMA_V2, operation, backend, "refused", "incomplete", metrics, limits)


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def test_v2_round_trip_is_canonical_and_renders_both_views() -> None:
    report = _report()
    data = encode_report(report)
    assert decode_report(data) == report and data == _canonical(report.to_payload())
    assert render_check_text(report).startswith("valid cloe-resource-view-v2: operation local_refresh")
    assert "sealing_read_bytes: 3 bytes (measured, call_meter_exact)" in render_report_text(report)


def test_the_v2_bound_is_read_but_every_non_v2_input_over_the_v1_bound_stays_too_large() -> None:
    report = _report(value=2**63 - 1)
    data = encode_report(report)
    assert len(data) <= 0.75 * MAX_FILE_BYTES_V2 and decode_report(data) == report
    assert (MAX_FILE_BYTES, MAX_FILE_BYTES_V2) == (8193, 16385)
    oversized_v1 = b'{"schema":"cloe-resource-view-v1"' + b" " * MAX_FILE_BYTES + b"}\n"
    for data in (oversized_v1, b"{" * (MAX_FILE_BYTES + 1) + b"\n"):
        with pytest.raises(ResourceReportError) as raised:
            decode_report(data)
        assert raised.value.category == "too_large", "incumbent category for every non-v2 oversize input"
    with pytest.raises(ResourceReportError, match="too_large"):
        decode_report(b"x" * (MAX_FILE_BYTES_V2 + 1))


def _mutated(mutate) -> bytes:
    payload = _report().to_payload()
    mutate(payload)
    return _canonical(payload)


@pytest.mark.parametrize(("mutate", "category"), [
    (lambda p: p.__setitem__("schema", SCHEMA), "invalid_domain"),
    (lambda p: p.__setitem__("schema", "cloe-resource-view-v3"), "invalid_domain"),
    (lambda p: p["metrics"].pop(), "invalid_domain"),
    (lambda p: p["metrics"][10].__setitem__("basis", "estimate"), "invalid_domain"),
    (lambda p: p["limits"].reverse(), "invalid_domain"),
    (lambda p: p["limits"][0].__setitem__("extra", 1), "invalid_shape"),
    (lambda p: p.__setitem__("outcome", "preview"), "invalid_domain"),
    (lambda p: p["metrics"][0].__setitem__("value", -1), "invalid_domain"),
])
def test_strict_v2_refusals(mutate, category: str) -> None:
    with pytest.raises(ResourceReportError) as raised:
        decode_report(_mutated(mutate))
    assert raised.value.category == category


def test_v1_reader_semantics_reject_v2_only_vocabulary_inside_a_v1_schema() -> None:
    payload = _report().to_payload()
    payload["schema"] = SCHEMA
    with pytest.raises(ResourceReportError, match="invalid_domain"):
        decode_report(_canonical(payload))
    v1 = ResourceReport(SCHEMA, None, None, "not_recorded", "incomplete")
    assert decode_report(encode_report(v1)) == v1 and type(decode_report(encode_report(v1))) is ResourceReport


def test_non_canonical_and_float_payloads_are_refused() -> None:
    data = encode_report(_report())
    with pytest.raises(ResourceReportError, match="not_canonical"):
        decode_report(data.replace(b",", b", ", 1))
    with pytest.raises(ResourceReportError, match="non_integer_number"):
        decode_report(data.replace(b'"value":3', b'"value":3.0', 1))


def test_encode_refuses_foreign_records_and_domain_drift() -> None:
    with pytest.raises(ResourceReportError, match="invalid_shape"):
        encode_report(cast(Any, _report().to_payload()))
    report = _report()
    drifted = ResourceReportV2(report.schema, report.operation, report.backend, report.outcome,
                               report.instrumentation, report.metrics[:-1], report.limits)
    with pytest.raises(ResourceReportError, match="invalid_domain"):
        encode_report(drifted)


def test_file_reader_admits_v2_sized_private_files_and_refuses_beyond(tmp_path: Path) -> None:
    data = encode_report(_report(value=2**63 - 1))
    path = tmp_path / "report.json"
    path.write_bytes(data)
    path.chmod(0o600)
    assert decode_report(read_report_file(path)) == _report(value=2**63 - 1)
    path.write_bytes(b" " * MAX_FILE_BYTES_V2)
    assert len(read_report_file(path)) == MAX_FILE_BYTES_V2, "read within the v2 bound"
    with pytest.raises(ResourceReportError, match="too_large"):
        decode_report(read_report_file(path))
    path.write_bytes(b"x" * (MAX_FILE_BYTES_V2 + 1))
    with pytest.raises(ResourceReportError, match="too_large"):
        read_report_file(path)
