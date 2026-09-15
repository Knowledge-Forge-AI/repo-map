from __future__ import annotations

import time

import psycopg

from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
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


class _Observer:
    def register_connection(self, connection) -> None:
        assert connection.closed is False


def _run_query(_observer: _Observer, current: object) -> object:
    assert isinstance(current, psycopg.Connection)
    return current.execute("SELECT pg_sleep(5)").fetchone()


def test_disposable_postgres_observer_query_is_cancelled_and_settles() -> None:
    require_postgres_binaries()
    decision_support_policy = ObserverDeadlinePolicy(
        connection_timeout_seconds=2,
        server_statement_timeout_ms=100,
        client_cancel_after_seconds=0.2,
        cancel_request_timeout_seconds=0.2,
        caller_operation_timeout_seconds=0.5,
    )
    with temporary_postgres() as postgres:
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        connection = psycopg.connect(
            host=params["host"],
            port=int(params["port"]),
            user=params["user"],
            dbname=params["dbname"],
            autocommit=True,
        )
        session = BackendObserverSession(
            observer_factory=_Observer,
            connection_factory=lambda: connection,
            failure_causality=None,
            child_released=lambda: True,
            deadline_policy=decision_support_policy,
        )
        session.open(1)
        session.mark_startup_validated()
        session.activate_and_release(lambda: None)

        started = time.monotonic()
        try:
            try:
                session.run(
                    ObserverFailureBoundary.ACTIVE_SUMMARY,
                    _run_query,
                    allowed_states=(ObserverSessionState.ACTIVE,),
                    timeout_seconds=0.5,
                )
            except BackendMonitorError as error:
                assert error.category == "backend_observer_failed"
                assert (
                    error.observer_boundary
                    is ObserverFailureBoundary.OPERATION_EXECUTION_TIMEOUT
                )
            else:
                raise AssertionError("observer query did not time out")
            assert time.monotonic() - started < 1.0
        finally:
            session.close(timeout_seconds=0.5)
        assert connection.closed is True
