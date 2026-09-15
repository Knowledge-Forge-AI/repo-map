from __future__ import annotations

from itertools import permutations
from threading import Event, Thread

import psycopg
import pytest

from repomap_test_support.test_cov5a_startup_model import (
    ALTERNATIVES,
    fits_unchanged_ceiling,
    release_is_authorized,
)
from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import (
    ObserverConnectionSettings,
    ObserverDeadlinePolicy,
)


class _Connection:
    def __init__(
        self,
        release: Event | None = None,
        cancel_error: Exception | None = None,
    ) -> None:
        self.broken = False
        self.cancel_count = 0
        self.cancel_attempted = Event()
        self.closed = False
        self.release = release
        self.cancel_error = cancel_error

    def cancel_safe(self, *, timeout: float) -> None:
        assert timeout > 0
        self.cancel_count += 1
        self.cancel_attempted.set()
        if self.release is not None:
            self.release.set()
        if self.cancel_error is not None:
            raise self.cancel_error

    def close(self) -> None:
        self.closed = True


class _Observer:
    def register_connection(self, _connection: object) -> None:
        return None


class _StatementTimeoutCanceled(psycopg.errors.QueryCanceled):
    @property
    def diag(self):
        return type(
            "_Diagnostic",
            (),
            {"message_primary": "canceling statement due to statement timeout"},
        )()


def _active_session(connection: _Connection) -> BackendObserverSession:
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda _settings=None: connection,
        failure_causality=None,
        child_released=lambda: True,
    )
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session


def test_short_sql_operation_is_refused_below_the_admission_floor() -> None:
    policy = ObserverDeadlinePolicy()

    with pytest.raises(ValueError, match="insufficient"):
        policy.operation_deadlines(0.2)


def test_connection_start_settings_precede_first_observer_sql() -> None:
    captured = {}
    connection = _Connection()

    def connect(settings: ObserverConnectionSettings) -> object:
        captured.update(
            settings.apply(
                {
                    "host": "127.0.0.1",
                    "port": 5432,
                    "dbname": "observer",
                    "options": "-c search_path=public",
                }
            )
        )
        return connection

    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=connect,
        failure_causality=None,
        child_released=lambda: False,
    )
    session.open(1)
    try:
        assert isinstance(captured["connect_timeout"], int)
        assert captured["connect_timeout"] >= 2
        assert isinstance(captured["options"], str)
        assert "search_path=public" in captured["options"]
        assert "statement_timeout=" in captured["options"]
    finally:
        session.close()


def test_connection_settings_reject_ambiguous_hosts_and_timeout_options() -> None:
    checked = []

    def connect(settings: ObserverConnectionSettings) -> object:
        with pytest.raises(ValueError, match="exactly one host"):
            settings.apply(
                {
                    "host": "127.0.0.1,127.0.0.2",
                    "port": "5432,5433",
                    "dbname": "observer",
                }
            )
        with pytest.raises(ValueError, match="statement_timeout"):
            settings.apply(
                {
                    "host": "127.0.0.1",
                    "port": 5432,
                    "dbname": "observer",
                    "options": "-c statement_timeout=1s",
                }
            )
        checked.append(True)
        return _Connection()

    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=connect,
        failure_causality=None,
        child_released=lambda: False,
    )
    session.open(1)
    try:
        assert checked == [True]
    finally:
        session.close()


def test_server_query_canceled_has_stable_timeout_classification() -> None:
    connection = _Connection()
    session = _active_session(connection)
    try:
        with pytest.raises(BackendMonitorError) as caught:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                lambda _observer, _connection: (_ for _ in ()).throw(
                    _StatementTimeoutCanceled()
                ),
                allowed_states=(ObserverSessionState.ACTIVE,),
            )
        assert caught.value.observer_boundary is not None
        assert caught.value.observer_boundary.value == (
            "observer_operation_execution_timeout"
        )
        assert caught.value.observer_timeout_mechanism is not None
        assert caught.value.observer_timeout_mechanism.value == (
            "server_statement_timeout"
        )
    finally:
        session.close()


def test_unexpected_query_canceled_is_not_a_scheduled_timeout() -> None:
    connection = _Connection()
    session = _active_session(connection)
    try:
        with pytest.raises(BackendMonitorError) as caught:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                lambda _observer, _connection: (_ for _ in ()).throw(
                    psycopg.errors.QueryCanceled()
                ),
                allowed_states=(ObserverSessionState.ACTIVE,),
            )
        assert caught.value.observer_boundary is not None
        assert caught.value.observer_boundary.value == (
            "observer_unexpected_cancellation"
        )
        assert caught.value.observer_timeout_mechanism is not None
        assert caught.value.observer_timeout_mechanism.value == (
            "unexpected_query_canceled"
        )
    finally:
        session.close()


