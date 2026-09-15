from __future__ import annotations

import socket

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


class _Observer:
    def __init__(self) -> None:
        self.registered = 0

    def register_connection(self, _connection: object) -> None:
        self.registered += 1


def _connection_parameters(postgres) -> dict[str, object]:
    return {
        "host": postgres.host,
        "port": postgres.port,
        "user": postgres.user,
        "dbname": postgres.database,
        "password": postgres.password,
    }


def _session(parameters: dict[str, object]):
    observer = _Observer()
    opened: list[psycopg.Connection] = []

    def connect(settings=None):
        selected = parameters if settings is None else settings.apply(parameters)
        connection = psycopg.connect(**selected, autocommit=True)
        opened.append(connection)
        return connection

    session = BackendObserverSession(
        observer_factory=lambda: observer,
        connection_factory=connect,
        failure_causality=None,
        child_released=lambda: True,
    )
    return session, observer, opened


def _force_server_timeout(_observer: object, connection: psycopg.Connection):
    connection.execute("SET statement_timeout = '1ms'")
    return connection.execute("SELECT pg_sleep(0.02)").fetchone()


def test_ten_real_tcp_bootstrap_and_registration_repetitions() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        parameters = _connection_parameters(postgres)
        for case_number in range(10):
            session, observer, opened = _session(parameters)
            session.open(case_number + 1)
            try:
                assert observer.registered == 1
                assert opened[0].execute("SELECT 1").fetchone() == (1,)
            finally:
                session.close()
            assert opened[0].closed is True


def test_ten_immediate_refusal_bootstrap_repetitions_are_bounded_and_clean() -> None:
    for case_number in range(10):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()
        session, _observer, opened = _session(
            {
                "host": "127.0.0.1",
                "port": port,
                "user": "public_safe",
                "dbname": "public_safe",
            }
        )
        with pytest.raises(BackendMonitorError) as captured:
            session.open(case_number + 1)
        assert captured.value.observer_boundary is not None
        assert captured.value.observer_boundary.value == "observer_connection_create"
        assert not opened or opened[0].closed is True
        session.close()


def test_twenty_five_server_timeouts_and_twenty_five_ordinary_queries() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        parameters = _connection_parameters(postgres)
        for case_number in range(50):
            session, observer, opened = _session(parameters)
            session.open(case_number + 1)
            session.mark_startup_validated()
            session.activate_and_release(lambda: None)
            try:
                if case_number % 2 == 0:
                    with pytest.raises(BackendMonitorError) as captured:
                        session.run(
                            ObserverFailureBoundary.ACTIVE_SUMMARY,
                            _force_server_timeout,
                            allowed_states=(ObserverSessionState.ACTIVE,),
                        )
                    assert captured.value.observer_boundary is not None
                    assert captured.value.observer_boundary.value == (
                        "observer_operation_execution_timeout"
                    )
                    assert captured.value.observer_timeout_mechanism is not None
                    assert captured.value.observer_timeout_mechanism.value == (
                        "server_statement_timeout"
                    )
                    assert opened[0].execute("SELECT 1").fetchone() == (1,)
                else:
                    row = session.run(
                        ObserverFailureBoundary.ACTIVE_SUMMARY,
                        lambda _observer, connection: connection.execute(
                            "SELECT 1"
                        ).fetchone(),
                        allowed_states=(ObserverSessionState.ACTIVE,),
                    )
                    assert row == (1,)
                assert observer.registered == 1
            finally:
                session.close()
            assert opened[0].closed is True
