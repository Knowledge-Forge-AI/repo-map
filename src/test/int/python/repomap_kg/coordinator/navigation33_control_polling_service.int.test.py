"""Integration contracts for Order 2: control state/maintenance/polling, desired state, polling scheduler, startup recovery, service, and lifecycle authority."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from threading import Event
import time
from typing import Any, cast
import unittest

from repomap_kg.coordinator._control_maintenance import (
    _sanitize_error_category,
    cleanup_terminal,
)
from repomap_kg.coordinator._control_polling import (
    _safe_graph_id,
    _validate,
    record_condition,
)
from repomap_kg.coordinator._control_state import (
    _validate_progress,
    schedule_retry,
    validate_state_publication,
)
from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator._lifecycle_authority import (
    CoordinatorControlError,
    LocalControlAuthority,
    _maintenance_window,
    _reconcile_control_roles,
    _validate_reference_database,
)
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.desired_state import (
    DesiredStateReconciler,
    PollOutcome,
    WatcherHint,
)
from repomap_kg.coordinator.polling import PollingScheduler
from repomap_kg.coordinator.service import CoordinatorService
from repomap_kg.coordinator.startup_recovery import (
    RecoveryDiagnostic,
    _format_unexpected_diagnostic,
    _record_marker,
    recover_startup,
)
from repomap_kg.ops.source_generation import SourceGenerationResult
from repomap_test_support.test_scratch import short_test_directory


class _MinimalPollingSnapshot:
    def __init__(self, source: SourceGenerationResult) -> None:
        self.source = source
        self.config_generation = "cg1:a"
        self.extractor_generation = "eg1:a"
        self.canonicalizer_generation = "kg1:a"


class Navigation33ControlPollingServiceIntegrationTests(unittest.TestCase):
    """Integration contracts for control helpers, desired-state reconciliation, polling, recovery, and service."""

    def test_control_state_maintenance_polling_and_lifecycle_authority_guards(self) -> None:
        """Control state, maintenance, polling, and lifecycle authority enforce input and capability bounds."""
        # _control_state
        with self.assertRaisesRegex(ValueError, "requires safely unpublished state"):
            validate_state_publication("failed", "committed")
        with self.assertRaisesRegex(ValueError, "commit_unknown publication cannot be retried"):
            validate_state_publication("queued", "commit_unknown")
        with self.assertRaisesRegex(ValueError, "completed progress is invalid"):
            _validate_progress(-1, 10, 100)
        with self.assertRaisesRegex(ValueError, "total progress is invalid"):
            _validate_progress(10, 5, 100)
        claim = JobClaim(job_id="j1", graph_id="g1", attempt=1, instance_id="i1", fencing_epoch=1)
        with self.assertRaisesRegex(ValueError, "retry delay is invalid"):
            schedule_retry(
                cast(Any, lambda: None), claim, expected_state="running",
                delay=timedelta(seconds=-1), category="transient", max_attempts=3,
            )

        # _control_maintenance
        self.assertEqual(_sanitize_error_category(FileNotFoundError("x")), "not_found")
        self.assertEqual(_sanitize_error_category(OSError("x")), "os_error")
        self.assertEqual(_sanitize_error_category(RuntimeError("x")), "unknown_error")
        with self.assertRaisesRegex(ValueError, "cleanup bounds are invalid"):
            cleanup_terminal(cast(Any, lambda: None), minimum_age=timedelta(seconds=-1), limit=10, dry_run=True)

        # _control_polling
        with self.assertRaisesRegex(ValueError, "graph_id is invalid"):
            _safe_graph_id("bad graph!")
        with self.assertRaisesRegex(ValueError, "reconciliation delay is invalid"):
            record_condition(cast(Any, lambda: None), "graph_a", "source_unstable", next_reconcile_seconds=0)
        with self.assertRaisesRegex(ValueError, "reconciliation generations are invalid"):
            _validate("graph_a", ("sg1:a", "cg1:a"), 10.0)
        with self.assertRaisesRegex(ValueError, "reconciliation delay is invalid"):
            _validate("graph_a", ("sg1:a", "cg1:a", "eg1:a", "kg1:a"), 0.0)

        # _lifecycle_authority
        _reconcile_control_roles(object())
        with self.assertRaisesRegex(TypeError, "reconcile_control_roles is not callable"):
            _reconcile_control_roles(type("BadAuth", (), {"reconcile_control_roles": 123})())
        with self.assertRaisesRegex(RuntimeError, "maintenance authority is unavailable"):
            with _maintenance_window(object(), graph_databases=("repomap_g1",)):
                pass
        with self.assertRaisesRegex(CoordinatorControlError, "coordinator_control_reference_invalid"):
            _validate_reference_database("repomap_other_db")
        with self.assertRaisesRegex(ValueError, "database capability is invalid"):
            LocalControlAuthority(Path("/tmp"), capability="invalid_cap")

    def test_desired_state_and_polling_scheduler_contracts(self) -> None:
        """Desired-state reconciler and polling scheduler cover cancellation, jitter, capacity, and outcomes."""
        hint = WatcherHint(graph_id="graph_a", category="modified", observed_at="2026-01-01T00:00:00Z")
        self.assertEqual(hint.to_public()["graph_id"], "graph_a")
        with self.assertRaisesRegex(ValueError, "watcher hint is invalid"):
            WatcherHint(graph_id="bad graph!", category="modified", observed_at="2026-01-01T00:00:00Z")
        with self.assertRaisesRegex(ValueError, "reconciliation timing is invalid"):
            DesiredStateReconciler(cast(Any, object()), cast(Any, object()), next_reconcile_seconds=0)

        # Resolver without cancel_event parameter + cancel set during snapshot
        cancel_ev = Event()
        src_ok = SourceGenerationResult(
            generation="sg1:" + "a" * 64, category="current", file_count=1, total_bytes=10,
        )
        src_none = SourceGenerationResult(
            generation=None, category="source_unstable", file_count=0, total_bytes=0,
        )

        class _NoCancelParamResolver:
            def __init__(self, *, set_cancel_in_snapshot: bool = False, set_cancel_in_pub: bool = False, bad_pub: bool = False, unstable: bool = False) -> None:
                self._set_snap = set_cancel_in_snapshot
                self._set_pub = set_cancel_in_pub
                self._bad_pub = bad_pub
                self._unstable = unstable

            def polling_snapshot(self, _graph_id: str) -> Any:
                if self._set_snap:
                    cancel_ev.set()
                return _MinimalPollingSnapshot(src_none if self._unstable else src_ok)

            def latest_publication(self, _graph_id: str) -> dict[str, object] | None:
                if self._set_pub:
                    cancel_ev.set()
                if self._bad_pub:
                    return None
                return {
                    "source_generation": "sg1:" + "a" * 64 if self._set_pub is False else "sg1:" + "b" * 64,
                    "config_generation": "cg1:a",
                    "extractor_generation": "eg1:a",
                    "canonicalizer_generation": "kg1:a",
                }

        class _StoreWithoutRecorders:
            def coalesce_automatic(self, _req: Any, *, requester: str = "polling") -> Any:
                del requester
                return type("Res", (), {"replayed": True})()

        rec1 = DesiredStateReconciler(
            cast(Any, _NoCancelParamResolver(set_cancel_in_snapshot=True)),
            cast(Any, _StoreWithoutRecorders()),
            cancel_event=cancel_ev,
        )
        self.assertEqual(rec1.reconcile_graph("graph_a").category, "cancelled")

        # Cancel set in latest_publication before coalesce
        cancel_ev = Event()
        rec2 = DesiredStateReconciler(
            cast(Any, _NoCancelParamResolver(set_cancel_in_pub=True)),
            cast(Any, _StoreWithoutRecorders()),
            cancel_event=cancel_ev,
        )
        self.assertEqual(rec2.reconcile_graph("graph_a").category, "cancelled")

        # Store without record_reconciliation_current / record_reconciliation_condition
        cancel_ev = Event()
        rec3 = DesiredStateReconciler(
            cast(Any, _NoCancelParamResolver()),
            cast(Any, _StoreWithoutRecorders()),
            cancel_event=cancel_ev,
        )
        self.assertEqual(rec3.reconcile_graph("graph_a").category, "current")

        rec4 = DesiredStateReconciler(
            cast(Any, _NoCancelParamResolver(unstable=True)),
            cast(Any, _StoreWithoutRecorders()),
            cancel_event=Event(),
        )
        self.assertEqual(rec4.reconcile_graph("graph_a").category, "source_unstable")

        # PollingScheduler validation, jitter, target removal, and outcome counters
        with self.assertRaisesRegex(ValueError, "polling limits are invalid"):
            PollingScheduler(cast(Any, object()), cast(Any, object()), interval_seconds=0)

        targets = ["g_coalesce", "g_unstable"]

        class _SchedResolver:
            def polling_graphs(self) -> tuple[tuple[str, str], ...]:
                return tuple((g, "polling") for g in targets)

        class _SchedReconciler:
            def cancel(self) -> None:
                return None

            def reconcile_graph(self, graph_id: str) -> PollOutcome:
                if graph_id == "g_coalesce":
                    return PollOutcome("refresh_coalesced", False, 1, 10)
                return PollOutcome("source_unstable", False, 0, 0)

        sched = PollingScheduler(
            cast(Any, _SchedResolver()),
            cast(Any, _SchedReconciler()),
            interval_seconds=10.0,
            retry_seconds=5.0,
            jitter_seconds=0.5,
            max_concurrent_polls=1,
            scheduler_wake_seconds=0.02,
        )
        self.assertGreater(sched._deterministic_jitter("g_coalesce"), 0.0)
        sched.start()
        try:
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                h = sched.health()
                if cast(int, h["automatic_refreshes_coalesced"]) >= 1 and cast(int, h["polls_unstable"]) >= 1:
                    break
                time.sleep(0.02)
            self.assertGreaterEqual(cast(int, sched.health()["automatic_refreshes_coalesced"]), 1)
            self.assertGreaterEqual(cast(int, sched.health()["polls_unstable"]), 1)
            targets.pop()
            sched._wake.set()
            time.sleep(0.05)
        finally:
            sched.stop()

    def test_startup_recovery_and_coordinator_service_degrade_and_diagnostics(self) -> None:
        """Startup recovery and CoordinatorService handle singleton loss, diagnostics overflow, and heartbeat degrade."""
        # RecoveryDiagnostic defaults and _format_unexpected_diagnostic
        diag = RecoveryDiagnostic(sequence=1, error_type="CustomErr", category="", summary="")
        self.assertEqual(diag.category, "unexpected_recovery_error")
        self.assertEqual(diag.summary, "CustomErr")
        weird_exc = type("Bad-Class!", (Exception,), {})()
        self.assertEqual(_format_unexpected_diagnostic(weird_exc), "Exception")

        # _record_marker with store lacking record_publication_marker
        _record_marker(cast(Any, object()), object(), {"latest_run_identity": "r1"})

        # recover_startup when renew_singleton returns False and expected refusal in reader
        c_legacy = JobClaim(job_id="jl1", graph_id="g1", attempt=1, instance_id="i1", fencing_epoch=1, graph_lease_fencing_epoch=0)
        c_norm = JobClaim(job_id="jn1", graph_id="g2", attempt=1, instance_id="i1", fencing_epoch=1, graph_lease_fencing_epoch=1)

        class _RecStore:
            def __init__(self, claims: list[JobClaim]) -> None:
                self._claims = claims

            def reconciliation_claims(self, _limit: int) -> list[JobClaim]:
                return list(self._claims)

            def reconcile_publication(self, *_a: Any, **_kw: Any) -> str:
                return "reconciliation_required"

        rep_stop_immediately = recover_startup(
            cast(Any, _RecStore([c_legacy])), lambda _c: None,
            instance_id="i1", fencing_epoch=2, limit=10,
            renew_singleton=lambda: False,
        )
        self.assertEqual(rep_stop_immediately.refused, 1)
        self.assertEqual(rep_stop_immediately.pending, 1)

        calls = 0

        def _renew_once() -> bool:
            nonlocal calls
            calls += 1
            return calls == 1

        rep_stop_after_legacy = recover_startup(
            cast(Any, _RecStore([c_legacy, c_norm])), lambda _c: None,
            instance_id="i1", fencing_epoch=2, limit=10,
            renew_singleton=_renew_once,
        )
        self.assertEqual(rep_stop_after_legacy.pending, 2)

        from psycopg.errors import LockNotAvailable
        from repomap_kg.coordinator._restart_fencing import StaleDurableAuthorityError

        class _RecStoreWithProver(_RecStore):
            def prove_worker_fenced(self, *_a: Any, **_kw: Any) -> object:
                return object()

        rep_perm = recover_startup(
            cast(Any, _RecStoreWithProver([c_norm])),
            lambda _c: (_ for _ in ()).throw(LockNotAvailable("locked")),
            publication_closer=lambda _c, _p: (_ for _ in ()).throw(StaleDurableAuthorityError("fenced")),
            instance_id="i1", fencing_epoch=2, limit=10,
        )
        self.assertEqual(rep_perm.refused, 2)

        # Diagnostics ring overflow > 32 and CoordinatorService heartbeat failure
        many_claims = [
            JobClaim(job_id=f"j_{i}", graph_id=f"g_{i}", attempt=1, instance_id="i1", fencing_epoch=1, graph_lease_fencing_epoch=1)
            for i in range(35)
        ]

        class _FullCoordStore:
            def acquire_singleton(self, _id: str, _ttl: timedelta) -> int:
                return 1

            def stop_singleton(self, _id: str, _ep: int) -> bool:
                return True

            def reconciliation_claims(self, _limit: int) -> list[JobClaim]:
                return many_claims

            def reconcile_publication(self, *_a: Any, **_kw: Any) -> str:
                return "reconciliation_required"

            def claim_next(self, *_a: Any, **_kw: Any) -> None:
                return None

        coord = SyntheticCoordinator(
            cast(Any, _FullCoordStore()), "i1", lambda _c, _e: {},
            publication_reader=lambda _c: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        with self.assertRaisesRegex(RuntimeError, "coordinator is not started"):
            coord.recover_startup()
        coord.startup(coord.recover_startup)
        self.assertEqual(len(coord.recovery_diagnostics), 32)

        # CoordinatorService with heartbeat returning False -> degrades service
        class _DegradingCoord:
            recovery_diagnostics = (
                type("BadDiag", (), {"sequence": -1, "category": "bad", "summary": "bad"})(),
                RecoveryDiagnostic(sequence=1, error_type="RuntimeError"),
            )

            def startup(self, fn: Any) -> int:
                fn()
                return 1

            def run_once(self) -> str:
                return "idle"

            def heartbeat(self) -> bool:
                return False

            def shutdown(self) -> None:
                return None

            def health(self) -> dict[str, object]:
                return {"ownership": {"status": "owned", "instance_id": "i1", "fencing_epoch": 1}}

        with short_test_directory("nav33-svc-", "coord.sock") as d:
            root = Path(d)
            svc = CoordinatorService(
                cast(Any, _DegradingCoord()),
                cast(Any, _FullCoordStore()),
                root,
                heartbeat_seconds=0.02,
                idle_poll_seconds=0.02,
            )
            svc.start(lambda: None)
            try:
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and svc.health()["status"] != "degraded":
                    time.sleep(0.02)
                self.assertEqual(svc.health()["status"], "degraded")
                self.assertEqual(len(cast(list[Any], svc.health()["recovery_diagnostics"])), 1)
            finally:
                svc.stop()
