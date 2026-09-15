"""Coverage status and presentation helpers for test reports."""

from __future__ import annotations

import html
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


CoverageState = Literal["measured", "disabled", "unavailable", "incomplete"]
_COVERAGE_STATES = frozenset({"measured", "disabled", "unavailable", "incomplete"})


@dataclass(frozen=True)
class CoverageStatus:
    """Typed state for coverage evidence retained by a test report."""

    state: CoverageState
    detail: str = ""
    diagnostics: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.state not in _COVERAGE_STATES:
            raise ValueError(f"unknown coverage state: {self.state!r}")


def normalize_coverage_status(
    coverage: Any,
    status: CoverageStatus | CoverageState | None,
    *,
    detail: str | None = None,
    diagnostics: Sequence[Mapping[str, Any]] = (),
) -> CoverageStatus:
    if isinstance(status, CoverageStatus):
        state = status.state
        status_detail = status.detail
        status_diagnostics = status.diagnostics
    else:
        state = (
            ("measured" if coverage is not None else "unavailable")
            if status is None
            else status
        )
        status_detail = ""
        status_diagnostics = ()
    if detail:
        status_detail = detail
    if diagnostics:
        status_diagnostics = tuple(dict(item) for item in diagnostics)
    return CoverageStatus(
        state=state,
        detail=status_detail,
        diagnostics=tuple(dict(item) for item in status_diagnostics),
    )


def coverage_payload(coverage: Any, status: CoverageStatus) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status.state, "passed": False}
    if status.detail:
        payload["detail"] = status.detail
    if status.diagnostics:
        payload["diagnostics"] = list(status.diagnostics)
    if coverage is None:
        return payload
    payload.update(
        {
            "line": {
                "covered": coverage.covered_lines,
                "total": coverage.total_lines,
                "percent": round(coverage.line_percent, 1),
                "hard_threshold": coverage.line_hard_threshold,
                "warn_threshold": coverage.line_warn_threshold,
                "passed": coverage.line_percent >= coverage.line_hard_threshold,
            },
            "branch": {
                "covered": coverage.covered_branches,
                "total": coverage.total_branches,
                "percent": round(coverage.branch_percent, 1),
                "hard_threshold": coverage.branch_hard_threshold,
                "warn_threshold": coverage.branch_warn_threshold,
                "passed": coverage.branch_percent >= coverage.branch_hard_threshold,
            },
            "passed": status.state == "measured" and coverage.passed,
        }
    )
    return payload


def coverage_badge_status(coverage: Any, status: CoverageStatus) -> str:
    if status.state != "measured":
        return status.state
    return "passed" if coverage is not None and coverage.passed else "failed"


def coverage_notice(status: CoverageStatus) -> str:
    detail = html.escape(status.detail, quote=True)
    diagnostics = (
        f"; {len(status.diagnostics)} diagnostic snapshot(s) retained"
        if status.diagnostics
        else ""
    )
    message = html.escape(f"Coverage is {status.state}{diagnostics}", quote=True)
    if detail:
        message = f"{message}: {detail}"
    return (
        f'<p class="coverage-notice status-{html.escape(status.state)}">{message}</p>'
    )


def obligations_notice(payload: Mapping[str, Any] | None) -> str:
    """Display both obligations without treating missing evidence as success."""
    if payload is None:
        return ""
    from staging_report_contract import qualifies
    outcome = "qualified" if qualifies(payload) else "not qualified"
    parts = [f"Staging evidence: {outcome}"]
    for name in ("M", "A"):
        leg = payload.get("legs", {}).get(name, {})
        measurement = leg.get("measurement", {}).get("state", "unknown")
        parts.append(f"{name}: {leg.get('status', 'unknown')}; measurement {measurement}")
    text = html.escape(". ".join(parts), quote=True)
    return (f'<p class="coverage-notice">{text}. '
            '<a href="staging_contract_report.json">Population and lifecycle evidence</a></p>')


def coverage_unavailable_row(status: CoverageStatus) -> str:
    detail = html.escape(status.detail, quote=True)
    message = f"Coverage {html.escape(status.state)}"
    if detail:
        message += f": {detail}"
    return (
        '<div class="tree-grid row coverage-empty">'
        f'<div class="cell path-cell" colspan="8">{message}</div>'
        "</div>"
    )


def record_report_error(path: Path, error: Exception) -> None:
    """Add a bounded renderer failure to already-persisted report evidence."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["report"] = {
            "status": "failed",
            "error": f"{type(error).__name__}: {str(error).strip()}"[:1000],
        }
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except Exception:
        # Preserve the original rendering failure and the summary written before
        # rendering even if recording the secondary error is unavailable.
        pass


def coverage_error_detail(error: object) -> str:
    """Return a bounded, display-safe measurement diagnostic."""
    if isinstance(error, str):
        detail = error.strip()
    else:
        detail = f"{type(error).__name__}: {error}".strip()
    return detail[:1000] or "coverage failure without a diagnostic"


def coverage_diagnostics(session: object) -> tuple[dict[str, Any], ...]:
    """Convert session snapshots to JSON-safe report evidence."""
    if session is None:
        return ()
    snapshots = getattr(session, "diagnostic_snapshots", ())
    diagnostics: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if hasattr(snapshot, "to_dict"):
            diagnostics.append(dict(snapshot.to_dict()))
        elif isinstance(snapshot, dict):
            diagnostics.append(dict(snapshot))
        else:
            diagnostics.append({"detail": coverage_error_detail(snapshot)})
    return tuple(diagnostics)


def finish_coverage_run(
    coverage_runner: Any,
    *,
    session: Any | None,
    save: bool,
) -> Any:
    """Finish coverage without masking the pytest outcome.

    The caller invokes this helper from a ``finally`` block. Each measurement
    step is therefore recorded on the runner and allowed to complete without
    raising over a returned pytest exit code or a primary pytest exception.
    Combining is skipped when stopping or saving failed because its input is
    not trustworthy; the caller will report the attached instrumentation error.
    """
    final_runner = coverage_runner
    finalization_errors: list[tuple[str, Exception]] = []
    try:
        coverage_runner.stop()
    except Exception as error:
        finalization_errors.append(("stop", error))
    if save:
        try:
            coverage_runner.save()
        except Exception as error:
            finalization_errors.append(("save", error))

    if session is not None and not finalization_errors:
        try:
            reporting_runner = session.combine(coverage_runner)
            if reporting_runner is not None:
                setattr(reporting_runner, "_repomap_session", session)
                final_runner = reporting_runner
        except Exception as error:
            finalization_errors.append(("combine", error))

    if finalization_errors:
        detail = "; ".join(
            f"coverage {stage} failed: {coverage_error_detail(error)}"
            for stage, error in finalization_errors
        )
        existing = getattr(coverage_runner, "_instrumentation_error", None)
        if existing:
            detail = f"{existing}; {detail}"
        setattr(coverage_runner, "_instrumentation_error", detail)
        print(f"WARNING: coverage instrumentation error: {detail}", file=sys.stderr)
    return final_runner


__all__ = (
    "CoverageState",
    "CoverageStatus",
    "coverage_badge_status",
    "coverage_notice",
    "coverage_payload",
    "coverage_unavailable_row",
    "coverage_diagnostics",
    "coverage_error_detail",
    "finish_coverage_run",
    "normalize_coverage_status",
    "record_report_error",
)
