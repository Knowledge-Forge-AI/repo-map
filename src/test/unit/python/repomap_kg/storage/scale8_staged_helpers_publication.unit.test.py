from __future__ import annotations
from typing import Any
from dataclasses import replace
from unittest.mock import Mock, patch
import pytest
import psycopg
from repomap_kg.storage._staged_ingestion_stages import _handle_refresh_failure
from repomap_kg.storage.authority import AttemptNumber, JobId, StageId
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.publication import (
    PortablePublicationBinding,
    RunPublicationAttempt,
    RunPublicationGenerations,
    RunPublicationReceipt,
)
from repomap_kg.storage.publication_fencing import PublicationHandoff
from repomap_kg.storage.staged_publication import (
    _mark_commit_unknown,
    _publication_marker,
    execute_final_transaction,
    mark_failed_before_publication,
    publication_run,
    reconcile_commit_unknown,
)

from src.test.unit.python.repomap_kg.storage.scale8_staged_helpers_fixtures import (
    StrictFakeConnection,
    _handoff,
    _owner,
    _portable_binding,
)

def test_publication_marker_and_stage_failure_helpers_fail_closed() -> None:
    connection = Mock()
    portable_fields = PortablePublicationBinding.field_names()
    legacy_portable_values = (None,) * len(portable_fields)
    current_portable_mapping = _portable_binding().to_mapping()
    current_portable_values = tuple(
        current_portable_mapping[field] for field in portable_fields
    )
    connection.execute.return_value.fetchone.return_value = None
    assert _publication_marker(connection, 7, 41) is None

    connection.execute.return_value.fetchone.return_value = (
        "complete",
        41,
        "sg1:source",
        "cg1:config",
        "eg1:extractor",
        "kg1:canonicalizer",
        *legacy_portable_values,
    )
    assert _publication_marker(connection, 7, 41) == {
        "latest_run_identity": "run-41",
        "source_generation": "sg1:source",
        "config_generation": "cg1:config",
        "extractor_generation": "eg1:extractor",
        "canonicalizer_generation": "kg1:canonicalizer",
    }
    connection.execute.return_value.fetchone.return_value = (
        "complete",
        41,
        "sg1:source",
        "cg1:config",
        "eg1:extractor",
        "kg1:canonicalizer",
        *current_portable_values,
    )
    assert _publication_marker(connection, 7, 41) == {
        "latest_run_identity": "run-41",
        "source_generation": "sg1:source",
        "config_generation": "cg1:config",
        "extractor_generation": "eg1:extractor",
        "canonicalizer_generation": "kg1:canonicalizer",
        **dict(zip(portable_fields, current_portable_values, strict=True)),
    }

    connection.execute.return_value.fetchone.return_value = (
        "complete",
        41,
        "sg1:source",
        "cg1:config",
        "eg1:extractor",
        "kg1:canonicalizer",
        current_portable_values[0],
        *legacy_portable_values[1:],
    )
    with pytest.raises(StorageSchemaError, match="present all-or-none"):
        _publication_marker(connection, 7, 41)

    connection.execute.return_value.fetchone.return_value = (
        "complete",
        41,
        "sg1:source",
        "cg1:config",
        "eg1:extractor",
        "kg1:canonicalizer",
    )
    with pytest.raises(StorageSchemaError, match="selected schema"):
        _publication_marker(connection, 7, 41)

    connection.execute.return_value.fetchone.return_value = (
        "running",
        41,
        "sg1:source",
        "cg1:config",
        "eg1:extractor",
        "kg1:canonicalizer",
        *legacy_portable_values,
    )
    assert _publication_marker(connection, 7, 41) is None

    connection.execute.return_value.rowcount = 0
    with pytest.raises(StorageSchemaError, match="failure transition"):
        mark_failed_before_publication(connection, "stage-scale8-helper", 41, _owner())

    connection.execute.return_value.fetchone.return_value = ("commit_unknown",)
    _mark_commit_unknown(connection, _handoff())
    connection.execute.return_value.rowcount = 1
    _mark_commit_unknown(connection, _handoff())
    connection.execute.return_value.rowcount = 0
    connection.execute.return_value.fetchone.return_value = None
    with pytest.raises(StorageSchemaError, match="reconciliation failed"):
        _mark_commit_unknown(connection, _handoff())


def _valid_runs_row() -> tuple[Any, ...]:
    fields = PortablePublicationBinding.field_names()
    mapping = _portable_binding().to_mapping()
    return (
        "complete", 41, "sg1:source", "cg1:config", "eg1:extractor", "kg1:canonicalizer",
        *(mapping[f] for f in fields),
    )


