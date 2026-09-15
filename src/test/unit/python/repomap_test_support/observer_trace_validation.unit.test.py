from dataclasses import replace

import pytest

from repomap_test_support.observer_trace import (
    ObserverCaller,
    ObserverTraceEvent,
    ObserverTraceEvidenceError,
    ObserverTraceKind,
    ObserverTraceSnapshot,
)


def _event(
    sequence: int,
    kind: ObserverTraceKind,
    *,
    operation_id: int | None = 1,
    session_token: str | None = "session-1",
    **values,
) -> ObserverTraceEvent:
    return ObserverTraceEvent(
        sequence,
        sequence,
        kind,
        session_token=session_token,
        operation_id=operation_id,
        **values,
    )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("kind", "private-kind"),
        ("caller", "private-caller"),
        ("active_owner_caller", "private-owner"),
        ("session_token", "private-session"),
        ("port_token", "private-port"),
        ("boundary", "private-boundary"),
        ("operation_class", "private-class"),
        ("caller_thread_token", "private-thread"),
        ("owner_thread_token", "private-thread"),
        ("active_owner_boundary", "private-boundary"),
        ("active_owner_operation_class", "private-class"),
        ("active_owner_thread_token", "private-thread"),
        ("session_state", "private-state"),
        ("detail", "private-detail"),
    ),
)
def test_every_public_string_or_enum_field_has_closed_validation(
    field_name: str,
    invalid_value: object,
) -> None:
    event = ObserverTraceEvent(1, 1, ObserverTraceKind.RUN_CALL_ENTRY)
    corrupted = replace(event)
    # Inject the exact invalid value without changing the event runtime class.
    object.__setattr__(corrupted, field_name, invalid_value)
    assert type(corrupted) is ObserverTraceEvent
    assert getattr(corrupted, field_name) == invalid_value
    snapshot = ObserverTraceSnapshot((corrupted,))

    with pytest.raises(ObserverTraceEvidenceError):
        snapshot.to_public_payload()


@pytest.mark.parametrize(
    "field_name",
    (
        "sequence",
        "monotonic_ns",
        "operation_id",
        "generation",
        "caller_timeout_ns",
        "remaining_authority_ns",
        "sql_admission_floor_ns",
        "duration_ns",
        "nominal_ns",
        "active_owner_operation_id",
        "active_owner_generation",
    ),
)
@pytest.mark.parametrize("invalid_value", (True, 1.5, -1))
def test_every_public_numeric_field_rejects_bool_float_and_negative(
    field_name: str,
    invalid_value: object,
) -> None:
    event = ObserverTraceEvent(1, 1, ObserverTraceKind.RUN_CALL_ENTRY)
    corrupted = replace(event)
    # Inject the exact invalid value without changing the event runtime class.
    object.__setattr__(corrupted, field_name, invalid_value)
    assert type(corrupted) is ObserverTraceEvent
    assert getattr(corrupted, field_name) == invalid_value
    snapshot = ObserverTraceSnapshot((corrupted,))

    with pytest.raises(ObserverTraceEvidenceError):
        snapshot.validate()


@pytest.mark.parametrize(
    "events",
    (
        (_event(1, ObserverTraceKind.CALLBACK_DISPATCH),),
        (_event(1, ObserverTraceKind.RUN_CALL_ENTRY, session_token=None),),
        (
            _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
            _event(2, ObserverTraceKind.CALLBACK_RETURN),
            _event(3, ObserverTraceKind.CALLBACK_DISPATCH),
        ),
        (
            _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
            _event(2, ObserverTraceKind.REQUEST_SETTLEMENT),
            _event(3, ObserverTraceKind.CANCELLATION_REQUEST_CREATED),
        ),
        (
            _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
            _event(2, ObserverTraceKind.OPERATION_SETTLEMENT),
        ),
        (
            _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
            _event(2, ObserverTraceKind.SESSION_OWNER_RELEASED),
        ),
        (
            _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
            _event(2, ObserverTraceKind.CALLBACK_DISPATCH),
            _event(3, ObserverTraceKind.CALLBACK_RETURN),
            _event(4, ObserverTraceKind.CALLBACK_RAISE),
        ),
        (
            _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
            _event(2, ObserverTraceKind.SESSION_RUN_RETURN),
            _event(3, ObserverTraceKind.SESSION_RUN_RAISE),
        ),
    ),
)
def test_operation_trace_structure_rejects_incoherent_groups(events) -> None:
    with pytest.raises(ObserverTraceEvidenceError):
        ObserverTraceSnapshot(events).operation_traces()


