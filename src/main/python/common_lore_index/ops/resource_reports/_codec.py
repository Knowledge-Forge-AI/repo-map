"""Strict canonical encoding and decoding of resource-report files.

A file is the canonical compact UTF-8 JSON of one closed report followed by
exactly one LF. Version 1 (``cloe-resource-view-v1``, at most 8,193 file
bytes) stays the default; an explicitly versioned ``cloe-resource-view-v2``
file may hold up to 16,385 bytes. Any input over the v1 bound that is not a
valid v2 report keeps the incumbent ``too_large`` category. Decoding proves format and domain validity only: it is not
evidence of producer authenticity, measurement truth, qualification,
publication or transaction success, and no identity binding is inferred.
"""

from __future__ import annotations

import json
from typing import Any, TypedDict, cast

from common_lore_index.ops.resource_view._canonical import CanonicalBoundError, canonical_bytes, parse_digits
from common_lore_index.ops.resource_view._contracts import (
    MAX_PAYLOAD_BYTES, ResourceLimit, ResourceMetric, ResourceReport,
)
from common_lore_index.ops.resource_view._contracts_v2 import (
    MAX_PAYLOAD_BYTES_V2, SCHEMA_V2, ResourceLimitV2, ResourceMetricV2, ResourceReportV2,
)
from common_lore_index.ops.resource_view._slots import check_report_domain
from common_lore_index.ops.resource_view._slots_v2 import check_report_domain_v2

MAX_FILE_BYTES = MAX_PAYLOAD_BYTES + 1
MAX_FILE_BYTES_V2 = MAX_PAYLOAD_BYTES_V2 + 1
MAX_DEPTH = 3
CATEGORIES = frozenset({
    "unreadable", "unsafe_input", "too_large", "not_utf8", "too_deep", "malformed_json",
    "duplicate_key", "non_integer_number", "invalid_shape", "invalid_domain", "not_canonical",
})
_TOP_KEYS = frozenset({
    "schema", "operation", "backend", "outcome", "instrumentation", "metrics", "limits",
})
_METRIC_KEYS = frozenset({"name", "value", "unit", "availability", "basis", "reason"})
_LIMIT_KEYS = frozenset({"name", "value", "unit", "enforcement", "applies_this_call"})


class _MetricPayload(TypedDict):
    name: str
    value: int | None
    unit: str
    availability: str
    basis: str | None
    reason: str | None


class _LimitPayload(TypedDict):
    name: str
    value: int | None
    unit: str
    enforcement: str
    applies_this_call: bool | None


class ResourceReportError(ValueError):
    """A closed, path-free refusal category for report bytes or files."""

    def __init__(self, category: str) -> None:
        if category not in CATEGORIES:
            category = "invalid_domain"
        self.category = category
        super().__init__(f"resource-report-invalid: {category}")


def encode_report(report: ResourceReport | ResourceReportV2) -> bytes:
    """Return the file bytes for a report after the shared domain checks.

    A manually constructed record is validated here too; constructing it is
    not permission to bypass the per-operation slot tables.
    """
    if type(report) is ResourceReportV2:
        check, budget = check_report_domain_v2, MAX_PAYLOAD_BYTES_V2
    elif type(report) is ResourceReport:
        check, budget = check_report_domain, MAX_PAYLOAD_BYTES
    else:
        raise ResourceReportError("invalid_shape")
    try:
        check(report)
        return canonical_bytes(report.to_payload(), budget) + b"\n"
    except CanonicalBoundError:
        raise ResourceReportError("too_large") from None
    except ValueError:
        raise ResourceReportError("invalid_domain") from None


def _depth_within_bound(text: str) -> bool:
    depth = 0
    in_string = escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                return False
        elif character in "]}":
            depth -= 1
    return True


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ResourceReportError("duplicate_key")
        result[key] = value
    return result


def _reject_float(_text: str) -> object:
    raise ResourceReportError("non_integer_number")


def _reject_constant(_text: str) -> object:
    raise ResourceReportError("non_integer_number")


def _parse_int(text: str) -> int:
    try:
        return parse_digits(text, MAX_PAYLOAD_BYTES_V2)
    except ValueError:
        raise ResourceReportError("invalid_domain") from None


def _record(raw: object, keys: frozenset[str]) -> dict[str, object]:
    if type(raw) is not dict or set(raw) != keys:
        raise ResourceReportError("invalid_shape")
    return raw


def _report_from_payload(payload: object) -> ResourceReport | ResourceReportV2:
    top = _record(payload, _TOP_KEYS)
    metrics, limits = top["metrics"], top["limits"]
    if type(metrics) is not list or type(limits) is not list:
        raise ResourceReportError("invalid_shape")
    # The version is selected before any record is constructed or validated,
    # so v1 records never admit a v2-only name, reason, basis or enforcement.
    v2 = top["schema"] == SCHEMA_V2
    metric_type: Any = ResourceMetricV2 if v2 else ResourceMetric
    limit_type: Any = ResourceLimitV2 if v2 else ResourceLimit
    report_type: Any = ResourceReportV2 if v2 else ResourceReport
    try:
        # These casts describe constructor inputs; the closed constructors
        # still validate every untrusted value before any report is returned.
        metric_rows = tuple(
            metric_type(**cast(_MetricPayload, _record(item, _METRIC_KEYS))) for item in metrics
        )
        limit_rows = tuple(
            limit_type(**cast(_LimitPayload, _record(item, _LIMIT_KEYS))) for item in limits
        )
        report = report_type(
            cast(str, top["schema"]), cast(str | None, top["operation"]),
            cast(str | None, top["backend"]), cast(str, top["outcome"]),
            cast(str, top["instrumentation"]), metric_rows, limit_rows,
        )
        (check_report_domain_v2 if v2 else check_report_domain)(report)
    except ResourceReportError:
        raise
    except (TypeError, ValueError):
        raise ResourceReportError("invalid_domain") from None
    return report


def decode_report(data: bytes) -> ResourceReport | ResourceReportV2:
    """Decode file bytes, refusing anything but the exact canonical form."""
    if not isinstance(data, bytes):
        raise ResourceReportError("invalid_shape")
    if len(data) > MAX_FILE_BYTES_V2:
        raise ResourceReportError("too_large")
    if len(data) <= MAX_FILE_BYTES:
        return _decode_bounded(data)
    try:
        report = _decode_bounded(data)
    except ResourceReportError:
        raise ResourceReportError("too_large") from None
    if type(report) is not ResourceReportV2:
        raise ResourceReportError("too_large")
    return report


def _decode_bounded(data: bytes) -> ResourceReport | ResourceReportV2:
    if not data.endswith(b"\n"):
        raise ResourceReportError("not_canonical")
    body = data[:-1]
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise ResourceReportError("not_utf8") from None
    if not _depth_within_bound(text):
        raise ResourceReportError("too_deep")
    try:
        payload = json.loads(
            text, object_pairs_hook=_pairs, parse_float=_reject_float,
            parse_int=_parse_int, parse_constant=_reject_constant,
        )
    except ResourceReportError:
        raise
    except (ValueError, RecursionError):
        raise ResourceReportError("malformed_json") from None
    report = _report_from_payload(payload)
    if encode_report(report) != data:
        raise ResourceReportError("not_canonical")
    return report


__all__ = (
    "CATEGORIES", "MAX_FILE_BYTES", "MAX_FILE_BYTES_V2", "ResourceReportError", "decode_report",
    "encode_report",
)
