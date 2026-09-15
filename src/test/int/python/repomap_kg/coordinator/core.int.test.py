from __future__ import annotations

import hashlib
import threading
import time
import unittest
from datetime import timedelta

import psycopg

from repomap_kg.coordinator import normalize_request
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.storage import ControlStore
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.synthetic_worker_adapter import (
    build_synthetic_coordinator,
)


class SyntheticCoordinatorIntegrationTests(unittest.TestCase):
    def setUp(self):
        require_postgres_binaries()
        self.postgres_context = temporary_postgres()
        self.postgres = self.postgres_context.__enter__()
        self.store = ControlStore(self._connect)
        self.store.initialize_schema()

    def tearDown(self):
        self.postgres_context.__exit__(None, None, None)

    def _connect(self):
        return psycopg.connect(
            host=self.postgres.host,
            port=self.postgres.port,
            user=self.postgres.user,
            dbname=self.postgres.database,
            password=self.postgres.password,
        )

    def test_real_store_claim_publication_terminal_and_lease_release(self):
        request = self._request()
        submitted = self.store.submit(request)

        def worker(_claim, _cancel):
            return {
                "status": "succeeded",
                "publication_state": "committed",
                "latest_run_identity": "run-public-1",
                "source_generation": request.source_generation,
                "config_generation": request.config_generation,
                "extractor_generation": "eg1:synthetic",
                "canonicalizer_generation": "kg1:synthetic",
                "_termination_proved": True,
            }

        coordinator = SyntheticCoordinator(
            self.store,
            "coordinator-core",
            worker,
            singleton_ttl=timedelta(seconds=30),
        )
        self._assert_successful_lifecycle(coordinator, submitted.job_id)

    def test_protocol_adapter_carries_claim_graph_and_generation_identity(self):
        submitted = self.store.submit(self._request())
        coordinator = build_synthetic_coordinator(
            self.store, "coordinator-adapter", "success"
        )
        self._assert_successful_lifecycle(coordinator, submitted.job_id)

    def test_protocol_adapter_delivers_durable_cancel_to_active_worker(self):
        submitted = self.store.submit(self._request())
        coordinator = build_synthetic_coordinator(
            self.store, "coordinator-cancel", "cooperative_cancellation"
        )
        coordinator.startup(lambda: None)
        results = []
        thread = threading.Thread(
            target=lambda: results.append(coordinator.run_once())
        )
        thread.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with coordinator._lock:
                if submitted.job_id in coordinator._active_cancellations:
                    break
            time.sleep(0.005)
        self.assertEqual(
            coordinator.request_cancel(submitted.job_id), "cancel_requested"
        )
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, ["cancelled"])
        self.assertEqual(self.store.status(submitted.job_id).state, "cancelled")
        coordinator.shutdown()

    def test_conflicting_existing_marker_is_quarantined_and_pauses_graph(self):
        request = self._request()
        submitted = self.store.submit(request)

        def worker(claim, _cancel):
            self.store.record_publication_marker(
                claim,
                run_identity="run-public-1",
                source_generation=request.source_generation,
                config_generation=request.config_generation,
                extractor_generation="eg1:synthetic",
                canonicalizer_generation="kg1:synthetic",
                outcome="conflicting",
            )
            return {
                "status": "succeeded",
                "publication_state": "committed",
                "latest_run_identity": "run-public-1",
                "source_generation": request.source_generation,
                "config_generation": request.config_generation,
                "extractor_generation": "eg1:synthetic",
                "canonicalizer_generation": "kg1:synthetic",
                "_termination_proved": True,
            }

        coordinator = SyntheticCoordinator(
            self.store, "coordinator-conflict", worker
        )
        coordinator.startup(lambda: None)
        self.assertEqual(coordinator.run_once(), "quarantined")
        self.assertEqual(
            self.store.status(submitted.job_id).state, "quarantined"
        )
        with self.assertRaisesRegex(ValueError, "graph intent is paused"):
            self.store.coalesce_automatic(
                normalize_request(
                    {
                        "schema_version": 1,
                        "job_kind": "refresh_graph",
                        "graph_id": "synthetic-core",
                        "request_id": "request-follow-up",
                        "idempotency_key": "follow-up-key",
                        "priority": "automatic",
                        "operation_options": {"reason": "watcher-hint"},
                    },
                    source_generation=request.source_generation,
                    config_generation=request.config_generation,
                )
            )
        coordinator.shutdown()

    def test_protocol_failure_is_quarantined_without_retry(self):
        submitted = self.store.submit(self._request())
        coordinator = build_synthetic_coordinator(
            self.store, "coordinator-protocol", "malformed_json"
        )
        coordinator.startup(lambda: None)
        self.assertEqual(coordinator.run_once(), "quarantined")
        status = self.store.status(submitted.job_id)
        self.assertEqual(status.state, "quarantined")
        self.assertEqual(status.attempt, 1)
        coordinator.shutdown()

    def _request(self):
        return normalize_request(
            {
                "schema_version": 1,
                "job_kind": "refresh_graph",
                "graph_id": "synthetic-core",
                "request_id": "request-core",
                "idempotency_key": "core-key",
                "priority": "manual",
                "operation_options": {"reason": "operator-request"},
            },
            source_generation="sg1:" + hashlib.sha256(b"source").hexdigest(),
            config_generation="cg1:" + hashlib.sha256(b"config").hexdigest(),
        )

    def _assert_successful_lifecycle(self, coordinator, job_id):
        coordinator.startup(lambda: None)
        self.assertEqual(coordinator.run_once(), "succeeded")
        self.assertEqual(self.store.status(job_id).state, "succeeded")
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM graph_leases")
                self.assertEqual(cursor.fetchone()[0], 0)
        coordinator.shutdown()
