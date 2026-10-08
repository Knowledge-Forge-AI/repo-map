"""Adversarial closure registration checks use real OS children."""
from dataclasses import dataclass, replace
import os
from pathlib import Path
import sys

import pytest

from repomap_kg.coordinator import _supervisor_fencing as fencing
from repomap_kg.coordinator._protocol_execution import _run_protocol_worker
from repomap_kg.coordinator.limits import CoordinatorLimits
from repomap_kg.coordinator.process_supervision import launch_managed_process
from repomap_kg.coordinator.refresh_adapter import RefreshCapability, create_refresh_capability
from repomap_test_support.fencing_control_fakes import FencingControl


@dataclass
class ReapedResult:
    argv: tuple[str, ...]
    waited: bool = True
    process_group_cleaned: bool = True


@pytest.fixture
def sealed_launch(tmp_path):
    tmp_path.chmod(0o700)
    config = tmp_path / "ops.toml"
    config.write_text("schema_version = 1\n")
    config.chmod(0o600)
    psql = tmp_path / "psql"
    psql.touch()
    psql.chmod(0o755)
    cap = RefreshCapability(
        schema_version=1, job_id="binding-fixture", attempt=1, graph_id="fixture",
        config_path=config, psql_path=psql, postgres_user="fixture", postgres_password="fixture",
        executable_search_path=(tmp_path,), source_generation="sg1:fixture", config_generation="cg1:fixture",
        extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
        coordinator_instance_id="owner", singleton_fencing_epoch=3, graph_lease_fencing_epoch=91,
    )
    path = create_refresh_capability(tmp_path, cap)
    argv = (sys.executable, "-m", "repomap_kg.coordinator.refresh_worker", "--capability",
            str(path), "--job-id", cap.job_id, "--attempt", str(cap.attempt))
    ticket = fencing.register_worker_launch(cap, argv)
    yield cap, path, argv, ticket
    fencing.release_unlaunched_registration(ticket)


def test_noop_cannot_borrow_live_real_worker_registration(sealed_launch, tmp_path):
    cap, _path, argv, ticket = sealed_launch
    control = FencingControl(cap)
    fencing.bind_durable_launch(ticket, cap, control.connect)
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[6] / "src/main/python")}
    worker = launch_managed_process(argv, environment, tmp_path)
    noop = launch_managed_process((sys.executable, "-c", "pass"), environment, tmp_path)
    try:
        fencing._bind_launch_process(ticket, worker)
        assert worker.poll() is None
        noop.wait(timeout=5)
        assert noop.cleanup(1, 1)
        stolen = ReapedResult(argv)
        with pytest.raises(PermissionError, match="exact registered child"):
            fencing._record_reaped_launch(stolen, noop, ticket)
        with pytest.raises(PermissionError, match="unauthorized supervisor mock"):
            fencing.earn_in_process_fencing_proof(stolen, cap, FencingControl(cap).connect)
        with pytest.raises(PermissionError, match="live launch registration"):
            fencing.register_worker_launch(cap, argv)
    finally:
        assert noop.cleanup(1, 1)
        assert worker.cleanup(1, 1)
        exact = ReapedResult(argv)
        fencing._record_reaped_launch(exact, worker, ticket)
    proof = fencing.earn_in_process_fencing_proof(exact, cap, control.connect)
    assert proof.proof_kind == "in_process_reaped"
    with pytest.raises(PermissionError, match="reused or stale"):
        fencing._record_reaped_launch(exact, worker, ticket)
    with pytest.raises(PermissionError, match="unauthorized supervisor mock"):
        fencing.earn_in_process_fencing_proof(exact, cap, control.connect)


def test_fabricated_ticket_and_changed_sealed_capability_are_rejected(sealed_launch):
    cap, path, argv, ticket = sealed_launch
    identity = {"job_id": cap.job_id, "attempt": cap.attempt}
    with pytest.raises(PermissionError, match="fabricated"):
        fencing._validate_launch(replace(ticket), argv, identity)
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(PermissionError, match="sealed capability registration mismatch"):
        fencing._validate_launch(ticket, argv, identity)