@pytest.mark.parametrize(
    ("cancel_error", "expected_limitation"),
    (
        (
            psycopg.errors.CancellationTimeout("cancel deadline"),
            "cancellation_timeout",
        ),
        (OSError("cancel transport unavailable"), "cancellation_failure"),
    ),
)
def test_client_fallback_classifies_cancellation_limitation(
    cancel_error: Exception,
    expected_limitation: str,
) -> None:
    release = Event()
    operation_started = Event()
    connection = _Connection(cancel_error=cancel_error)
    session = _active_session(connection)
    failures: list[BackendMonitorError] = []

    def run_active_operation() -> None:
        def _execute(_observer: object, _connection: object) -> None:
            operation_started.set()
            release.wait()

        try:
            session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                _execute,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.5,
            )
        except BackendMonitorError as error:
            failures.append(error)

    operation_thread = Thread(target=run_active_operation)
    operation_thread.start()
    try:
        assert operation_started.wait(1.0)
        assert connection.cancel_attempted.wait(1.0)
        assert session.snapshot().operation_in_flight is True
        assert connection.closed is False
        release.set()
        operation_thread.join(1.0)
        assert operation_thread.is_alive() is False
        assert len(failures) == 1
        assert failures[0].observer_timeout_mechanism is not None
        assert failures[0].observer_timeout_mechanism.value == (
            "client_cancel_fallback"
        )
        assert failures[0].observer_cancellation_limitation is not None
        assert failures[0].observer_cancellation_limitation.value == (
            expected_limitation
        )
        assert connection.cancel_count == 1
        assert connection.closed is False
    finally:
        release.set()
        operation_thread.join(1.0)
        session.close()
    assert connection.closed is True


def test_event_application_gets_next_session_turn_after_active_operation() -> None:
    connection = _Connection()
    session = _active_session(connection)
    active = Event()
    release = Event()
    order = []

    def hold_active_operation() -> None:
        def _hold(_observer: object, _connection: object) -> None:
            active.set()
            release.wait()

        session.run(
            ObserverFailureBoundary.ACTIVE_SUMMARY,
            _hold,
            allowed_states=(ObserverSessionState.ACTIVE,),
        )

    def run_operation(boundary: ObserverFailureBoundary, label: str) -> None:
        session.run(
            boundary,
            lambda _observer, _connection: order.append(label),
            allowed_states=(ObserverSessionState.ACTIVE,),
        )

    holder = Thread(target=hold_active_operation)
    event_apply = Thread(
        target=run_operation,
        args=(ObserverFailureBoundary.EVENT_APPLY, "event"),
    )
    competing_summary = Thread(
        target=run_operation,
        args=(ObserverFailureBoundary.ACTIVE_SUMMARY, "summary"),
    )
    try:
        holder.start()
        assert active.wait(1)
        event_apply.start()
        with session._condition:
            assert session._condition.wait_for(
                lambda: session._event_apply_waiters == 1,
                timeout=1,
            )
        competing_summary.start()
        release.set()
        for thread in (holder, event_apply, competing_summary):
            thread.join(timeout=1)
            assert not thread.is_alive()
        assert order == ["event", "summary"]
    finally:
        release.set()
        session.close()


def test_one_hundred_twenty_startup_orderings_fail_closed() -> None:
    events = (
        "resource_start",
        "observer_register",
        "ownership_first",
        "resource_settle",
        "ownership_second",
    )
    observed = tuple(permutations(events))

    assert len(observed) == 120
    authorized = [order for order in observed if release_is_authorized(order)]
    assert authorized
    assert all(
        order.index("resource_settle") < order.index("ownership_second")
        for order in authorized
    )


def test_five_sequencing_alternatives_keep_contract_and_budget_separate() -> None:
    assert len(ALTERNATIVES) == 5
    results = {
        alternative.name: fits_unchanged_ceiling(
            alternative,
            available_budget_units=5,
        )
        for alternative in ALTERNATIVES
    }
    assert results == {
        "reported_candidate": False,
        "resource_settlement_before_final_ownership": True,
        "observer_before_resource_sampling": True,
        "reuse_authoritative_snapshot": False,
        "reserve_complete_operation_budget": True,
    }
