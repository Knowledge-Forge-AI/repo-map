"""Real-child launch registration and durable one-use closure under currency locks."""
from datetime import timedelta
import os
from pathlib import Path
import sys

import pytest

from repomap_kg.coordinator import _publication_phase as phase
from repomap_kg.coordinator import _supervisor_fencing as supervisor
from repomap_kg.coordinator._supervisor_registration import in_process_currency_context, persist_supervisor_registration
from repomap_kg.coordinator._restart_fencing import StaleDurableAuthorityError
from repomap_kg.coordinator.process_supervision import launch_managed_process
from repomap_kg.coordinator.refresh_adapter import RefreshCapability, create_refresh_capability
from repomap_kg.coordinator.configured_refresh import ConfiguredRefreshResolver
from repomap_kg.ops.config import load_ops_config
from repomap_kg.runtime.postgres_route import effective_postgres_route
from repomap_test_support.startup_recovery_scenarios import _assert_retry_waiting_and_advance, _make_refresh_fixture, _refresh_harness, _req_norm, _search_path


class ReapedResult:
    def __init__(self, argv):
        self.argv = argv
        self.waited = True
        self.process_group_cleaned = True


def test_real_launch_registration_is_durable_consumed_and_rotated():
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
        store.submit(_req_norm("durable-real-launch", sg, cg, eg, kg))
        epoch = store.acquire_singleton("launch-owner", timedelta(seconds=300))
        claim = store.claim_next("launch-owner", epoch, timedelta(seconds=300))
        assert claim is not None
        for before, after in (("claimed", "starting"), ("starting", "running")):
            assert store.compare_and_set_state(claim.job_id, expected_state=before, new_state=after,
                attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=claim.fencing_epoch)
        route = effective_postgres_route(load_ops_config(config))
        capability = RefreshCapability(
            schema_version=1, job_id=claim.job_id, attempt=claim.attempt, graph_id=claim.graph_id,
            config_path=config, psql_path=Path(postgres.psql_command), postgres_user=postgres.user,
            postgres_host=route.host, postgres_port=route.port, postgres_route_kind=route.kind,
            postgres_password=postgres.password, executable_search_path=_search_path(),
            source_generation=sg, config_generation=cg, extractor_generation=eg, canonicalizer_generation=kg,
            coordinator_instance_id=claim.instance_id, singleton_fencing_epoch=epoch,
            graph_lease_fencing_epoch=claim.graph_lease_fencing_epoch,
        )
        sealed = create_refresh_capability(cap_dir, capability)
        argv = (sys.executable, "-m", "repomap_kg.coordinator.refresh_worker", "--capability",
                str(sealed), "--job-id", claim.job_id, "--attempt", str(claim.attempt))
        ticket = supervisor.register_worker_launch(capability, argv)
        store.register_supervisor_launch(ticket, capability)
        params = (claim.job_id, claim.attempt)
        query = ("SELECT supervisor_registration_digest, supervisor_registration_consumed, "
                 "coordinator_instance_id, fencing_epoch, graph_lease_fencing_epoch "
                 "FROM job_attempts WHERE job_id = %s AND attempt = %s")
        with connect() as connection:
            assert connection.execute(query, params).fetchone() == (
                ticket.registration_digest, False, claim.instance_id, epoch, claim.graph_lease_fencing_epoch,
            )
        with pytest.raises(PermissionError, match="already exists"):
            persist_supervisor_registration(connect, claim, "b" * 64)
        with pytest.raises(StaleDurableAuthorityError):
            with in_process_currency_context(connect, claim, "f" * 64):
                pytest.fail("forged digest admitted")
        environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[6] / "src/main/python")}
        worker = launch_managed_process(argv, environment, cap_dir)
        try:
            supervisor._bind_launch_process(ticket, worker)
            assert worker.poll() is None
        finally:
            assert worker.cleanup(1, 1)
            result = ReapedResult(argv)
            supervisor._record_reaped_launch(result, worker, ticket)
        phase.initialize(cap_dir, claim)
        proof = store.in_process_fencing_proof(result, capability)
        assert proof.registration_digest == ticket.registration_digest
        assert phase.close_unpublished(cap_dir, claim, proof=proof)
        with connect() as connection:
            assert connection.execute(query, params).fetchone() == (
                ticket.registration_digest, True, claim.instance_id, epoch, claim.graph_lease_fencing_epoch,
            )
        with pytest.raises(StaleDurableAuthorityError):
            with in_process_currency_context(connect, claim, ticket.registration_digest):
                pytest.fail("durable replay admitted")
        with pytest.raises(PermissionError, match="consumed"):
            persist_supervisor_registration(connect, claim, ticket.registration_digest)
        # Crash while the registered attempt is still running. Startup owns
        # abandonment classification and registration invalidation.
        with connect() as connection:
            connection.execute("UPDATE coordinator_instances SET expires_at = now() - interval '1 second'")
            connection.execute("UPDATE graph_leases SET expires_at = now() - interval '1 second'")
        replacement_epoch = store.acquire_singleton("launch-replacement", timedelta(seconds=300))
        assert store.recover_abandoned_attempts("launch-replacement", replacement_epoch, 1) == 1
        with connect() as connection:
            assert connection.execute(query, params).fetchone()[0:2] == (None, True)
        with pytest.raises(StaleDurableAuthorityError):
            with in_process_currency_context(connect, claim, ticket.registration_digest):
                pytest.fail("old registration after restart admitted")
        resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
        store.set_durable_fence_callback(resolver.install_graph_publication_fence)
        assert store.close_unpublished_reconciliation(claim, reconciler_instance_id="launch-replacement",
            reconciler_epoch=replacement_epoch, file_closer=lambda attempt, evidence: phase.close_unpublished(cap_dir, attempt, proof=evidence))
        assert store.reconcile_publication(claim, reconciler_instance_id="launch-replacement",
                                          reconciler_epoch=replacement_epoch, unpublished_proved=True) == "queued"
        _assert_retry_waiting_and_advance(store, connect, claim, "launch-replacement", replacement_epoch)
        next_claim = store.claim_next("launch-replacement", replacement_epoch, timedelta(seconds=300))
        assert next_claim is not None and next_claim.attempt == claim.attempt + 1
        assert next_claim.instance_id == "launch-replacement"
        assert next_claim.fencing_epoch > claim.fencing_epoch
        assert next_claim.graph_lease_fencing_epoch > claim.graph_lease_fencing_epoch
        with connect() as connection:
            assert connection.execute(query, (next_claim.job_id, next_claim.attempt)).fetchone()[0:2] == (None, False)
        sealed.unlink()
        assert store.stop_singleton("launch-replacement", replacement_epoch)
