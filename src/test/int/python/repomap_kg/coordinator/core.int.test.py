from __future__ import annotations

import hashlib
import threading
import time
import unittest
from datetime import timedelta

import psycopg

from repomap_kg.coordinator import normalize_request
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.storage import ControlStore, SingletonActiveError
from repomap_kg.coordinator.protocol import WorkerLaunchError
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

    def _assert_attempt(
        self,
        job_id: str,
        attempt: int,
        *,
        is_current: bool,
        result_category: str | None,
        publication_state: str,
        diagnostic: str | None = None,
        finished: bool = True,
    ) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT is_current, result_category, publication_state, diagnostic_summary, "
                "finished_at IS NOT NULL FROM job_attempts WHERE job_id = %s AND attempt = %s",
                (job_id, attempt),
            )
            self.assertEqual(
                cursor.fetchone(),
                (is_current, result_category, publication_state, diagnostic, finished),
            )

    def _assert_no_leases(self, job_id: str | None = None) -> None:
        with self._connect() as connection, connection.cursor() as cursor:
            query = "SELECT count(*) FROM graph_leases" if job_id is None else "SELECT count(*) FROM graph_leases WHERE job_id = %s"
            cursor.execute(query, () if job_id is None else (job_id,))
            self.assertEqual(cursor.fetchone()[0], 0)

    def _success_terminal(self, request, run_identity: str = "run-public-1") -> dict[str, object]:
        return {
            "status": "succeeded", "publication_state": "committed",
            "latest_run_identity": run_identity, "source_generation": request.source_generation,
            "config_generation": request.config_generation, "extractor_generation": "eg1:synthetic",
            "canonicalizer_generation": "kg1:synthetic", "_termination_proved": True,
        }

    def test_real_store_claim_publication_terminal_and_lease_release(self):
        request = self._request()
        submitted = self.store.submit(request)
        coordinator = SyntheticCoordinator(
            self.store,
            "coordinator-core",
            lambda _claim, _cancel: self._success_terminal(request),
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
        status = self.store.status(submitted.job_id)
        self.assertEqual(
            (status.state, status.publication_state, status.error_category, status.attempt),
            ("cancelled", "rolled_back", "cancelled", 1),
        )
        self._assert_no_leases(submitted.job_id)
        self._assert_attempt(
            submitted.job_id, 1, is_current=False, result_category="cancelled", publication_state="rolled_back"
        )
        coordinator.shutdown()

    def test_conflicting_existing_marker_is_quarantined_and_pauses_graph(self):
        request = self._request()
        submitted = self.store.submit(request)

        def worker(claim, _cancel):
            self.store.record_publication_marker(
                claim, run_identity="run-public-1",
                source_generation=request.source_generation, config_generation=request.config_generation,
                extractor_generation="eg1:synthetic", canonicalizer_generation="kg1:synthetic",
                outcome="conflicting",
            )
            return self._success_terminal(request)

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
                self._request(
                    request_id="request-follow-up",
                    key="follow-up-key",
                    priority="automatic",
                    options={"reason": "watcher-hint"},
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
        self.assertEqual(
            (status.state, status.attempt, status.error_category),
            ("quarantined", 1, "protocol"),
        )
        self._assert_no_leases(submitted.job_id)
        coordinator.shutdown()

    def test_coordinator_heartbeat_and_idle_queue_drain(self):
        coordinator = SyntheticCoordinator(self.store, "coord-heartbeat", lambda _c, _k: {})
        epoch = coordinator.startup(lambda: None)
        self.assertGreaterEqual(epoch, 1)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT instance_id, fencing_epoch, status, expires_at FROM coordinator_instances "
                "WHERE singleton_scope = 'control'"
            )
            before = cursor.fetchone()
            assert before is not None
            self.assertEqual(before[:3], ("coord-heartbeat", epoch, "active"))
        with self.assertRaises(SingletonActiveError):
            self.store.acquire_singleton("coord-heartbeat-conflict", timedelta(seconds=30))
        self.assertTrue(coordinator.heartbeat())
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT instance_id, fencing_epoch, status, expires_at "
                           "FROM coordinator_instances WHERE singleton_scope = 'control'")
            after = cursor.fetchone()
            assert after is not None
            self.assertEqual(after[:3], before[:3])
            self.assertGreater(after[3], before[3])
        self.assertEqual(coordinator.run_once(), "idle")
        coordinator.shutdown()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM coordinator_instances WHERE singleton_scope = 'control'"
            )
            self.assertEqual(cursor.fetchone(), ("stopped",))
        next_epoch = self.store.acquire_singleton("coord-heartbeat-next", timedelta(seconds=30))
        self.assertEqual(next_epoch, epoch + 1)
        self.assertTrue(self.store.stop_singleton("coord-heartbeat-next", next_epoch))

    def test_transient_failure_schedules_retry(self):
        submitted = self.store.submit(self._request())

        def transient_worker(_claim, _cancel):
            return {
                "status": "failed", "publication_state": "not_started",
                "error_category": "transient", "_diagnostic_summary": "transient:connection_reset",
                "_termination_proved": True,
            }

        coordinator = SyntheticCoordinator(self.store, "coord-retry", transient_worker)
        coordinator.startup(lambda: None)
        self.assertEqual(coordinator.run_once(), "queued")
        status = self.store.status(submitted.job_id)
        self.assertEqual(
            (status.state, status.attempt, status.publication_state, status.error_category),
            ("queued", 1, "not_started", "transient"),
        )
        self._assert_no_leases(submitted.job_id)
        self._assert_attempt(
            submitted.job_id, 1, is_current=False, result_category="transient",
            publication_state="not_started", diagnostic="transient:connection_reset",
        )
        coordinator.shutdown()

    def test_permanent_failure_transitions_to_failed_and_releases_lease(self):
        submitted = self.store.submit(self._request())

        def permanent_worker(_claim, _cancel):
            return {
                "status": "failed", "publication_state": "not_started",
                "error_category": "permanent", "_diagnostic_summary": "permanent:schema_mismatch",
                "_termination_proved": True,
            }

        coordinator = SyntheticCoordinator(self.store, "coord-perm", permanent_worker)
        coordinator.startup(lambda: None)
        self.assertEqual(coordinator.run_once(), "failed")
        status = self.store.status(submitted.job_id)
        self.assertEqual(
            (status.state, status.attempt, status.publication_state, status.error_category),
            ("failed", 1, "not_started", "permanent"),
        )
        self._assert_no_leases(submitted.job_id)
        self._assert_attempt(
            submitted.job_id, 1, is_current=False, result_category="permanent",
            publication_state="not_started", diagnostic="permanent:schema_mismatch",
        )
        coordinator.shutdown()

    def test_worker_runner_unhandled_crash_marks_reconciliation_required(self):
        submitted = self.store.submit(self._request())

        def crashing_worker(_claim, _cancel):
            raise RuntimeError("unhandled worker process fault")

        coordinator = SyntheticCoordinator(self.store, "coord-crash", crashing_worker)
        epoch = coordinator.startup(lambda: None)
        self.assertEqual(coordinator.run_once(), "reconciliation_required")
        status = self.store.status(submitted.job_id)
        self.assertEqual(
            (status.state, status.attempt, status.publication_state, status.error_category),
            ("reconciliation_required", 1, "commit_unknown", "worker_crash"),
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT graph_id, job_id, attempt, coordinator_instance_id, fencing_epoch "
                "FROM graph_leases WHERE job_id = %s",
                (submitted.job_id,),
            )
            self.assertEqual(cursor.fetchone(), ("synthetic-core", submitted.job_id, 1, "coord-crash", epoch))
        self._assert_attempt(
            submitted.job_id, 1, is_current=True, result_category="worker_crash",
            publication_state="commit_unknown", diagnostic="worker_crash:unhandled_exception",
            finished=False,
        )
        claims = self.store.reconciliation_claims(limit=10)
        self.assertEqual(len(claims), 1)
        claim = claims[0]
        self.assertEqual(claim.job_id, submitted.job_id)
        # Releasing the lease while unresolved is refused
        self.assertFalse(
            self.store.release_graph_lease(
                claim.graph_id, claim.job_id, claim.attempt, claim.instance_id,
                claim.fencing_epoch, reconciler_instance_id="coord-crash",
                reconciler_epoch=epoch,
            )
        )
        # Reconciling without proved termination refuses lease release and retains state
        self.assertEqual(
            self.store.reconcile_publication(
                claim, reconciler_instance_id="coord-crash",
                reconciler_epoch=epoch,
            ),
            "reconciliation_required",
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT graph_id, job_id, attempt, coordinator_instance_id, fencing_epoch "
                "FROM graph_leases WHERE job_id = %s",
                (submitted.job_id,),
            )
            self.assertEqual(cursor.fetchone(), ("synthetic-core", submitted.job_id, 1, "coord-crash", epoch))
        status = self.store.status(submitted.job_id)
        self.assertEqual((status.state, status.publication_state),
                         ("reconciliation_required", "commit_unknown"))
        coordinator.shutdown()

    def test_worker_launch_error_disposes_as_failed(self):
        submitted = self.store.submit(self._request())

        def failing_launch_worker(_claim, _cancel):
            raise WorkerLaunchError("failed to spawn worker")

        coordinator = SyntheticCoordinator(self.store, "coord-launch-err", failing_launch_worker)
        coordinator.startup(lambda: None)
        self.assertEqual(coordinator.run_once(), "failed")
        status = self.store.status(submitted.job_id)
        self.assertEqual(
            (status.state, status.attempt, status.publication_state, status.error_category),
            ("failed", 1, "not_started", "worker_launch"),
        )
        self._assert_no_leases(submitted.job_id)
        self._assert_attempt(
            submitted.job_id, 1, is_current=False, result_category="worker_launch", publication_state="not_started"
        )
        coordinator.shutdown()

    def test_prestart_cancellation_disposes_before_worker_run(self):
        submitted = self.store.submit(self._request())
        self.assertEqual(self.store.request_cancellation(submitted.job_id), "cancel_requested")

        called = []

        def worker(_claim, _cancel):
            called.append(True)
            return {"status": "succeeded", "publication_state": "committed"}

        coordinator = SyntheticCoordinator(self.store, "coord-prestart", worker)
        coordinator.startup(lambda: None)
        self.assertEqual(coordinator.run_once(), "cancelled")
        self.assertFalse(called)
        status = self.store.status(submitted.job_id)
        self.assertEqual(
            (status.state, status.attempt, status.publication_state, status.error_category),
            ("cancelled", 1, "not_started", "cancelled"),
        )
        self._assert_no_leases(submitted.job_id)
        self._assert_attempt(
            submitted.job_id, 1, is_current=False, result_category="cancelled", publication_state="not_started"
        )
        coordinator.shutdown()

    def _request(
        self,
        request_id: str = "request-core",
        key: str = "core-key",
        priority: str = "manual",
        options: dict[str, str] | None = None,
    ):
        return normalize_request(
            {
                "schema_version": 1, "job_kind": "refresh_graph", "graph_id": "synthetic-core",
                "request_id": request_id, "idempotency_key": key, "priority": priority,
                "operation_options": options or {"reason": "operator-request"},
            },
            source_generation="sg1:" + hashlib.sha256(b"source").hexdigest(),
            config_generation="cg1:" + hashlib.sha256(b"config").hexdigest(),
        )

    def _assert_successful_lifecycle(self, coordinator, job_id):
        epoch = coordinator.startup(lambda: None)
        self.assertGreaterEqual(epoch, 1)
        self.assertEqual(coordinator.run_once(), "succeeded")
        status = self.store.status(job_id)
        self.assertEqual(
            (status.state, status.publication_state, status.error_category, status.attempt),
            ("succeeded", "committed", None, 1),
        )
        self._assert_no_leases(job_id)
        self._assert_attempt(
            job_id, 1, is_current=False, result_category=None, publication_state="committed"
        )
        coordinator.shutdown()
