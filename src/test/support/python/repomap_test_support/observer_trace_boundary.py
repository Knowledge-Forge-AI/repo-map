"""SQL, observer, and monitor boundary trace wrappers."""

from __future__ import annotations

from functools import wraps
from typing import Callable

from repomap_test_support.observer_trace_context import (
    _CALLER,
    _TRACE,
    _context_owns_connection,
    _exception_detail,
    _record_context,
    _seconds_ns,
)
from repomap_test_support.observer_trace_evidence import (
    ObserverTraceKind,
)
from repomap_test_support.observer_trace_monitor import install_monitor_trace_wrappers
from repomap_test_support.observer_trace_recorder import ObserverTraceRecorder


def install_boundary_trace_wrappers(
    *,
    recorder: ObserverTraceRecorder,
    patch: Callable[[object, str, object], None],
    psycopg,
    observer_module,
    monitor_module,
) -> None:
    """Install wrappers for SQL, observer, and monitor-owned boundaries."""
    patch_boundary_targets = (
        (
            psycopg.Connection,
            "execute",
            ObserverTraceKind.SQL_EXECUTE_ENTRY,
            ObserverTraceKind.SQL_EXECUTE_RETURN,
            ObserverTraceKind.SQL_EXECUTE_RAISE,
        ),
        (
            psycopg.Cursor,
            "fetchall",
            ObserverTraceKind.SQL_FETCHALL_ENTRY,
            ObserverTraceKind.SQL_FETCHALL_RETURN,
            ObserverTraceKind.SQL_FETCHALL_RAISE,
        ),
        (
            psycopg.Cursor,
            "fetchone",
            ObserverTraceKind.SQL_FETCHONE_ENTRY,
            ObserverTraceKind.SQL_FETCHONE_RETURN,
            ObserverTraceKind.SQL_FETCHONE_RAISE,
        ),
    )

    def patch_boundary(
        owner,
        name,
        entry_kind,
        return_kind,
        raise_kind,
        *,
        connection_scoped=False,
    ):
        original = getattr(owner, name)

        @wraps(original)
        def wrapper(*args, **kwargs):
            context = _TRACE.get()
            if (
                connection_scoped
                and (
                    context is None
                    or not args
                    or not _context_owns_connection(context, args[0])
                )
            ):
                return original(*args, **kwargs)
            _record_context(entry_kind)
            try:
                result = original(*args, **kwargs)
            except BaseException as error:
                _record_context(raise_kind, detail=_exception_detail(error))
                raise
            _record_context(return_kind)
            return result

        patch(owner, name, wrapper)

    for target in patch_boundary_targets:
        patch_boundary(*target, connection_scoped=True)
    patch_boundary(
        observer_module.BackendOwnershipObserver,
        "public_summary",
        ObserverTraceKind.PUBLIC_SUMMARY_ENTRY,
        ObserverTraceKind.PUBLIC_SUMMARY_RETURN,
        ObserverTraceKind.PUBLIC_SUMMARY_RAISE,
    )
    patch_boundary(
        observer_module,
        "read_backend_activity",
        ObserverTraceKind.BACKEND_ACTIVITY_ENTRY,
        ObserverTraceKind.BACKEND_ACTIVITY_RETURN,
        ObserverTraceKind.BACKEND_ACTIVITY_RAISE,
    )
    patch_boundary(
        observer_module,
        "current_backend_identity",
        ObserverTraceKind.BACKEND_IDENTITY_ENTRY,
        ObserverTraceKind.BACKEND_IDENTITY_RETURN,
        ObserverTraceKind.BACKEND_IDENTITY_RAISE,
    )
    install_monitor_trace_wrappers(
        recorder=recorder,
        monitor_type=monitor_module.BackendOwnershipMonitor,
        patch=patch,
        caller_context=_CALLER,
        seconds_ns=_seconds_ns,
        exception_detail=_exception_detail,
    )


__all__ = ["install_boundary_trace_wrappers"]
