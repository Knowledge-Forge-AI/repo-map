from __future__ import annotations
from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import Mock, patch
import psycopg
import pytest
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.staged_ingestion import (
    _create_run,
    _ensure_repository,
    _mark_prepared,
    run_staged_full_refresh,
)
from repomap_kg.storage.staged_publication import (
    _execute,
    existing_stage_state,
    publication_run,
)
from repomap_kg.storage.staged_validation import (
    mark_validated,
    mark_validating,
    validate_stage,
)
from repomap_kg.storage.staging import STAGING_FAMILIES

from src.test.unit.python.repomap_kg.storage.scale8_staged_helpers_fixtures import (
    _authority,
    _owner,
)

def test_validation_helpers_reject_transition_and_completeness_failures() -> None:
    connection = Mock()
    connection.execute.return_value.rowcount = 0

    with pytest.raises(StorageSchemaError, match="prepared transition"):
        _mark_prepared(connection, "stage-scale8-helper", {})
    with pytest.raises(StorageSchemaError, match="validating transition"):
        mark_validating(connection, "stage-scale8-helper")
    with pytest.raises(StorageSchemaError, match="validated transition"):
        mark_validated(connection, "stage-scale8-helper")

    connection.execute.return_value.fetchone.return_value = None
    with pytest.raises(StorageSchemaError, match="completeness"):
        validate_stage(
            connection,
            "stage-scale8-helper",
            {family: 0 for family in STAGING_FAMILIES},
        )

    connection.execute.return_value.fetchone.return_value = (1,)
    with pytest.raises(StorageSchemaError, match="completeness"):
        validate_stage(
            connection,
            "stage-scale8-helper",
            {family: 0 for family in STAGING_FAMILIES},
        )


def test_publication_lookup_helpers_are_bounded_and_owner_scoped() -> None:
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = None
    assert existing_stage_state(connection, "stage-scale8-helper", _owner()) is None
    assert (
        publication_run(
            connection,
            7,
            _authority().receipt(),
            complete_only=True,
        )
        is None
    )

    owner = _owner()
    connection.execute.return_value.fetchone.return_value = (
        owner.repository_id,
        "other-operation",
        owner.job_id,
        owner.attempt,
        owner.execution_mode,
        owner.coordinator_instance_id,
        owner.singleton_fencing_epoch,
        owner.graph_lease_fencing_epoch,
        owner.source_generation,
        owner.config_generation,
        owner.extractor_generation,
        owner.canonicalizer_generation,
        "published",
    )
    with pytest.raises(StorageSchemaError, match="ownership"):
        existing_stage_state(connection, "stage-scale8-helper", owner)

    connection.execute.return_value.fetchone.return_value = (41, "running")
    assert publication_run(
        connection,
        7,
        _authority().receipt(),
        complete_only=False,
    ) == (41, "running")


def test_statement_executor_skips_empty_and_comment_only_sql() -> None:
    connection = Mock()
    _execute(connection, ("", "-- comment", "SELECT 1"))
    connection.execute.assert_called_once_with("SELECT 1")


def test_staged_ingestion_rejects_invalid_expiry_and_connection_failure() -> None:
    with pytest.raises(ValueError, match="expiry"):
        run_staged_full_refresh(
            ("psql",),
            (),
            repository_name="fixture",
            root_path="fixture-root",
            authority=_authority(),
            stage_ttl=timedelta(0),
        )

    def fail_connection(**_params: object) -> object:
        raise psycopg.OperationalError("connection unavailable")

    with (
        patch(
            "repomap_kg.storage.staged_ingestion._psycopg_connection_params_from_psql_args",
            return_value={},
        ),
        patch(
            "repomap_kg.storage.staged_ingestion.maintenance_activity",
            return_value=nullcontext(),
        ),
        pytest.raises(StorageSchemaError, match="connection failed"),
    ):
        run_staged_full_refresh(
            ("psql",),
            (),
            repository_name="fixture",
            root_path="fixture-root",
            authority=_authority(),
            connect=fail_connection,
        )


