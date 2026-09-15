from __future__ import annotations

from collections import Counter
from threading import Event, Thread
from typing import cast

import psycopg
import pytest

from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.test_cov5d_qualification import (
    QualificationManifest,
    observed_result,
    qualification_record,
)
from scale28_backend_observer_session import (
    BackendMonitorError,
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)
from scale28_observer_deadlines import ObserverDeadlinePolicy


_PREDECESSOR_DEFAULT_POLICY = ObserverDeadlinePolicy(
    server_statement_timeout_ms=400,
    client_cancel_after_seconds=0.45,
    cancel_request_timeout_seconds=0.04,
    caller_operation_timeout_seconds=0.5,
)
_SYNTHETIC_LIMITATION_POLICY = ObserverDeadlinePolicy(
    server_statement_timeout_ms=10,
    client_cancel_after_seconds=0.02,
    cancel_request_timeout_seconds=0.01,
    caller_operation_timeout_seconds=0.05,
)


class _Observer:
    def register_connection(self, connection: object, /) -> object:
        assert isinstance(connection, (psycopg.Connection, _CancellationProxy))
        assert connection.closed is False
        return None


class _CancellationProxy:
    def __init__(
        self,
        connection: psycopg.Connection,
        cancellation_error: Exception,
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
        raise self._cancellation_error

    def close(self) -> None:
        if self.session is not None:
            self.close_while_active |= self.session.snapshot().operation_in_flight
        self.close_count += 1
        self._connection.close()


def _parameters(postgres) -> dict[str, str | int | None]:
    return {
        "host": postgres.host,
        "port": postgres.port,
        "user": postgres.user,
        "dbname": postgres.database,
        "password": postgres.password,
    }


def _real_session(
    parameters: dict[str, str | int | None],
    *,
    policy: ObserverDeadlinePolicy | None = None,
) -> tuple[BackendObserverSession, psycopg.Connection]:
    opened: list[psycopg.Connection] = []

    def connect(settings=None):
        selected = parameters if settings is None else settings.apply(parameters)
        conninfo = psycopg.conninfo.make_conninfo(
            "", **cast(dict[str, str | int | None], selected)
        )
        connection = psycopg.connect(conninfo, autocommit=True)
        opened.append(connection)
        return connection

    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=connect,
        failure_causality=None,
        child_released=lambda: True,
        **({} if policy is None else {"deadline_policy": policy}),
    )
    session.open(1)
    connection = opened[0]
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session, connection


def _proxied_session(
    parameters: dict[str, str | int | None],
    cancellation_error: Exception,
) -> tuple[BackendObserverSession, _CancellationProxy]:
    conninfo = psycopg.conninfo.make_conninfo("", **parameters)
    connection = psycopg.connect(conninfo, autocommit=True)
    connection.execute("SET statement_timeout = 0")
    proxy = _CancellationProxy(connection, cancellation_error)
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda _settings=None: proxy,
        failure_causality=None,
        child_released=lambda: True,
        deadline_policy=_SYNTHETIC_LIMITATION_POLICY,
    )
    proxy.session = session
    session.open(1)
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session, proxy


def _sleep(seconds: float):
    return lambda _observer, connection: connection.execute(
        f"SELECT pg_sleep({seconds})"
    ).fetchone()


def test_thirty_real_server_statement_timeout_operations() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        session, connection = _real_session(_parameters(postgres))
        connection.execute("SET statement_timeout = '5ms'")
        try:
            for _case_number in range(30):
                with pytest.raises(BackendMonitorError) as caught:
                    session.run(
                        ObserverFailureBoundary.ACTIVE_SUMMARY,
                        _sleep(0.05),
                        allowed_states=(ObserverSessionState.ACTIVE,),
                    )
                assert caught.value.observer_timeout_mechanism is not None
                assert caught.value.observer_timeout_mechanism.value == (
                    "server_statement_timeout"
                )
                assert (
                    session.snapshot().cancellation.cancellation_requested is False
                )
        finally:
            session.close()
        assert connection.closed is True


