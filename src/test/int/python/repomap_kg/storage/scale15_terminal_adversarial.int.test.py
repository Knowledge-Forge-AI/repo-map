from __future__ import annotations

from collections.abc import Callable
from unittest.mock import patch

import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from repomap_kg.observations import RawObservation
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import (
    AttemptNumber,
    JobId,
    OperationId,
    PublicationGenerations,
)
from repomap_kg.storage.publication import RunPublicationAttempt
from repomap_kg.storage.readback_driver import (
    _psycopg_connection_params_from_psql_args,
)
from repomap_kg.storage.staged_ingestion import (
    IngestionAuthority,
    run_staged_full_refresh,
)
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from scale15_actual_path_readback import read_scale15_terminal_state
import scale15_actual_path_readback as scale15_readback
from scale16_actual_path_readback import read_scale16_terminal_state
from scale15_terminal_contracts import (
    ExpectedRefreshAuthority,
    FINAL_FAMILY_CODES,
    PublicationState,
)


GENERATIONS = PublicationGenerations(
    "sg1:scale15-source",
    "cg1:scale15-config",
    "eg1:scale15-extractor",
    "kg1:scale15-canonicalizer",
)
REPOSITORY_NAME = "public-fixture"


def _observations() -> tuple[RawObservation, ...]:
    return (
        RawObservation(
            kind="file",
            source_id="src/app.py",
            path="src/app.py",
            confidence="manual",
            extractor="scale15-fixture",
            extractor_version="1.0.0",
            metadata={
                "language": "python",
                "role": "source",
                "content_hash": "a" * 64,
                "generated": False,
                "executable": False,
            },
        ),
        RawObservation(
            kind="python.import",
            source_id="src/app.py#import:json",
            path="src/app.py",
            start_line=1,
            end_line=1,
            name="json",
            target="module:json",
            confidence="heuristic",
            extractor="scale15-fixture",
            extractor_version="1.0.0",
            metadata={"module": "json"},
        ),
    )


def _expected(identity: str) -> ExpectedRefreshAuthority:
    prepared = build_staged_rows(
        _observations(),
        repository_name=REPOSITORY_NAME,
        stage_id="scale15-counts",
    )
    try:
        counts = {
            family: int(prepared.row_counts[family])
            for family in FINAL_FAMILY_CODES
        }
    finally:
        prepared.close()
    return ExpectedRefreshAuthority(
        repository_identity=identity,
        repository_name=REPOSITORY_NAME,
        generations=GENERATIONS,
        execution_mode="direct",
        zero_state_first_publication=True,
        expected_family_counts=counts,
        expected_structural_digest=None,
    ).validate()


def _publish(postgres, case: str) -> ExpectedRefreshAuthority:
    identity = f"repo1:scale15-{case}"
    authority = IngestionAuthority(
        operation_id=OperationId(f"scale15-{case}"),
        attempt=AttemptNumber(1),
        execution_mode="direct",
        source_generation=GENERATIONS.source_generation,
        config_generation=GENERATIONS.config_generation,
        extractor_generation=GENERATIONS.extractor_generation,
        canonicalizer_generation=GENERATIONS.canonicalizer_generation,
    )
    run_staged_full_refresh(
        postgres.psql_args,
        _observations(),
        repository_name=REPOSITORY_NAME,
        root_path="public-fixture-root",
        repository_identity=identity,
        authority=authority,
    )
    return _expected(identity)


def _repository_id(connection) -> int:
    return int(
        connection.execute(
            "SELECT id FROM repositories WHERE name = %s",
            (REPOSITORY_NAME,),
        ).fetchone()[0]
    )


def _clear_receipt(connection, repository_id: int) -> None:
    connection.execute(
        "UPDATE runs SET publication_job_id = NULL, publication_attempt = NULL, "
        "source_generation = NULL, config_generation = NULL, "
        "extractor_generation = NULL, canonicalizer_generation = NULL "
        "WHERE repository_id = %s",
        (repository_id,),
    )


def _receiptless_complete(connection, repository_id: int) -> None:
    _clear_receipt(connection, repository_id)
    connection.execute(
        "UPDATE ingestion_stages SET state = 'failed', "
        "merge_status = 'rolled_back', "
        "publication_reconciliation_state = 'reconciled', "
        "cleanup_eligibility = 'eligible' WHERE repository_id = %s",
        (repository_id,),
    )


def _partial_receipt(connection, repository_id: int) -> None:
    connection.execute(
        "UPDATE runs SET publication_attempt = NULL WHERE repository_id = %s",
        (repository_id,),
    )


def _generation_mismatch(connection, repository_id: int) -> None:
    other = (
        "sg1:other",
        "cg1:other",
        "eg1:other",
        "kg1:other",
    )
    connection.execute(
        "UPDATE runs SET source_generation = %s, config_generation = %s, "
        "extractor_generation = %s, canonicalizer_generation = %s "
        "WHERE repository_id = %s",
        (*other, repository_id),
    )
    connection.execute(
        "UPDATE ingestion_stages SET source_generation = %s, "
        "config_generation = %s, extractor_generation = %s, "
        "canonicalizer_generation = %s WHERE repository_id = %s",
        (*other, repository_id),
    )


