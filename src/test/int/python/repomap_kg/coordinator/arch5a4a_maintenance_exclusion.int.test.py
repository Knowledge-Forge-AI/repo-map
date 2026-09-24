from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

from repomap_kg.coordinator.contracts import JobRequest
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.local_lifecycle import (
    initialize_coordinator_control,
    maintenance_activity_for_home,
    maintenance_window_for_database_drop,
    maintenance_window_for_graph_upgrade,
)
from repomap_kg.storage.authority import RequestId
from repomap_kg.coordinator.storage import ControlStore
from repomap_test_support.test_scratch import short_test_directory
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


def test_coordinator_execution_and_admission_excluded_during_maintenance() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        connect = _connect_factory(postgres)
        store = ControlStore(connect)
        store.initialize_schema()

        submitted = store.submit(_request(priority="manual", suffix="coord-maint"))
        worker_calls = []

        def worker(claim, _cancel_event):
            worker_calls.append(claim.job_id)
            return {
                "status": "succeeded",
                "publication_state": "committed",
                "latest_run_identity": "run-maintenance",
                "source_generation": claim.source_generation,
                "config_generation": claim.config_generation,
                "extractor_generation": claim.extractor_generation,
                "canonicalizer_generation": claim.canonicalizer_generation,
                "_termination_proved": True,
            }

        coordinator = SyntheticCoordinator(
            store,
            "coordinator-maint",
            worker,
            singleton_ttl=timedelta(seconds=30),
        )
        coordinator.startup(lambda: None)
        try:
            with store.maintenance_window():
                assert store.maintenance_ready() is False
                with pytest.raises(MaintenanceUnavailableError, match="maintenance"):
                    coordinator.run_once()
                assert worker_calls == []

            assert store.maintenance_ready() is True
            assert coordinator.run_once() == "succeeded"
            assert worker_calls == [submitted.job_id]
            assert store.status(submitted.job_id).state == "succeeded"
        finally:
            coordinator.shutdown()


def test_lifecycle_maintenance_windows_and_database_ownership_validation(
    monkeypatch,
) -> None:
    require_postgres_binaries()
    with short_test_directory("arch5a-", "ops/configured.rp.toml") as directory:
        root = Path(directory)
        with temporary_postgres() as postgres:
            monkeypatch.setenv("ARCH5A_TEST_PASSWORD", postgres.password)
            home = root / "ops"
            home.mkdir(mode=0o700, exist_ok=True)
            repository = root / "repository"
            repository.mkdir()
            (home / "configured.rp.toml").write_text(
                f'''schema_version = 1

[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"

[postgres]
host = "{postgres.host}"
port = {postgres.port}
database = "{postgres.database}"
user = "{postgres.user}"
password_env = "ARCH5A_TEST_PASSWORD"

[[graphs]]
id = "graph-a"
name = "Graph A"
root_path = "{repository}"
repository_name = "repo-a"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "disabled"
mode = "read_only"
''',
                encoding="utf-8",
            )
            initialize = initialize_coordinator_control(home)
            assert initialize["result"] == "ready"

            with pytest.raises(MaintenanceUnavailableError, match="not an owned graph database"):
                with maintenance_window_for_graph_upgrade(home, "unowned-graph"):
                    pass

            with pytest.raises(MaintenanceUnavailableError, match="not an owned database"):
                with maintenance_window_for_database_drop(home, "unowned-drop"):
                    pass

            with maintenance_window_for_graph_upgrade(home, postgres.database):
                with pytest.raises(MaintenanceUnavailableError, match="maintenance"):
                    with maintenance_activity_for_home(home):
                        pytest.fail("control plane activity admitted during graph upgrade")

            with pytest.raises(MaintenanceUnavailableError, match="maintenance authority is unavailable"):
                with maintenance_activity_for_home(root / "nonexistent"):
                    pass
