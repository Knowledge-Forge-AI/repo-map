"""Runtime instrumentation wrappers for observer trace evidence."""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from inspect import signature
from typing import Iterator

from repomap_test_support.observer_trace_context import (
    _CALLER,
    _TRACE,
    _TraceContext,
    _context_owns_connection,
    _context_values,
    _exception_detail,
    _record_context,
    _seconds_ns,
    _value,
)
from repomap_test_support.observer_trace_boundary import install_boundary_trace_wrappers
from repomap_test_support.observer_trace_evidence import (
    ObserverCaller,
    ObserverTraceKind,
)
from repomap_test_support.observer_trace_lifecycle import install_lifecycle_trace_wrappers
from repomap_test_support.observer_trace_recorder import (
    ObserverTraceRecorder,
    _ActiveOwner,
)


@contextmanager
def _instrument_observer_runtime(
    recorder: ObserverTraceRecorder,
    restorations: list[tuple[object, str, object]],
) -> Iterator[ObserverTraceRecorder]:
    """Install bounded test-only wrappers and restore exact originals."""
    if not recorder.enabled:
        yield recorder
        return
    import psycopg
    import repomap_kg.storage.backend_observer as observer_module
    import scale14_backend_monitor as monitor_module
    import scale28_backend_observer_session as session_module
    import scale28_observer_deadlines as deadline_module

    def patch(owner: object, name: str, replacement: object) -> None:
        restorations.append((owner, name, getattr(owner, name)))
        setattr(owner, name, replacement)

    original_run = session_module.BackendObserverSession.run
    run_parameters = signature(original_run).parameters
    run_category_default = run_parameters["category"].default
    run_timeout_default = run_parameters["timeout_seconds"].default

    @wraps(original_run)
    def traced_run(
        self,
        boundary,
        operation,
        *,
        allowed_states,
        category=run_category_default,
        operation_class=None,
        timeout_seconds=run_timeout_default,
    ):
        session_token = recorder.session_token(self)
        connection = getattr(self, "_connection", None)
        if connection is not None:
            recorder.register_connection(session_token, connection)
        operation_id = recorder.next_operation_id()
        caller = _CALLER.get()
        exact_class = operation_class or self._operation_class_for(boundary)
        entry = recorder.record_with_active_owner(
            ObserverTraceKind.RUN_CALL_ENTRY,
            session_token=session_token,
            operation_id=operation_id,
            boundary=_value(boundary),
            operation_class=_value(exact_class),
            caller=caller,
            caller_thread_token=recorder.thread_token(),
            caller_timeout_ns=_seconds_ns(timeout_seconds),
            remaining_authority_ns=_seconds_ns(timeout_seconds),
            sql_admission_floor_ns=int(
                (self._deadline_policy.minimum_sql_caller_seconds or 0)
                * 1_000_000_000
            ),
            session_state=_value(self._state),
        )
        if entry is None:
            return original_run(
                self,
                boundary,
                operation,
                allowed_states=allowed_states,
                category=category,
                operation_class=exact_class,
                timeout_seconds=timeout_seconds,
            )
        context = _TraceContext(
            recorder,
            session_token,
            operation_id,
            _value(boundary) or "unknown",
            _value(exact_class) or "serialization_only",
            caller,
        )

        @wraps(operation)
        def traced_operation(observer, connection):
            recorder.register_connection(session_token, connection)
            context.generation = int(self._operation_generation)
            owner = recorder.active_owner(session_token)
            if owner is None:
                owner = _ActiveOwner(
                    operation_id,
                    context.boundary or "unknown",
                    context.operation_class or "serialization_only",
                    context.generation,
                    recorder.thread_token(),
                    caller,
                )
                recorder.acquire_owner(session_token, owner)
            nominal = recorder.timer_nominal(
                session_token,
                context.generation,
            )
            dispatch = recorder.record(
                ObserverTraceKind.CALLBACK_DISPATCH,
                duration_from_ns=entry.monotonic_ns,
                remaining_deadline_ns=(
                    nominal if context.operation_class == "sql_bounded" else None
                ),
                owner_thread_token=owner.thread_token,
                **_context_values(context),
            )
            try:
                result = operation(observer, connection)
            except BaseException as error:
                recorder.record(
                    ObserverTraceKind.CALLBACK_RAISE,
                    duration_from_ns=(dispatch.monotonic_ns if dispatch else None),
                    detail=_exception_detail(error),
                    **_context_values(context),
                )
                raise
            recorder.record(
                ObserverTraceKind.CALLBACK_RETURN,
                duration_from_ns=(dispatch.monotonic_ns if dispatch else None),
                **_context_values(context),
            )
            return result

        token = _TRACE.set(context)
        try:
            result = original_run(
                self,
                boundary,
                traced_operation,
                allowed_states=allowed_states,
                category=category,
                operation_class=exact_class,
                timeout_seconds=timeout_seconds,
            )
        except BaseException as error:
            recorder.record(
                ObserverTraceKind.SESSION_RUN_RAISE,
                detail=_exception_detail(error),
                session_state=_value(self._state),
                **_context_values(context),
            )
            raise
        else:
            recorder.record(
                ObserverTraceKind.SESSION_RUN_RETURN,
                session_state=_value(self._state),
                **_context_values(context),
            )
            return result
        finally:
            recorder.discard_owner_after_run(session_token, operation_id)
            _TRACE.reset(token)

    patch(session_module.BackendObserverSession, "run", traced_run)
    original_timer = session_module.Timer

    def traced_timer_start(self):
        context = _TRACE.get()
        if context is not None:
            generation = int(self.args[0]) if self.args else context.generation
            context.generation = generation
            if generation is not None and context.operation_id is not None:
                recorder.acquire_owner(
                    context.session_token,
                    _ActiveOwner(
                        context.operation_id,
                        context.boundary or "unknown",
                        context.operation_class or "serialization_only",
                        generation,
                        recorder.thread_token(),
                        context.caller,
                    ),
                )
            event = recorder.record(
                ObserverTraceKind.TIMER_SCHEDULED,
                nominal_offset_ns=int(self.interval * 1_000_000_000),
                **_context_values(context),
            )
            if event and event.nominal_ns is not None and generation is not None:
                recorder.remember_timer(context.session_token, generation, event.nominal_ns)
        return super(type(self), self).start()

    TracedTimer = type(
        "TracedTimer",
        (original_timer,),
        {"start": traced_timer_start},
    )

    patch(session_module, "Timer", TracedTimer)
    original_expire = session_module.BackendObserverSession._expire_operation

    @wraps(original_expire)
    def traced_expire(self, generation):
        session_token = recorder.session_token(self)
        operation_id = recorder.operation_for_generation(session_token, generation)
        owner = recorder.owner_for_generation(session_token, generation)
        context = _TraceContext(
            recorder,
            session_token,
            operation_id,
            owner.boundary if owner else None,
            owner.operation_class if owner else None,
            owner.caller if owner else ObserverCaller.UNKNOWN,
            generation,
        )
        nominal = recorder.timer_nominal(session_token, generation)
        recorder.record(
            ObserverTraceKind.TIMER_ACTUAL_FIRE,
            session_token=session_token,
            operation_id=operation_id,
            generation=generation,
            boundary=context.boundary,
            operation_class=context.operation_class,
            caller=context.caller,
            caller_thread_token=recorder.thread_token(),
            nominal_ns=nominal,
            nonnegative_duration_from_ns=nominal,
        )
        token = _TRACE.set(context)
        try:
            return original_expire(self, generation)
        finally:
            _TRACE.reset(token)

    patch(session_module.BackendObserverSession, "_expire_operation", traced_expire)
    original_cancel = session_module.BackendObserverSession._cancel_connection

    @wraps(original_cancel)
    def traced_cancel(self, connection, timeout_seconds, generation):
        parent_context = _TRACE.get()
        session_token = recorder.session_token(self)
        recorder.register_connection(session_token, connection)
        operation_id = recorder.operation_for_generation(session_token, generation)
        owner = recorder.owner_for_generation(session_token, generation)
        same_session_parent = (
            parent_context is not None
            and parent_context.session_token == session_token
        )
        caller = (
            parent_context.caller
            if same_session_parent and parent_context is not None
            else owner.caller
            if owner
            else ObserverCaller.CLOSE_OR_SETTLEMENT
        )
        suppress_request_settlement = (
            parent_context.suppress_request_settlement
            if same_session_parent and parent_context is not None
            else False
        )
        if same_session_parent and parent_context is not None:
            parent_context.suppress_request_settlement = False
        context = _TraceContext(
            recorder,
            session_token,
            operation_id,
            owner.boundary if owner else None,
            owner.operation_class if owner else None,
            caller,
            generation,
            suppress_request_settlement,
        )
        start = recorder.record(
            ObserverTraceKind.CANCELLATION_DISPATCH_START,
            caller_timeout_ns=_seconds_ns(timeout_seconds),
            **_context_values(context),
        )
        token = _TRACE.set(context)
        try:
            return original_cancel(self, connection, timeout_seconds, generation)
        finally:
            recorder.record(
                ObserverTraceKind.CANCELLATION_DISPATCH_FINISH,
                duration_from_ns=start.monotonic_ns if start else None,
                **_context_values(context),
            )
            _TRACE.reset(token)

    patch(session_module.BackendObserverSession, "_cancel_connection", traced_cancel)
    install_lifecycle_trace_wrappers(
        recorder=recorder,
        patch=patch,
        session_module=session_module,
        deadline_module=deadline_module,
    )
    original_cancel_safe = psycopg.Connection.cancel_safe
    cancel_safe_timeout_default = signature(original_cancel_safe).parameters[
        "timeout"
    ].default

    @wraps(original_cancel_safe)
    def traced_cancel_safe(self, *, timeout=cancel_safe_timeout_default):
        context = _TRACE.get()
        if context is None or not _context_owns_connection(context, self):
            return original_cancel_safe(self, timeout=timeout)
        _record_context(ObserverTraceKind.CANCEL_SAFE_START)
        try:
            result = original_cancel_safe(self, timeout=timeout)
        except BaseException as error:
            detail = (
                "cancellation_timeout"
                if isinstance(error, psycopg.errors.CancellationTimeout)
                else "other_error"
            )
            _record_context(ObserverTraceKind.CANCEL_SAFE_RAISE, detail=detail)
            raise
        _record_context(ObserverTraceKind.CANCEL_SAFE_RETURN)
        return result

    patch(psycopg.Connection, "cancel_safe", traced_cancel_safe)
    original_record_result = session_module.BackendObserverSession._record_cancellation_result

    @wraps(original_record_result)
    def traced_record_result(self, generation, error):
        result = original_record_result(self, generation, error)
        if isinstance(error, psycopg.errors.CancellationTimeout):
            outcome = "request_timed_out"
        elif error is not None:
            outcome = "request_failed"
        else:
            outcome = "request_succeeded"
        _record_context(ObserverTraceKind.CANCELLATION_OUTCOME, detail=outcome)
        return result

    patch(
        session_module.BackendObserverSession,
        "_record_cancellation_result",
        traced_record_result,
    )
    install_boundary_trace_wrappers(
        recorder=recorder,
        patch=patch,
        psycopg=psycopg,
        observer_module=observer_module,
        monitor_module=monitor_module,
    )
    yield recorder


@contextmanager
def instrument_observer_runtime(recorder: ObserverTraceRecorder) -> Iterator[ObserverTraceRecorder]:
    """Install all runtime wrappers transactionally and restore them on exit."""
    restorations: list[tuple[object, str, object]] = []
    try:
        with _instrument_observer_runtime(recorder, restorations) as active:
            yield active
    finally:
        first_error: BaseException | None = None
        for owner, name, original in reversed(restorations):
            try:
                setattr(owner, name, original)
            except BaseException as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error


__all__ = ["instrument_observer_runtime"]
