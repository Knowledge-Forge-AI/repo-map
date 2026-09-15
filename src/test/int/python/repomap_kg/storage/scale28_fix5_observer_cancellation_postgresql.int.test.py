from __future__ import annotations

from threading import Event, Thread

import psycopg
import pytest

from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import ObserverDeadlinePolicy


_SYNTHETIC_LIMITATION_POLICY = ObserverDeadlinePolicy(
    server_statement_timeout_ms=10,
    client_cancel_after_seconds=0.02,
    cancel_request_timeout_seconds=0.01,
    caller_operation_timeout_seconds=0.05,
)


class _Observer:
    def register_connection(self, connection: object) -> None:
        assert getattr(connection, "closed", None) is False


class _CancellationProxy:
    def __init__(
        self,
        connection: psycopg.Connection,
        cancellation_error: Exception | None,
    ) -> None:
        self._connection = connection
        self._cancellation_error = cancellation_error
        self.cancel_attempted = Event()
        self.close_count = 0
        self.close_while_active = False
        self.session: BackendObserverSession | None = None

    @property
    def broken(self) -> bool:
        return self._connection.broken

    @property
    def closed(self) -> bool:
        return self._connection.closed

    def execute(self, *args, **kwargs):
        return self._connection.execute(*args, **kwargs)

    def cancel_safe(self, *, timeout: float) -> None:
        assert timeout > 0
        self.cancel_attempted.set()
        if self._cancellation_error is not None:
            raise self._cancellation_error
        self._connection.cancel_safe(timeout=timeout)

    def close(self) -> None:
        if self.session is not None:
            self.close_while_active |= self.session.snapshot().operation_in_flight
        self.close_count += 1
        self._connection.close()


def _connection_parameters(postgres) -> dict[str, object]:
    return {
        "host": postgres.host,
        "port": postgres.port,
        "user": postgres.user,
        "dbname": postgres.database,
        "password": postgres.password,
    }


def _active_session(
    parameters: dict[str, object],
    *,
    cancellation_error: Exception | None = None,
    disable_statement_timeout: bool = False,
    deadline_policy: ObserverDeadlinePolicy | None = None,
) -> tuple[BackendObserverSession, _CancellationProxy]:
    opened: list[_CancellationProxy] = []

    def connect(settings=None):
        selected = parameters if settings is None else settings.apply(parameters)
        connection = psycopg.connect(**selected, autocommit=True)
        if disable_statement_timeout:
            connection.execute("SET statement_timeout = 0")
        proxy = _CancellationProxy(connection, cancellation_error)
        opened.append(proxy)
        return proxy

    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=connect,
        failure_causality=None,
        child_released=lambda: True,
        **(
            {}
            if deadline_policy is None
            else {"deadline_policy": deadline_policy}
        ),
    )
    session.open(1)
    proxy = opened[0]
    proxy.session = session
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session, proxy


def _active_real_session(
    parameters: dict[str, object],
    *,
    deadline_policy: ObserverDeadlinePolicy,
) -> tuple[BackendObserverSession, psycopg.Connection]:
    opened: list[psycopg.Connection] = []

    def connect(settings=None):
        selected = parameters if settings is None else settings.apply(parameters)
        connection = psycopg.connect(**selected, autocommit=True)
        opened.append(connection)
        return connection

    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=connect,
        failure_causality=None,
        child_released=lambda: True,
        deadline_policy=deadline_policy,
    )
    session.open(1)
    connection = opened[0]
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session, connection


def _server_timeout(_observer: object, connection: object) -> object:
    assert isinstance(connection, _CancellationProxy)
    connection.execute("SET statement_timeout = '1ms'")
    return connection.execute("SELECT pg_sleep(0.02)").fetchone()


def _long_query(_observer: object, connection: object) -> object:
    assert isinstance(connection, (psycopg.Connection, _CancellationProxy))
    return connection.execute("SELECT pg_sleep(5)").fetchone()