def test_thirty_successful_client_fallbacks_with_decision_support_policy() -> None:
    require_postgres_binaries()
    policy = ObserverDeadlinePolicy(
        connection_timeout_seconds=2,
        server_statement_timeout_ms=100,
        client_cancel_after_seconds=0.2,
        cancel_request_timeout_seconds=0.2,
        caller_operation_timeout_seconds=0.5,
    )
    with temporary_postgres() as postgres:
        parameters = _parameters(postgres)
        for _case_number in range(30):
            session, connection = _real_session(parameters, policy=policy)
            connection.execute("SET statement_timeout = 0")
            try:
                with pytest.raises(BackendMonitorError) as caught:
                    session.run(
                        ObserverFailureBoundary.ACTIVE_SUMMARY,
                        _sleep(1.0),
                        allowed_states=(ObserverSessionState.ACTIVE,),
                        timeout_seconds=0.5,
                    )
                assert caught.value.observer_timeout_mechanism is not None
                assert caught.value.observer_timeout_mechanism.value == (
                    "client_cancel_fallback"
                )
                assert caught.value.observer_cancellation_limitation is None
                assert session.snapshot().cancellation.request_outcome.value == (
                    "request_succeeded"
                )
            finally:
                session.close()
            assert connection.closed is True


def test_twenty_predecessor_default_results_remain_historical_evidence() -> None:
    require_postgres_binaries()
    manifest = QualificationManifest(
        required_group_counts={"postgres_cancellation": 20}
    )
    actual_categories: list[str] = []
    with temporary_postgres() as postgres:
        parameters = _parameters(postgres)
        for case_number in range(20):
            session, connection = _real_session(
                parameters,
                policy=_PREDECESSOR_DEFAULT_POLICY,
            )
            connection.execute("SET statement_timeout = 0")
            try:
                with pytest.raises(BackendMonitorError) as caught:
                    session.run(
                        ObserverFailureBoundary.ACTIVE_SUMMARY,
                        _sleep(0.7),
                        allowed_states=(ObserverSessionState.ACTIVE,),
                        timeout_seconds=0.5,
                    )
                snapshot = session.snapshot()
                actual_category = snapshot.cancellation.request_outcome.value
                actual_categories.append(actual_category)
                assert caught.value.observer_timeout_mechanism is not None
                assert caught.value.observer_timeout_mechanism.value == (
                    "client_cancel_fallback"
                )
                observed = observed_result(
                    f"default-reserve-{case_number:02d}",
                    actual_category,
                    payload={
                        "operation_settled": (
                            snapshot.cancellation.operation_settled
                        ),
                        "request_outcome": actual_category,
                    },
                )
                record = qualification_record(
                    authority_id=f"postgres-default-{case_number:02d}",
                    semantic_group="postgres_cancellation",
                    case_id=f"default-reserve-{case_number:02d}",
                    operation_kind="exact_connection_default_cancel",
                    entry_point="BackendObserverSession.run",
                    expected_contract_category="request_succeeded",
                    observed=observed,
                )
                manifest.add(record, observed)
            finally:
                session.close()
            assert connection.closed is True

    assert set(actual_categories) <= {
        "request_succeeded",
        "request_timed_out",
    }
    assert len(manifest.finish()["postgres_cancellation"]) == 20
    print(
        "cov5d_default_reserve_outcomes="
        + repr(dict(sorted(Counter(actual_categories).items())))
    )


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
def test_five_actual_blocked_queries_per_cancellation_limitation(
    cancellation_error: Exception,
    expected_limitation: str,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        parameters = _parameters(postgres)
        for _case_number in range(5):
            session, connection = _proxied_session(
                parameters,
                cancellation_error,
            )
            failures: list[BaseException] = []

            def run_operation() -> None:
                try:
                    session.run(
                        ObserverFailureBoundary.ACTIVE_SUMMARY,
                        _sleep(0.25),
                        allowed_states=(ObserverSessionState.ACTIVE,),
                        timeout_seconds=0.1,
                    )
                except BaseException as error:
                    failures.append(error)

            operation_thread = Thread(target=run_operation)
            operation_thread.start()
            try:
                assert connection.cancel_attempted.wait(1.0)
                with pytest.raises(BackendMonitorError) as settlement:
                    session.close(timeout_seconds=0.05)
                assert settlement.value.observer_boundary is (
                    ObserverFailureBoundary.SETTLEMENT_TIMEOUT
                )
                assert connection.close_count == 0
                operation_thread.join(1.0)
                assert operation_thread.is_alive() is False
                assert len(failures) == 1
                failure = failures[0]
                assert isinstance(failure, BackendMonitorError)
                assert failure.observer_cancellation_limitation is not None
                assert failure.observer_cancellation_limitation.value == (
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
