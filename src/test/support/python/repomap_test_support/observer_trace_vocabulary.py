"""Closed vocabulary for public-safe observer trace evidence."""

from __future__ import annotations

from enum import Enum
import re


class ObserverTraceEvidenceError(RuntimeError):
    """Trace evidence is incomplete, contradictory, or unsafe to publish."""


class ObserverCaller(str, Enum):
    TELEMETRY_EVENT_APPLICATION = "telemetry_event_application"
    STARTUP_SUMMARY = "startup_summary"
    ACTIVE_SUMMARY = "active_summary"
    PRE_RELEASE_SUMMARY = "pre_release_summary"
    FINAL_STABLE_SAMPLE = "final_stable_sample"
    CONTRACT_VALIDATION = "contract_validation"
    RESOURCE_READ = "resource_read"
    TERMINAL_WAIT = "terminal_wait"
    CLOSE_OR_SETTLEMENT = "close_or_settlement"
    UNKNOWN = "unknown"


class ObserverTraceKind(str, Enum):
    RUN_CALL_ENTRY = "run_call_entry"
    SESSION_OWNER_ACQUIRED = "session_serialization_owner_acquired"
    SESSION_OWNER_RELEASED = "session_serialization_owner_released"
    CALLBACK_DISPATCH = "operation_callback_dispatch"
    CALLBACK_RETURN = "operation_callback_return"
    CALLBACK_RAISE = "operation_callback_raise"
    SESSION_RUN_RETURN = "session_run_return"
    SESSION_RUN_RAISE = "session_run_raise"
    TIMER_SCHEDULED = "timer_scheduled"
    TIMER_ACTUAL_FIRE = "timer_actual_fire"
    CANCELLATION_REQUEST_CREATED = "cancellation_request_created"
    CANCELLATION_DISPATCH_START = "cancellation_dispatch_start"
    CANCELLATION_DISPATCH_FINISH = "cancellation_dispatch_finish"
    CANCEL_SAFE_START = "cancel_safe_start"
    CANCEL_SAFE_RETURN = "cancel_safe_return"
    CANCEL_SAFE_RAISE = "cancel_safe_raise"
    CANCELLATION_OUTCOME = "cancellation_outcome"
    OPERATION_SETTLEMENT = "operation_settlement"
    REQUEST_SETTLEMENT = "request_settlement"
    CLOSE_BEGIN = "close_begin"
    CLOSE_FINISH = "close_finish"
    CLOSE_RAISE = "close_raise"
    PUBLIC_SUMMARY_ENTRY = "public_summary_entry"
    PUBLIC_SUMMARY_RETURN = "public_summary_return"
    PUBLIC_SUMMARY_RAISE = "public_summary_raise"
    BACKEND_ACTIVITY_ENTRY = "read_backend_activity_entry"
    BACKEND_ACTIVITY_RETURN = "read_backend_activity_return"
    BACKEND_ACTIVITY_RAISE = "read_backend_activity_raise"
    BACKEND_IDENTITY_ENTRY = "current_backend_identity_entry"
    BACKEND_IDENTITY_RETURN = "current_backend_identity_return"
    BACKEND_IDENTITY_RAISE = "current_backend_identity_raise"
    SQL_EXECUTE_ENTRY = "psycopg_execute_entry"
    SQL_EXECUTE_RETURN = "psycopg_execute_return"
    SQL_EXECUTE_RAISE = "psycopg_execute_raise"
    SQL_FETCHALL_ENTRY = "psycopg_fetchall_entry"
    SQL_FETCHALL_RETURN = "psycopg_fetchall_return"
    SQL_FETCHALL_RAISE = "psycopg_fetchall_raise"
    SQL_FETCHONE_ENTRY = "psycopg_fetchone_entry"
    SQL_FETCHONE_RETURN = "psycopg_fetchone_return"
    SQL_FETCHONE_RAISE = "psycopg_fetchone_raise"
    FINAL_WINDOW_OPEN = "final_window_open"
    FINAL_WINDOW_FINISH = "final_window_finish"
    FINAL_WINDOW_RAISE = "final_window_raise"
    SUMMARY_VALIDATION_ENTRY = "summary_validation_entry"
    SUMMARY_VALIDATION_RETURN = "summary_validation_return"
    SUMMARY_VALIDATION_RAISE = "summary_validation_raise"
    PORT_STOP_REQUESTED = "port_stop_requested"
    PORT_CONTAINER_STOPPED = "port_container_stop_completion"
    PORT_CONTAINER_REMOVED = "port_container_removal_completion"
    PORT_NETWORK_REMOVED = "port_network_removal_completion"
    PORT_PROCESS_SETTLED = "port_harness_process_settlement"
    PORT_BINDABLE = "port_first_bindable_probe"
    CLEANUP_RESULT = "cleanup_result"


_SAFE_DETAILS = frozenset(
    {
        "backend_monitor_error",
        "cancellation_timeout",
        "client_cancel_fallback",
        "closed",
        "completed",
        "failed",
        "other_error",
        "request_failed",
        "request_succeeded",
        "request_timed_out",
        "server_statement_timeout",
        "unexpected_query_canceled",
    }
)
_SAFE_BOUNDARIES = frozenset(
    {
        "observer_active_summary",
        "observer_connection_create",
        "observer_connection_lost",
        "observer_connection_timeout",
        "observer_construction",
        "observer_contract_validation",
        "observer_event_apply",
        "observer_identity_changed",
        "observer_local_close",
        "observer_operation_execution_timeout",
        "observer_operation_wait_timeout",
        "observer_registration",
        "observer_resource_read",
        "observer_settlement_timeout",
        "observer_startup_summary",
        "observer_terminal_wait",
        "observer_unexpected_cancellation",
        "unknown",
    }
)
_SAFE_OPERATION_CLASSES = frozenset(
    {"connection_startup", "serialization_only", "settlement", "sql_bounded"}
)
_SAFE_SESSION_STATES = frozenset(
    {
        "active",
        "closed",
        "closing",
        "connection_created",
        "constructed",
        "failed",
        "registered",
        "startup_validated",
    }
)
_TOKEN_PATTERN = re.compile(r"(?:session|thread)-[1-9][0-9]*\Z")
_PORT_TOKEN_PATTERN = re.compile(r"port-[1-9][0-9]*\Z")
_LINKED_OPERATION_KINDS = frozenset(
    {
        ObserverTraceKind.SESSION_OWNER_ACQUIRED,
        ObserverTraceKind.SESSION_OWNER_RELEASED,
        ObserverTraceKind.TIMER_SCHEDULED,
        ObserverTraceKind.TIMER_ACTUAL_FIRE,
        ObserverTraceKind.CANCELLATION_REQUEST_CREATED,
        ObserverTraceKind.CANCELLATION_DISPATCH_START,
        ObserverTraceKind.CANCELLATION_DISPATCH_FINISH,
        ObserverTraceKind.CANCEL_SAFE_START,
        ObserverTraceKind.CANCEL_SAFE_RETURN,
        ObserverTraceKind.CANCEL_SAFE_RAISE,
        ObserverTraceKind.CANCELLATION_OUTCOME,
        ObserverTraceKind.OPERATION_SETTLEMENT,
        ObserverTraceKind.REQUEST_SETTLEMENT,
    }
)


__all__ = [
    "ObserverCaller",
    "ObserverTraceEvidenceError",
    "ObserverTraceKind",
]
