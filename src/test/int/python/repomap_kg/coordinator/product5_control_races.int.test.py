"""Real control-store races retain cancellation, retry, and cleanup ownership."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.startup_recovery import StartupRecoveryReport
from repomap_kg.coordinator.storage import ControlStoreError
from repomap_test_support.startup_recovery_scenarios import _harness, _req


@pytest.mark.parametrize("boundary", ["before-running", "after-running"])
def test_cancellation_at_running_transition_settles_without_publication(monkeypatch, boundary):
    with _harness() as (store, _, connect):
        submitted = store.submit(_req("synthetic-cancellation", "transition"))
        original = store.compare_and_set_state
        launches: list[str] = []

        def transition(job_id, **kwargs):
            if kwargs["new_state"] == "running" and boundary == "before-running":
                assert store.request_cancellation(job_id) == "cancel_requested"
            changed = original(job_id, **kwargs)
            if changed and kwargs["new_state"] == "running" and boundary == "after-running":
                assert store.request_cancellation(job_id) == "cancel_requested"
            return changed

        def worker(claim, cancel_event):
            launches.append(claim.job_id)
            assert cancel_event.is_set()
            return {"status": "cancelled", "publication_state": "not_started", "_termination_proved": True}

        monkeypatch.setattr(store, "compare_and_set_state", transition)
        coordinator = SyntheticCoordinator(store, "cancellation-owner", worker)
        coordinator.startup(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
        try:
            assert coordinator.run_once() == "cancelled"
            assert launches == ([] if boundary == "before-running" else [submitted.job_id])
            with connect() as conn:
                assert conn.execute("SELECT state, publication_state FROM jobs WHERE job_id = %s", (submitted.job_id,)).fetchone() == ("cancelled", "not_started")
                assert conn.execute("SELECT count(*) FROM graph_leases WHERE job_id = %s", (submitted.job_id,)).fetchone() == (0,)
                assert conn.execute("SELECT count(*) FROM synthetic_publication_markers WHERE job_id = %s", (submitted.job_id,)).fetchone() == (0,)
        finally:
            coordinator.shutdown()


@pytest.mark.parametrize("race", ["transient", "persistent", "unexpected"])
def test_claim_retry_is_bounded_and_only_accepts_graph_lease_conflicts(monkeypatch, race):
    with _harness() as (store, _, connect):
        epoch = store.acquire_singleton("claim-owner", timedelta(seconds=300))
        held = store.submit(_req("synthetic-held", "held"))
        lease = store.claim_next("claim-owner", epoch, timedelta(seconds=300))
        assert lease is not None and lease.job_id == held.job_id
        queued = store.submit(_req("synthetic-free", "queued"))
        original = store._claim_once
        attempts = 0

        def contend(*args: Any, **kwargs: Any):
            nonlocal attempts
            attempts += 1
            if race == "transient" and attempts == 3:
                return original(*args, **kwargs)
            # Generate authentic PostgreSQL constraint diagnostics in an isolated
            # transaction, then exercise the maintained claim retry boundary.
            with connect() as conn:
                if race == "unexpected":
                    conn.execute("INSERT INTO jobs SELECT * FROM jobs WHERE job_id = %s", (held.job_id,))
                else:
                    conn.execute("INSERT INTO graph_leases SELECT * FROM graph_leases WHERE graph_id = %s", (lease.graph_id,))
            raise AssertionError("database accepted a duplicate primary key")

        with monkeypatch.context() as fault:
            fault.setattr(store, "_claim_once", contend)
            if race == "unexpected":
                with pytest.raises(ControlStoreError, match="unexpected control-store uniqueness violation"):
                    store.claim_next("claim-owner", epoch, timedelta(seconds=300))
                assert attempts == 1
            else:
                result = store.claim_next("claim-owner", epoch, timedelta(seconds=300))
                assert attempts == 3
                if race == "transient":
                    assert result is not None and result.job_id == queued.job_id
                else:
                    assert result is None
        assert store.status(held.job_id).state == "claimed"
        if race != "transient":
            assert store.status(queued.job_id).state == "queued"
            result = store.claim_next("claim-owner", epoch, timedelta(seconds=300))
            assert result is not None and result.job_id == queued.job_id
        with connect() as conn:
            assert conn.execute("SELECT job_id, attempt FROM graph_leases WHERE graph_id = %s", (lease.graph_id,)).fetchone() == (held.job_id, lease.attempt)
        assert store.stop_singleton("claim-owner", epoch)


def test_cleanup_retains_jobs_and_sanitized_residuals_when_evidence_io_fails():
    with _harness() as (store, _, connect):
        submitted = store.submit(_req("synthetic-cleanup", "cleanup"))
        fail_retirement = False

        def retire(_: object):
            if fail_retirement:
                raise PermissionError("fixture evidence directory unavailable")

        coordinator = SyntheticCoordinator(
            store, "cleanup-owner",
            lambda *_: {"status": "failed", "publication_state": "not_started", "error_category": "permanent", "_termination_proved": True},
            publication_retirer=retire,
        )
        coordinator.startup(lambda: StartupRecoveryReport(0, 0, 0, 0, 0))
        try:
            assert coordinator.run_once() == "failed"
            fail_retirement = True
            report = coordinator.cleanup_terminal(timedelta(0), limit=1)
            assert report.deleted_job_ids == ()
            assert report.residual_count == 1
            assert report.residuals == (f"{submitted.job_id}:1:permission_denied",)
            assert coordinator.residual_evidence == report.residuals
            assert store.status(submitted.job_id).state == "failed"
            with connect() as conn:
                assert conn.execute("SELECT count(*) FROM job_attempts WHERE job_id = %s", (submitted.job_id,)).fetchone() == (1,)
            fail_retirement = False
            settled = coordinator.cleanup_terminal(timedelta(0), limit=1)
            assert settled.deleted_job_ids == (submitted.job_id,)
            assert settled.residuals == ()
        finally:
            coordinator.shutdown()