def test_publication_reconciliation_handles_absent_and_conflicting_markers() -> None:
    conn_absent = StrictFakeConnection(runs_row=None)
    assert reconcile_commit_unknown(lambda **_: conn_absent, {}, _handoff(), 7) is False
    assert conn_absent.committed == 1
    assert conn_absent.closed == 1
    unknown_stmts = [(sql, params) for sql, params in conn_absent.executed if "state = 'commit_unknown'" in sql]
    assert len(unknown_stmts) == 1
    assert "repository_id = %s" in unknown_stmts[0][0]
    assert "singleton_fencing_epoch = %s" in unknown_stmts[0][0]
    assert unknown_stmts[0][1][1] == _handoff().merge.owner.repository_id

    conn_conflict = StrictFakeConnection(runs_row=_valid_runs_row(), stage_row=("validated",))
    conflicting_handoff = PublicationHandoff(
        _handoff().merge,
        RunPublicationReceipt(
            _handoff().receipt.attempt,
            _handoff().receipt.generations,
            replace(_portable_binding(), candidate_id="cand1:" + "8" * 64),
        ),
    )
    with pytest.raises(StorageSchemaError, match="receipt conflicts"):
        reconcile_commit_unknown(lambda **_: conn_conflict, {}, conflicting_handoff, 7)
    assert conn_conflict.committed == 1
    assert conn_conflict.closed == 1
    quarantine_stmts = [(sql, params) for sql, params in conn_conflict.executed if "state = 'quarantined'" in sql]
    assert len(quarantine_stmts) == 1
    assert f"repository_id = {conflicting_handoff.merge.owner.repository_id}" in quarantine_stmts[0][0]
    assert f"singleton_fencing_epoch = {conflicting_handoff.merge.owner.singleton_fencing_epoch}" in quarantine_stmts[0][0]


def test_reconcile_commit_unknown_matching_committed_marker() -> None:
    conn = StrictFakeConnection(runs_row=_valid_runs_row())
    handoff = PublicationHandoff(
        _handoff().merge,
        RunPublicationReceipt(
            _handoff().receipt.attempt,
            _handoff().receipt.generations,
            _portable_binding(),
        ),
    )
    assert reconcile_commit_unknown(lambda **_: conn, {}, handoff, 7) is True
    assert conn.committed == 1
    assert conn.rolled_back == 0
    assert conn.closed == 1


def test_reconcile_commit_unknown_published_matching_accepted_with_contradictory_handoff() -> None:
    conn = StrictFakeConnection(runs_row=_valid_runs_row(), stage_row=("published",))
    conflicting_handoff = PublicationHandoff(
        _handoff().merge,
        RunPublicationReceipt(
            _handoff().receipt.attempt,
            _handoff().receipt.generations,
            replace(_portable_binding(), candidate_id="cand1:" + "8" * 64),
        ),
    )
    with pytest.raises(StorageSchemaError, match="receipt conflicts"):
        reconcile_commit_unknown(lambda **_: conn, {}, conflicting_handoff, 7)
    assert not any("quarantined" in sql for sql, _ in conn.executed)
    assert conn.committed == 0
    assert conn.rolled_back == 1
    assert conn.closed == 1


def test_reconcile_commit_unknown_driver_query_failure_and_unusable_row() -> None:
    conn_fail = StrictFakeConnection(query_failure=RuntimeError("db conn dropped"))
    with pytest.raises(RuntimeError, match="db conn dropped"):
        reconcile_commit_unknown(lambda **_: conn_fail, {}, _handoff(), 7)
    assert conn_fail.committed == 0
    assert conn_fail.rolled_back == 1
    assert conn_fail.closed == 1

    handoff = PublicationHandoff(
        _handoff().merge,
        RunPublicationReceipt(
            _handoff().receipt.attempt,
            _handoff().receipt.generations,
            replace(_portable_binding(), candidate_id="cand1:" + "8" * 64),
        ),
    )
    conn_bad_stage = StrictFakeConnection(runs_row=_valid_runs_row(), stage_row=())
    with pytest.raises(StorageSchemaError, match="stage row does not match"):
        reconcile_commit_unknown(lambda **_: conn_bad_stage, {}, handoff, 7)
    assert conn_bad_stage.committed == 0
    assert conn_bad_stage.rolled_back == 1
    assert conn_bad_stage.closed == 1

    conn_bad_runs = StrictFakeConnection(
        runs_row=_valid_runs_row(),
        stage_row=("published",),
        runs_status_row=("complete",),
    )
    with pytest.raises(StorageSchemaError, match="run row does not match"):
        reconcile_commit_unknown(lambda **_: conn_bad_runs, {}, handoff, 7)
    assert conn_bad_runs.committed == 0
    assert conn_bad_runs.rolled_back == 1
    assert conn_bad_runs.closed == 1


def test_reconcile_commit_unknown_owner_mismatch_refusal() -> None:
    factory_called = False

    def factory(**_):
        nonlocal factory_called
        factory_called = True
        return StrictFakeConnection()

    with pytest.raises(StorageSchemaError, match="staged stage ownership mismatch"):
        reconcile_commit_unknown(factory, {}, _handoff(), repository_id=999)
    assert not factory_called