def test_twenty_real_server_statement_timeout_operations() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        parameters = _connection_parameters(postgres)
        for _case_number in range(20):
            session, connection = _active_session(parameters)
            try:
                with pytest.raises(BackendMonitorError) as caught:
                    session.run(
                        ObserverFailureBoundary.ACTIVE_SUMMARY,
                        _server_timeout,
                        allowed_states=(ObserverSessionState.ACTIVE,),
                    )
                timeout_mechanism = caught.value.observer_timeout_mechanism
                assert timeout_mechanism is not None
                assert timeout_mechanism.value == (
                    "server_statement_timeout"
                )
                assert connection.cancel_attempted.is_set() is False
            finally:
                session.close()
            assert connection.close_count == 1
            assert connection.close_while_active is False


def test_ten_real_client_fallbacks_with_decision_support_reserve() -> None:
    require_postgres_binaries()
    decision_support_policy = ObserverDeadlinePolicy(
        connection_timeout_seconds=2,
        server_statement_timeout_ms=100,
        client_cancel_after_seconds=0.2,
        cancel_request_timeout_seconds=0.2,
        caller_operation_timeout_seconds=0.5,
    )
    with temporary_postgres() as postgres:
        parameters = _connection_parameters(postgres)
        for _case_number in range(10):
            session, connection = _active_real_session(
                parameters,
                deadline_policy=decision_support_policy,
            )
            connection.execute("SET statement_timeout = 0")
            try:
                with pytest.raises(BackendMonitorError) as caught:
                    session.run(
                        ObserverFailureBoundary.ACTIVE_SUMMARY,
                        _long_query,
                        allowed_states=(ObserverSessionState.ACTIVE,),
                        timeout_seconds=0.5,
                    )
                timeout_mechanism = caught.value.observer_timeout_mechanism
                assert timeout_mechanism is not None
                assert timeout_mechanism.value == (
                    "client_cancel_fallback"
                )
                assert caught.value.observer_cancellation_limitation is None
                assert connection.closed is False
                assert session.snapshot().cancellation.request_outcome.value == (
                    "request_succeeded"
                )
            finally:
                session.close()
            session.close()
            assert connection.closed is True


@pytest.mark.parametrize(
    ("cancellation_error", "expected_limitation"),
    (
        (
            psycopg.errors.CancellationTimeout("bounded cancellation timeout"),
            "cancellation_timeout",
        ),
        (OSError("bounded cancellation transport failure"), "cancellation_failure"),
    ),
)
def test_ten_actual_blocked_queries_per_cancellation_limitation(
    cancellation_error: Exception,
    expected_limitation: str,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        parameters = _connection_parameters(postgres)
        for _case_number in range(10):
            session, connection = _active_session(
                parameters,
                cancellation_error=cancellation_error,
                disable_statement_timeout=True,
                deadline_policy=_SYNTHETIC_LIMITATION_POLICY,
            )
            operation_failures: list[BaseException] = []

            def run_operation() -> None:
                try:
                    def run_query(_observer: object, current: object) -> object:
                        assert isinstance(current, _CancellationProxy)
                        return current.execute("SELECT pg_sleep(0.25)").fetchone()

                    session.run(
                        ObserverFailureBoundary.ACTIVE_SUMMARY,
                        run_query,
                        allowed_states=(ObserverSessionState.ACTIVE,),
                        timeout_seconds=0.1,
                    )
                except BaseException as error:
                    operation_failures.append(error)

            operation_thread = Thread(target=run_operation)
            operation_thread.start()
            try:
                assert connection.cancel_attempted.wait(1.0)
                assert session.snapshot().operation_in_flight is True
                assert connection.closed is False
                with pytest.raises(BackendMonitorError) as settlement:
                    session.close(timeout_seconds=0.05)
                assert settlement.value.observer_boundary is (
                    ObserverFailureBoundary.SETTLEMENT_TIMEOUT
                )
                assert connection.close_count == 0

                operation_thread.join(1.0)
                assert operation_thread.is_alive() is False
                assert len(operation_failures) == 1
                operation_error = operation_failures[0]
                assert isinstance(operation_error, BackendMonitorError)
                limitation = operation_error.observer_cancellation_limitation
                assert limitation is not None
                assert limitation.value == (
                    expected_limitation
                )
                session.close()
                session.close()
                assert connection.close_count == 1
                assert connection.close_while_active is False
            finally:
                operation_thread.join(1.0)
                if not connection.closed:
                    session.close()
