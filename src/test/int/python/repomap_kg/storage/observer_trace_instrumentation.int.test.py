import psycopg
import pytest

from repomap_kg.storage.backend_observer import (
    BackendOwnershipObserver,
    current_backend_identity,
)
from repomap_test_support.observer_trace import (
    ObserverTraceKind,
    ObserverTraceRecorder,
    instrument_observer_runtime,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from scale28_backend_observer_session import (
    BackendObserverSession,
    ObserverFailureBoundary,
    ObserverSessionState,
)


@pytest.mark.parametrize("_smoke_cycle", range(3), ids=lambda value: f"cycle-{value + 1}")
def test_real_observer_trace_preserves_exact_connection_and_sql_boundaries(_smoke_cycle) -> None:
    require_postgres_binaries()
    recorder = ObserverTraceRecorder.for_supervised_cycle()
    opened = []

    with temporary_postgres() as postgres:
        parameters = {
            "host": postgres.host,
            "port": postgres.port,
            "user": postgres.user,
            "dbname": postgres.database,
            "password": postgres.password,
        }

        def connect(settings):
            connection = psycopg.connect(
                **settings.apply(parameters),
                autocommit=True,
            )
            opened.append(connection)
            return connection

        session = BackendObserverSession(
            observer_factory=BackendOwnershipObserver,
            connection_factory=connect,
            failure_causality=None,
            child_released=lambda: True,
        )
        with instrument_observer_runtime(recorder):
            session.open(1)
            connection = opened[0]
            session.mark_startup_validated()
            session.activate_and_release(lambda: None)
            seen = []

            def public_summary(observer, current):
                seen.append(current)
                assert current_backend_identity(current) is not None
                return observer.public_summary(current)

            result = session.run(
                ObserverFailureBoundary.ACTIVE_SUMMARY,
                public_summary,
                allowed_states=(ObserverSessionState.ACTIVE,),
                timeout_seconds=0.5,
            )
            session.close()

    snapshot = recorder.snapshot()
    kinds = [event.kind for event in snapshot.events]
    assert seen == [connection]
    assert result["observer"] == 1
    assert ObserverTraceKind.PUBLIC_SUMMARY_ENTRY in kinds
    assert ObserverTraceKind.BACKEND_ACTIVITY_ENTRY in kinds
    assert ObserverTraceKind.SQL_EXECUTE_ENTRY in kinds
    assert ObserverTraceKind.SQL_EXECUTE_RETURN in kinds
    assert ObserverTraceKind.SQL_FETCHALL_ENTRY in kinds
    assert ObserverTraceKind.SQL_FETCHALL_RETURN in kinds
    assert ObserverTraceKind.SQL_FETCHONE_ENTRY in kinds
    assert ObserverTraceKind.SQL_FETCHONE_RETURN in kinds
    assert ObserverTraceKind.CALLBACK_RETURN in kinds
    assert ObserverTraceKind.SESSION_OWNER_ACQUIRED in kinds
    assert ObserverTraceKind.SESSION_OWNER_RELEASED in kinds
    assert ObserverTraceKind.OPERATION_SETTLEMENT in kinds
    assert connection.closed is True
    payload = repr(snapshot.to_public_payload())
    assert postgres.password not in payload
    assert "SELECT" not in payload
    metadata = recorder.capacity_metadata()
    assert recorder.capacity_pre_registered is True
    assert metadata["configured_capacity"] > metadata["retained_events"]
    assert metadata["overflowed"] is False
