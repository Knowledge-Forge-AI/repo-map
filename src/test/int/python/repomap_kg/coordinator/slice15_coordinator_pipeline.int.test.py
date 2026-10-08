"""Slice15 repairs composing durable ownership, service, transport, and client."""

from contextlib import contextmanager
from pathlib import Path
import unittest

import psycopg

from repomap_kg.coordinator.client import CoordinatorClientError, LocalCoordinatorClient
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.storage import ControlStore
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.synthetic_worker_adapter import build_synthetic_coordinator
from repomap_test_support.test_scratch import short_test_directory


@contextmanager
def _service():
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        def connect():
            return psycopg.connect(host=postgres.host, port=postgres.port,
                                   user=postgres.user, dbname=postgres.database,
                                   password=postgres.password)

        store = ControlStore(connect)
        store.initialize_schema()
        coordinator = build_synthetic_coordinator(store, "slice15-service", "success")
        with short_test_directory("s15-", "coordinator.sock") as directory:
            service = CoordinatorService(coordinator, store, Path(directory),
                                         idle_poll_seconds=0.01, heartbeat_seconds=0.05)
            try:
                yield service
            finally:
                service.stop()


class Slice15CoordinatorPipelineIntegrationTests(unittest.TestCase):
    def test_s15_c01_coordinator_service_start(self) -> None:
        with _service() as service:
            reconciled = []
            service.start(lambda: reconciled.append(True))
            client = LocalCoordinatorClient(service.socket_path, service.token_path)
            self.assertEqual(reconciled, [True])
            self.assertEqual(client.health()["status"], "ready")
            self.assertTrue(service.socket_path.exists())
            self.assertTrue(service.token_path.exists())
            with self.assertRaisesRegex(RuntimeError, "already started"):
                service.start(lambda: None)
            self.assertEqual(client.health()["status"], "ready")
            service.stop()
            self.assertEqual(service.health()["status"], "stopped")
            self.assertFalse(service.socket_path.exists())
            self.assertFalse(service.token_path.exists())

    def test_s15_c02_coordinator_service_stop(self) -> None:
        with _service() as service:
            service.stop()
            service.start(lambda: None)
            stale = LocalCoordinatorClient(service.socket_path, service.token_path)
            self.assertEqual(stale.health()["status"], "ready")
            service.stop()
            service.stop()
            self.assertFalse(service.socket_path.exists())
            self.assertFalse(service.token_path.exists())
            service.start(lambda: None)
            with self.assertRaisesRegex(CoordinatorClientError, "unauthorized"):
                stale.health()
            current = LocalCoordinatorClient(service.socket_path, service.token_path)
            self.assertEqual(current.health()["status"], "ready")
