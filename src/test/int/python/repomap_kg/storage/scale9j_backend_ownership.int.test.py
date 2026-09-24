from __future__ import annotations

import time
from threading import Event, Thread

import psycopg

import pytest

from repomap_kg.storage.backend_observer import (
    BackendObservationError,
    BackendOwnershipObserver,
)
from repomap_kg.storage.backend_ownership import (
    BackendClassification,
    BackendIdentity,
    ConnectionRole,
)
from repomap_kg.storage.backend_telemetry import (
    BackendTelemetry,
    ConnectionTelemetryEvent,
    TelemetryEventKind,
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


def test_observer_refuses_non_autocommit_or_unregistered_and_projects_public_summary() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo, autocommit=True) as observer_connection:
            observer = BackendOwnershipObserver()
            observer_identity = observer.register_connection(observer_connection)

            observer.register_observer(observer_identity)
            assert observer.observer_identities == (observer_identity,)

            foreign_identity = BackendIdentity(
                backend_pid=999999, backend_start=observer_identity.backend_start
            )
            with pytest.raises(BackendObservationError, match="observer limit exceeded"):
                observer.register_observer(foreign_identity)

            with psycopg.connect(conninfo, autocommit=False) as non_autocommit_conn:
                with pytest.raises(
                    BackendObservationError, match="observer connection is unavailable"
                ):
                    observer.classify(non_autocommit_conn)

            with psycopg.connect(conninfo, autocommit=True) as other_conn:
                with pytest.raises(
                    BackendObservationError, match="observer connection is unavailable"
                ):
                    observer.classify(other_conn)

            summary = observer.public_summary(observer_connection)
            assert summary.get(BackendClassification.OBSERVER.value) == 1
            assert set(summary) <= {category.value for category in BackendClassification}
            assert all(isinstance(count, int) and count >= 0 for count in summary.values())


def test_observer_event_sink_refuses_closed_or_mismatched_connection() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        with psycopg.connect(conninfo, autocommit=True) as observer_connection:
            observer = BackendOwnershipObserver()
            observer.register_connection(observer_connection)
            sink = observer.event_sink(observer_connection)

            client_conn = psycopg.connect(conninfo)
            event = ConnectionTelemetryEvent(
                connection_sequence=1,
                backend_pid=client_conn.info.backend_pid,
                connection_role=ConnectionRole.DIRECT_STAGED_REFRESH,
                schema_version=1, connection_generation=1,
                event=TelemetryEventKind.CONNECTION_READY,
                monotonic_ns=1000,
            )

            client_conn.close()
            with pytest.raises(
                BackendObservationError, match="source connection is unavailable"
            ):
                sink(event, client_conn)
            assert observer.owned_backends == ()

            other_conn = psycopg.connect(conninfo)
            mismatched_event = ConnectionTelemetryEvent(
                connection_sequence=2,
                backend_pid=other_conn.info.backend_pid + 99999,
                connection_role=ConnectionRole.DIRECT_STAGED_REFRESH,
                schema_version=1, connection_generation=1,
                event=TelemetryEventKind.CONNECTION_READY,
                monotonic_ns=2000,
            )
            try:
                with pytest.raises(
                    BackendObservationError, match="source connection is unavailable"
                ):
                    sink(mismatched_event, other_conn)
                assert observer.owned_backends == ()
            finally:
                other_conn.close()
