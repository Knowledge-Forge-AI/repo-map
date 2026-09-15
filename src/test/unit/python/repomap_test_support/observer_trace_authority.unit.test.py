from dataclasses import fields, make_dataclass, replace

import pytest

import repomap_test_support.observer_trace as trace_module
import repomap_test_support.observer_trace_context as trace_context_module

from repomap_test_support.observer_trace import (
    ObserverCaller,
    ObserverTraceEvent,
    ObserverTraceEvidenceError,
    ObserverTraceKind,
    ObserverTraceRecorder,
    ObserverTraceSnapshot,
    _ActiveOwner,
)


def _ownership_kind() -> ObserverTraceKind:
    return getattr(
        ObserverTraceKind,
        "SESSION_OWNER_ACQUIRED",
        ObserverTraceKind.CALLBACK_DISPATCH,
    )


def _with_field(
    event: ObserverTraceEvent,
    name: str,
    value: object,
) -> ObserverTraceEvent:
    if name in {item.name for item in fields(event)}:
        corrupted = replace(event)
        # Deliberate invalid fixture: preserve the runtime value for validation.
        object.__setattr__(corrupted, name, value)
        return corrupted
    extended = make_dataclass(
        "ExtendedObserverTraceEvent",
        [(name, object)],
        bases=(ObserverTraceEvent,),
        frozen=True,
        slots=True,
        kw_only=True,
    )
    values = {item.name: getattr(event, item.name) for item in fields(event)}
    return extended(**values, **{name: value})


def _owner_and_waiter() -> ObserverTraceSnapshot:
    recorder = ObserverTraceRecorder()
    recorder.record(
        ObserverTraceKind.RUN_CALL_ENTRY,
        session_token="session-1",
        operation_id=1,
        boundary="observer_active_summary",
        operation_class="sql_bounded",
        caller=ObserverCaller.ACTIVE_SUMMARY,
        caller_thread_token="thread-1",
    )
    recorder.record(
        _ownership_kind(),
        session_token="session-1",
        operation_id=1,
        generation=7,
        boundary="observer_active_summary",
        operation_class="sql_bounded",
        caller=ObserverCaller.ACTIVE_SUMMARY,
        owner_thread_token="thread-1",
    )
    waiting_values = {
        "session_token": "session-1",
        "operation_id": 2,
        "boundary": "observer_resource_read",
        "operation_class": "sql_bounded",
        "caller": ObserverCaller.RESOURCE_READ,
        "caller_thread_token": "thread-2",
        "active_owner_operation_id": 1,
        "active_owner_boundary": "observer_active_summary",
        "active_owner_generation": 7,
        "active_owner_thread_token": "thread-1",
        "active_owner_caller": ObserverCaller.ACTIVE_SUMMARY,
    }
    if "active_owner_operation_class" in {
        item.name for item in fields(ObserverTraceEvent)
    }:
        waiting_values["active_owner_operation_class"] = "sql_bounded"
    recorder.record(ObserverTraceKind.RUN_CALL_ENTRY, **waiting_values)
    return recorder.snapshot()


@pytest.mark.parametrize("method_name", ("validate", "to_public_payload"))
def test_active_owner_caller_rejects_private_value_before_serialization(
    method_name: str,
) -> None:
    recorder = ObserverTraceRecorder()
    event = recorder.record(ObserverTraceKind.RUN_CALL_ENTRY)
    assert event is not None
    corrupted = replace(event)
    # The enum field deliberately contains an invalid raw string.
    object.__setattr__(corrupted, "active_owner_caller", "private-value")
    assert event.active_owner_caller is None
    assert corrupted.active_owner_caller == "private-value"
    snapshot = ObserverTraceSnapshot((corrupted,))

    with pytest.raises(ObserverTraceEvidenceError):
        getattr(snapshot, method_name)()


@pytest.mark.parametrize(
    ("field_name", "incorrect_value"),
    (
        ("active_owner_boundary", "observer_resource_read"),
        ("active_owner_operation_class", "serialization_only"),
        ("active_owner_generation", 8),
        ("active_owner_caller", ObserverCaller.RESOURCE_READ),
        ("active_owner_thread_token", "thread-9"),
    ),
)
def test_active_owner_metadata_must_match_exact_owner(
    field_name: str,
    incorrect_value: object,
) -> None:
    snapshot = _owner_and_waiter()
    waiting = _with_field(snapshot.events[-1], field_name, incorrect_value)
    mutated = replace(snapshot, events=(*snapshot.events[:-1], waiting))

    with pytest.raises(ObserverTraceEvidenceError, match="active owner"):
        mutated.validate()