def test_protocol_rejects_noop_before_spawn_even_with_real_ticket(sealed_launch, tmp_path):
    cap, _path, _argv, ticket = sealed_launch
    with pytest.raises(PermissionError, match="registration mismatch"):
        _run_protocol_worker(
            (sys.executable, "-c", "pass"), {}, tmp_path, False,
            {"job_id": cap.job_id, "attempt": cap.attempt}, CoordinatorLimits(),
            job_context=None, cancel_event=None, _launch_ticket=ticket,
        )


def test_unlaunched_registration_is_revoked(sealed_launch):
    cap, _path, argv, ticket = sealed_launch
    fencing.release_unlaunched_registration(ticket)
    with pytest.raises(PermissionError, match="stale"):
        fencing._validate_launch(ticket, argv, {"job_id": cap.job_id, "attempt": cap.attempt})


def test_registration_digest_persisted_no_raw_token_persisted(sealed_launch, tmp_path):
    cap, _path, argv, ticket = sealed_launch
    control = FencingControl(cap)
    fencing.bind_durable_launch(ticket, cap, control.connect)
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[6] / "src/main/python")}
    worker = launch_managed_process(argv, environment, tmp_path)
    try:
        fencing._bind_launch_process(ticket, worker)
    finally:
        assert worker.cleanup(1, 1)
        exact = ReapedResult(argv)
        fencing._record_reaped_launch(exact, worker, ticket)

    proof = fencing.earn_in_process_fencing_proof(exact, cap, control.connect)

    # 1. Ticket has raw token (32 random bytes) and computed 64-char sha256 hex digest
    assert isinstance(ticket.token, bytes)
    assert len(ticket.token) == 32
    assert isinstance(ticket.registration_digest, str)
    assert len(ticket.registration_digest) == 64
    assert proof.registration_digest == ticket.registration_digest

    # 2. Durable row received 64-char digest, never raw token bytes
    assert control.attempt["supervisor_registration_digest"] == ticket.registration_digest
    for query, params in control.executions:
        for p in params:
            assert p != ticket.token
        assert ticket.token not in str(query).encode("ascii")


def test_store_validates_one_use_digest_and_rejects_replay(sealed_launch, tmp_path):
    from repomap_kg.coordinator._control_types import JobClaim
    from repomap_kg.coordinator._restart_fencing import in_process_currency_context, StaleDurableAuthorityError

    cap, _path, argv, ticket = sealed_launch
    control = FencingControl(cap)
    fencing.bind_durable_launch(ticket, cap, control.connect)
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[6] / "src/main/python")}
    worker = launch_managed_process(argv, environment, tmp_path)
    try:
        fencing._bind_launch_process(ticket, worker)
    finally:
        assert worker.cleanup(1, 1)
        exact = ReapedResult(argv)
        fencing._record_reaped_launch(exact, worker, ticket)

    proof = fencing.earn_in_process_fencing_proof(exact, cap, control.connect)
    claim = JobClaim(
        job_id=cap.job_id, attempt=cap.attempt, graph_id=cap.graph_id,
        instance_id=cap.coordinator_instance_id, fencing_epoch=cap.singleton_fencing_epoch,
        graph_lease_fencing_epoch=cap.graph_lease_fencing_epoch,
        source_generation=cap.source_generation, config_generation=cap.config_generation,
        extractor_generation=cap.extractor_generation, canonicalizer_generation=cap.canonicalizer_generation,
    )
    assert proof.registration_digest == ticket.registration_digest

    # 1. First currency validation consumes the digest
    control.committed = False
    with in_process_currency_context(control.connect, claim, ticket.registration_digest):
        assert bool(control.committed) is False  # locks remain held through the file decision
    assert control.attempt["supervisor_registration_digest"] == ticket.registration_digest
    assert control.attempt["supervisor_registration_consumed"] is True
    assert bool(control.committed) is True

    # 2. The retained digest is consumed; replay and a new reservation both fail.
    with pytest.raises(StaleDurableAuthorityError, match="turned over"):
        with in_process_currency_context(control.connect, claim, ticket.registration_digest):
            pass
    from repomap_kg.coordinator._supervisor_registration import persist_supervisor_registration
    with pytest.raises(PermissionError, match="consumed"):
        persist_supervisor_registration(control.connect, claim, ticket.registration_digest)


