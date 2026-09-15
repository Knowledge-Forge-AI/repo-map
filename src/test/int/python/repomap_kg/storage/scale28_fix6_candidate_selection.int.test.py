from __future__ import annotations

from collections import Counter
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


_C120_420 = ObserverDeadlinePolicy(
    connection_timeout_seconds=2,
    server_statement_timeout_ms=400,
    client_cancel_after_seconds=0.42,
    cancel_request_timeout_seconds=0.12,
    caller_operation_timeout_seconds=0.57,
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
        assert timeout == pytest.approx(0.12)
        self.cancel_attempted.set()
        raise self._cancellation_error

    def close(self) -> None:
        self.close_count += 1
        self._connection.close()


def _parameters(postgres) -> dict[str, object]:
    return {
        "host": postgres.host,
        "port": postgres.port,
        "user": postgres.user,
        "dbname": postgres.database,
        "password": postgres.password,
    }


def _real_session(
    parameters: dict[str, object],
    *,
    deadline_policy: ObserverDeadlinePolicy | None,
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
        **(
            {}
            if deadline_policy is None
            else {"deadline_policy": deadline_policy}
        ),
    )
    session.open(1)
    connection = opened[0]
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session, connection


def _proxied_session(
    parameters: dict[str, object],
    cancellation_error: Exception,
    *,
    deadline_policy: ObserverDeadlinePolicy | None,
) -> tuple[BackendObserverSession, _CancellationProxy]:
    conninfo = " ".join(f"{k}={v}" for k, v in parameters.items())
    connection = psycopg.connect(conninfo, autocommit=True)
    connection.execute("SET statement_timeout = 0")
    proxy = _CancellationProxy(connection, cancellation_error)
    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=lambda _settings=None: proxy,
        failure_causality=None,
        child_released=lambda: True,
        **(
            {}
            if deadline_policy is None
            else {"deadline_policy": deadline_policy}
        ),
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


def _run_fallbacks(
    parameters: dict[str, object],
    *,
    count: int,
    deadline_policy: ObserverDeadlinePolicy | None,
) -> Counter[str]:
    outcomes: Counter[str] = Counter()
    for _case_number in range(count):
        session, connection = _real_session(
            parameters,
            deadline_policy=deadline_policy,
        )
        construction_snapshots = []
        original_execution_timeout = session._execution_timeout

        def observe_execution_timeout(
            category: str,
            cause: Exception | None = None,
        ) -> BackendMonitorError:
            with session._condition:
                construction_snapshots.append(session.snapshot())
                return original_execution_timeout(category, cause)

        setattr(session, "_execution_timeout", observe_execution_timeout)
        connection.execute("SET statement_timeout = 0")
        try:
            with pytest.raises(BackendMonitorError) as caught:
                session.run(
                    ObserverFailureBoundary.ACTIVE_SUMMARY,
                    _sleep(0.8),
                    allowed_states=(ObserverSessionState.ACTIVE,),
                    timeout_seconds=0.57,
                )
            assert len(construction_snapshots) == 1
            construction_snapshot = construction_snapshots[0]
            snapshot = session.snapshot()
            outcomes[snapshot.cancellation.request_outcome.value] += 1
            assert caught.value.observer_timeout_mechanism is not None
            assert caught.value.observer_timeout_mechanism.value == (
                "client_cancel_fallback"
            )
            construction_outcome = (
                construction_snapshot.cancellation.request_outcome.value
            )
            if construction_outcome == "request_succeeded":
                assert caught.value.observer_cancellation_limitation is None
            elif construction_outcome == "request_timed_out":
                assert caught.value.observer_cancellation_limitation is not None
                assert (
                    caught.value.observer_cancellation_limitation.value
                    == "cancellation_timeout"
                )
            else:
                assert construction_outcome == "not_requested"
                assert caught.value.observer_cancellation_limitation is None
            assert snapshot.cancellation.request_outcome.value in {
                "request_succeeded",
                "request_timed_out",
            }
            assert snapshot.cancellation.operation_settled is True
            assert snapshot.cancellation.request_in_flight is False
            assert snapshot.cancellation.close_eligible is True
        finally:
            session.close()
        assert connection.closed is True
    return outcomes


def _run_server_timeouts(
    parameters: dict[str, object],
    *,
    count: int,
    deadline_policy: ObserverDeadlinePolicy | None,
) -> Counter[str]:
    outcomes: Counter[str] = Counter()
    for _case_number in range(count):
        session, connection = _real_session(
            parameters,
            deadline_policy=deadline_policy,
        )
        try:
            with pytest.raises(BackendMonitorError) as caught:
                session.run(
                    ObserverFailureBoundary.ACTIVE_SUMMARY,
                    _sleep(0.8),
                    allowed_states=(ObserverSessionState.ACTIVE,),
                    timeout_seconds=0.57,
                )
            assert caught.value.observer_timeout_mechanism is not None
            mechanism = caught.value.observer_timeout_mechanism.value
            outcomes[mechanism] += 1
            assert mechanism == "server_statement_timeout"
            assert session.snapshot().cancellation.cancellation_requested is False
        finally:
            session.close()
        assert connection.closed is True
    return outcomes


def _run_limitations(
    parameters: dict[str, object],
    cancellation_error: Exception,
    expected_limitation: str,
    *,
    count: int,
    deadline_policy: ObserverDeadlinePolicy | None,
) -> None:
    for _case_number in range(count):
        session, connection = _proxied_session(
            parameters,
            cancellation_error,
            deadline_policy=deadline_policy,
        )
        failures: list[BaseException] = []

        def run_operation() -> None:
            try:
                session.run(
                    ObserverFailureBoundary.ACTIVE_SUMMARY,
                    _sleep(0.7),
                    allowed_states=(ObserverSessionState.ACTIVE,),
                    timeout_seconds=0.57,
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
            assert connection.close_count == 1
        finally:
            operation_thread.join(1.0)
            if not connection.closed:
                session.close()


def test_c120_420_candidate_real_characterization_cohorts() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        parameters = _parameters(postgres)
        fallback_outcomes = _run_fallbacks(
            parameters,
            count=10,
            deadline_policy=_C120_420,
        )
        server_outcomes = _run_server_timeouts(
            parameters,
            count=10,
            deadline_policy=_C120_420,
        )
        _run_limitations(
            parameters,
            psycopg.errors.CancellationTimeout(
                "bounded cancellation timeout"
            ),
            "cancellation_timeout",
            count=5,
            deadline_policy=_C120_420,
        )
        _run_limitations(
            parameters,
            OSError("bounded cancellation transport failure"),
            "cancellation_failure",
            count=5,
            deadline_policy=_C120_420,
        )

    assert sum(fallback_outcomes.values()) == 10
    assert set(fallback_outcomes) <= {
        "request_succeeded",
        "request_timed_out",
    }
    assert server_outcomes == {"server_statement_timeout": 10}
    print(f"fix6_candidate_c120_420_fallbacks={dict(fallback_outcomes)!r}")
    print(f"fix6_candidate_c120_420_server={dict(server_outcomes)!r}")
