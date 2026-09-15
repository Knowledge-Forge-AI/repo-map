"""Session close and cancellation-state trace wrappers."""

from __future__ import annotations

from functools import wraps
from inspect import signature
from typing import Callable

from repomap_test_support.observer_trace_context import (
    _TRACE,
    _TraceContext,
    _exception_detail,
    _record_context,
    _seconds_ns,
    _value,
)
from repomap_test_support.observer_trace_evidence import (
    ObserverCaller,
    ObserverTraceKind,
)
from repomap_test_support.observer_trace_recorder import ObserverTraceRecorder


def install_lifecycle_trace_wrappers(
    *,
    recorder: ObserverTraceRecorder,
    patch: Callable[[object, str, object], None],
    session_module,
    deadline_module,
) -> None:
    """Install close and cancellation-state wrappers on owned classes."""
    session_type = session_module.BackendObserverSession
    deadline_state = deadline_module.ObserverCancellationState
    original_close = session_type.close
    close_timeout_default = signature(original_close).parameters["timeout_seconds"].default

    @wraps(original_close)
    def traced_close(self, timeout_seconds=close_timeout_default):
        session_token = recorder.session_token(self)
        context = _TraceContext(
            recorder,
            session_token,
            None,
            "unknown",
            "settlement",
            ObserverCaller.CLOSE_OR_SETTLEMENT,
        )
        begin = recorder.record_with_active_owner(
            ObserverTraceKind.CLOSE_BEGIN,
            session_token=session_token,
            caller=ObserverCaller.CLOSE_OR_SETTLEMENT,
            caller_thread_token=recorder.thread_token(),
            caller_timeout_ns=_seconds_ns(timeout_seconds),
            session_state=_value(self._state),
        )
        token = _TRACE.set(context)
        try:
            result = original_close(self, timeout_seconds)
        except BaseException as error:
            recorder.record(
                ObserverTraceKind.CLOSE_RAISE,
                session_token=session_token,
                duration_from_ns=begin.monotonic_ns if begin else None,
                detail=_exception_detail(error),
                session_state=_value(self._state),
            )
            raise
        else:
            recorder.record(
                ObserverTraceKind.CLOSE_FINISH,
                session_token=session_token,
                duration_from_ns=begin.monotonic_ns if begin else None,
                detail="closed",
                session_state=_value(self._state),
            )
            return result
        finally:
            _TRACE.reset(token)

    patch(session_type, "close", traced_close)
    state_methods = (
        ("request", ObserverTraceKind.CANCELLATION_REQUEST_CREATED),
        ("record_request_outcome", ObserverTraceKind.REQUEST_SETTLEMENT),
        ("settle_operation", ObserverTraceKind.OPERATION_SETTLEMENT),
    )
    for method_name, request_kind in state_methods:
        original = getattr(deadline_state, method_name)

        def make_state_wrapper(exact_original, exact_kind):
            @wraps(exact_original)
            def state_wrapper(self, *args, **kwargs):
                result = exact_original(self, *args, **kwargs)
                context = _TRACE.get()
                if (
                    exact_kind is ObserverTraceKind.OPERATION_SETTLEMENT
                    and context is not None
                    and context.operation_id is not None
                ):
                    context.recorder.settle_and_release_owner(
                        context.session_token,
                        context.operation_id,
                    )
                    return result
                detail = None
                if exact_kind is ObserverTraceKind.REQUEST_SETTLEMENT:
                    detail = _value(result.request_outcome)
                    if context is not None and context.suppress_request_settlement:
                        context.suppress_request_settlement = False
                        return result
                if (
                    context is not None
                    and context.operation_id is None
                    and exact_kind
                    in {
                        ObserverTraceKind.CANCELLATION_REQUEST_CREATED,
                        ObserverTraceKind.REQUEST_SETTLEMENT,
                    }
                ):
                    event = context.recorder.record_for_active_operation(
                        exact_kind,
                        session_token=context.session_token,
                        caller=context.caller,
                        detail=detail,
                    )
                    if (
                        exact_kind is ObserverTraceKind.CANCELLATION_REQUEST_CREATED
                        and event is None
                    ):
                        context.suppress_request_settlement = True
                    return result
                _record_context(exact_kind, detail=detail)
                return result

            return state_wrapper

        patch(
            deadline_state,
            method_name,
            make_state_wrapper(original, request_kind),
        )


__all__ = ["install_lifecycle_trace_wrappers"]
