from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import psycopg
import pytest

from repomap_kg.coordinator.contracts import JobRequest
from repomap_kg.storage.authority import RequestId
from repomap_kg.coordinator.storage import ControlStore
from repomap_kg.runtime.maintenance import (
    MaintenanceUnavailableError,
    maintenance_activity,
    maintenance_ready,
    maintenance_window,
    require_transaction_admission,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def _connect_factory(postgres):
    def connect():
        return psycopg.connect(
            host=postgres.host,
            port=postgres.port,
            user=postgres.user,
            dbname=postgres.database,
            password=postgres.password,
        )

    return connect


def test_exclusive_maintenance_refuses_admission_and_reports_not_ready() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        connect = _connect_factory(postgres)

        assert maintenance_ready(connect) is True
        with maintenance_window(connect):
            assert maintenance_ready(connect) is False
            with pytest.raises(MaintenanceUnavailableError, match="maintenance"):
                with maintenance_activity(connect):
                    pytest.fail("maintenance activity admitted")
            with connect() as connection:
                with pytest.raises(
                    MaintenanceUnavailableError,
                    match="maintenance",
                ):
                    require_transaction_admission(connection)

        assert maintenance_ready(connect) is True


def test_exclusive_request_drains_active_shared_work_and_blocks_later_work() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        connect = _connect_factory(postgres)
        activity_entered = threading.Event()
        release_activity = threading.Event()
        maintenance_entered = threading.Event()

        def active_work() -> None:
            with maintenance_activity(connect):
                activity_entered.set()
                assert release_activity.wait(timeout=5)

        def maintenance_work() -> None:
            with maintenance_window(connect):
                maintenance_entered.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            active = executor.submit(active_work)
            assert activity_entered.wait(timeout=5)
            maintenance = executor.submit(maintenance_work)

            deadline = time.monotonic() + 5
            while maintenance_ready(connect) and time.monotonic() < deadline:
                threading.Event().wait(0.01)

            assert maintenance_ready(connect) is False
            assert maintenance_entered.is_set() is False
            with pytest.raises(MaintenanceUnavailableError, match="maintenance"):
                with maintenance_activity(connect):
                    pytest.fail("later activity admitted")

            release_activity.set()
            active.result(timeout=5)
            maintenance.result(timeout=5)

        assert maintenance_entered.is_set() is True
        assert maintenance_ready(connect) is True


def test_session_lock_releases_after_activity_failure() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        connect = _connect_factory(postgres)

        with pytest.raises(RuntimeError, match="synthetic"):
            with maintenance_activity(connect):
                raise RuntimeError("synthetic activity failure")

        assert maintenance_ready(connect) is True


def _request(*, priority: str, suffix: str) -> JobRequest:
    return JobRequest(
        schema_version=1,
        job_kind="refresh_graph",
        graph_id="synthetic-graph",
        request_id=RequestId(f"request-{suffix}"),
        idempotency_key=f"idempotency-{suffix}",
        priority=priority,
        operation_options=(("reason", "maintenance-test"),),
        source_generation="sg1:synthetic",
        config_generation="cg1:synthetic",
    )


def test_control_store_refuses_submit_coalesce_and_claim_during_maintenance() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        connect = _connect_factory(postgres)
        store = ControlStore(connect)
        store.initialize_schema()

        assert store.maintenance_ready() is True
        with store.maintenance_window():
            assert store.maintenance_ready() is False
            with pytest.raises(MaintenanceUnavailableError, match="maintenance"):
                store.submit(_request(priority="manual", suffix="manual"))
            with pytest.raises(MaintenanceUnavailableError, match="maintenance"):
                store.coalesce_automatic(
                    _request(priority="automatic", suffix="automatic")
                )
            with pytest.raises(MaintenanceUnavailableError, match="maintenance"):
                store.claim_next(
                    "synthetic-instance",
                    1,
                    timedelta(seconds=30),
                )

        assert store.maintenance_ready() is True
