from __future__ import annotations

import os
from threading import Event, Thread

import psycopg

from repomap_kg.storage.backend_observer import BackendOwnershipObserver
from repomap_kg.storage.backend_ownership import (
    BackendClassification,
    ConnectionRole,
)
from repomap_kg.storage.backend_telemetry import (
    TelemetryEventKind,
    read_telemetry_event,
    telemetry_from_inherited_fds,
)
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def test_acknowledged_pipe_registers_exact_live_backend_before_source_use() -> None:
    require_postgres_binaries()
    event_read_fd, event_write_fd = os.pipe()
    ack_read_fd, ack_write_fd = os.pipe()
    registered = Event()
    consumed = Event()
    errors: list[BaseException] = []
    evidence: dict[str, object] = {}
    tracked = None
    try:
        with temporary_postgres() as postgres:
            params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
            with psycopg.connect(
                host=params["host"],
                port=int(params["port"]),
                user=params["user"],
                dbname=params["dbname"],
                autocommit=True,
            ) as observer_connection:
                observer = BackendOwnershipObserver()
                observer.register_connection(observer_connection)

                def consume_events() -> None:
                    try:
                        with os.fdopen(event_read_fd, "rb", closefd=False) as events:
                            opened = read_telemetry_event(events)
                            ready = read_telemetry_event(events)
                            assert opened is not None
                            assert ready is not None
                            assert opened.event is TelemetryEventKind.CONNECTION_OPENED
                            assert ready.event is TelemetryEventKind.CONNECTION_READY
                            observer.consume_pipe_event(
                                opened,
                                observer_connection,
                                ack_write_fd,
                            )
                            observer.consume_pipe_event(
                                ready,
                                observer_connection,
                                ack_write_fd,
                            )
                            snapshot = observer.classify(observer_connection)
                            direct = next(
                                entry
                                for entry in snapshot
                                if entry.activity.identity.backend_pid == ready.backend_pid
                            )
                            evidence["owned_identity"] = observer.owned_backends[0].identity
                            evidence["activity_identity"] = direct.activity.identity
                            evidence["classification"] = direct.classification
                            registered.set()

                            terminal = read_telemetry_event(events)
                            assert terminal is not None
                            assert terminal.event is TelemetryEventKind.CONNECTION_CLOSED
                            observer.consume_pipe_event(
                                terminal,
                                observer_connection,
                                ack_write_fd,
                            )
                    except BaseException as error:
                        errors.append(error)
                    finally:
                        consumed.set()

                supervisor = Thread(target=consume_events)
                supervisor.start()
                source_connection = psycopg.connect(
                    host=params["host"],
                    port=int(params["port"]),
                    user=params["user"],
                    dbname=params["dbname"],
                )
                telemetry = telemetry_from_inherited_fds(
                    event_write_fd,
                    ack_read_fd,
                    ready_ack_timeout_seconds=2.0,
                )
                tracked = telemetry.track(
                    source_connection,
                    ConnectionRole.DIRECT_STAGED_REFRESH,
                )

                assert registered.wait(timeout=2.0)
                assert errors == []
                assert evidence["owned_identity"] == evidence["activity_identity"]
                assert evidence["classification"] is (
                    BackendClassification.DIRECT_OWNED_CLIENT
                )

                tracked.close()
                tracked = None
                assert consumed.wait(timeout=2.0)
                supervisor.join(timeout=2.0)
                assert not supervisor.is_alive()
                assert errors == []
                assert observer.owned_backends == ()
    finally:
        if tracked is not None:
            tracked.close()
        for fd in (event_read_fd, event_write_fd, ack_read_fd, ack_write_fd):
            try:
                os.close(fd)
            except OSError:
                pass
