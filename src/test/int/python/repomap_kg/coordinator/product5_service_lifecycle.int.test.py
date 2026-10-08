"""Integration coverage for native CoordinatorService lifecycle, rollback, and degraded loops."""

from __future__ import annotations

from contextlib import contextmanager

import sys
import threading
import time
import unittest
from typing import Callable, TypeVar, cast

from repomap_kg.coordinator.client import LocalCoordinatorClient
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.endpoint import load_endpoint_descriptor
from repomap_kg.coordinator.limits import DEFAULT_LIMITS
from repomap_kg.coordinator.service import CoordinatorService, default_transport_factory
from repomap_kg.coordinator.startup_recovery import StartupRecoveryReport
from repomap_kg.coordinator.transport import LoopbackTcpService, UnixSocketService
from repomap_test_support.test_scratch import short_test_directory
from repomap_test_support.startup_recovery_scenarios import _harness, _req


@contextmanager
def _service_harness():
    # PostgreSQL retains its harness; this owner supplies the portable endpoint root.
    with _harness() as (store, _cap_dir, connect):
        with short_test_directory("p5-service-", "coordinator/coordinator.sock") as home:
            yield store, home, connect

_T = TypeVar("_T")


class _NarrowCoordinatorProxy:
    """Delegating wrapper around real SyntheticCoordinator allowing narrow failure triggers."""

    def __init__(
        self,
        delegate: SyntheticCoordinator,
        *,
        startup_epoch: object = None,
        pause_claims: bool = False,
        claim_error: Exception | None = None,
        heartbeat_error: Exception | None = None,
        shutdown_error: Exception | None = None,
    ) -> None:
        self._delegate = delegate
        self._pause_claims = pause_claims
        self._startup_epoch = startup_epoch
        self._claim_error = claim_error
        self._claim_hook: Callable[[], None] | None = None
        self._heartbeat_error = heartbeat_error
        self._shutdown_error = shutdown_error
        self.shutdown_called = False

    def startup(self, reconcile: Callable[[], object]) -> int:
        epoch = self._delegate.startup(reconcile)
        return cast(int, self._startup_epoch) if self._startup_epoch is not None else epoch

    def shutdown(self) -> None:
        self.shutdown_called = True
        self._delegate.shutdown()
        if self._shutdown_error is not None:
            raise self._shutdown_error

    def submit(self, action: Callable[[], _T]) -> _T:
        return self._delegate.submit(action)

    def request_cancel(self, job_id: str) -> str:
        return self._delegate.request_cancel(job_id)

    def run_once(self) -> str:
        if self._pause_claims:
            return "idle"
        if self._claim_error is not None:
            if self._claim_hook is not None:
                self._claim_hook()
            raise self._claim_error
        return self._delegate.run_once()

    def heartbeat(self) -> bool:
        if self._heartbeat_error is not None:
            raise self._heartbeat_error
        return self._delegate.heartbeat()

    def acknowledge_recovery_diagnostics(self, seq: int) -> None:
        self._delegate.acknowledge_recovery_diagnostics(seq)

    @property
    def _instance_id(self) -> str:
        return self._delegate._instance_id

    @property
    def _epoch(self) -> int | None:
        return self._delegate._epoch

    @property
    def startup_recovery_report(self) -> object:
        return self._delegate.startup_recovery_report

    @property
    def recovery_diagnostics(self) -> list:
        return list(self._delegate.recovery_diagnostics)


class _MockReconciler:
    def __init__(self, *, stop_error: Exception | None = None, health_error: Exception | None = None) -> None:
        self.started = False
        self.stopped = False
        self.stop_error = stop_error
        self.health_error = health_error
        self.on_start: Callable[[], None] | None = None

    def start(self) -> None:
        self.started = True
        if self.on_start is not None:
            self.on_start()

    def stop(self) -> None:
        self.stopped = True
        if self.stop_error is not None:
            raise self.stop_error

    def health(self) -> dict[str, object]:
        if self.health_error is not None:
            raise self.health_error
        return {"status": "ready"}