def test_publication_run_portable_clause_generation() -> None:
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = (55, "complete")
    binding = _portable_binding()
    receipt = RunPublicationReceipt(
        RunPublicationAttempt(JobId("job-port"), AttemptNumber(1)),
        RunPublicationGenerations("sg1:s", "cg1:c", "eg1:e", "kg1:k"),
        binding,
    )

    result = publication_run(connection, 7, receipt, complete_only=True)
    assert result == (55, "complete")
    executed_sql, params = connection.execute.call_args[0]
    assert "AND graph_candidate_id = %s" in executed_sql
    assert "AND status = 'complete'" in executed_sql
    assert binding.candidate_id in params


def test_execute_final_transaction_advisory_lock_failure() -> None:
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = (False,)
    handoff = _handoff()

    with pytest.raises(StorageSchemaError, match="graph publication already active"):
        execute_final_transaction(connection, handoff)


def test_mark_failed_before_publication_success_transition() -> None:
    connection = Mock()
    connection.execute.return_value.rowcount = 1
    owner = _owner()

    mark_failed_before_publication(connection, "stage-scale8-helper", 41, owner)
    assert connection.execute.call_count == 2
    executed_sql = connection.execute.call_args_list[0][0][0]
    assert "SET state = 'failed', merge_status = 'rolled_back'" in executed_sql


def test_mark_failed_before_publication_rowcount_zero_raises() -> None:
    connection = Mock()
    connection.execute.return_value.rowcount = 0
    owner = _owner()
    with pytest.raises(StorageSchemaError, match="staged failure transition failed"):
        mark_failed_before_publication(connection, "stage-scale8-helper", 41, owner)


def test_execute_final_transaction_measurement_contracts() -> None:
    from repomap_kg.storage.staging_observability import StagingMeasurements
    from repomap_kg.storage.staging_merge_operations import MergeScope
    from repomap_kg.storage.staged_publication import _execute_measured_merge

    connection = Mock()
    connection.execute.return_value.fetchone.return_value = (True,)
    handoff = _handoff()
    measurements = StagingMeasurements(lambda _event: None)

    with patch(
        "repomap_kg.storage.staged_publication.build_publication_prepare_statements",
        return_value=("one",),
    ):
        with pytest.raises(
            StorageSchemaError, match="staged prepare measurement contract is invalid"
        ):
            execute_final_transaction(
                connection, handoff, staging_measurements=measurements
            )

    with patch(
        "repomap_kg.storage.staged_publication.build_publication_finalize_statements",
        return_value=("one",),
    ):
        with pytest.raises(
            StorageSchemaError, match="staged finalize measurement contract is invalid"
        ):
            execute_final_transaction(
                connection, handoff, staging_measurements=measurements
            )

    with pytest.raises(
        StorageSchemaError, match="staged merge measurement contract is invalid"
    ):
        _execute_measured_merge(
            connection, ("only_one",), MergeScope.SOURCE_INDEX, measurements
        )


def test_reconcile_commit_unknown_exception_rollback_path() -> None:
    connection = Mock()
    connection.execute.side_effect = RuntimeError("database link broken")
    factory = lambda **_kwargs: connection
    handoff = _handoff()

    with pytest.raises(RuntimeError, match="database link broken"):
        reconcile_commit_unknown(factory, {}, handoff, 7)

    connection.rollback.assert_called_once()
    connection.close.assert_called_once()


@pytest.mark.parametrize('message', [
    'staged publication receipt conflicts',
    'staged publication commit is unknown',
    'staged operation cannot be replayed',
])
def test_public_failure_preserves_typed_storage_classification(message) -> None:
    error = StorageSchemaError(message)
    connection = Mock()
    with pytest.raises(StorageSchemaError, match=message) as caught:
        _handle_refresh_failure(
            connection, error, handoff=_handoff(), stage_committed=True,
            owner=_owner(), resolved_stage_id=StageId(_handoff().merge.stage_id), run_id=41,
        )
    assert caught.value is error
    assert caught.value.__cause__ is None
    connection.execute.assert_not_called()
    connection.commit.assert_not_called()


def test_public_failure_sanitizes_driver_error_and_retains_exact_cause() -> None:
    error = psycopg.errors.CheckViolation('fixture-only internal fence detail')
    connection = Mock()
    with pytest.raises(StorageSchemaError, match='^staged PostgreSQL operation failed$') as caught:
        _handle_refresh_failure(
            connection, error, handoff=None, stage_committed=False,
            owner=None, resolved_stage_id=StageId(_handoff().merge.stage_id), run_id=None,
        )
    assert caught.value.__cause__ is error
    assert 'internal fence detail' not in str(caught.value)
    connection.rollback.assert_called_once()
    connection.execute.assert_not_called()
    connection.commit.assert_not_called()


def test_commit_unknown_refuses_untransitioned_published_stage() -> None:
    """Characterize the retained refusal; this is not an observed hosted cause."""
    connection = Mock()
    connection.execute.return_value.rowcount = 0
    connection.execute.return_value.fetchone.return_value = ('published',)
    with pytest.raises(StorageSchemaError, match='^staged publication stage reconciliation failed$'):
        _mark_commit_unknown(connection, _handoff())
    connection.commit.assert_not_called()
