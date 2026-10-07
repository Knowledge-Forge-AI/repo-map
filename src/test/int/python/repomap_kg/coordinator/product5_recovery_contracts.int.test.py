"""Behavioral integration tests for Product5 startup recovery contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping, cast

import pytest
from repomap_kg.coordinator import _publication_phase
from repomap_kg.coordinator._control_types import JobClaim, SingletonActiveError
from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.limits import DEFAULT_LIMITS
from repomap_kg.coordinator.startup_recovery import (
    PublicationRouteChangedError,
    recover_startup,
)
from repomap_kg.coordinator.storage import ControlStore
from repomap_test_support.startup_recovery_scenarios import (
    _harness,
    _make_refresh_fixture,
    _refresh_harness,
    _req,
    _req_norm,
)


def _to_running(store: Any, claim: JobClaim, epoch: int) -> None:
    for exp, nxt in (("claimed", "starting"), ("starting", "running")):
        assert store.compare_and_set_state(
            claim.job_id, expected_state=exp, new_state=nxt,
            attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=epoch,
        )


@pytest.mark.parametrize("kind", ["failed", "cancelled", "protocol", "conflicting"])
def test_reconciliation_terminal_classifications_and_marker_conflicts(kind: str) -> None:
    with _refresh_harness() as (_, cap_dir, connect, postgres, graph_db):
        # A maintained one-attempt policy reaches permanent failure naturally.
        store = ControlStore(connect, limits=replace(DEFAULT_LIMITS, max_retry_attempts=1))
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
        store.set_durable_fence_callback(lambda cl, **kw: resolver.install_graph_publication_fence(cl, **kw))
        epoch = store.acquire_singleton("prior", timedelta(seconds=300))
        store.submit(_req_norm("terminal", sg, cg, eg, kg))
        claim = store.claim_next("prior", epoch, timedelta(seconds=300))
        assert claim is not None
        _to_running(store, claim, epoch)
        expected = "running"
        if kind == "cancelled":
            assert store.request_cancellation(claim.job_id) == "cancel_requested"
            expected = "cancel_requested"
        assert store.mark_reconciliation_required(
            claim, expected_state=expected, category="protocol" if kind == "protocol" else "worker_crash",
        )
        assert store.mark_attempt_terminated(claim, process_cleanup_proved=True)
        if kind == "conflicting":
            assert store.record_publication_marker(
                claim, run_identity="conflicting-run", source_generation="sg1:different",
                config_generation=cg, extractor_generation=eg, canonicalizer_generation=kg, outcome="committed",
            )
        with connect() as conn:
            conn.execute("UPDATE graph_leases SET expires_at = now() - interval '1 second' WHERE job_id = %s", (claim.job_id,))
        assert store.stop_singleton("prior", epoch)
        replacement = store.acquire_singleton("replacement", timedelta(seconds=300))
        assert replacement > epoch
        closed = kind in {"failed", "cancelled"}
        if closed:
            _publication_phase.initialize(cap_dir, claim)
            assert store.close_unpublished_reconciliation(
                claim, reconciler_instance_id="replacement", reconciler_epoch=replacement,
                file_closer=lambda cl, proof: _publication_phase.close_unpublished(cap_dir, cl, proof=proof),
            )
        outcome = store.reconcile_publication(
            claim, reconciler_instance_id="replacement", reconciler_epoch=replacement, unpublished_proved=closed,
        )
        target = kind if closed else "quarantined"
        category = {"failed": "permanent", "cancelled": "cancelled", "protocol": "protocol", "conflicting": "publication_unknown"}[kind]
        assert outcome == target
        with connect() as conn:
            assert conn.execute(
                "SELECT state, publication_state, error_category, finished_at IS NOT NULL FROM jobs WHERE job_id = %s",
                (claim.job_id,),
            ).fetchone() == (target, "rolled_back" if closed else "commit_unknown", category, True)
            assert conn.execute("SELECT is_current, result_category, finished_at IS NOT NULL FROM job_attempts WHERE job_id = %s", (claim.job_id,)).fetchone() == (False, category, True)
            assert conn.execute("SELECT count(*) FROM graph_leases WHERE job_id = %s", (claim.job_id,)).fetchone() == (0,)
            if not closed:
                assert conn.execute("SELECT paused, dirty FROM coalescing_state WHERE graph_id = %s", (claim.graph_id,)).fetchone() == (True, True)
        if closed:
            assert len(_publication_phase.retire_evidence(cap_dir, claim)) == 2
        assert store.stop_singleton("replacement", replacement)


@pytest.mark.parametrize("failure", [PublicationRouteChangedError, OSError, KeyError])
def test_startup_reader_failures_retain_durable_uncertainty(failure: type[Exception]) -> None:
    with _harness() as (store, _, connect):
        epoch = store.acquire_singleton("reader", timedelta(seconds=300))
        store.submit(_req("synthetic-reader", "reader"))
        claim = store.claim_next("reader", epoch, timedelta(seconds=300))
        assert claim is not None
        _to_running(store, claim, epoch)
        assert store.mark_reconciliation_required(claim, expected_state="running", category="worker_crash")
        assert store.mark_attempt_terminated(claim, process_cleanup_proved=True)
        def reader(_: object) -> Mapping[str, object] | None:
            raise failure("fixture failure")
        report = recover_startup(store, reader, instance_id="reader", fencing_epoch=epoch, limit=10)
        assert (report.scanned, report.resolved, report.pending) == (1, 0, 1)
        assert report.route_changed == int(failure is PublicationRouteChangedError)
        assert report.unavailable == int(failure in {OSError, KeyError})
        assert report.refused == 0
        assert report.unexpected == (("KeyError",) if failure is KeyError else ())
        with connect() as conn:
            assert conn.execute("SELECT state, publication_state FROM jobs WHERE job_id = %s", (claim.job_id,)).fetchone() == ("reconciliation_required", "commit_unknown")
        assert store.stop_singleton("reader", epoch)


def test_prover_only_compatibility_cannot_guess_durable_rollback() -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
        store.set_durable_fence_callback(lambda cl, **kw: resolver.install_graph_publication_fence(cl, **kw))
        epoch = store.acquire_singleton("old", timedelta(seconds=300))
        store.submit(_req_norm("compatibility", sg, cg, eg, kg))
        claim = store.claim_next("old", epoch, timedelta(seconds=300))
        assert claim is not None
        _to_running(store, claim, epoch)
        assert store.mark_reconciliation_required(claim, expected_state="running", category="worker_crash")
        assert store.mark_attempt_terminated(claim, process_cleanup_proved=True)
        _publication_phase.initialize(cap_dir, claim)
        with connect() as conn:
            conn.execute("UPDATE graph_leases SET expires_at = now() - interval '1 second' WHERE job_id = %s", (claim.job_id,))
        assert store.stop_singleton("old", epoch)
        replacement = store.acquire_singleton("new", timedelta(seconds=300))
        class ProverOnlyStore:
            def __getattr__(self, name: str) -> Any:
                if name == "close_unpublished_reconciliation":
                    raise AttributeError(name)
                return getattr(store, name)
        report = recover_startup(
            cast(Any, ProverOnlyStore()), lambda _: {"publication_state": "commit_unknown"},
            instance_id="new", fencing_epoch=replacement, limit=10,
            publication_closer=lambda cl, proof: _publication_phase.close_unpublished(cap_dir, cl, proof=cast(Any, proof)),
        )
        assert (report.resolved, report.pending) == (0, 1)
        assert _publication_phase.publication_state(cap_dir, claim) == "not_started"
        # File closure alone is insufficient; the durable store must also close.
        assert store.status(claim.job_id).publication_state == "commit_unknown"
        assert store.stop_singleton("new", replacement)


def test_recovery_diagnostics_and_acknowledgement() -> None:
    with _harness() as (store, cap_dir, connect):
        epoch_init = store.acquire_singleton("inst-diag-init", timedelta(seconds=300))
        store.submit(_req("synthetic-diag", "diag-key"))
        claim = store.claim_next("inst-diag-init", epoch_init, timedelta(seconds=300))
        assert claim is not None
        _to_running(store, claim, epoch_init)
        assert store.mark_reconciliation_required(claim, expected_state="running", category="worker_crash")
        assert store.mark_attempt_terminated(claim, process_cleanup_proved=True)
        store.stop_singleton("inst-diag-init", epoch_init)

        call_count = 0
        class CustomExtractionError(Exception): pass

        def failing_reader(c: object) -> Mapping[str, object] | None:
            nonlocal call_count
            call_count += 1
            raise CustomExtractionError(f"read failure {call_count}")

        coord = SyntheticCoordinator(
            store, "inst-diag",
            lambda *_: {"status": "failed", "_termination_proved": True},
            publication_reader=failing_reader,
            singleton_ttl=timedelta(seconds=300),
        )

        with pytest.raises(ValueError, match="nonnegative sequence"): coord.acknowledge_recovery_diagnostics(-1)
        with pytest.raises(ValueError, match="nonnegative sequence"): coord.acknowledge_recovery_diagnostics(cast(Any, "invalid"))

        # Real coordinator startup executes recover_startup and records diagnostic
        coord.startup(coord.recover_startup)
        diagnostics = coord.recovery_diagnostics
        assert len(diagnostics) == 1
        assert diagnostics[0].sequence == 1 and diagnostics[0].summary == "CustomExtractionError"
        assert diagnostics[0].to_dict() == {"category": "unexpected_recovery_error", "summary": "CustomExtractionError", "sequence": 1}

        # Repeated real recovery passes retain only the latest 32 diagnostics.
        for _ in range(32):
            assert coord.heartbeat() is True
        diagnostics2 = coord.recovery_diagnostics
        assert len(diagnostics2) == 32
        assert diagnostics2[0].sequence == 2 and diagnostics2[-1].sequence == 33
        assert all(item.summary == "CustomExtractionError" for item in diagnostics2)

        coord.acknowledge_recovery_diagnostics(32)
        remaining = coord.recovery_diagnostics
        assert len(remaining) == 1 and remaining[0].sequence == 33

        coord.shutdown()

        # Startup exception stops singleton and clears epoch
        def failing_startup() -> None: raise RuntimeError("simulated startup crash")
        with pytest.raises(RuntimeError, match="simulated startup crash"): coord.startup(failing_startup)

        assert coord._epoch is None
        with connect() as conn:
            assert conn.execute("SELECT status FROM coordinator_instances WHERE instance_id = 'inst-diag'").fetchone() == ("stopped",)


def test_recovery_singleton_loss_and_retirer_residuals() -> None:
    with _harness() as (store, _, connect):
        epoch = store.acquire_singleton("inst-renew", timedelta(seconds=300))

        # 1. Residual evidence when publication_retirer raises OSError or ValueError
        store.submit(_req("synthetic-res-1", "res-key-1"))
        claim_res = store.claim_next("inst-renew", epoch, timedelta(seconds=300))
        assert claim_res is not None
        _to_running(store, claim_res, epoch)
        assert store.mark_reconciliation_required(claim_res, expected_state="running", category="worker_crash")
        assert store.mark_attempt_terminated(claim_res, process_cleanup_proved=True)
        store.record_publication_marker(
            claim_res, run_identity="run-res-1", source_generation=claim_res.source_generation,
            config_generation=claim_res.config_generation, extractor_generation=claim_res.extractor_generation,
            canonicalizer_generation=claim_res.canonicalizer_generation, outcome="committed",
        )

        def failing_retirer(claim: object) -> None: raise OSError("permission denied during retire")
        rep_res = recover_startup(store, lambda c: {"publication_state": "committed"}, instance_id="inst-renew", fencing_epoch=epoch, limit=10, publication_retirer=failing_retirer)
        assert (rep_res.resolved, rep_res.residuals, rep_res.pending) == (1, 1, 0)
        with connect() as conn:
            assert conn.execute("SELECT state, publication_state FROM jobs WHERE job_id = %s", (claim_res.job_id,)).fetchone() == ("succeeded", "committed")

        # 2. Singleton renewal failure during claim scan breaks recovery loop early
        store.submit(_req("synthetic-renew-a", "renew-key-a"))
        store.submit(_req("synthetic-renew-b", "renew-key-b"))
        claim_a = store.claim_next("inst-renew", epoch, timedelta(seconds=300))
        claim_b = store.claim_next("inst-renew", epoch, timedelta(seconds=300))
        assert claim_a is not None and claim_b is not None
        for cl in (claim_a, claim_b):
            _to_running(store, cl, epoch)
            assert store.mark_reconciliation_required(cl, expected_state="running", category="worker_crash")
            assert store.mark_attempt_terminated(cl, process_cleanup_proved=True)
            store.record_publication_marker(
                cl, run_identity=f"run-{cl.job_id}", source_generation=cl.source_generation,
                config_generation=cl.config_generation, extractor_generation=cl.extractor_generation,
                canonicalizer_generation=cl.canonicalizer_generation, outcome="committed",
            )

        renew_count = 0
        def expiring_renew() -> bool:
            nonlocal renew_count
            renew_count += 1
            return renew_count <= 1

        rep_renew = recover_startup(store, lambda c: {"publication_state": "committed"}, instance_id="inst-renew", fencing_epoch=epoch, limit=10, renew_singleton=expiring_renew)
        assert (rep_renew.scanned, rep_renew.resolved, rep_renew.pending, rep_renew.refused) == (2, 1, 1, 1)
        with connect() as conn:
            assert conn.execute("SELECT state FROM jobs WHERE job_id = %s", (claim_a.job_id,)).fetchone() == ("succeeded",)
            assert conn.execute("SELECT state FROM jobs WHERE job_id = %s", (claim_b.job_id,)).fetchone() == ("reconciliation_required",)
        store.stop_singleton("inst-renew", epoch)


def test_control_ownership_coalescing_and_duration_guards() -> None:
    with _harness() as (store, _, connect):
        # Durations must be strictly positive via maintained store operations
        epoch_g = store.acquire_singleton("inst-guard", timedelta(seconds=300))
        with pytest.raises(ValueError, match="duration must be positive"):
            store.claim_next("inst-guard", epoch_g, timedelta(seconds=-1))
        with pytest.raises(ValueError, match="duration must be positive"):
            store.claim_next("inst-guard", epoch_g, timedelta(seconds=0))
        store.stop_singleton("inst-guard", epoch_g)

        req = replace(_req("synthetic-auto-guard", "auto-guard-key"), priority="automatic")
        store.coalesce_automatic(req, requester="watcher")
        with connect() as conn:
            assert conn.execute(
                "SELECT queued_job_id IS NOT NULL, running_job_id, dirty, paused FROM coalescing_state WHERE graph_id = %s",
                (req.graph_id,),
            ).fetchone() == (True, None, True, False)

        epoch = store.acquire_singleton("inst-auto-guard", timedelta(seconds=300))
        store.submit(_req("synthetic-man-guard", "man-guard-key"))
        claim_auto = store.claim_next("inst-auto-guard", epoch, timedelta(seconds=300), automatic_only=True)
        assert claim_auto is not None and claim_auto.graph_id == req.graph_id

        with connect() as conn:
            assert conn.execute(
                "SELECT queued_job_id, running_job_id, dirty FROM coalescing_state WHERE graph_id = %s",
                (req.graph_id,),
            ).fetchone() == (None, claim_auto.job_id, False)

        # reconcile_publication edge cases
        _to_running(store, claim_auto, epoch)
        assert store.mark_reconciliation_required(claim_auto, expected_state="running", category="worker_crash")
        assert store.reconcile_publication(claim_auto, reconciler_instance_id="inst-auto-guard", reconciler_epoch=epoch) == "reconciliation_required"

        assert store.mark_attempt_terminated(claim_auto, process_cleanup_proved=True)
        assert store.reconcile_publication(claim_auto, reconciler_instance_id="inst-auto-guard", reconciler_epoch=epoch, unpublished_proved=True) == "reconciliation_required"

        ghost_claim = JobClaim(
            "synthetic-ghost-job", "synthetic-ghost-graph", 1, "inst-auto-guard", epoch,
            source_generation="sg1:ghost", config_generation="cg1:ghost",
            extractor_generation="eg1:ghost", canonicalizer_generation="kg1:ghost",
        )
        assert store.reconcile_publication(ghost_claim, reconciler_instance_id="inst-auto-guard", reconciler_epoch=epoch) == "ownership_lost"

        assert store.stop_singleton("inst-auto-guard", epoch)
        with pytest.raises(SingletonActiveError, match="not owned"):
            store.reconcile_publication(claim_auto, reconciler_instance_id="inst-auto-guard", reconciler_epoch=epoch)