def test_duplicate_run_entry_for_one_operation_is_rejected() -> None:
    recorder = ObserverTraceRecorder()
    for _ in range(2):
        recorder.record(
            ObserverTraceKind.RUN_CALL_ENTRY,
            session_token="session-1",
            operation_id=1,
        )

    with pytest.raises(ObserverTraceEvidenceError, match="run entry"):
        recorder.snapshot()


def test_completed_operation_cannot_be_projected_as_active_owner() -> None:
    snapshot = _owner_and_waiter()
    terminal = replace(
        snapshot.events[1],
        sequence=3,
        kind=ObserverTraceKind.SESSION_RUN_RETURN,
    )
    waiting = replace(snapshot.events[2], sequence=4)
    completed = replace(
        snapshot,
        events=(snapshot.events[0], snapshot.events[1], terminal, waiting),
    )

    with pytest.raises(ObserverTraceEvidenceError, match="active owner"):
        completed.validate()


def test_active_owner_projection_is_appended_under_one_recorder_lock() -> None:
    recorder = ObserverTraceRecorder()
    owner = _ActiveOwner(
        1,
        "observer_active_summary",
        "sql_bounded",
        7,
        "thread-1",
        ObserverCaller.ACTIVE_SUMMARY,
    )
    recorder.record(
        ObserverTraceKind.RUN_CALL_ENTRY,
        session_token="session-1",
        operation_id=1,
        boundary=owner.boundary,
        operation_class=owner.operation_class,
        caller=owner.caller,
    )
    recorder.acquire_owner("session-1", owner)

    waiting = recorder.record_with_active_owner(
        ObserverTraceKind.RUN_CALL_ENTRY,
        session_token="session-1",
        operation_id=2,
        boundary="observer_resource_read",
        operation_class="sql_bounded",
        caller=ObserverCaller.RESOURCE_READ,
    )

    assert waiting is not None
    assert waiting.active_owner_operation_id == owner.operation_id
    assert waiting.active_owner_operation_class == owner.operation_class
    recorder.snapshot()


def test_disabled_recorder_public_append_paths_retain_no_state() -> None:
    recorder = ObserverTraceRecorder(enabled=False)
    owner = _ActiveOwner(
        1,
        "observer_active_summary",
        "sql_bounded",
        7,
        "thread-1",
        ObserverCaller.ACTIVE_SUMMARY,
    )

    recorder.acquire_owner("session-1", owner)
    assert recorder.session_token(object()) == "session-1"
    assert recorder.thread_token() == "thread-1"
    assert recorder.next_operation_id() == 1
    assert recorder.next_operation_id() == 1
    recorder.register_connection("session-1", object())
    recorder.remember_timer("session-1", 7, 100)
    recorder.settle_and_release_owner("session-1", 1)
    recorder.discard_owner_after_run("session-1", 1)

    assert recorder.active_owner("session-1") is None
    assert recorder.timer_nominal("session-1", 7) is None
    assert recorder._sessions == {}
    assert recorder._threads == {}
    assert recorder._connections == {}
    assert recorder._next_operation == 1
    assert recorder.snapshot().events == ()


def test_facade_context_anchors_preserve_owner_and_nested_reset() -> None:
    assert trace_module._TraceContext is trace_context_module._TraceContext
    assert trace_module._TRACE is trace_context_module._TRACE
    previous = trace_context_module._TRACE.get()
    context = trace_module._TraceContext(
        ObserverTraceRecorder(),
        "session-1",
        None,
        "unknown",
        "settlement",
        ObserverCaller.CLOSE_OR_SETTLEMENT,
    )
    outer_token = trace_module._TRACE.set(context)
    try:
        inner_token = trace_context_module._TRACE.set(None)
        try:
            assert trace_module._TRACE.get() is None
        finally:
            trace_module._TRACE.reset(inner_token)
        assert trace_context_module._TRACE.get() is context
    finally:
        trace_module._TRACE.reset(outer_token)
    assert trace_context_module._TRACE.get() is previous
