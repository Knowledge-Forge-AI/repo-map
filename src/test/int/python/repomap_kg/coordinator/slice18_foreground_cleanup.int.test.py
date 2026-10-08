"""Foreground callback failure releases real service ownership and local endpoints."""

from pathlib import Path
import signal
from threading import Event

import psycopg
import pytest

from repomap_kg.coordinator.client import LocalCoordinatorClient
from repomap_kg.coordinator.local_mode import LocalCoordinatorRuntime, serve_configured_coordinator
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.startup_recovery import StartupRecoveryReport
from repomap_kg.coordinator.storage import ControlStore
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.synthetic_worker_adapter import build_synthetic_coordinator
from repomap_test_support.test_scratch import short_test_directory


def test_foreground_failure_restores_signal_handlers_and_service_can_restart():
    require_postgres_binaries()
    with temporary_postgres() as postgres, short_test_directory("s18-", "coordinator.sock") as directory:
        def connect():
            return psycopg.connect(host=postgres.host, port=postgres.port, user=postgres.user,
                                   dbname=postgres.database, password=postgres.password)

        store = ControlStore(connect)
        store.initialize_schema()
        coordinator = build_synthetic_coordinator(store, "slice18-foreground", "success")
        service = CoordinatorService(coordinator, store, Path(directory),
                                     idle_poll_seconds=0.01, heartbeat_seconds=0.05)
        runtime = LocalCoordinatorRuntime(service, StartupRecoveryReport(0, 0, 0, 0, 0))
        signals = (signal.SIGINT, signal.SIGTERM)
        before = {sig: signal.getsignal(sig) for sig in signals}

        def start(_home, *, psql_path=None):
            service.start(lambda: None)
            return runtime

        def fail_ready(payload):
            assert payload["result"] == "ready"
            assert LocalCoordinatorClient(service.socket_path, service.token_path).health()["status"] == "ready"
            raise ValueError("consumer refused readiness")

        try:
            with pytest.raises(ValueError, match="consumer refused readiness"):
                serve_configured_coordinator(directory, fail_ready, runtime_factory=start)
            assert {sig: signal.getsignal(sig) for sig in signals} == before
            assert service.health()["status"] == "stopped"
            assert not service.socket_path.exists() and not service.token_path.exists()
            stop = Event()

            def accept_ready(payload):
                assert payload["result"] == "ready"
                assert LocalCoordinatorClient(service.socket_path, service.token_path).health()["status"] == "ready"
                stop.set()

            serve_configured_coordinator(directory, accept_ready, runtime_factory=start, stop_event=stop)
            assert service.health()["status"] == "stopped"
            assert not service.socket_path.exists() and not service.token_path.exists()
        finally:
            service.stop()
