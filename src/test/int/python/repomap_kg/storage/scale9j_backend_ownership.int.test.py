from __future__ import annotations

import time
from threading import Event, Thread

import psycopg

from repomap_kg.storage.backend_observer import BackendOwnershipObserver
from repomap_kg.storage.backend_ownership import (
    BackendClassification,
    ConnectionRole,
)
from repomap_kg.storage.backend_telemetry import (
    BackendTelemetry,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _classifications(observer: BackendOwnershipObserver, connection) -> dict[int, str]:
    return {
        entry.activity.identity.backend_pid: entry.classification.value
        for entry in observer.classify(connection)
    }


def test_observer_uses_exact_backend_pid_and_start_for_owned_connection() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo, autocommit=True) as observer_connection:
            observer = BackendOwnershipObserver()
            observer_identity = observer.register_connection(observer_connection)
            direct_connection = psycopg.connect(conninfo)
            events: list[object] = []
            telemetry = BackendTelemetry(
                events.append,
                ownership_sink=observer.event_sink(observer_connection),
            )
            tracked = telemetry.track(
                direct_connection,
                ConnectionRole.DIRECT_STAGED_REFRESH,
            )
            try:
                snapshot = observer.classify(observer_connection)
                classifications = {
                    entry.activity.identity.backend_pid: entry.classification.value
                    for entry in snapshot
                }
                observed_direct_identity = next(
                    entry.activity.identity
                    for entry in snapshot
                    if entry.activity.identity.backend_pid
                    == direct_connection.info.backend_pid
                )

                assert observer.owned_backends[0].identity == observed_direct_identity
                assert classifications[direct_connection.info.backend_pid] == (
                    BackendClassification.DIRECT_OWNED_CLIENT.value
                )
                assert classifications[observer_identity.backend_pid] == (
                    BackendClassification.OBSERVER.value
                )
            finally:
                tracked.close()

            assert observer.owned_backends == ()


def test_observer_supports_two_exact_owned_connections() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo, autocommit=True) as observer_connection:
            observer = BackendOwnershipObserver()
            observer.register_connection(observer_connection)
            first_connection = psycopg.connect(conninfo)
            second_connection = psycopg.connect(conninfo)
            events: list[object] = []
            telemetry = BackendTelemetry(
                events.append,
                ownership_sink=observer.event_sink(observer_connection),
            )
            first = telemetry.track(
                first_connection,
                ConnectionRole.DIRECT_STAGED_REFRESH,
            )
            second = telemetry.track(
                second_connection,
                ConnectionRole.DIRECT_STAGED_REFRESH,
            )
            try:
                classifications = _classifications(observer, observer_connection)

                assert len(observer.owned_backends) == 2
                assert classifications[first_connection.info.backend_pid] == (
                    BackendClassification.DIRECT_OWNED_CLIENT.value
                )
                assert classifications[second_connection.info.backend_pid] == (
                    BackendClassification.DIRECT_OWNED_CLIENT.value
                )
            finally:
                first.close()
                second.close()


def test_observer_fails_closed_for_unregistered_client_connection() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo, autocommit=True) as observer_connection:
            observer = BackendOwnershipObserver()
            observer.register_connection(observer_connection)
            direct_connection = psycopg.connect(conninfo)
            ambient_connection = psycopg.connect(conninfo)
            events: list[object] = []
            telemetry = BackendTelemetry(
                events.append,
                ownership_sink=observer.event_sink(observer_connection),
            )
            tracked = telemetry.track(
                direct_connection,
                ConnectionRole.DIRECT_STAGED_REFRESH,
            )
            try:
                classifications = _classifications(observer, observer_connection)

                assert classifications[ambient_connection.info.backend_pid] == (
                    BackendClassification.AMBIENT_CLIENT.value
                )
            finally:
                tracked.close()
                ambient_connection.close()