def _conflicting_receipt(connection, repository_id: int) -> None:
    connection.execute(
        "UPDATE ingestion_stages SET operation_id = 'scale15-conflict-other' "
        "WHERE repository_id = %s",
        (repository_id,),
    )


def _canonical_only(connection, repository_id: int) -> None:
    connection.execute(
        "DELETE FROM raw_observations WHERE repository_id = %s",
        (repository_id,),
    )
    connection.execute(
        "DELETE FROM files WHERE repository_id = %s",
        (repository_id,),
    )


def _raw_only(connection, repository_id: int) -> None:
    connection.execute(
        "DELETE FROM canonical_nodes WHERE repository_id = %s",
        (repository_id,),
    )
    connection.execute(
        "DELETE FROM canonical_evidence WHERE repository_id = %s",
        (repository_id,),
    )
    connection.execute(
        "DELETE FROM files WHERE repository_id = %s",
        (repository_id,),
    )


def _published_without_receipt(connection, repository_id: int) -> None:
    _clear_receipt(connection, repository_id)


def _unreconciled_stage(connection, repository_id: int) -> None:
    connection.execute(
        "UPDATE ingestion_stages SET state = 'validating', "
        "publication_reconciliation_state = 'required', "
        "cleanup_eligibility = 'blocked' WHERE repository_id = %s",
        (repository_id,),
    )


def _commit_unknown(connection, repository_id: int) -> None:
    connection.execute(
        "UPDATE ingestion_stages SET state = 'commit_unknown', "
        "merge_status = 'unknown', "
        "publication_reconciliation_state = 'required', "
        "cleanup_eligibility = 'blocked' WHERE repository_id = %s",
        (repository_id,),
    )


CASES: tuple[
    tuple[str, Callable[[object, int], None], PublicationState], ...
] = (
    ("receiptless", _receiptless_complete, PublicationState.RECEIPTLESS_COMPLETE),
    ("partial", _partial_receipt, PublicationState.PARTIAL_RECEIPT),
    ("generation", _generation_mismatch, PublicationState.GENERATION_MISMATCH),
    ("conflict", _conflicting_receipt, PublicationState.RECEIPT_CONFLICT),
    ("canonical-only", _canonical_only, PublicationState.FAMILY_STATE_MISMATCH),
    ("raw-only", _raw_only, PublicationState.FAMILY_STATE_MISMATCH),
    (
        "published-without-receipt",
        _published_without_receipt,
        PublicationState.RECEIPTLESS_COMPLETE,
    ),
    ("unreconciled-stage", _unreconciled_stage, PublicationState.RECEIPT_CONFLICT),
    (
        "commit-unknown",
        _commit_unknown,
        PublicationState.COMMIT_UNKNOWN_UNRESOLVED,
    ),
)


def test_fix4_actual_psycopg_success_and_transport_refusal() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        expected = _publish(postgres, "fix4-bounded-success")
        result = read_scale15_terminal_state(
            postgres.psql_args,
            expected,
            psql_command=postgres.psql_command,
        )
        assert result.publication_state is PublicationState.PUBLISHED
        authority = scale15_readback.read_run_authority(
            postgres.psql_args,
            expected.repository_name,
            psql_command=postgres.psql_command,
        )
        canonical = scale15_readback.read_latest_receipt_bearing_publication(
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        disposable = postgres.create_database("scale15_refused")
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(make_conninfo(**params), autocommit=True) as connection:
            connection.execute('DROP DATABASE "scale15_refused"')
        refused_psql_args = tuple(disposable.psql_args)
        psql_command = postgres.psql_command

    with (
        patch.object(scale15_readback, "read_run_authority", return_value=authority),
        patch.object(
            scale15_readback,
            "read_latest_receipt_bearing_publication",
            return_value=canonical,
        ),
        pytest.raises(psycopg.OperationalError),
    ):
        read_scale15_terminal_state(
            refused_psql_args,
            expected,
            psql_command=psql_command,
        )


def test_scale15_database_adversarial_terminal_fixtures() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in params.items())
        for case, mutate, expected_state in CASES:
            expected = _publish(postgres, case)
            with psycopg.connect(conninfo, autocommit=True) as connection:
                if case == "partial":
                    connection.execute(
                        "ALTER TABLE runs DROP CONSTRAINT "
                        "runs_publication_attempt_receipt"
                    )
                mutate(connection, _repository_id(connection))
            readback = read_scale15_terminal_state(
                postgres.psql_args,
                expected,
                psql_command=postgres.psql_command,
            )
            assert readback.publication_state is expected_state
            assert "public-fixture-root" not in repr(readback)
            with psycopg.connect(conninfo, autocommit=True) as connection:
                connection.execute(
                    "DELETE FROM repositories WHERE name = %s",
                    (REPOSITORY_NAME,),
                )

        expected = _publish(postgres, "foreign-publication")
        bound = expected.bind(RunPublicationAttempt(JobId("scale16-bound-a"), AttemptNumber(1)))
        readback = read_scale16_terminal_state(
            postgres.psql_args,
            bound,
            psql_command=postgres.psql_command,
        )
        assert readback.publication_state is (
            PublicationState.FOREIGN_PUBLICATION_DETECTED
        )
        assert "scale16-bound-a" not in repr(readback)
