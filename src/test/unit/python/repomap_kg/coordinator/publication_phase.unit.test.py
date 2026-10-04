import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest


from repomap_kg.coordinator import _publication_phase as phase
from repomap_kg.coordinator.semantics import RetryPolicy
from repomap_kg.ops.portable_refresh import PortableRefreshError, _worker_references


def _attempt():
    return SimpleNamespace(
        job_id="job-fixture", attempt=1, graph_id="fixture", instance_id="owner",
        fencing_epoch=3, graph_lease_fencing_epoch=91, source_generation="sg1:fixture", config_generation="cg1:fixture",
        extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
    )


def _proof(claim, root):
    from repomap_kg.coordinator.refresh_adapter import RefreshCapability, create_refresh_capability, run_refresh_worker
    from repomap_kg.coordinator._supervisor_fencing import bind_durable_launch, earn_in_process_fencing_proof
    from repomap_kg.coordinator.limits import CoordinatorLimits
    from repomap_test_support.fencing_control_fakes import FencingControl

    control = FencingControl(claim)
    worker_root = Path(root) / f"cap_run_{claim.job_id}_{claim.attempt}"
    worker_root.mkdir(parents=True, exist_ok=True)
    worker_root.chmod(0o700)
    cfg = worker_root / "ops.toml"
    cfg.write_text("schema_version = 1\n", encoding="utf-8")
    cfg.chmod(0o600)
    psql = worker_root / "bin" / "psql"
    psql.parent.mkdir(parents=True, exist_ok=True)
    psql.touch()
    psql.chmod(0o755)
    cap = RefreshCapability(
        schema_version=1, job_id=claim.job_id, attempt=claim.attempt, graph_id=claim.graph_id,
        config_path=cfg, psql_path=psql,
        postgres_user="user", postgres_host="localhost", postgres_port=5432,
        postgres_route_kind="configured", postgres_password="pwd",
        executable_search_path=(psql.parent,), source_generation=claim.source_generation,
        config_generation=claim.config_generation, extractor_generation=claim.extractor_generation,
        canonicalizer_generation=claim.canonicalizer_generation,
        coordinator_instance_id=claim.instance_id, singleton_fencing_epoch=claim.fencing_epoch,
        graph_lease_fencing_epoch=claim.graph_lease_fencing_epoch,
    )
    cap_path = create_refresh_capability(worker_root, cap)
    limits = CoordinatorLimits(process_deadline_seconds=5, heartbeat_seconds=1, refresh_attempt_deadline_seconds=10)
    identity = {"job_id": claim.job_id, "attempt": claim.attempt}
    job_context = {"graph_id": claim.graph_id, "source_generation": claim.source_generation, "config_generation": claim.config_generation}
    result = run_refresh_worker(cap_path, identity, limits, job_context=job_context,
                                launch_registrar=lambda ticket, capability: bind_durable_launch(ticket, capability, control.connect))
    assert result.waited and result.process_group_cleaned
    return earn_in_process_fencing_proof(result, claim, control.connect), control


def test_closed_prepublication_attempt_is_durable_and_cannot_publish(tmp_path):
    claim = _attempt()
    phase.initialize(tmp_path, claim)
    assert phase.publication_state(tmp_path, claim) == "commit_unknown"
    assert not phase._path(tmp_path, claim, "decision").exists()

    with pytest.raises(TypeError, match="WorkerFencingProof is required"):
        phase.close_unpublished(tmp_path, claim, proof=cast(Any, True))

    proof, _control = _proof(claim, tmp_path)
    assert phase.close_unpublished(tmp_path, claim, proof=proof) is True
    assert phase.publication_state(tmp_path, claim) == "not_started"
    with pytest.raises(FileExistsError):
        phase.before_publication(tmp_path, claim)



def test_started_publication_and_unusable_evidence_remain_uncertain(tmp_path):
    claim = _attempt()
    assert phase.publication_state(tmp_path, claim) == "commit_unknown"
    phase.initialize(tmp_path, claim)
    phase.before_publication(tmp_path, claim)
    assert phase.publication_state(tmp_path, claim) == "commit_unknown"
    claim.attempt = 2
    assert phase.publication_state(tmp_path, claim) == "commit_unknown"
    phase.initialize(tmp_path, claim)
    decision = phase._path(tmp_path, claim, "decision")
    decision.write_text("{")
    decision.chmod(0o600)
    assert phase.publication_state(tmp_path, claim) == "commit_unknown"


