from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from repomap_kg.storage.authority import AttemptNumber, JobId, OperationId
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.publication import (
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import PublicationHandoff
from repomap_kg.storage.staged_publication import execute_final_transaction
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_ownership import StageOwner


def _handoff(mode: str) -> PublicationHandoff:
    coordinator = mode == "coordinator"
    operation_id = OperationId("job-arch1c" if coordinator else "direct-arch1c")
    job_id = JobId(str(operation_id)) if coordinator else None
    owner = StageOwner(
        repository_id=7,
        operation_id=operation_id,
        attempt=AttemptNumber(1),
        execution_mode=mode,
        source_generation="sg1:source",
        config_generation="cg1:config",
        extractor_generation="eg1:extractor",
        canonicalizer_generation="kg1:canonicalizer",
        job_id=job_id,
        coordinator_instance_id="coord-arch1c" if coordinator else None,
        singleton_fencing_epoch=11 if coordinator else 0,
        graph_lease_fencing_epoch=101 if coordinator else 0,
    )
    receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId(str(operation_id)), AttemptNumber(1)),
        RunPublicationGenerations(
            "sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer"
        ),
    )
    return PublicationHandoff(MergeContext("stage-arch1c", owner, 41), receipt)


@pytest.mark.parametrize("mode", ("direct", "coordinator"))
def test_final_transaction_uses_one_nonblocking_graph_lock(mode: str) -> None:
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = (True,)

    with patch("repomap_kg.storage.staged_publication._execute") as execute:
        execute_final_transaction(connection, _handoff(mode))

    connection.execute.assert_called_once_with(
        "SELECT pg_try_advisory_xact_lock(%s, %s)",
        (19042, 7),
    )
    assert execute.call_count == 4


@pytest.mark.parametrize("mode", ("direct", "coordinator"))
def test_final_transaction_rejects_contention_before_mutation(mode: str) -> None:
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = (False,)

    with (
        patch("repomap_kg.storage.staged_publication._execute") as execute,
        pytest.raises(StorageSchemaError, match="graph publication already active"),
    ):
        execute_final_transaction(connection, _handoff(mode))

    execute.assert_not_called()
