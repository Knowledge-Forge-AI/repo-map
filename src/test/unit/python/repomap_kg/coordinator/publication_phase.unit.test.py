import json
from types import SimpleNamespace

import pytest


from repomap_kg.coordinator import _publication_phase as phase
from repomap_kg.coordinator.semantics import RetryPolicy
from repomap_kg.ops.portable_refresh import PortableRefreshError, _worker_references


def _attempt():
    return SimpleNamespace(
        job_id="job-fixture", attempt=1, graph_id="fixture", instance_id="owner",
        fencing_epoch=3, source_generation="sg1:fixture", config_generation="cg1:fixture",
        extractor_generation="eg1:fixture", canonicalizer_generation="kg1:fixture",
    )


def test_closed_prepublication_attempt_is_durable_and_cannot_publish(tmp_path):
    claim = _attempt()
    phase.initialize(tmp_path, claim)
    assert phase.publication_state(tmp_path, claim) == "commit_unknown"
    assert phase.publication_state(tmp_path, claim, close_unpublished=True) == "not_started"
    assert phase.publication_state(tmp_path, claim) == "not_started"
    with pytest.raises(FileExistsError):
        phase.before_publication(tmp_path, claim)


def test_started_publication_and_unusable_evidence_remain_uncertain(tmp_path):
    claim = _attempt()
    assert phase.publication_state(tmp_path, claim) == "commit_unknown"
    phase.initialize(tmp_path, claim)
    phase.before_publication(tmp_path, claim)
    assert phase.publication_state(tmp_path, claim, close_unpublished=True) == "commit_unknown"
    claim.attempt = 2
    assert phase.publication_state(tmp_path, claim) == "commit_unknown"
    phase.initialize(tmp_path, claim)
    decision = phase._path(tmp_path, claim, "decision")
    decision.write_text("{")
    decision.chmod(0o600)
    assert phase.publication_state(tmp_path, claim, close_unpublished=True) == "commit_unknown"


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
    assert phase.publication_state(tmp_path, claim, close_unpublished=True) == "not_started"
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
    assert phase.publication_state(tmp_path, claim, close_unpublished=True) == "not_started"
    # Even after time passes or recovery restarts, state remains not_started
    assert phase.publication_state(tmp_path, claim) == "not_started"