@pytest.mark.parametrize("category,expected,retry", [
    ("contract_validation", "contract_validation", False),
    ("unsupported_contract", "unsupported_contract", False),
    ("unsupported_capability", "unsupported_capability", False),
    ("source_capture", "worker_crash", True),
    ("source_changed", "worker_crash", True),
    ("source_invalid", "worker_crash", True),
    ("semantic_workload", "worker_crash", True),
    ("artifact_missing", "worker_crash", True),
    ("artifact_stale", "worker_crash", True),
    ("artifact_corrupt", "worker_crash", True),
    ("artifact_bounds", "worker_crash", True),
    ("manifest_bounds", "worker_crash", True),
    ("malformed_protocol", "worker_crash", True),
    ("identity_mismatch", "worker_crash", True),
    ("cancelled", "worker_crash", True),
    ("worker_crash", "worker_crash", True),
])
def test_portable_category_retry_policy_is_explicit(category, expected, retry):
    with pytest.raises(PortableRefreshError) as caught:
        _worker_references({"status": "failed", "error_category": category})
    error = caught.value
    assert error.category == expected
    assert error.publication_state == "not_started"
    assert RetryPolicy(3, 1, 30).may_retry(1, error.category, error.publication_state) is retry


@pytest.mark.parametrize("reason,expected", [
    ("process_exit", "worker_crash"), ("cleanup_failed", "worker_crash"), ("protocol", "protocol"),
])
def test_synthesized_worker_exit_reasons_have_explicit_categories(reason, expected):
    with pytest.raises(PortableRefreshError) as caught:
        _worker_references({"message_type": "worker_exit", "reason": reason})
    assert caught.value.category == expected


def test_retained_evidence_while_reconciliation_is_required(tmp_path):
    claim = _attempt()
    phase.initialize(tmp_path, claim)
    phase.before_publication(tmp_path, claim)
    assert phase.publication_state(tmp_path, claim) == "commit_unknown"
    init_path = phase._path(tmp_path, claim, "initial")
    dec_path = phase._path(tmp_path, claim, "decision")
    assert init_path.is_file() and dec_path.is_file()


def test_retirement_after_successful_terminal_publication(tmp_path):
    claim = _attempt()
    phase.initialize(tmp_path, claim)
    phase.before_publication(tmp_path, claim)
    init_path = phase._path(tmp_path, claim, "initial")
    dec_path = phase._path(tmp_path, claim, "decision")
    assert init_path.is_file() and dec_path.is_file()
    retired = phase.retire_evidence(tmp_path, claim)
    assert set(retired) == {init_path, dec_path}
    assert not init_path.exists()
    assert not dec_path.exists()
    assert phase.retire_evidence(tmp_path, claim) == ()


def test_retirement_after_terminal_non_publication(tmp_path):
    claim = _attempt()
    phase.initialize(tmp_path, claim)
    proof, _control = _proof(claim, tmp_path)
    assert phase.close_unpublished(tmp_path, claim, proof=proof) is True
    assert phase.publication_state(tmp_path, claim) == "not_started"
    init_path = phase._path(tmp_path, claim, "initial")
    dec_path = phase._path(tmp_path, claim, "decision")
    assert init_path.is_file() and dec_path.is_file()
    retired = phase.retire_evidence(tmp_path, claim)
    assert set(retired) == {init_path, dec_path}
    assert not init_path.exists()
    assert not dec_path.exists()


def test_refusal_to_delete_malformed_unowned_mismatched_evidence(tmp_path):
    claim = _attempt()
    phase.initialize(tmp_path, claim)
    init_path = phase._path(tmp_path, claim, "initial")

    # Corrupted JSON
    init_path.write_text("{malformed", encoding="utf-8")
    with pytest.raises(ValueError, match="publication evidence is not valid json"):
        phase.retire_evidence(tmp_path, claim)
    assert init_path.is_file()

    # Insecure file mode
    init_path.unlink()
    phase.initialize(tmp_path, claim)
    init_path.chmod(0o644)
    with pytest.raises(ValueError, match="invalid publication evidence file"):
        phase.retire_evidence(tmp_path, claim)
    assert init_path.is_file()

    # Identity mismatch
    init_path.chmod(0o600)
    init_path.write_text(json.dumps({"job_id": "different-job"}), encoding="utf-8")
    with pytest.raises(ValueError, match="publication evidence identity mismatch"):
        phase.retire_evidence(tmp_path, claim)
    assert init_path.is_file()



def test_atomic_validation_preserves_both_files_on_partial_failure(tmp_path):
    claim = _attempt()
    phase.initialize(tmp_path, claim)
    phase.before_publication(tmp_path, claim)
    init_path = phase._path(tmp_path, claim, "initial")
    dec_path = phase._path(tmp_path, claim, "decision")

    # Corrupt decision file
    dec_path.write_text("{corrupt", encoding="utf-8")
    with pytest.raises(ValueError):
        phase.retire_evidence(tmp_path, claim)
    # Neither file should be unlinked!
    assert init_path.is_file()
    assert dec_path.is_file()


def test_startup_recovery_still_succeeds_when_evidence_is_legitimately_retained(tmp_path):
    claim = _attempt()
    phase.initialize(tmp_path, claim)
    proof, _control = _proof(claim, tmp_path)
    assert phase.close_unpublished(tmp_path, claim, proof=proof) is True
    # Even after time passes or recovery restarts, state remains not_started
    assert phase.publication_state(tmp_path, claim) == "not_started"