def test_observer_replaces_closed_owned_connection_with_new_generation() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo, autocommit=True) as observer_connection:
            observer = BackendOwnershipObserver()
            observer.register_connection(observer_connection)
            events: list[object] = []
            telemetry = BackendTelemetry(
                events.append,
                ownership_sink=observer.event_sink(observer_connection),
            )
            assert observer_connection.autocommit is True
            first = telemetry.track(
                psycopg.connect(conninfo),
                ConnectionRole.DIRECT_STAGED_REFRESH,
            )
            first_identity = observer.owned_backends[0].identity
            first_sequence = observer.owned_backends[0].connection_sequence
            first.close()
            empty_backends = observer.owned_backends
            assert empty_backends == ()

            second = telemetry.track(
                psycopg.connect(conninfo),
                ConnectionRole.DIRECT_STAGED_REFRESH,
            )
            try:
                owned = observer.owned_backends
                classifications = _classifications(observer, observer_connection)

                assert len(owned) == 1
                assert owned[0].connection_sequence == first_sequence + 1
                assert owned[0].connection_generation == 2
                assert owned[0].identity != first_identity
                assert classifications[second.info.backend_pid] == (
                    BackendClassification.DIRECT_OWNED_CLIENT.value
                )
            finally:
                second.close()


def test_observer_classifies_a_real_parallel_worker_for_an_owned_leader() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo) as setup_connection:
            setup_connection.execute(
                "CREATE TABLE parallel_fixture AS "
                "SELECT value::bigint AS value FROM generate_series(1, 1000000) AS value"
            )
            setup_connection.execute("ANALYZE parallel_fixture")
            setup_connection.commit()

        with psycopg.connect(conninfo, autocommit=True) as observer_connection:
            observer = BackendOwnershipObserver()
            observer.register_connection(observer_connection)
            direct_connection = psycopg.connect(conninfo)
            events: list[object] = []
            telemetry = BackendTelemetry(
                events.append,
                ownership_sink=observer.event_sink(observer_connection),
            )
            tracked = telemetry.track(
                direct_connection,
                ConnectionRole.DIRECT_STAGED_REFRESH,
            )
            with tracked.cursor() as cursor:
                cursor.execute("SET max_parallel_workers_per_gather = 2")
                cursor.execute("SET min_parallel_table_scan_size = 0")
                cursor.execute("SET parallel_setup_cost = 0")
                cursor.execute("SET parallel_tuple_cost = 0")

            started = Event()
            finished = Event()
            errors: list[BaseException] = []

            def execute_parallel_query() -> None:
                started.set()
                try:
                    tracked.execute(
                        "SELECT count(*) FROM parallel_fixture "
                        "CROSS JOIN generate_series(1, 64) AS multiplier"
                    )
                except BaseException as error:
                    errors.append(error)
                finally:
                    finished.set()

            worker = Thread(target=execute_parallel_query)
            worker.start()
            assert started.wait(timeout=1.0)
            worker_found = False
            deadline = time.monotonic() + 10.0
            try:
                while not finished.is_set() and time.monotonic() < deadline:
                    snapshot = observer.classify(observer_connection)
                    classifications = {
                        entry.activity.identity.backend_pid: entry.classification.value
                        for entry in snapshot
                    }
                    owned_workers = [
                        entry
                        for entry in snapshot
                        if entry.classification
                        is BackendClassification.DIRECT_OWNED_PARALLEL_WORKER
                    ]
                    worker_found = bool(owned_workers)
                    if worker_found:
                        assert classifications[direct_connection.info.backend_pid] == (
                            BackendClassification.DIRECT_OWNED_CLIENT.value
                        )
                        assert all(
                            entry.activity.leader_pid == direct_connection.info.backend_pid
                            for entry in owned_workers
                        )
                        tracked.cancel_safe(timeout=1.0)
                        break
                    time.sleep(0.01)
                worker.join(timeout=5.0)
                assert not worker.is_alive()
                assert worker_found
                assert len(errors) == 1
                assert isinstance(errors[0], psycopg.errors.QueryCanceled)
            finally:
                tracked.close()
