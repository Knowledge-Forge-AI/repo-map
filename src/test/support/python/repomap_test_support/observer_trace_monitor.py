"""Backend-monitor caller and final-release trace installation."""

from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
from typing import Callable, Protocol

from repomap_test_support.observer_trace_evidence import (
    ObserverCaller,
    ObserverTraceEvent,
    ObserverTraceKind,
)


class _TraceRecorder(Protocol):
    def session_token(self, session: object) -> str: ...

    def thread_token(self) -> str: ...

    def record(
        self,
        kind: ObserverTraceKind,
        *,
        duration_from_ns: int | None = None,
        nonnegative_duration_from_ns: int | None = None,
        nominal_offset_ns: int | None = None,
        remaining_deadline_ns: int | None = None,
        detail: str | None = None,
        **values: object,
    ) -> ObserverTraceEvent | None: ...


def install_monitor_trace_wrappers(
    *,
    recorder: _TraceRecorder,
    monitor_type,
    patch: Callable[[object, str, object], None],
    caller_context: ContextVar[ObserverCaller],
    seconds_ns: Callable[[object], int | None],
    exception_detail: Callable[[BaseException], str],
) -> None:
    """Install monitor-owned caller and final-release observation wrappers."""
    caller_methods = {
        "startup_summary": ObserverCaller.STARTUP_SUMMARY,
        "summary": ObserverCaller.ACTIVE_SUMMARY,
        "pre_release_summary": ObserverCaller.PRE_RELEASE_SUMMARY,
        "validate_summary": ObserverCaller.CONTRACT_VALIDATION,
        "read": ObserverCaller.RESOURCE_READ,
        "wait_quiescent": ObserverCaller.TERMINAL_WAIT,
        "_consume": ObserverCaller.TELEMETRY_EVENT_APPLICATION,
    }
    for name, caller in caller_methods.items():
        original = getattr(monitor_type, name)

        def make_caller_wrapper(exact_original, exact_caller):
            @wraps(exact_original)
            def caller_wrapper(*args, **kwargs):
                token = caller_context.set(exact_caller)
                try:
                    return exact_original(*args, **kwargs)
                finally:
                    caller_context.reset(token)

            return caller_wrapper

        patch(monitor_type, name, make_caller_wrapper(original, caller))

    original_release = monitor_type.release_when_ready

    @wraps(original_release)
    def traced_release(self, release, summary_validator, **kwargs):
        session_token = recorder.session_token(self._session)
        supplied_timeout = kwargs.get("timeout_seconds")
        timeout = (
            self._deadline_policy.final_release_timeout_seconds
            if supplied_timeout is None
            else supplied_timeout
        )
        opened = recorder.record(
            ObserverTraceKind.FINAL_WINDOW_OPEN,
            session_token=session_token,
            caller=ObserverCaller.FINAL_STABLE_SAMPLE,
            caller_thread_token=recorder.thread_token(),
            caller_timeout_ns=seconds_ns(timeout),
            remaining_authority_ns=seconds_ns(timeout),
        )

        @wraps(summary_validator)
        def traced_validator(summary):
            recorder.record(
                ObserverTraceKind.SUMMARY_VALIDATION_ENTRY,
                session_token=session_token,
                caller=ObserverCaller.FINAL_STABLE_SAMPLE,
            )
            try:
                result = summary_validator(summary)
            except BaseException as error:
                recorder.record(
                    ObserverTraceKind.SUMMARY_VALIDATION_RAISE,
                    session_token=session_token,
                    caller=ObserverCaller.FINAL_STABLE_SAMPLE,
                    detail=exception_detail(error),
                )
                raise
            recorder.record(
                ObserverTraceKind.SUMMARY_VALIDATION_RETURN,
                session_token=session_token,
                caller=ObserverCaller.FINAL_STABLE_SAMPLE,
            )
            return result

        token = caller_context.set(ObserverCaller.FINAL_STABLE_SAMPLE)
        try:
            result = original_release(self, release, traced_validator, **kwargs)
        except BaseException as error:
            recorder.record(
                ObserverTraceKind.FINAL_WINDOW_RAISE,
                session_token=session_token,
                caller=ObserverCaller.FINAL_STABLE_SAMPLE,
                duration_from_ns=(opened.monotonic_ns if opened else None),
                detail=exception_detail(error),
            )
            raise
        finally:
            caller_context.reset(token)
        recorder.record(
            ObserverTraceKind.FINAL_WINDOW_FINISH,
            session_token=session_token,
            caller=ObserverCaller.FINAL_STABLE_SAMPLE,
            duration_from_ns=(opened.monotonic_ns if opened else None),
        )
        return result

    patch(monitor_type, "release_when_ready", traced_release)


__all__ = ["install_monitor_trace_wrappers"]