def test_store_rejects_forged_and_restarted_digest(sealed_launch, tmp_path):
    from repomap_kg.coordinator._control_types import JobClaim
    from repomap_kg.coordinator._restart_fencing import in_process_currency_context, StaleDurableAuthorityError

    cap, _path, argv, ticket = sealed_launch
    claim = JobClaim(
        job_id=cap.job_id, attempt=cap.attempt, graph_id=cap.graph_id,
        instance_id=cap.coordinator_instance_id, fencing_epoch=cap.singleton_fencing_epoch,
        graph_lease_fencing_epoch=cap.graph_lease_fencing_epoch,
        source_generation=cap.source_generation, config_generation=cap.config_generation,
        extractor_generation=cap.extractor_generation, canonicalizer_generation=cap.canonicalizer_generation,
    )

    # 1. Forged digest fails store validation
    control = FencingControl(cap)
    control.attempt["supervisor_registration_digest"] = "f" * 64
    with pytest.raises(StaleDurableAuthorityError, match="turned over"):
        with in_process_currency_context(control.connect, claim, "e" * 64):
            pass

    # 2. Process restart / turnover clears digest and rejects in-process currency
    restart_control = FencingControl(cap, restart=True)
    restart_control.attempt["supervisor_registration_digest"] = None
    with pytest.raises(StaleDurableAuthorityError, match="turned over"):
        with in_process_currency_context(restart_control.connect, claim, ticket.registration_digest):
            pass


def test_id_weakref_reuse_cannot_steal_registration(sealed_launch):
    import gc
    cap, _path, argv, ticket = sealed_launch

    res1 = ReapedResult(argv)
    fencing._retain_result(res1, ticket)
    assert len(fencing._REAPED) == 1

    # Drop original object and collect
    del res1
    gc.collect()

    # Even if new object occupies memory address, identity check and weakref prevent theft
    res2 = ReapedResult(argv)
    with pytest.raises(PermissionError, match="unauthorized supervisor mock: no real reaped process registration"):
        fencing.earn_in_process_fencing_proof(res2, cap, FencingControl(cap).connect)


def test_durable_reservation_blocks_another_registration_after_module_restart(sealed_launch):
    cap, _path, _argv, ticket = sealed_launch
    control = FencingControl(cap)
    fencing.bind_durable_launch(ticket, cap, control.connect)
    assert control.attempt["supervisor_registration_digest"] == ticket.registration_digest
    from repomap_kg.coordinator._supervisor_registration import persist_supervisor_registration
    # The row remains authoritative even with another nonce and no Python map.
    with pytest.raises(PermissionError, match="already exists"):
        persist_supervisor_registration(control.connect, fencing._claim_from_identity(fencing._fencing_identity(cap)), "b" * 64)


@pytest.mark.parametrize("field", ["fencing_epoch", "graph_lease_fencing_epoch", "coordinator_instance_id"])
def test_store_rejects_registration_after_durable_identity_turnover(sealed_launch, field):
    cap, _path, _argv, ticket = sealed_launch
    control = FencingControl(cap)
    fencing.bind_durable_launch(ticket, cap, control.connect)
    if field == "coordinator_instance_id":
        control.attempt[field] = "replacement"
    else:
        previous = control.attempt[field]
        assert isinstance(previous, int)
        control.attempt[field] = previous + 1
    from repomap_kg.coordinator._supervisor_registration import in_process_currency_context
    with pytest.raises(PermissionError, match="turned over"):
        with in_process_currency_context(control.connect, fencing._claim_from_identity(fencing._fencing_identity(cap)), ticket.registration_digest):
            pytest.fail("stale identity admitted")


