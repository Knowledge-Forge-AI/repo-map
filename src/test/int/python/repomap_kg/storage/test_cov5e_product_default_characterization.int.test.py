from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import hashlib
from pathlib import Path
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
    )
    session.open(1)
    connection = opened[0]
    connection.execute("SET statement_timeout = 0")
    session.mark_startup_validated()
    session.activate_and_release(lambda: None)
    return session, connection


@contextmanager
def _bounded_unrelated_contention(root: Path):
    stop = Event()
    started = (Event(), Event())
    failures: list[BaseException] = []
    payload = b"test-cov5e-unrelated-contention" * 2_048

    def cpu_worker() -> None:
        started[0].set()
        try:
            while not stop.is_set():
                hashlib.sha256(payload).digest()
        except BaseException as error:
            failures.append(error)

    def filesystem_worker() -> None:
        started[1].set()
        counter = 0
        try:
            while not stop.is_set():
                path = root / f"unrelated-{counter % 4}.bin"
                path.write_bytes(payload)
                assert path.read_bytes() == payload
                counter += 1
        except BaseException as error:
            failures.append(error)

    threads = (
        Thread(target=cpu_worker, name="cov5e-unrelated-cpu"),
        Thread(target=filesystem_worker, name="cov5e-unrelated-filesystem"),
    )
    for thread in threads:
        thread.start()
    try:
        assert all(event.wait(1.0) for event in started)
        yield
    finally:
        stop.set()
        for thread in threads:
            thread.join(2.0)
            assert thread.is_alive() is False
        assert failures == []


def _run_default_fallback_cohort(
    parameters: dict[str, object],
) -> Counter[str]:
    outcomes: Counter[str] = Counter()
    def _execute_sleep(_observer: object, selected: object) -> object:
        assert isinstance(selected, psycopg.Connection)
        return selected.execute("SELECT pg_sleep(0.7)").fetchone()

    for _case_number in range(5):
        session, connection = _session(parameters)
        try:
            with pytest.raises(BackendMonitorError) as caught:
                session.run(
                    ObserverFailureBoundary.ACTIVE_SUMMARY,
                    _execute_sleep,
                    allowed_states=(ObserverSessionState.ACTIVE,),
                    timeout_seconds=0.5,
                )
            snapshot = session.snapshot()
            outcome = snapshot.cancellation.request_outcome.value
            outcomes[outcome] += 1
            assert caught.value.observer_timeout_mechanism is not None
            assert caught.value.observer_timeout_mechanism.value == (
                "client_cancel_fallback"
            )
            assert outcome in {"request_succeeded", "request_timed_out"}
            assert snapshot.operation_in_flight is False
            assert snapshot.cancellation.operation_settled is True
            assert snapshot.cancellation.request_in_flight is False
            assert snapshot.cancellation.close_eligible is True
        finally:
            session.close()
            session.close()
        assert connection.closed is True
    return outcomes


@pytest.mark.parametrize("mode", ("quiet", "bounded_contention"))
def test_actual_product_default_under_quiet_and_unrelated_contention(
    mode: str,
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        parameters = _parameters(postgres)
        if mode == "quiet":
            outcomes = _run_default_fallback_cohort(parameters)
        else:
            contention_root = tmp_path / "unrelated"
            contention_root.mkdir()
            with _bounded_unrelated_contention(contention_root):
                outcomes = _run_default_fallback_cohort(parameters)

    assert sum(outcomes.values()) == 5
    assert set(outcomes) <= {"request_succeeded", "request_timed_out"}
    print(f"cov5e_{mode}_default_outcomes={dict(sorted(outcomes.items()))!r}")
