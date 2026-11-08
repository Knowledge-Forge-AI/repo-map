"""Invocation-owned ``--resource-report`` session for single-operation seams.

One parsed Namespace owns at most one session and one admitted destination,
including across the repeated SQLite dispatcher seam. Ownership is explicit on
the Namespace; there is no global or thread-local state. Without the option
every helper is a no-op and no observer keyword is forwarded.

Delivery runs after stdout and the exit code are fixed and outside every
subject catch block. Ordinary delivery, report or cleanup errors print one
fixed, path-free warning and never change the subject's exit code. Uncaught
subject exceptions produce no report; the session is only closed, which can
never replace them. A delivery-only interrupt propagates after cleanup.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
import sys
from typing import Any

from common_lore_index.ops.resource_reports._admission import (
    ResourceReportRefusal, admit_report_destination, configured_roots,
)
from common_lore_index.ops.resource_reports._codec import ResourceReportError, encode_report
from common_lore_index.ops.resource_reports._delivery import AdmittedDestination, DeliveryError, deliver
from common_lore_index.ops.resource_view import ResourceObserver
from common_lore_index.ops.resource_view._contracts import ResourceReport
from common_lore_index.ops.resource_view._contracts_v2 import SCHEMA_V2, ResourceReportV2, upgrade_report

_SESSION_ATTRIBUTE = "_cloe_resource_report_session"
ReportFactory = Callable[[], ResourceReport | ResourceReportV2]


def _warning(message: str) -> None:
    """A secondary warning sink cannot change the completed subject result."""
    try:
        print(message, file=sys.stderr)
    except Exception:
        pass


class ResourceReportSession:
    """One explicit destination plus the observer for one subject call."""

    __slots__ = ("_text", "_destination", "_attempted", "observer")

    def __init__(self, text: str, schema: int | None = None) -> None:
        self._text = text
        self._destination: AdmittedDestination | None = None
        self._attempted = False
        # Schema 2 is explicit (``--resource-report-schema 2``); v1 stays the default.
        self.observer = (
            ResourceObserver(report_schema=SCHEMA_V2) if schema == 2 else ResourceObserver()
        )

    @property
    def admitted(self) -> bool:
        return self._destination is not None and self._destination.descriptor is not None

    def admit(self, config: object, *, overrides: Iterable[object] = ()) -> None:
        if self._attempted:
            raise ResourceReportRefusal("already_admitted")
        self._attempted = True
        self._destination = admit_report_destination(
            self._text, configured_roots(config, overrides=overrides),
        )

    def deliver(self, factory: ReportFactory | None) -> None:
        destination = self._destination
        if destination is None or destination.descriptor is None:
            return
        try:
            sys.stdout.flush()
        except Exception:
            pass  # stdout custody belongs to the subject; delivery stays independent
        try:
            report = factory() if factory is not None else self.observer.report()
            if self.observer.report_schema == SCHEMA_V2 and type(report) is ResourceReport:
                report = upgrade_report(report)  # equal lexical/context tables, explicit v2
            deliver(destination, encode_report(report))
        except DeliveryError as error:
            state = "incomplete" if error.installed else "not-delivered"
            _warning(f"WARNING: resource-report-{state}: {error.category}")
        except ResourceReportError as error:
            _warning(f"WARNING: resource-report-not-delivered: {error.category}")
        except Exception:
            _warning("WARNING: resource-report-not-delivered: report_unavailable")

    def close(self) -> None:
        destination = self._destination
        if destination is not None:
            destination.close()


def report_session(args: argparse.Namespace) -> ResourceReportSession | None:
    """Return this Namespace's session, creating it once when the option is set."""
    text = getattr(args, "resource_report", None)
    if text is None:
        return None
    session = getattr(args, _SESSION_ATTRIBUTE, None)
    if not isinstance(session, ResourceReportSession):
        session = ResourceReportSession(str(text), getattr(args, "resource_report_schema", None))
        setattr(args, _SESSION_ATTRIBUTE, session)
    return session


def admit_report(
    args: argparse.Namespace, config: object, *, overrides: Iterable[object] = ()
) -> ResourceReportSession | None:
    """Admit after existing refusals and config resolution, before DB/source work."""
    session = report_session(args)
    if session is not None:
        session.admit(config, overrides=overrides)
    return session


def report_observer_kwargs(session: ResourceReportSession | None) -> dict[str, Any]:
    if session is None or not session.admitted:
        return {}
    return {"resource_observer": session.observer}


def finish_report(
    session: ResourceReportSession | None, exit_code: int, factory: ReportFactory | None = None,
) -> int:
    """Deliver after the subject fixed stdout and its exit code; return that code."""
    if session is None:
        return exit_code
    try:
        session.deliver(factory)
    except Exception:
        _warning("WARNING: resource-report-not-delivered: report_unavailable")
    except BaseException:
        _close_session(session, preserve_primary=True)
        raise
    else:
        _close_session(session)
        return exit_code
    _close_session(session)
    return exit_code


def _close_session(session: ResourceReportSession, *, preserve_primary: bool = False) -> None:
    try:
        session.close()
    except BaseException as error:
        if preserve_primary:
            return  # The caller re-raises its exact active exception.
        if isinstance(error, Exception):
            _warning("WARNING: resource-report-incomplete: cleanup_failed")
        else:
            raise


def close_report_session(
    session: ResourceReportSession | None, *, preserve_primary: bool = False,
) -> None:
    if session is not None:
        _close_session(session, preserve_primary=preserve_primary)


def release_report_session(args: argparse.Namespace, *, preserve_primary: bool = False) -> None:
    """Release the invocation, preserving any active primary exception."""
    session = getattr(args, _SESSION_ATTRIBUTE, None)
    if isinstance(session, ResourceReportSession):
        close_report_session(session, preserve_primary=preserve_primary)


__all__ = (
    "ResourceReportRefusal", "ResourceReportSession", "admit_report", "close_report_session",
    "finish_report", "release_report_session", "report_observer_kwargs", "report_session",
)
