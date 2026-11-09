"""Maintained refresh_worker M proof for ticketed and coordinator abnormal custody.

Every case runs the real registered nine-argument ``refresh_worker`` through
``run_refresh_worker`` with durable registration. Spies delegate to production
code; the effective canonical launch function is never replaced.
"""

from __future__ import annotations

from datetime import timedelta
import os
from pathlib import Path
import threading
from typing import Any

import pytest

import common_lore_index.coordinator._launch_custody as custody
import common_lore_index.coordinator._protocol_execution as execution
import common_lore_index.coordinator._supervisor_fencing as fencing
import common_lore_index.coordinator.process_supervision as supervision
from common_lore_index.coordinator import _publication_phase
from common_lore_index.coordinator._protocol_core import ProtocolError
from common_lore_index.coordinator.configured_refresh import ConfiguredRefreshResolver
from common_lore_index.coordinator.core import SyntheticCoordinator
from common_lore_index.coordinator.refresh_adapter import (
    RefreshCapability,
    build_refresh_worker_runner,
    create_refresh_capability,
    run_refresh_worker,
)
from common_lore_index.ops.config import load_ops_config
from common_lore_index.runtime.postgres_route import effective_postgres_route
from repomap_test_support.portable_worker_scenarios import coordinator_test_limits
from repomap_test_support.startup_recovery_scenarios import (
    _make_refresh_fixture,
    _refresh_harness,
    _req_norm,
    _search_path,
)

_LIMITS = {
    "process_deadline_seconds": 60, "refresh_attempt_deadline_seconds": 120,
    "heartbeat_seconds": 30, "hello_deadline_seconds": 30,
    "cancellation_after_seconds": 5, "cancel_deadline_seconds": 1,
    "process_termination_grace_seconds": 1, "max_diagnostic_bytes": 4096,
    "max_protocol_line_bytes": 1024 * 1024, "max_array_items": 32,
}
_DIGEST_QUERY = ("SELECT supervisor_registration_digest, supervisor_registration_consumed "
                 "FROM job_attempts WHERE job_id = %s AND attempt = %s")


def _spies(monkeypatch) -> tuple[list[Any], list[Any], list[Any]]:
    launched: list[Any] = []
    outcomes: list[Any] = []
    tickets: list[Any] = []
    real_launch, real_settle = supervision._launch_posix, custody.settle_abnormal_exit
    real_register = fencing.register_worker_launch

    def launch(*args: Any, **kwargs: Any) -> Any:
        launched.append(real_launch(*args, **kwargs))
        return launched[-1]

    def settle(*args: Any, **kwargs: Any) -> Any:
        outcomes.append(real_settle(*args, **kwargs))
        return outcomes[-1]

    def register(*args: Any, **kwargs: Any) -> Any:
        tickets.append(real_register(*args, **kwargs))
        return tickets[-1]

    monkeypatch.setattr(supervision, "_launch_posix", launch)
    monkeypatch.setattr(custody, "settle_abnormal_exit", settle)
    monkeypatch.setattr(fencing, "register_worker_launch", register)
    return launched, outcomes, tickets


def _running_capability(store: Any, cap_dir: Path, postgres: Any, graph_db: str, key: str):
    config, sg, cg, eg, kg = _make_refresh_fixture(postgres, cap_dir, graph_db)
    store.submit(_req_norm(key, sg, cg, eg, kg))
    epoch = store.acquire_singleton(key, timedelta(seconds=300))
    claim = store.claim_next(key, epoch, timedelta(seconds=300))
    assert claim is not None
    for before, after in (("claimed", "starting"), ("starting", "running")):
        assert store.compare_and_set_state(claim.job_id, expected_state=before, new_state=after,
            attempt=claim.attempt, instance_id=claim.instance_id, fencing_epoch=epoch)
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
    context = {"graph_id": claim.graph_id, "source_generation": sg, "config_generation": cg}
    return epoch, claim, sealed, context


def _assert_no_proof_and_unconsumed(connect: Any, ticket: Any, claim: Any) -> None:
    assert all(entry[1] is not ticket for entry in fencing._REAPED), "no reaped/fencing result"
    with connect() as connection:
        assert connection.execute(_DIGEST_QUERY, (claim.job_id, claim.attempt)).fetchone() == (
            ticket.registration_digest, False), "durable digest unconsumed"


def _assert_released(ticket: Any, process: Any, outcome: Any) -> None:
    assert outcome.proven and outcome.status_known and process.closed
    assert process.reap_state() == "reaped" and process.returncode == -9
    with pytest.raises(ProcessLookupError):
        os.killpg(process.pid, 0)
    assert ticket.token not in fencing._PENDING_LAUNCHES
    assert ticket.identity not in fencing._ACTIVE_IDENTITIES


def test_ticketed_synchronous_failure_settles_the_exact_child_without_proof(monkeypatch) -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        epoch, claim, sealed, context = _running_capability(store, cap_dir, postgres, graph_db, "gov3-ticketed")
        launched, outcomes, tickets = _spies(monkeypatch)
        with pytest.raises(ProtocolError, match="invalid_job_context"):
            run_refresh_worker(
                sealed, {"job_id": claim.job_id, "attempt": claim.attempt}, _LIMITS,
                job_context={**context, "unexpected": "extra"},
                fencing_prover=store.in_process_fencing_proof,
                launch_registrar=store.register_supervisor_launch,
            )
        (ticket,), (process,), (outcome,) = tickets, launched, outcomes
        assert tuple(process.popen.args) == ticket.expected_argv
        _assert_released(ticket, process, outcome)
        _assert_no_proof_and_unconsumed(connect, ticket, claim)
        assert not sealed.exists()
        store.stop_singleton(claim.instance_id, epoch)


