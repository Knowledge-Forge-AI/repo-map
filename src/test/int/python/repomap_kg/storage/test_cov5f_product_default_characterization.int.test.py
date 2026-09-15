from __future__ import annotations

from collections import Counter

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
    def register_connection(self, connection: object, /) -> object:
        assert isinstance(connection, psycopg.Connection)
        assert connection.closed is False
        return None


def _parameters(postgres) -> dict[str, object]:
    return {
        "host": postgres.host,
        "port": postgres.port,
        "user": postgres.user,
        "dbname": postgres.database,
        "password": postgres.password,
    }


def _session(
    parameters: dict[str, object],
) -> tuple[BackendObserverSession, psycopg.Connection]:
    opened: list[psycopg.Connection] = []

    def connect(settings):
        connection = psycopg.connect(
            **settings.apply(parameters),
            autocommit=True,
        )
        opened.append(connection)
        return connection

    session = BackendObserverSession(
        observer_factory=_Observer,
        connection_factory=connect,
        failure_causality=None,
        child_released=lambda: True,
    )
    session.open(1)
    connection = opened[0]
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session, connection


def test_cov5f_thirty_product_default_fallback_outcomes_are_bounded() -> None:
    require_postgres_binaries()
    outcomes: Counter[str] = Counter()

    with temporary_postgres() as postgres:
        parameters = _parameters(postgres)
        for _case_number in range(30):
            session, connection = _session(parameters)
            connection.execute("SET statement_timeout = 0")
            def _sleep_operation(
                _observer: object, exact_connection: object
            ) -> object:
                assert isinstance(exact_connection, psycopg.Connection)
                return exact_connection.execute(
                    "SELECT pg_sleep(0.8)"
                ).fetchone()

            try:
                with pytest.raises(BackendMonitorError) as captured:
                    session.run(
                        ObserverFailureBoundary.ACTIVE_SUMMARY,
                        _sleep_operation,
                        allowed_states=(ObserverSessionState.ACTIVE,),
                        timeout_seconds=0.5,
                    )
                cancellation = session.snapshot().cancellation
                outcomes[cancellation.request_outcome.value] += 1
                assert captured.value.observer_timeout_mechanism is not None
                assert captured.value.observer_timeout_mechanism.value == (
                    "client_cancel_fallback"
                )
                if cancellation.request_outcome.value == "request_succeeded":
                    assert (
                        captured.value.observer_cancellation_limitation is None
                    )
                else:
                    assert cancellation.request_outcome.value == (
                        "request_timed_out"
                    )
                    assert (
                        captured.value.observer_cancellation_limitation
                        is not None
                    )
                    assert (
                        captured.value.observer_cancellation_limitation.value
                        == "cancellation_timeout"
                    )
                assert cancellation.request_in_flight is False
                assert cancellation.operation_settled is True
                assert cancellation.close_eligible is True
            finally:
                session.close()
            assert connection.closed is True

    assert sum(outcomes.values()) == 30
    assert set(outcomes) <= {"request_succeeded", "request_timed_out"}
    print(f"cov5f_product_default_outcomes={dict(sorted(outcomes.items()))!r}")