def _owner(sequence: int, kind: ObserverTraceKind, operation_id: int = 1):
    return _event(
        sequence,
        kind,
        operation_id=operation_id,
        generation=7,
        boundary="observer_active_summary",
        operation_class="sql_bounded",
        caller=ObserverCaller.ACTIVE_SUMMARY,
        owner_thread_token="thread-1",
    )


def _waiter(sequence: int, *, session_token: str = "session-1"):
    return _event(
        sequence,
        ObserverTraceKind.RUN_CALL_ENTRY,
        operation_id=2,
        session_token=session_token,
        active_owner_operation_id=1,
        active_owner_boundary="observer_active_summary",
        active_owner_operation_class="sql_bounded",
        active_owner_generation=7,
        active_owner_thread_token="thread-1",
        active_owner_caller=ObserverCaller.ACTIVE_SUMMARY,
    )


@pytest.mark.parametrize(
    "events",
    (
        (
            _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
            _waiter(2),
            _owner(3, ObserverTraceKind.SESSION_OWNER_ACQUIRED),
        ),
        (
            _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
            _waiter(2),
        ),
        (
            _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
            _owner(2, ObserverTraceKind.SESSION_OWNER_ACQUIRED),
            _owner(3, ObserverTraceKind.SESSION_OWNER_RELEASED),
            _waiter(4),
        ),
        (
            _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
            _owner(2, ObserverTraceKind.SESSION_OWNER_ACQUIRED),
            _waiter(3, session_token="session-2"),
        ),
        (
            _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
            replace(
                _owner(2, ObserverTraceKind.SESSION_OWNER_ACQUIRED),
                active_owner_operation_id=1,
                active_owner_boundary="observer_active_summary",
                active_owner_operation_class="sql_bounded",
                active_owner_generation=7,
                active_owner_thread_token="thread-1",
                active_owner_caller=ObserverCaller.ACTIVE_SUMMARY,
            ),
        ),
    ),
)
def test_active_owner_rejects_future_missing_released_foreign_and_self(events) -> None:
    with pytest.raises(ObserverTraceEvidenceError, match="active owner"):
        ObserverTraceSnapshot(events).validate()


def test_generation_binding_cannot_be_reused_by_another_operation() -> None:
    events = (
        _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
        _owner(2, ObserverTraceKind.SESSION_OWNER_ACQUIRED),
        _owner(3, ObserverTraceKind.SESSION_OWNER_RELEASED),
        _event(4, ObserverTraceKind.RUN_CALL_ENTRY, operation_id=2),
        _owner(5, ObserverTraceKind.SESSION_OWNER_ACQUIRED, operation_id=2),
    )

    with pytest.raises(ObserverTraceEvidenceError, match="generation binding"):
        ObserverTraceSnapshot(events).validate()


def test_late_generation_binding_resolves_earlier_cancellation_event() -> None:
    events = (
        _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
        _event(
            2,
            ObserverTraceKind.CANCELLATION_DISPATCH_START,
            operation_id=None,
            generation=7,
            boundary=None,
            operation_class=None,
        ),
        _owner(3, ObserverTraceKind.SESSION_OWNER_ACQUIRED),
    )

    traces = ObserverTraceSnapshot(events).operation_traces()

    assert len(traces) == 1
    assert traces[0].operation_id == 1
    assert traces[0].events[1].operation_id is None


def test_operation_settlement_without_owner_linkage_is_rejected() -> None:
    events = (
        _event(1, ObserverTraceKind.RUN_CALL_ENTRY),
        _event(
            2,
            ObserverTraceKind.OPERATION_SETTLEMENT,
            operation_id=None,
        ),
    )

    with pytest.raises(ObserverTraceEvidenceError, match="linkage"):
        ObserverTraceSnapshot(events).validate()


def test_operation_metadata_must_remain_coherent() -> None:
    events = (
        _event(
            1,
            ObserverTraceKind.RUN_CALL_ENTRY,
            operation_class="sql_bounded",
        ),
        _event(
            2,
            ObserverTraceKind.CALLBACK_DISPATCH,
            operation_class="serialization_only",
        ),
    )

    with pytest.raises(ObserverTraceEvidenceError, match="metadata"):
        ObserverTraceSnapshot(events).validate()
