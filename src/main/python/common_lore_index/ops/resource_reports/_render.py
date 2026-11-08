"""Bounded human rendering of a validated resource report.

Each metric and limit is an individual row, so a huge count widens only its
own row instead of being padded into every row of a table. Integer text uses
the chunked canonical renderer, independent of the interpreter's conversion
limit. Rendering states format validity only, never authenticity.
"""

from __future__ import annotations

from common_lore_index.ops.resource_view._canonical import render_int
from common_lore_index.ops.resource_view._contracts import MAX_PAYLOAD_BYTES, ResourceReport
from common_lore_index.ops.resource_view._contracts_v2 import ResourceReportV2


def _number(value: int | None) -> str:
    # Every closed integer of either schema renders within the v1 payload bound.
    return "unavailable" if value is None else render_int(value, MAX_PAYLOAD_BYTES)


def _flag(value: bool | None) -> str:
    return "unknown" if value is None else "yes" if value else "no"


def render_report_text(report: ResourceReport | ResourceReportV2) -> str:
    """Return a line-oriented summary; values come only from closed fields."""
    lines = [
        f"schema: {report.schema}",
        "validation: format and domain only (not authenticity or measurement truth)",
        f"operation: {report.operation or 'none'}",
        f"backend: {report.backend or 'none'}",
        f"outcome: {report.outcome}",
        f"instrumentation: {report.instrumentation}",
        f"metrics: {len(report.metrics)}",
    ]
    for metric in report.metrics:
        detail = (
            f"measured, {metric.basis}" if metric.reason is None
            else f"unavailable: {metric.reason}"
        )
        lines.append(f"  {metric.name}: {_number(metric.value)} {metric.unit} ({detail})")
    lines.append(f"limits: {len(report.limits)}")
    for limit in report.limits:
        lines.append(
            f"  {limit.name}: {_number(limit.value)} {limit.unit} "
            f"({limit.enforcement}, applies this call: {_flag(limit.applies_this_call)})"
        )
    return "\n".join(lines)


def render_check_text(report: ResourceReport | ResourceReportV2) -> str:
    return (
        f"valid {report.schema}: operation {report.operation or 'none'}, "
        f"outcome {report.outcome}, instrumentation {report.instrumentation}"
    )


__all__ = ("render_check_text", "render_report_text")
