from __future__ import annotations

from types import SimpleNamespace

import pytest

from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.staging import STAGING_FAMILIES
from repomap_kg.storage.staging_cleanup import (
    CleanupContractError,
    CleanupRequest,
    build_stage_cleanup_statements,
    execute_stage_cleanup,
)
from repomap_kg.storage.staging_ownership import StageOwner


def _owner(*, mode: str = "coordinator") -> StageOwner:
    coordinator = mode == "coordinator"
    return StageOwner(
        repository_id=7,
        operation_id=OperationId("job-scale6" if coordinator else "direct-scale6"),
        attempt=AttemptNumber(2),
        execution_mode=mode,
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
        job_id=JobId("job-scale6") if coordinator else None,
        coordinator_instance_id="coord-scale6" if coordinator else None,
        singleton_fencing_epoch=9 if coordinator else 0,
        graph_lease_fencing_epoch=9 if coordinator else 0,
    )


def _request(
    *,
    owner: StageOwner | None = None,
    stage_id: str = "stage-scale6",
    attempt_live: bool = False,
    batch_size: int = 100,
) -> CleanupRequest:
    return CleanupRequest(
        owner=_owner() if owner is None else owner,
        stage_id=stage_id,
        attempt_live=attempt_live,
        batch_size=batch_size,
    )


def test_cleanup_builder_is_caller_owned_bounded_and_stage_only() -> None:
    statements = build_stage_cleanup_statements(_request())
    assert len(statements) == 1
    statement = statements[0]
    assert "BEGIN;" not in statement
    assert "COMMIT;" not in statement
    assert "publication_reconciliation_state = 'reconciled'" in statement
    assert "state IN ('published', 'failed', 'cancelled', 'abandoned', 'cleanup_pending')" in statement
    assert "LIMIT 100" in statement
    for family in STAGING_FAMILIES:
        assert f"DELETE FROM stage_{family}" in statement
    assert "DELETE FROM files" not in statement
    assert "DELETE FROM nodes" not in statement


def test_cleanup_execution_preserves_the_uninstrumented_default_path() -> None:
    request = _request()
    executed: list[str] = []

    execute_stage_cleanup(SimpleNamespace(execute=executed.append), request)

    assert executed == list(build_stage_cleanup_statements(request))


def test_cleanup_request_requires_expired_no_live_attempt_proof() -> None:
    with pytest.raises(CleanupContractError, match="live attempt"):
        build_stage_cleanup_statements(_request(attempt_live=True))

    with pytest.raises(CleanupContractError, match="batch"):
        build_stage_cleanup_statements(_request(batch_size=0))
    with pytest.raises(CleanupContractError, match="batch"):
        build_stage_cleanup_statements(_request(batch_size=100_001))


def test_cleanup_request_preserves_direct_mode_without_coordinator_fields() -> None:
    request = _request(owner=_owner(mode="direct"))
    assert build_stage_cleanup_statements(request)

    with pytest.raises(CleanupContractError, match="stage"):
        build_stage_cleanup_statements(_request(stage_id="stage/invalid"))


def test_cleanup_request_rejects_invalid_owner_without_echoing_sensitive_values() -> None:
    invalid = _owner()
    invalid = StageOwner(**{**invalid.__dict__, "source_generation": "sensitive-source"})
    with pytest.raises(CleanupContractError) as caught:
        build_stage_cleanup_statements(_request(owner=invalid))
    assert "sensitive-source" not in str(caught.value)