def test_file_decision_error_still_consumes_registration_durably(sealed_launch):
    cap, _path, _argv, ticket = sealed_launch
    control = FencingControl(cap)
    fencing.bind_durable_launch(ticket, cap, control.connect)
    from repomap_kg.coordinator._supervisor_registration import in_process_currency_context
    claim = fencing._claim_from_identity(fencing._fencing_identity(cap))
    control.committed = False
    with pytest.raises(OSError, match="file refusal"):
        with in_process_currency_context(control.connect, claim, ticket.registration_digest):
            assert control.committed is False
            raise OSError("file refusal")
    assert control.committed and control.attempt["supervisor_registration_consumed"]
    with pytest.raises(PermissionError):
        with in_process_currency_context(control.connect, claim, ticket.registration_digest):
            pytest.fail("replay admitted")


def test_unregistered_reaped_process_cannot_mint_durable_closure(sealed_launch, tmp_path):
    cap, _path, argv, ticket = sealed_launch
    worker = launch_managed_process(argv, {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[6] / "src/main/python")}, tmp_path)
    try:
        fencing._bind_launch_process(ticket, worker)
    finally:
        assert worker.cleanup(1, 1)
        result = ReapedResult(argv)
        fencing._record_reaped_launch(result, worker, ticket)
    with pytest.raises(PermissionError, match="turned over"):
        fencing.earn_in_process_fencing_proof(result, cap, FencingControl(cap).connect)


def test_contention_in_in_process_proof_raises_permission_error(sealed_launch, tmp_path):
    from psycopg.errors import LockNotAvailable, QueryCanceled
    from repomap_kg.coordinator._control_types import JobClaim
    from repomap_kg.coordinator._restart_fencing import in_process_currency_context, persist_supervisor_registration

    cap, _path, argv, ticket = sealed_launch
    claim = JobClaim(
        job_id=cap.job_id, attempt=cap.attempt, graph_id=cap.graph_id,
        instance_id=cap.coordinator_instance_id, fencing_epoch=cap.singleton_fencing_epoch,
        graph_lease_fencing_epoch=cap.graph_lease_fencing_epoch,
        source_generation=cap.source_generation, config_generation=cap.config_generation,
        extractor_generation=cap.extractor_generation, canonicalizer_generation=cap.canonicalizer_generation,
    )

    class ContendingControl(FencingControl):
        def __init__(self, err):
            super().__init__(cap)
            self._err = err

        def execute(self, query: str, params: tuple = ()):
            if "FOR UPDATE" in query or "UPDATE job_attempts" in query:
                raise self._err("contention")
            super().execute(query, params)

    # Persist registration fails closed on LockNotAvailable
    with pytest.raises(PermissionError, match="durable lock contention"):
        persist_supervisor_registration(ContendingControl(LockNotAvailable).connect, claim, ticket.registration_digest)

    # Persist registration fails closed on QueryCanceled
    with pytest.raises(PermissionError, match="durable lock contention"):
        persist_supervisor_registration(ContendingControl(QueryCanceled).connect, claim, ticket.registration_digest)

    # In-process currency validation fails closed on LockNotAvailable
    with pytest.raises(PermissionError, match="durable lock contention"):
        with in_process_currency_context(ContendingControl(LockNotAvailable).connect, claim, ticket.registration_digest):
            pass

    # In-process currency validation fails closed on QueryCanceled
    with pytest.raises(PermissionError, match="durable lock contention"):
        with in_process_currency_context(ContendingControl(QueryCanceled).connect, claim, ticket.registration_digest):
            pass