def test_staged_identity_helpers_reject_missing_database_identity() -> None:
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = None

    with pytest.raises(StorageSchemaError, match="repository identity"):
        _ensure_repository(connection, "fixture", "fixture-root")
    with pytest.raises(StorageSchemaError, match="run identity"):
        _create_run(connection, 7, None)


def test_staged_ingestion_refreshes_node_evidence_statistics_before_prepare() -> None:
    prepared = Mock(files=0, row_counts={})
    connection = Mock()
    timeline: list[str] = []

    def record(name: str):
        def callback(*_args: object, **_kwargs: object) -> None:
            timeline.append(name)

        return callback

    with (
        patch(
            "repomap_kg.storage.staged_ingestion.build_staged_rows",
            return_value=prepared,
        ),
        patch(
            "repomap_kg.storage.staged_ingestion._psycopg_connection_params_from_psql_args",
            return_value={},
        ),
        patch(
            "repomap_kg.storage.staged_ingestion.maintenance_activity",
            return_value=nullcontext(),
        ),
        patch(
            "repomap_kg.storage.staged_ingestion.open_owned_connection",
            return_value=connection,
        ),
        patch("repomap_kg.storage.staged_ingestion.close_owned_connection"),
        patch(
            "repomap_kg.storage.staged_ingestion._install_connection_signal_handlers",
            return_value={},
        ),
        patch(
            "repomap_kg.storage.staged_ingestion._restore_connection_signal_handlers"
        ),
        patch("repomap_kg.storage.staged_ingestion._ensure_repository", return_value=7),
        patch(
            "repomap_kg.storage.staged_ingestion.existing_stage_state",
            return_value=None,
        ),
        patch("repomap_kg.storage.staged_ingestion._create_run", return_value=11),
        patch("repomap_kg.storage.staged_ingestion._create_stage"),
        patch(
            "repomap_kg.storage.staged_ingestion._copy_families",
            side_effect=record("copy"),
        ),
        patch(
            "repomap_kg.storage.staged_ingestion._refresh_canonical_node_evidence_statistics",
            side_effect=record("statistics"),
        ),
        patch(
            "repomap_kg.storage.staged_ingestion._mark_prepared",
            side_effect=record("prepared"),
        ),
        patch(
            "repomap_kg.storage.staged_ingestion.mark_validating",
            side_effect=record("validating"),
        ),
        patch(
            "repomap_kg.storage.staged_ingestion.validate_stage",
            side_effect=record("validate"),
        ),
        patch(
            "repomap_kg.storage.staged_ingestion.mark_validated",
            side_effect=record("validated"),
        ),
        patch(
            "repomap_kg.storage.staged_ingestion.execute_final_transaction",
            side_effect=record("final"),
        ),
    ):
        run_staged_full_refresh(
            ("psql",),
            (),
            repository_name="fixture",
            root_path="fixture-root",
            authority=_authority(),
            stage_id="stage-scale9l-order",
            connect=Mock(),
        )

    assert timeline.count("statistics") == 1
    assert (
        timeline.index("copy")
        < timeline.index("statistics")
        < timeline.index("prepared")
        < timeline.index("validating")
        < timeline.index("validate")
    )


def test_existing_stage_state_success_and_failures() -> None:
    connection = Mock()
    owner = _owner()
    valid_row = (
        owner.repository_id,
        owner.operation_id,
        owner.job_id,
        owner.attempt,
        owner.execution_mode,
        owner.coordinator_instance_id,
        owner.singleton_fencing_epoch,
        owner.graph_lease_fencing_epoch,
        owner.source_generation,
        owner.config_generation,
        owner.extractor_generation,
        owner.canonicalizer_generation,
        "validated",
    )
    connection.execute.return_value.fetchone.return_value = valid_row
    assert existing_stage_state(connection, "stage-scale8-helper", owner) == "validated"

    mismatched_row = list(valid_row)
    mismatched_row[8] = "sg1:other"
    connection.execute.return_value.fetchone.return_value = tuple(mismatched_row)
    with pytest.raises(StorageSchemaError, match="staged stage ownership mismatch"):
        existing_stage_state(connection, "stage-scale8-helper", owner)