def test_coordinator_executor_failure_keeps_reconciliation_and_publication_truth(monkeypatch) -> None:
    with _refresh_harness() as (store, directory, connect, postgres, graph_db):
        config, sg, cg, eg, kg = _make_refresh_fixture(postgres, directory, graph_db)
        resolver = ConfiguredRefreshResolver(config, Path(postgres.psql_command))
        submitted = store.submit(_req_norm("gov3-coordinator", sg, cg, eg, kg))
        store.set_durable_fence_callback(resolver.install_graph_publication_fence)
        launched, outcomes, tickets = _spies(monkeypatch)
        injected = RuntimeError("injected synchronous executor failure")
        seam_threads: list[str] = []

        def failing_job_start(_identity: object, _context: object) -> dict[str, object]:
            seam_threads.append(threading.current_thread().name)
            raise injected  # after real hello, inside the executor's supervising thread

        monkeypatch.setattr(execution, "_job_start", failing_job_start)
        claims: list[Any] = []
        limits = {**vars(coordinator_test_limits()), "heartbeat_seconds": 30}
        runner = build_refresh_worker_runner(
            resolver.resolve_authority, directory, limits,
            fencing_prover=store.in_process_fencing_proof, launch_registrar=store.register_supervisor_launch,
        )

        def run(claim: Any, cancellation: threading.Event) -> Any:
            claims.append(claim)
            return runner(claim, cancellation)

        coordinator = SyntheticCoordinator(
            store, "gov3-coordinator", run, publication_reader=resolver.read_publication,
            publication_retirer=lambda claim: _publication_phase.retire_evidence(directory, claim),
            singleton_ttl=timedelta(seconds=300), lease_ttl=timedelta(seconds=300),
        )
        coordinator.startup(lambda: None)
        try:
            assert coordinator.run_once() == "reconciliation_required"
            assert seam_threads and seam_threads[0].startswith("synthetic-coordinator-worker")
            assert store.status(submitted.job_id).state == "reconciliation_required"
            # The executor failed after attempt initialization but before an
            # authoritative closure decision; absence is therefore unknown.
            assert _publication_phase.publication_state(directory, claims[0]) == "commit_unknown"
            (ticket,), (process,), (outcome,) = tickets, launched, outcomes
            _assert_released(ticket, process, outcome)
            _assert_no_proof_and_unconsumed(connect, ticket, claims[0])
        finally:
            coordinator.shutdown()


def test_unknown_status_propagates_kernel_echild_through_protocol_and_ticket(monkeypatch) -> None:
    with _refresh_harness() as (store, cap_dir, connect, postgres, graph_db):
        epoch, claim, sealed, context = _running_capability(store, cap_dir, postgres, graph_db, "gov3-unknown")
        launched, outcomes, tickets = _spies(monkeypatch)
        foreign: list[tuple[int, int]] = []
        seam_thread: list[int] = []

        def foreign_reap_then_owner_poll(_identity: object, _context: object) -> dict[str, object]:
            (process,) = launched
            seam_thread.append(threading.get_ident())
            process.kill_tree()  # exactly one owned signal, after real hello readiness
            foreign.append(os.waitpid(process.pid, 0))  # deliberate exact foreign reap (fault injection)
            process.poll()  # the real selected owner poll from the supervising thread
            raise AssertionError("the owner poll must fail closed")

        monkeypatch.setattr(execution, "_job_start", foreign_reap_then_owner_poll)
        try:
            with pytest.raises(ProtocolError, match="worker_status_unknown") as raised:
                run_refresh_worker(
                    sealed, {"job_id": claim.job_id, "attempt": claim.attempt}, _LIMITS,
                    job_context=context, fencing_prover=store.in_process_fencing_proof,
                    launch_registrar=store.register_supervisor_launch,
                )
            (ticket,), (process,), (outcome,) = tickets, launched, outcomes
            assert seam_thread == [threading.get_ident()] and foreign[0][0] == process.pid
            assert raised.value.code == "worker_status_unknown"
            assert process.reap_state() == "status_unknown" and process.returncode is None
            assert process.closed and not process.owner_reaped
            assert not outcome.proven and not outcome.status_known and outcome.reason == "status_unknown"
            assert outcome.returncode is None and outcome.readers_joined and outcome.streams_closed
            with pytest.raises(ProcessLookupError):
                os.killpg(process.pid, 0)
            held = fencing._PENDING_LAUNCHES.get(ticket.token)
            assert held is not None and held.process is process, "unproven custody holds registration"
            assert fencing._ACTIVE_IDENTITIES.get(ticket.identity) == ticket.token
            _assert_no_proof_and_unconsumed(connect, ticket, claim)
        finally:
            for ticket in tickets:  # test-owned release of the deliberately held registration
                fencing._PENDING_LAUNCHES.pop(ticket.token, None)
                fencing._ACTIVE_IDENTITIES.pop(ticket.identity, None)
            store.stop_singleton(claim.instance_id, epoch)
