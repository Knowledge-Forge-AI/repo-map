"""Real refresh publication remains authoritative across durable cancellation."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import threading
import time

import pytest

from repomap_kg.coordinator import _publication_phase, refresh_adapter
from repomap_kg.coordinator._control_types import JobClaim
from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
from repomap_kg.coordinator.core import SyntheticCoordinator
from repomap_kg.coordinator.process_supervision import ManagedProcess
from repomap_kg.coordinator.refresh_adapter import build_refresh_worker_runner
from repomap_kg.coordinator.semantics import reconcile_publication as model_reconcile
from repomap_test_support.portable_worker_scenarios import coordinator_test_limits
from repomap_test_support.startup_recovery_scenarios import _make_refresh_fixture, _refresh_harness, _req_norm


@pytest.mark.parametrize("lost_terminal", [False, True])
def test_matching_real_commit_after_cancellation_succeeds(lost_terminal):
    with _refresh_harness() as (store, directory, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, directory, graph_db)
        resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
        submitted = store.submit(_req_norm("committed-cancel", sg, cg, eg, kg))
        store.set_durable_fence_callback(resolver.install_graph_publication_fence)
        observations = []
        claims = []

        def cancel_after_authoritative_commit(result, capability):
            # The real child has settled. Read the graph receipt before the
            # parent adapter chooses its final result, reproducing the old race.
            record = resolver.read_publication(capability)
            assert record is not None and record["latest_run_identity"] == result.terminal["latest_run_identity"]
            observations.append(record)
            assert coordinator.request_cancel(capability.job_id) == "cancel_requested"
            return store.in_process_fencing_proof(result, capability)

        production_runner = build_refresh_worker_runner(
            resolver.resolve_authority, directory, coordinator_test_limits(),
            fencing_prover=cancel_after_authoritative_commit,
            launch_registrar=store.register_supervisor_launch,
        )

        def run(claim, cancellation):
            claims.append(claim)
            terminal = dict(production_runner(claim, cancellation))
            assert terminal["status"] == "succeeded"
            assert terminal["publication_state"] == "committed"
            if lost_terminal:
                # Fault injection at the transport/disposition boundary; actual
                # storage and receipt readback remain intact and unmocked.
                terminal.update(status="failed", publication_state="commit_unknown",
                                latest_run_identity=None, error_category="publication_unknown")
            return terminal

        coordinator = SyntheticCoordinator(
            store, "owner-committed-cancel", run, publication_reader=resolver.read_publication,
            publication_retirer=lambda claim: _publication_phase.retire_evidence(directory, claim),
            singleton_ttl=timedelta(seconds=300), lease_ttl=timedelta(seconds=300),
        )
        coordinator.startup(lambda: None)
        try:
            assert coordinator.run_once() == "succeeded"
            status = store.status(submitted.job_id)
            assert (status.state, status.publication_state, status.error_category) == ("succeeded", "committed", None)
            assert status.state == model_reconcile("commit_unknown", "matching_committed", True)
            assert status.diagnostic_summary == "cancellation_not_applied"
            assert resolver.read_publication(claims[0]) == observations[0]
            with pytest.raises(ValueError, match="job cannot be cancelled"):
                coordinator.request_cancel(submitted.job_id)
            assert store.status(submitted.job_id).state == "succeeded"
            assert store.status(submitted.job_id).diagnostic_summary == "cancellation_not_applied"
            with connect() as connection:
                assert connection.execute(
                    "SELECT a.publication_state, a.is_current, m.run_identity FROM job_attempts AS a "
                    "JOIN synthetic_publication_markers AS m USING (job_id, attempt) WHERE a.job_id = %s",
                    (submitted.job_id,),
                ).fetchone() == ("committed", False, observations[0]["latest_run_identity"])
                assert connection.execute(
                    "SELECT count(*) FROM graph_leases WHERE job_id = %s", (submitted.job_id,),
                ).fetchone() == (0,)
            assert not tuple(directory.glob("publication-*.json"))
        finally:
            coordinator.shutdown()


def test_cancellation_after_publication_gate_preserves_uncertainty(monkeypatch):
    with _refresh_harness() as (store, directory, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, directory, graph_db)
        resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
        submitted = store.submit(_req_norm("uncertain-cancel", sg, cg, eg, kg))
        store.set_durable_fence_callback(resolver.install_graph_publication_fence)
        trigger = directory / "publication-pause"
        trigger.touch()
        ready = Path(f"{trigger}.ready")
        # The hook is before the final transaction. Graceful SIGTERM can earn
        # rollback evidence there; uncertainty requires loss of that evidence.
        monkeypatch.setenv("_REPOMAP_SYSTEM_TEST_POST_PUBLICATION_PAUSE_PATH", str(trigger))
        claims: list[JobClaim] = []
        outcomes = []
        failures = []
        worker_observations = []
        proof_observations = []
        closure_observations = []
        terminal_observations = []
        abrupt_interruptions = []
        production_worker = refresh_adapter.run_refresh_worker
        production_closure = _publication_phase.close_unpublished

        def observe_closure(*args, **kwargs):
            closed = production_closure(*args, **kwargs)
            closure_observations.append(closed)
            return closed

        monkeypatch.setattr(_publication_phase, "close_unpublished", observe_closure)

        def interrupt_without_rollback_terminal(process):
            # Fault injection uses the actual owned process group and leaves
            # reaping, fencing proof, and durable disposition to production.
            try:
                phase = _publication_phase._read(_publication_phase._path(directory, claims[0], "decision"))
                phase_category = phase.pop("publication_state", None)
                abrupt_interruptions.append({
                    "ready_pid_matches": ready.is_file() and ready.read_text() == f"pid={process.pid}\n",
                    "cancel_requested": store.status(submitted.job_id).state == "cancel_requested",
                    "phase_category": phase_category,
                    "phase_identity_matches": phase == _publication_phase._identity(claims[0]),
                })
            finally:
                process.kill_tree()

        monkeypatch.setattr(ManagedProcess, "terminate_gracefully", interrupt_without_rollback_terminal)

        def observe_worker(*args, **kwargs):
            result = production_worker(*args, **kwargs)
            worker_observations.append({
                **{field: result.terminal.get(field) for field in (
                    "status", "publication_state", "error_category",
                )},
                **{field: getattr(result, field) for field in (
                    "synthesized_terminal", "waited", "process_group_cleaned",
                    "process_timed_out", "heartbeat_timed_out",
                )},
            })
            return result

        def observe_proof(result, capability):
            proof = store.in_process_fencing_proof(result, capability)
            proof_observations.append(proof is not None)
            return proof

        monkeypatch.setattr(refresh_adapter, "run_refresh_worker", observe_worker)
        # The real child emits heartbeats every five seconds. The portable
        # fixture's two-second watchdog can preempt cancellation escalation.
        limits = {**vars(coordinator_test_limits()), "heartbeat_seconds": 30}
        runner = build_refresh_worker_runner(
            resolver.resolve_authority, directory, limits,
            fencing_prover=observe_proof, launch_registrar=store.register_supervisor_launch,
        )

        def run(claim, cancellation):
            claims.append(claim)
            terminal = runner(claim, cancellation)
            terminal_observations.append({
                "category": terminal.get("_error_category"),
                "termination_proved": terminal.get("_termination_proved") is True,
                "phase_evidence": _publication_phase.publication_state(directory, claim),
                "absence_proved": _publication_phase.publication_state(directory, claim) == "not_started",
                "rollback_reported": terminal.get("publication_state") == "rolled_back",
            })
            return terminal

        coordinator = SyntheticCoordinator(
            store, "owner-uncertain-cancel", run, publication_reader=resolver.read_publication,
            publication_retirer=lambda claim: _publication_phase.retire_evidence(directory, claim),
            singleton_ttl=timedelta(seconds=300), lease_ttl=timedelta(seconds=300),
        )

        def execute():
            try:
                outcomes.append(coordinator.run_once())
            except BaseException as error:
                failures.append(error)

        coordinator.startup(lambda: None)
        task = threading.Thread(target=execute)
        task.start()
        try:
            deadline = time.monotonic() + 20
            while not ready.exists():
                assert task.is_alive() and time.monotonic() < deadline, "publication checkpoint unavailable"
                task.join(0.01)
            assert coordinator.request_cancel(submitted.job_id) == "cancel_requested"
            task.join(20)
            status = store.status(submitted.job_id)
            receipt = resolver.read_publication(claims[0]) if claims else None
            with connect() as connection:
                attempt_rows = connection.execute(
                    "SELECT publication_state, is_current, finished_at IS NOT NULL, result_category "
                    "FROM job_attempts WHERE job_id = %s", (submitted.job_id,),
                ).fetchall()
                lease_count = connection.execute(
                    "SELECT count(*) FROM graph_leases WHERE job_id = %s", (submitted.job_id,),
                ).fetchone()[0]
            diagnostic = {
                "outcomes": outcomes, "failure_count": len(failures), "thread_settled": not task.is_alive(),
                "worker": worker_observations, "terminal": terminal_observations,
                "proof_issued": proof_observations,
                "fenced_absence_proved": closure_observations,
                "abrupt_interruption_count": len(abrupt_interruptions),
                "abrupt_interruptions": abrupt_interruptions,
                "job_state": status.state, "job_publication_state": status.publication_state,
                "job_category": status.error_category, "attempts": attempt_rows,
                "matching_receipt": receipt is not None and all(
                    receipt.get(field) == getattr(claims[0], field)
                    for field in ("job_id", "attempt", "source_generation", "config_generation",
                                  "extractor_generation", "canonicalizer_generation")
                ),
                "phase_evidence": _publication_phase.publication_state(directory, claims[0]) if claims else "unobserved",
                "evidence_file_count": len(tuple(directory.glob("publication-*.json"))),
                "lease_count": lease_count,
            }
            assert not task.is_alive() and not failures, diagnostic
            assert abrupt_interruptions == [{
                "ready_pid_matches": True, "cancel_requested": True,
                "phase_category": "transaction_started", "phase_identity_matches": True,
            }], diagnostic
            assert len(worker_observations) == 1, diagnostic
            assert worker_observations[0] == {
                "status": "failed", "publication_state": "commit_unknown", "error_category": "publication_unknown",
                "synthesized_terminal": True, "waited": True, "process_group_cleaned": True,
                "process_timed_out": False, "heartbeat_timed_out": False,
            }, diagnostic
            assert proof_observations == [True], diagnostic
            assert closure_observations == [False], diagnostic
            assert terminal_observations == [{
                "category": "worker_crash", "termination_proved": True, "phase_evidence": "commit_unknown",
                "absence_proved": False, "rollback_reported": False,
            }], diagnostic
            assert outcomes == ["reconciliation_required"], diagnostic
            assert (status.state, status.publication_state) == ("reconciliation_required", "commit_unknown"), diagnostic
            assert status.state == model_reconcile("commit_unknown", "absent", True), diagnostic
            assert receipt is None, diagnostic
            assert diagnostic["phase_evidence"] == "commit_unknown", diagnostic
            assert diagnostic["evidence_file_count"] == 2, diagnostic
            assert attempt_rows == [("commit_unknown", True, True, "worker_crash")], diagnostic
            assert lease_count == 1, diagnostic
        finally:
            trigger.unlink(missing_ok=True)
            ready.unlink(missing_ok=True)
            task.join(20)
            assert not task.is_alive(), "owned coordinator task did not settle"
            coordinator.shutdown()


@pytest.mark.parametrize("cancel", [False, True])
def test_authentic_fenced_absence_matches_model_and_preserves_retry(cancel):
    with _refresh_harness() as (store, directory, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, directory, graph_db)
        resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
        store.set_durable_fence_callback(resolver.install_graph_publication_fence)
        job = store.submit(_req_norm("fenced-absence", sg, cg, eg, kg))
        epoch = store.acquire_singleton("absence-prior", timedelta(seconds=300))
        try:
            claim = store.claim_next("absence-prior", epoch, timedelta(seconds=300))
            assert claim is not None
            expected = "claimed"
            if cancel:
                assert store.request_cancellation(job.job_id) == "cancel_requested"
                expected = "cancel_requested"
            assert store.mark_reconciliation_required(claim, expected_state=expected, category="worker_crash")
            assert store.mark_attempt_terminated(claim, process_cleanup_proved=True)
            assert store.reconcile_publication(claim) == model_reconcile("commit_unknown", "absent", cancel)
            with connect() as connection:
                assert connection.execute(
                    "SELECT is_current, publication_state FROM job_attempts WHERE job_id = %s", (job.job_id,),
                ).fetchone() == (True, "commit_unknown")
                assert connection.execute(
                    "SELECT count(*) FROM graph_leases WHERE job_id = %s", (job.job_id,),
                ).fetchone() == (1,)
                connection.execute(
                    "UPDATE graph_leases SET expires_at = now() - interval '1 second' WHERE job_id = %s", (job.job_id,),
                )
            _publication_phase.initialize(directory, claim)
        finally:
            store.stop_singleton("absence-prior", epoch)
        replacement = store.acquire_singleton("absence-replacement", timedelta(seconds=300))
        try:
            closed = store.close_unpublished_reconciliation(
                claim, reconciler_instance_id="absence-replacement", reconciler_epoch=replacement,
                file_closer=lambda cl, proof: _publication_phase.close_unpublished(directory, cl, proof=proof),
            )
            assert closed is True and resolver.read_publication(claim) is None
            assert _publication_phase.publication_state(directory, claim) == "not_started"
            outcome = store.reconcile_publication(
                claim, reconciler_instance_id="absence-replacement", reconciler_epoch=replacement,
                unpublished_proved=closed,
            )
            assert outcome == model_reconcile("not_started", "absent", cancel, absence_proof="fenced_absence")
            assert store.status(job.job_id).state == ("cancelled" if cancel else "queued")
            with connect() as connection:
                assert connection.execute(
                    "SELECT is_current, finished_at IS NOT NULL, publication_state, result_category "
                    "FROM job_attempts WHERE job_id = %s", (job.job_id,),
                ).fetchone() == (False, True, "rolled_back" if cancel else "not_started", "cancelled" if cancel else "transient")
                assert connection.execute(
                    "SELECT count(*) FROM graph_leases WHERE job_id = %s", (job.job_id,),
                ).fetchone() == (0,)
            assert len(_publication_phase.retire_evidence(directory, claim)) == 2
        finally:
            store.stop_singleton("absence-replacement", replacement)
