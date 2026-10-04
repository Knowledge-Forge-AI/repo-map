from __future__ import annotations

import pytest

from repomap_kg.storage._publication_fencing_sql import (
    build_authority_check_sql,
    build_authority_upsert_sql,
)
from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.publication import (
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import (
    PublicationContractError,
    PublicationHandoff,
    build_graph_publication_fence_statements,
)
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_ownership import StageOwner, StageOwnershipError


def _owner(
    *,
    mode: str = "coordinator",
    job_id: str | None = "job-fence-1",
    singleton_epoch: int = 5,
    lease_epoch: int = 3,
) -> StageOwner:
    op_id = OperationId(job_id or "direct-operation")
    typed_job_id = JobId(job_id) if job_id is not None else None
    return StageOwner(
        repository_id=1,
        operation_id=op_id,
        attempt=AttemptNumber(1),
        execution_mode=mode,
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
        job_id=typed_job_id,
        coordinator_instance_id="coord-inst-1" if mode == "coordinator" else None,
        singleton_fencing_epoch=singleton_epoch if mode == "coordinator" else 0,
        graph_lease_fencing_epoch=lease_epoch if mode == "coordinator" else 0,
    )


def _handoff(
    *,
    mode: str = "coordinator",
    job_id: str | None = "job-fence-1",
    singleton_epoch: int = 5,
    lease_epoch: int = 3,
    stage_id: str = "stage-fence-1",
) -> PublicationHandoff:
    owner = _owner(
        mode=mode,
        job_id=job_id,
        singleton_epoch=singleton_epoch,
        lease_epoch=lease_epoch,
    )
    receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId(job_id or "direct-operation"), AttemptNumber(1)),
        RunPublicationGenerations(
            "sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer"
        ),
    )
    return PublicationHandoff(MergeContext(stage_id, owner, 10), receipt)


def test_build_graph_publication_fence_statements_coordinator_mode() -> None:
    owner = _owner()
    statements = build_graph_publication_fence_statements(owner)
    assert len(statements) == 1
    assert "DO $scale5_graph_fence$" in statements[0]
    assert "graph_publication_authority" in statements[0]
    assert "SCALE5 stale publication fence" in statements[0]
    assert "'fence'" in statements[0]
    assert "NULL" in statements[0]


def test_build_graph_publication_fence_statements_direct_mode() -> None:
    owner = _owner(mode="direct", job_id=None)
    assert build_graph_publication_fence_statements(owner) == ()


def test_build_graph_publication_fence_statements_invalid_owner() -> None:
    # Invalid repository_id
    invalid_owner = StageOwner(
        repository_id=-1,
        operation_id=OperationId("job-1"),
        attempt=AttemptNumber(1),
        execution_mode="coordinator",
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
        job_id=JobId("job-1"),
        coordinator_instance_id="coord-1",
        singleton_fencing_epoch=1,
        graph_lease_fencing_epoch=1,
    )
    with pytest.raises(StageOwnershipError):
        build_graph_publication_fence_statements(invalid_owner)


def test_lexicographical_epoch_upsert_sql() -> None:
    owner = _owner(singleton_epoch=2, lease_epoch=1)
    sql = build_authority_upsert_sql(owner, "stage-1", "NULL")
    assert "graph_publication_authority.singleton_fencing_epoch\n        < EXCLUDED.singleton_fencing_epoch" in sql
    assert "graph_publication_authority.singleton_fencing_epoch\n        = EXCLUDED.singleton_fencing_epoch\n    AND graph_publication_authority.graph_lease_fencing_epoch\n        < EXCLUDED.graph_lease_fencing_epoch" in sql


def test_lexicographical_epoch_check_sql() -> None:
    owner = _owner(singleton_epoch=2, lease_epoch=1)
    sql = build_authority_check_sql(owner)
    assert "singleton_fencing_epoch > 2" in sql
    assert "singleton_fencing_epoch = 2" in sql
    assert "graph_lease_fencing_epoch > 1" in sql


def test_publication_handoff_validation() -> None:
    handoff = _handoff()
    assert handoff.validate() is handoff

    # Negative: mismatched attempt
    mismatched_receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId("different-job"), AttemptNumber(1)),
        handoff.receipt.generations,
    )
    with pytest.raises(PublicationContractError, match="attempt identity"):
        PublicationHandoff(handoff.merge, mismatched_receipt).validate()

    # Negative: invalid stage id
    invalid_stage_merge = MergeContext("bad/stage/id", handoff.merge.owner, 10)
    with pytest.raises(PublicationContractError, match="invalid publication handoff"):
        PublicationHandoff(invalid_stage_merge, handoff.receipt).validate()