class Product5ServiceLifecycleIntegrationTests(unittest.TestCase):
    def test_service_timing_and_coordinator_bounds_validation(self) -> None:
        with _service_harness() as (store, cap_dir, _connect):
            coord = SyntheticCoordinator(store, "coord-b", lambda c, e: {})
            for bad_time in (-1.0, 0.0):
                with self.assertRaises(ValueError):
                    CoordinatorService(coord, store, cap_dir, idle_poll_seconds=bad_time)
                with self.assertRaises(ValueError):
                    CoordinatorService(coord, store, cap_dir, heartbeat_seconds=bad_time)
                with self.assertRaises(ValueError):
                    CoordinatorService(coord, store, cap_dir, wait_seconds=bad_time)
            with self.assertRaises(ValueError):
                CoordinatorService(coord, store, cap_dir, wait_seconds=31.0)

            self.assertIs(default_transport_factory("nt"), LoopbackTcpService)
            self.assertIs(default_transport_factory("posix"), UnixSocketService)

            with self.assertRaises(ValueError):
                SyntheticCoordinator(store, "", lambda c, e: {})
            with self.assertRaises(ValueError):
                SyntheticCoordinator(store, "coord-b", lambda c, e: {}, max_workers=0)
            with self.assertRaises(ValueError):
                SyntheticCoordinator(store, "coord-b", lambda c, e: {}, max_workers=DEFAULT_LIMITS.max_running_workers + 1)

            for action in (coord.run_once, coord.heartbeat, coord.shutdown, coord.cleanup_terminal):
                with self.assertRaises(RuntimeError):
                    action()
            with self.assertRaises(RuntimeError):
                coord.request_cancel("any-job")

    def test_service_loopback_tcp_descriptor_endpoint_lifecycle(self) -> None:
        with _service_harness() as (store, cap_dir, connect):
            coord = SyntheticCoordinator(store, "coord-tcp", lambda c, e: {})
            service = CoordinatorService(_NarrowCoordinatorProxy(coord, pause_claims=True), store, cap_dir, transport_factory=LoopbackTcpService, idle_poll_seconds=0.01, heartbeat_seconds=0.05)
            service.socket_path = cap_dir / "coordinator.endpoint.json"
            service.token_path = service.socket_path

            service.start(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
            try:
                self.assertTrue(service.socket_path.exists())
                client = LocalCoordinatorClient(service.socket_path, service.token_path)
                health = client.health()
                self.assertEqual(health["status"], "ready")
                self.assertEqual(health["health_schema_version"], 2)
                self.assertEqual(health["transport"], {"status": "ready"})

                req = {"schema_version": 1, "job_kind": "refresh_graph", "graph_id": "synthetic-service", "request_id": "req-tcp-1", "idempotency_key": "k-tcp-1", "priority": "manual", "operation_options": {"reason": "test"}}
                res = client.submit(req)
                self.assertIsInstance(res["job_id"], str)
                self.assertEqual(res["state"], "queued")
                with connect() as conn:
                    self.assertEqual(conn.execute("SELECT state FROM jobs WHERE job_id = %s", (res["job_id"],)).fetchone(), ("queued",))
            finally:
                service.stop()
            self.assertFalse(service.socket_path.exists())

    def test_service_start_failure_rollback_and_epoch_adaptation(self) -> None:
        with _service_harness() as (store, cap_dir, _connect):
            real_coord = SyntheticCoordinator(store, "coord-epoch", lambda c, e: {})
            for non_int in (None, 0, -1, False):
                proxy = _NarrowCoordinatorProxy(real_coord, startup_epoch=non_int)
                svc = CoordinatorService(proxy, store, cap_dir, transport_factory=LoopbackTcpService, idle_poll_seconds=0.01, heartbeat_seconds=0.05)
                svc.socket_path = cap_dir / "coordinator.endpoint.json"
                svc.token_path = svc.socket_path
                svc.start(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
                self.assertEqual(load_endpoint_descriptor(svc.socket_path).fencing_epoch, 1)
                svc.stop()

            reconciler = _MockReconciler()
            claim_failed_event = threading.Event()
            real_coord2 = SyntheticCoordinator(store, "coord-crash-start", lambda c, e: {})
            crash_coord = _NarrowCoordinatorProxy(real_coord2, startup_epoch=2, claim_error=RuntimeError("immediate claim loop failure"))
            crash_coord._claim_hook = claim_failed_event.set

            def sync_start() -> None:
                self.assertTrue(claim_failed_event.wait(timeout=2.0))
                deadline = time.monotonic() + 2.0
                while crash_svc.health()["status"] != "degraded" and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(crash_svc.health()["status"], "degraded")
            reconciler.on_start = sync_start

            crash_svc = CoordinatorService(crash_coord, store, cap_dir, desired_reconciler=reconciler, idle_poll_seconds=0.001, heartbeat_seconds=0.05)
            with self.assertRaises(RuntimeError) as cm:
                crash_svc.start(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
            self.assertIn("coordinator service task failed", str(cm.exception))
            self.assertTrue(reconciler.stopped)
            self.assertTrue(crash_coord.shutdown_called)
            self.assertFalse(crash_svc.socket_path.exists())
            self.assertFalse(crash_svc.token_path.exists())
            self.assertEqual(crash_svc.health()["service"], {"status": "stopped"})

    def test_service_degraded_heartbeat_and_claim_loops(self) -> None:
        with _service_harness() as (store, cap_dir, _connect):
            real_coord_hb = SyntheticCoordinator(store, "coord-hb-deg", lambda c, e: {})
            proxy_hb = _NarrowCoordinatorProxy(real_coord_hb)
            svc_hb = CoordinatorService(proxy_hb, store, cap_dir, idle_poll_seconds=0.01, heartbeat_seconds=0.01)
            svc_hb.start(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
            try:
                client_hb = LocalCoordinatorClient(svc_hb.socket_path, svc_hb.token_path)
                proxy_hb._heartbeat_error = RuntimeError("heartbeat lost")
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    if client_hb.health()["status"] == "degraded":
                        break
                    time.sleep(0.02)
                health_hb = client_hb.health()
                self.assertEqual(health_hb["status"], "degraded")
                self.assertEqual(health_hb["service"], {"status": "degraded"})
            finally:
                svc_hb.stop()

            real_coord_claim = SyntheticCoordinator(store, "coord-claim-deg", lambda c, e: {})
            proxy_claim = _NarrowCoordinatorProxy(real_coord_claim)
            svc_claim = CoordinatorService(proxy_claim, store, cap_dir, idle_poll_seconds=0.001, heartbeat_seconds=0.1)
            svc_claim.start(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
            try:
                client_claim = LocalCoordinatorClient(svc_claim.socket_path, svc_claim.token_path)
                proxy_claim._claim_error = RuntimeError("claim explosion")
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    if client_claim.health()["status"] == "degraded":
                        break
                    time.sleep(0.02)
                self.assertEqual(client_claim.health()["status"], "degraded")
            finally:
                svc_claim.stop()

    def test_service_stop_error_accumulation_and_cleanup(self) -> None:
        with _service_harness() as (store, cap_dir, _connect):
            reconciler = _MockReconciler(stop_error=RuntimeError("reconciler stop failed"))
            real_coord = SyntheticCoordinator(store, "coord-stop-err", lambda c, e: {})
            proxy = _NarrowCoordinatorProxy(real_coord, shutdown_error=RuntimeError("shutdown failed"))
            svc = CoordinatorService(proxy, store, cap_dir, desired_reconciler=reconciler, idle_poll_seconds=0.01, heartbeat_seconds=0.05)
            svc.start(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
            with self.assertRaises(RuntimeError) as cm:
                svc.stop()
            self.assertEqual(str(cm.exception), "reconciler stop failed")
            self.assertEqual(svc.health()["service"], {"status": "stopped"})
            self.assertFalse(svc.socket_path.exists())
            self.assertFalse(svc.token_path.exists())
            svc.stop()

    def test_service_health_readiness_probe_reconciler_and_diagnostics(self) -> None:
        with _service_harness() as (store, cap_dir, _connect):
            real_coord = SyntheticCoordinator(store, "coord-hlth-test", lambda c, e: {})
            reconciler = _MockReconciler()
            probe_outcome: list[object] = [True]

            def probe():
                if isinstance(probe_outcome[0], Exception):
                    raise probe_outcome[0]
                return bool(probe_outcome[0])

            svc = CoordinatorService(real_coord, store, cap_dir, desired_reconciler=reconciler, readiness_probe=probe, idle_poll_seconds=0.01, heartbeat_seconds=0.05)
            svc.start(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
            try:
                probe_outcome[0] = True
                h_ready = svc.health()
                self.assertEqual(h_ready["status"], "ready")
                self.assertEqual(h_ready["storage"], {"status": "ready"})
                self.assertEqual(h_ready["polling"], {"status": "ready"})

                probe_outcome[0] = False
                h_upgrade = svc.health()
                self.assertEqual(h_upgrade["status"], "not_ready")
                self.assertEqual(h_upgrade["storage"], {"status": "schema_upgrading"})

                probe_outcome[0] = RuntimeError("db unavailable")
                h_unavail = svc.health()
                self.assertEqual(h_unavail["status"], "not_ready")
                self.assertEqual(h_unavail["storage"], {"status": "unavailable"})

                reconciler.health_error = RuntimeError("polling failed")
                h_poll_deg = svc.health()
                self.assertEqual(h_poll_deg["polling"], {"status": "degraded"})

                svc.acknowledge_recovery_diagnostics(10)
            finally:
                svc.stop()

    def test_synthetic_coordinator_core_saturation_and_lifecycle_refusals(self) -> None:
        with _service_harness() as (store, cap_dir, connect):
            store.submit(_req("synthetic-service", "sat-1"))
            worker_started = threading.Event()
            worker_release = threading.Event()

            def blocking_worker(claim, cancel_event):
                worker_started.set()
                worker_release.wait(timeout=5.0)
                return {
                    "status": "succeeded", "publication_state": "committed",
                    "latest_run_identity": "r1", "source_generation": claim.source_generation,
                    "config_generation": claim.config_generation, "extractor_generation": claim.extractor_generation,
                    "canonicalizer_generation": claim.canonicalizer_generation, "_termination_proved": True,
                }

            coord = SyntheticCoordinator(store, "coord-core", blocking_worker, max_workers=1)
            coord.startup(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
            outcomes: list[str | BaseException] = []
            def run() -> None:
                try:
                    outcomes.append(coord.run_once())
                except BaseException as error:
                    outcomes.append(error)
            t = threading.Thread(target=run)
            t.start()
            try:
                self.assertTrue(worker_started.wait(timeout=5.0))
                self.assertEqual(coord.run_once(), "saturated")

            finally:
                worker_release.set()
                t.join(timeout=5.0)
            self.assertFalse(t.is_alive())
            self.assertEqual(outcomes, ["succeeded"])
            self.assertEqual(coord.run_once(), "idle")
            coord.shutdown()

            sub_fail = store.submit(_req("synthetic-service", "fail-diag"))
            def failing_worker(claim, cancel_event):
                raise RuntimeError("postgresql://user:secretpass@host:5432/dbname connection lost")

            coord_fail = SyntheticCoordinator(store, "coord-fail", failing_worker)
            coord_fail.startup(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
            self.assertEqual(coord_fail.run_once(), "reconciliation_required")
            status = store.status(sub_fail.job_id)
            self.assertEqual(status.state, "reconciliation_required")
            self.assertEqual(status.diagnostic_summary, "coordinator_exception:RuntimeError")
            with connect() as conn:
                row = conn.execute(
                    "SELECT diagnostic_summary FROM job_attempts WHERE job_id = %s AND is_current",
                    (sub_fail.job_id,),
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "coordinator_exception:RuntimeError")
            coord_fail.shutdown()

            coord_lost = SyntheticCoordinator(store, "coord-lost", lambda c, e: {})
            coord_lost.startup(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
            with connect() as conn:
                conn.execute("DELETE FROM coordinator_instances WHERE singleton_scope = 'control'")
            with self.assertRaises(RuntimeError) as cm_lost:
                coord_lost.shutdown()
            self.assertIn("coordinator singleton ownership was lost", str(cm_lost.exception))

            coord_clean = SyntheticCoordinator(store, "coord-clean", lambda c, e: {})
            coord_clean.startup(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
            coord_clean.cleanup_terminal()
            self.assertIsInstance(coord_clean.residual_evidence, tuple)
            coord_clean.shutdown()


if __name__ == "__main__":
    sys.exit("Direct execution unsupported: use tools/run_tests.py --suite int with container sandbox admission.")