def test_worker_fencing_proof_cannot_be_fabricated(tmp_path):
    from repomap_kg.coordinator import _supervisor_fencing as supervisor

    claim = _attempt()
    with pytest.raises(PermissionError, match="cannot be fabricated"):
        phase.WorkerFencingProof(waited=True, process_group_cleaned=True)
    fake = object.__new__(phase.WorkerFencingProof)
    with pytest.raises(PermissionError, match="cannot be fabricated"):
        phase.close_unpublished(tmp_path, claim, proof=fake)
    with pytest.raises(TypeError, match="WorkerFencingProof is required"):
        phase.close_unpublished(tmp_path, claim, proof=cast(Any, True))
    assert not hasattr(supervisor, "register_test_supervisor_result")
    assert not hasattr(supervisor, "register_supervisor_result")
    fake_result = SimpleNamespace(waited=True, process_group_cleaned=True)
    with pytest.raises(PermissionError, match="unauthorized supervisor mock"):
        supervisor.earn_in_process_fencing_proof(fake_result, claim, cast(Any, lambda: None))


@pytest.mark.parametrize("turnover", ["singleton", "attempt", "lease", "lease_expired"])
def test_real_supervisor_proof_rejects_durable_turnover(tmp_path, turnover):
    claim = _attempt()
    phase.initialize(tmp_path, claim)
    proof, control = _proof(claim, tmp_path)
    if turnover == "singleton":
        control.epoch += 1
    elif turnover == "attempt":
        control.attempt["fencing_epoch"] = claim.fencing_epoch + 1
    elif turnover == "lease":
        control.lease["graph_lease_fencing_epoch"] = claim.graph_lease_fencing_epoch + 1
    else:
        control.lease["lease_active"] = False
    assert not phase.close_unpublished(tmp_path, claim, proof=proof)
    assert phase.publication_state(tmp_path, claim) == "commit_unknown"
    assert not phase._path(tmp_path, claim, "decision").exists()


def test_real_supervisor_proof_binds_full_attempt_identity(tmp_path):
    claim = _attempt()
    proof, _control = _proof(claim, tmp_path)
    claim.graph_lease_fencing_epoch += 1
    with pytest.raises(ValueError, match="identity mismatch"):
        phase.close_unpublished(tmp_path, claim, proof=proof)


def test_adversarial_alternate_worker_rejected(tmp_path):
    from repomap_kg.coordinator import _supervisor_fencing as supervisor

    claim = _attempt()
    # Alternate worker command is rejected
    with pytest.raises(PermissionError, match="alternate worker executable"):
        supervisor.register_worker_launch(claim, (sys.executable, "-c", "pass"))

    # Wrong job-id in command line is rejected
    with pytest.raises(PermissionError, match="identity mismatch"):
        supervisor.register_worker_launch(
            claim,
            (sys.executable, "-m", "repomap_kg.coordinator.refresh_worker",
             "--capability", str(tmp_path), "--job-id", "different-job", "--attempt", str(claim.attempt)),
        )

    # Legacy direct call is rejected
    with pytest.raises(PermissionError, match="unforgeable registration required"):
        supervisor._register_reaped_result(SimpleNamespace(), SimpleNamespace(), phase._fencing_identity(claim))


def test_worker_fencing_proof_one_use_rejects_reuse(tmp_path):
    claim = _attempt()
    phase.initialize(tmp_path, claim)
    proof, control = _proof(claim, tmp_path)

    # First use succeeds
    assert phase.close_unpublished(tmp_path, claim, proof=proof) is True

    # Second use of the same proof instance is rejected (proof consumed)
    with pytest.raises(PermissionError, match="consumed or invalidated"):
        proof.open_closure_context(claim)


def test_exact_worker_accepted(tmp_path):
    claim = _attempt()
    phase.initialize(tmp_path, claim)
    proof, control = _proof(claim, tmp_path)
    assert proof.proof_kind == "in_process_reaped"
    assert phase.close_unpublished(tmp_path, claim, proof=proof) is True
    assert phase.publication_state(tmp_path, claim) == "not_started"


@pytest.mark.parametrize("error_type", ["LockNotAvailable", "QueryCanceled"])
def test_contention_refuses_in_process_closure_keeping_commit_unknown(tmp_path, error_type):
    from psycopg import errors

    claim = _attempt()
    phase.initialize(tmp_path, claim)
    proof, control = _proof(claim, tmp_path)

    # Force contention when proof's closure context is opened
    original_execute = control.execute
    def contending_execute(query, params=()):
        if "UPDATE job_attempts" in query:
            raise getattr(errors, error_type)("lock timeout")
        original_execute(query, params)
    control.execute = contending_execute

    assert phase.close_unpublished(tmp_path, claim, proof=proof) is False
    assert phase.publication_state(tmp_path, claim) == "commit_unknown"
